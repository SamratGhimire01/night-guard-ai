import difflib
import logging
import re
import time
import uuid
from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.exceptions import NotFoundError
from app.db.models.appointment import Appointment
from app.db.models.business import Business, LanguageMode
from app.db.models.conversation import Conversation, Message, MessageSenderType
from app.db.models.customer import Customer
from app.db.models.notification import NotificationStatus
from app.db.models.service import Service
from app.llm import get_embedding_provider
from app.llm.base import ContentFilterError
from app.memory import assemble_context
from app.memory.conversations import get_conversation
from app.memory.summarization import maybe_summarize_conversation
from app.schemas.conversation import ConversationIntent, ConversationLanguage
from app.services import (
    booking_service,
    business_hours_service,
    handoff_service,
    knowledge_service,
    payment_service,
    service_service,
    style_exemplar_service,
    takeover_service,
)
from app.services.channels import delivery
from app.services.conversation import appointment_tools  # noqa: F401  registers CANCELLATION/RESCHEDULING tools
from app.services.conversation import booking_tool  # noqa: F401  registers the BOOKING tool
from app.services.conversation.contact_tool import UpdateContactInfoTool
from app.services.conversation.fact_validator import _PRICE_RE, _SENTENCE_SPLIT_RE, check_response_facts
from app.services.conversation.formatting import format_service_list
from app.services.conversation.reply_polish import finalize_reply
from app.services.conversation.intent import classify_and_respond, translate_for_search
from app.services.conversation.style_checks import check_response_style, repair_response_style
from app.services.conversation.voice_pass import revoice
from app.services.conversation.response_templates import (
    already_sent,
    describe_business_hours,
    format_clock,
    format_day,
    format_slot_list,
    format_when,
    parse_language_choice,
    render,
    render_contact_gate,
    render_language_question,
    render_missing_slots,
    reply_history,
)
from app.services.conversation.tools import find_tool

logger = logging.getLogger(__name__)

KNOWLEDGE_TOP_K = 3

# Phase 25: how many CONSECUTIVE customer messages in a row must show a
# different language/script than the current lock before the lock actually
# moves — a single stray message (a one-word English reply mid-Nepali-
# conversation, an appointment id copy-pasted, etc.) must never flip it. 3 is
# a real, tunable judgment call, not derived from anything — see
# orchestrator._resolve_locked_language.
# ponytail: fixed threshold, no per-business config; revisit if real traffic
# shows 3 is too twitchy or too sticky.
_LANGUAGE_LOCK_STREAK_THRESHOLD = 3


_PARENTHETICAL_RE = re.compile(r"\s*\([^()]*\)")


def _resolve_service_by_name(services: list[Service], name: str) -> Service | None:
    """Exact (case-insensitive) match on the full name, else on the name with every "(...)" group removed on BOTH sides —
    the LLM is told to copy the name verbatim, but measured live it sometimes copies the services list's own suffix too
    ("Teeth Whitening (NPR 6000.00, 45 min)", or "Teeth Cleaning" for "Teeth Cleaning (Scaling & Polishing)"), which an
    exact-only match dropped and turned into the generic "which service, date and time?" question (PHASE_STATUS.md Phase 19).
    Still never a guess: the match must be unique. No match (including >1, e.g. two services differing only in their
    parenthetical) means "not enough information yet"."""
    wanted = name.strip().lower()
    matches = [s for s in services if s.name.strip().lower() == wanted]
    if len(matches) != 1:
        base = _PARENTHETICAL_RE.sub("", wanted).strip()
        matches = [s for s in services if base and _PARENTHETICAL_RE.sub("", s.name).strip().lower() == base]
    return matches[0] if len(matches) == 1 else None


def _resolve_booking_datetime(business: Business, date_str: str, time_str: str) -> datetime | None:
    try:
        tz = ZoneInfo(business.timezone)
        naive = datetime.strptime(f"{date_str} {time_str}", "%Y-%m-%d %H:%M")
        return naive.replace(tzinfo=tz)
    except (ValueError, KeyError):
        return None


def _format_local(dt: datetime, tz: ZoneInfo, language: str | None = None) -> str:
    return format_when(dt.astimezone(tz), language)


def _format_slot_options(slots: list[datetime], tz: ZoneInfo, language: str | None = None) -> str:
    """The slot-list body of "here's what's open". When EVERY slot is on the same real local date, the date is stated
    once and only times follow ("Monday, September 21 at 9:00 AM, 9:15 AM, 9:30 AM" / "Sombar (Sep 21) — bihana 9
    baje, sawa 9 baje") instead of repeating the full date before each time. If the slots span more than one real date,
    each keeps its own full date — dropping it there would make the list ambiguous."""
    return format_slot_list([slot.astimezone(tz) for slot in slots], language)


def _is_valid_date_str(value: str) -> bool:
    try:
        datetime.strptime(value, "%Y-%m-%d")
        return True
    except ValueError:
        return False


def _is_valid_time_str(value: str) -> bool:
    try:
        datetime.strptime(value, "%H:%M")
        return True
    except ValueError:
        return False


def _format_date_only(date_str: str, language: str | None = None) -> str:
    return format_day(datetime.strptime(date_str, "%Y-%m-%d"), language)


def _format_time_only(time_str: str, language: str | None = None) -> str:
    return format_clock(datetime.strptime(time_str, "%H:%M"), language)


def _offered_slot_pick(
    offered_slots: list[datetime] | None, tz: ZoneInfo | None, date_str: str | None, time_str: str | None
) -> tuple[bool, str | None]:
    """Is THIS turn's date/time the customer choosing from the slot list the SYSTEM just showed them?

    Returns (is_pick, offered_day). `offered_slots` is exactly what _propose_available_slots persisted on the previous
    turn (one-shot: handle_incoming_message hands it over before clearing it, so a stale list never counts). A pick is:
    date+time whose PAIR is an offered slot; a date that is one of the offered days; or a time-only reply ("first
    one" -> 09:00) that matches exactly one offered slot (offered_day is then that slot's day; a time offered on
    several days is ambiguous, so it is NOT treated as a pick and nothing is guessed). Anything else -- a date or
    slot the system never offered -- is the customer's own choice, i.e. a real switch."""
    if not offered_slots or tz is None or not (date_str or time_str):
        return False, None
    pairs = {(slot.astimezone(tz).strftime("%Y-%m-%d"), slot.astimezone(tz).strftime("%H:%M")) for slot in offered_slots}
    if date_str and time_str:
        return (date_str, time_str) in pairs, date_str
    if date_str:
        return date_str in {day for day, _ in pairs}, date_str
    days = {day for day, hhmm in pairs if hhmm == time_str}
    return (True, next(iter(days))) if len(days) == 1 else (False, None)


def _service_named_in(services: list[Service], text: str) -> Service | None:
    """The ONE real service the customer literally named in `text`, else None (no match, or more than one -- never a guess).
    Matches the full service name or the name without a trailing parenthetical ("Teeth Cleaning (Scaling & Polishing)" ->
    "Teeth Cleaning"), whole words only, case-insensitive. Backstop for the LLM leaving `booking_request.service` null on a
    booking-intent message that plainly names one (measured at low reasoning effort: 88% vs 99% extraction, concentrated in
    "what times do you have for a <service>?"-shaped questions -- PHASE_STATUS.md Phase 17)."""
    lower = text.lower()
    hits = []
    for service in services:
        keys = {service.name.lower(), re.sub(r"\s*\(.*?\)\s*", " ", service.name).strip().lower()}
        if any(key and re.search(rf"(?<![a-z]){re.escape(key)}(?![a-z])", lower) for key in keys):
            hits.append(service)
    return hits[0] if len(hits) == 1 else None


def _fill_missing_booking_service(
    services: list[Service],
    booking_request: dict,
    content: str,
    offered_service_id: uuid.UUID | None,
    this_turn_pick: Service | None = None,
) -> dict:
    """Backstop for a booking-intent turn whose `booking_request["service"]` came back
    empty/unresolvable. Two independent fallbacks, tried in order:

    1. A service the customer literally named in THIS message (`_service_named_in`) --
       by far the more common case (a botched/partial LLM extraction of a name the
       customer did state).
    2. Failing that, the service THIS conversation's own PREVIOUS turn offered/
       recommended (`offered_service_id` -- see Conversation.booking_draft_offered_
       service_id's docstring). Real bug found live (Samaj Dental Clinic transcript):
       the ASSISTANT itself proposed "Dental Consultation" answering a customer's
       question, the customer replied with a plain affirmative ("hunxa garau garau")
       naming no service of its own, and the draft stayed service-less -- re-asking
       "which service" as if nothing had ever been proposed. Exactly the same
       "customer said yes to what I offered" case `_offered_slot_pick` already
       resolves for date/time, just for the service slot.
    3. Failing both, the one service THIS turn's reply singled out (`this_turn_pick`). trekking-10 clarifier branch:
       "reserve a spot on the Annapurna Circuit" -> the model explains it goes through the Trek Booking Consultation but
       leaves `booking_request.service` null, and the "which service, date and time?" clarifier dropped that answer.

    Leaves `booking_request` untouched if no fallback resolves a real service."""
    named_service = _service_named_in(services, content)
    if named_service is not None:
        return {**booking_request, "service": named_service.name}
    if offered_service_id is not None:
        offered_service = next((s for s in services if s.id == offered_service_id), None)
        if offered_service is not None:
            return {**booking_request, "service": offered_service.name}
    if this_turn_pick is not None:
        return {**booking_request, "service": this_turn_pick.name}
    return booking_request


# Weekday names a customer may type -> Monday=0. Latin words match exactly; Devanagari tokens by prefix (case suffixes: "शनिबारमा").
_WEEKDAY_WORDS = {
    "monday": 0, "tuesday": 1, "tues": 1, "wednesday": 2, "thursday": 3, "thurs": 3, "thur": 3, "friday": 4, "saturday": 5,
    "sunday": 6,
    "sombar": 0, "somabar": 0, "mangalbar": 1, "mangalvar": 1, "budhabar": 2, "budhbar": 2, "bihibar": 3, "bihibaar": 3,
    "bihivar": 3, "sukrabar": 4, "shukrabar": 4, "sanibar": 5, "shanibar": 5, "aitabar": 6, "aaitabar": 6, "aitbar": 6,
}
_WEEKDAY_DEVANAGARI = (
    ("सोमबार", 0), ("मंगलबार", 1), ("मङ्गलबार", 1), ("बुधबार", 2), ("बिहीबार", 3), ("बिहिबार", 3), ("शुक्रबार", 4),
    ("शनिबार", 5), ("आइतबार", 6),
)
_TOKEN_RE = re.compile(r"[A-Za-z]+|[ऀ-ॿ]+")
# Anything that makes "the weekday in this text" NOT the whole story: another date reference, a calendar date, a multi-week phrase,
# or a negation ("not Thursday", "can't do Friday"). In those cases the model's date is left exactly as it is.
_OTHER_DATE_OR_NEGATION_RE = re.compile(
    r"\b(today|tonight|tomorrow|yesterday|week|weeks|month|weekend|next|last|aaja|bholi|parsi|hijo|"
    r"january|february|march|april|may|june|july|august|september|october|november|december|"
    r"jan|feb|mar|apr|jun|jul|aug|sep|sept|oct|nov|dec|"
    r"not|no|never|except|cannot|cant|wont|without|other than|rather than|instead of|but not)\b"
    r"|n't|\d{4}-\d{2}-\d{2}|\d{1,2}\s*(st|nd|rd|th)\b|\d{1,2}\s*[/.]\s*\d{1,2}"
    r"|आज|भोलि|पर्सि|हिजो|हप्ता|महिना",
    re.IGNORECASE,
)


def _named_weekday(text: str) -> int | None:
    """The ONE weekday (Monday=0) the customer's text names, else None (none named, or two different ones)."""
    found = set()
    for token in _TOKEN_RE.findall(text):
        if token.lower() in _WEEKDAY_WORDS:
            found.add(_WEEKDAY_WORDS[token.lower()])
        else:
            found.update(index for name, index in _WEEKDAY_DEVANAGARI if token.startswith(name))
    return next(iter(found)) if len(found) == 1 else None


def _verify_weekday_date(request: dict, text: str, today: date, *, fill_missing: bool = False) -> dict:
    """Python verifies what the LLM extracts (same principle as _service_named_in): a weekday the customer literally typed is
    resolved against the REAL calendar, and the model's date is overridden when it disagrees. Measured live: "Thursday" came back as
    Wednesday's date (always exactly a day early), 68% correct on terse messages ("Monday works?"), at both reasoning efforts --
    PHASE_STATUS.md Phase 18. Only acts when the text names exactly one weekday and carries no other date reference or negation
    (see _OTHER_DATE_OR_NEGATION_RE); otherwise the model's date is returned untouched. A date the model gave that already falls on
    the named weekday is never changed (it may be "next week's"). A wrong-weekday date is replaced by the named weekday's occurrence
    within +-3 days of it (so the model's week is kept), moved a week forward only if that would be in the past. A MISSING date is filled only when `fill_missing` (booking-intent turns) and the named weekday
    is not today's own (then "Thursday" could mean today or next week -- not ours to guess)."""
    weekday = _named_weekday(text)
    if weekday is None or _OTHER_DATE_OR_NEGATION_RE.search(text):
        return request
    model_date = request.get("date")
    if model_date and _is_valid_date_str(model_date):
        modelled = datetime.strptime(model_date, "%Y-%m-%d").date()
        if modelled.weekday() == weekday:
            return request
        fixed = modelled + timedelta(days=(weekday - modelled.weekday() + 3) % 7 - 3)  # the named weekday within +-3 days of the model's
        return {**request, "date": (fixed if fixed >= today else fixed + timedelta(days=7)).isoformat()}
    if fill_missing and weekday != today.weekday():
        return {**request, "date": (today + timedelta(days=(weekday - today.weekday()) % 7)).isoformat()}
    return request


def _merge_booking_draft(
    conversation: Conversation,
    services: list[Service],
    booking_request: dict | None,
    offered_slots: list[datetime] | None = None,
    tz: ZoneInfo | None = None,
    language: str | None = None,
) -> list[tuple[str, str]]:
    """Phase 25a — root-cause fix for the infinite booking-confirmation loop:
    real testing showed the LLM being asked, fresh every turn, to judge
    whether it had "enough information" to book — not deterministic, and the
    model could hedge on that judgment forever. Deterministically folds
    whatever slot(s) THIS turn's extraction actually provided into the
    persisted draft (Conversation.booking_draft_*) — never overwrites an
    already-filled slot with nothing, never trusts an unresolved service
    name or a malformed date/time string. The LLM's only job now (see
    intent.py rule 9) is reporting what THIS message says; accumulating
    slots and judging readiness is entirely this function's + _resolve_
    booking_draft's job, not the model's.

    Real gap found live (PHASE_STATUS.md, "silent service switch"): a
    customer naming a DIFFERENT service/date/time than what's already in the
    draft got a silent overwrite — no acknowledgment anywhere that the prior
    value was dropped (a real risk once contact info has already been given
    for it, one step from being booked). Returns a list of (old, new)
    human-readable description pairs for every field that just switched from
    one real, non-null CUSTOMER-STATED value to a genuinely different one —
    never for a field being filled in for the first time, which is not a
    switch. The caller folds this into whatever response already runs next
    as a brief factual addendum (see render("booking_draft_switch", ...)),
    never a new blocking question.

    DATE switch detection compares booking_draft_date ONLY — never
    conversation.booking_draft_search_anchor_date, which
    _propose_available_slots writes as its own internal "search from here"
    bookkeeping (see that column's docstring). This function is the ONLY
    writer of booking_draft_date/booking_draft_service_id/
    booking_draft_time, so all three are genuinely customer-stated facts,
    safe to compare directly for a real switch judgment. (A real false
    positive from an earlier version of this fix — a customer's FIRST real
    date being misreported as "switching FROM" the search anchor — is what
    made this separation necessary; see PHASE_STATUS.md.)

    Phase 13 (2026-09-19 series) — a real live bug: a customer asked for a
    closed day, the SYSTEM offered the next open day's slots, the customer
    picked "first one", and the reply then restated "Sunday ... instead of
    Monday ..." — a change the customer never initiated (nothing was silent:
    they had just been shown the alternative). `offered_slots` is the list
    the system showed on the previous turn; when this turn's date/time is a
    pick from it (see _offered_slot_pick) the date/time still moves into the
    draft — including landing on the OFFERED day when the LLM only extracted
    the slot's time and the draft still held the requested (closed) day —
    but is not reported as a switch. Only a date/time the customer states on
    their own, that the system did not offer, is a genuine switch."""
    if not booking_request:
        return []
    switches: list[tuple[str, str]] = []

    service_name = booking_request.get("service")
    if service_name:
        service = _resolve_service_by_name(services, service_name)
        if service is not None and service.id != conversation.booking_draft_service_id:
            if conversation.booking_draft_service_id is not None:
                old_service = next((s for s in services if s.id == conversation.booking_draft_service_id), None)
                if old_service is not None:
                    switches.append((old_service.name, service.name))
            conversation.booking_draft_service_id = service.id

    date_str = booking_request.get("date")
    time_str = booking_request.get("time")
    is_pick, offered_day = _offered_slot_pick(
        offered_slots, tz, date_str if date_str and _is_valid_date_str(date_str) else None,
        time_str if time_str and _is_valid_time_str(time_str) else None,
    )
    if is_pick and not date_str and offered_day:
        date_str = offered_day  # time-only pick: land on the offered day, not the requested (possibly closed) one

    if date_str and _is_valid_date_str(date_str) and date_str != conversation.booking_draft_date:
        if conversation.booking_draft_date is not None and not is_pick:
            switches.append((_format_date_only(conversation.booking_draft_date, language), _format_date_only(date_str, language)))
        conversation.booking_draft_date = date_str

    if time_str and _is_valid_time_str(time_str) and time_str != conversation.booking_draft_time:
        if conversation.booking_draft_time is not None and not is_pick:
            switches.append((_format_time_only(conversation.booking_draft_time, language), _format_time_only(time_str, language)))
        conversation.booking_draft_time = time_str

    return switches


def _effective_draft_date(conversation: Conversation) -> str | None:
    """The ONLY place these two real, distinct pieces of state are combined
    into a single "what date are we working with" answer — real customer
    intent (booking_draft_date) takes priority; the internal availability-
    search anchor (booking_draft_search_anchor_date) is a fallback ONLY, for
    completing a booking whose date was never actually stated by the
    customer (see the column's own docstring). `_merge_booking_draft`'s
    switch-detection deliberately does NOT use this — it compares
    booking_draft_date alone, since a switch judgment must never be
    triggered by Python's own bookkeeping."""
    return conversation.booking_draft_date or conversation.booking_draft_search_anchor_date


def _resolve_booking_draft(
    conversation: Conversation, services: list[Service], business: Business
) -> tuple[Service | None, datetime | None]:
    """Re-resolves the persisted draft against REAL current data every turn
    — never a raw presence check — so a draft referencing an archived/
    deleted service, or (vanishingly unlikely, since each field is format-
    validated at merge time) a date/time pair that fails to combine, is
    correctly treated as still incomplete rather than silently booked."""
    service = None
    if conversation.booking_draft_service_id is not None:
        service = next((s for s in services if s.id == conversation.booking_draft_service_id), None)
    scheduled_at = None
    effective_date = _effective_draft_date(conversation)
    if effective_date and conversation.booking_draft_time:
        scheduled_at = _resolve_booking_datetime(business, effective_date, conversation.booking_draft_time)
    return service, scheduled_at


def _describe_known_booking_slots(
    conversation: Conversation, services: list[Service], business: Business, language: str | None = None
) -> str | None:
    """Phase 25a-2 — root-cause fix for the "feels robotic" regression: real
    adversarial testing found the contact-info gate repeating one identical
    static sentence turn after turn while service/date/time genuinely
    accumulated in the background (confirmed by direct DB draft-state
    queries — the merge itself was already correct; only the customer-facing
    message never reflected it). Builds a short, human-readable description
    of whatever the persisted draft already has, so render_contact_gate can
    compose a sentence that visibly progresses as real information arrives.
    Returns None when nothing is known yet (draft fully empty) — the gate
    then falls back to the plain "nothing to acknowledge" wording."""
    service = None
    if conversation.booking_draft_service_id is not None:
        service = next((s for s in services if s.id == conversation.booking_draft_service_id), None)

    date_str, time_str = _effective_draft_date(conversation), conversation.booking_draft_time
    when = None
    if date_str and time_str:
        dt = _resolve_booking_datetime(business, date_str, time_str)
        if dt is not None:
            when = _format_local(dt, ZoneInfo(business.timezone), language)
    if when is None and date_str and _is_valid_date_str(date_str):
        when = _format_date_only(date_str, language)
    elif when is None and time_str and _is_valid_time_str(time_str):
        when = _format_time_only(time_str, language)

    parts = [p for p in (service.name if service else None, when) if p]
    return ", ".join(parts) if parts else None


def _booking_draft_missing(conversation: Conversation, service: Service | None, scheduled_at: datetime | None) -> list[str]:
    missing = []
    if service is None:
        missing.append("service")
    if scheduled_at is None:
        effective_date = _effective_draft_date(conversation)
        if not effective_date:
            missing.append("date")
        if not conversation.booking_draft_time:
            missing.append("time")
        if effective_date and conversation.booking_draft_time:
            # Both individually well-formed (format-validated at merge time)
            # but failed to resolve together — should not happen in practice,
            # but never silently treat as complete: ask for both again
            # rather than guess which one was actually the problem.
            missing.extend(["date", "time"])
    return missing


def _clear_booking_draft(conversation: Conversation) -> None:
    conversation.booking_draft_service_id = None
    conversation.booking_draft_date = None
    conversation.booking_draft_search_anchor_date = None
    conversation.booking_draft_time = None


def _clear_booking_draft_after_attempt(
    conversation: Conversation, result: dict, scheduled_at: datetime, tz: ZoneInfo
) -> None:
    """Phase 25a-2 — root-cause fix for the second real regression found live:
    a failed booking attempt (the specific date+time turned out to be
    unavailable) was clearing the ENTIRE draft, forcing the customer to
    re-state a service that was never actually invalid. On success, the
    draft's job is simply done (unchanged from Phase 25a). On failure, the
    service always survives — only the requested time is definitely
    invalidated by a failed attempt. Whether the DATE also survives is
    decided from the tool's own real `alternative_slots` (never guessed):
    if a real opening still exists somewhere on that SAME calendar day, the
    date was fine and only the time needs re-specifying; if the whole day
    has nothing available (closed day, fully booked), the date is cleared
    too rather than silently re-presenting an invalid day as if it still
    holds. Shared by both call sites that can complete a booking attempt
    (the main single-booking dispatch and the off-intent completion path)
    so this fix can't be missed in one of them."""
    if result["success"]:
        _clear_booking_draft(conversation)
        return
    conversation.booking_draft_time = None
    requested_date = scheduled_at.astimezone(tz).date()
    alternatives = result.get("alternative_slots") or []
    if not any(alt.astimezone(tz).date() == requested_date for alt in alternatives):
        conversation.booking_draft_date = None
        conversation.booking_draft_search_anchor_date = None


def _has_partial_booking_draft(conversation: Conversation) -> bool:
    return bool(
        conversation.booking_draft_service_id is not None
        or conversation.booking_draft_date
        or conversation.booking_draft_time
    )


def _resolve_known_appointment(context: dict | None, appointment_id_str: str | None) -> uuid.UUID | None:
    """Exact match against this customer's own active OR recent-past appointments
    (both already tenant/customer-scoped by Phase 7's appointment context) — never
    trusts the LLM's string directly. A recent-past match (e.g. already cancelled)
    is deliberately allowed to resolve: it lets the real tool run and honestly
    report "already cancelled" instead of silently falling back to a clarifying
    question, which is what the hallucination-proof test for this phase checks.
    Anything not in either list (ambiguous, or a hallucinated id) resolves to
    None — never a guess."""
    if not appointment_id_str or not context:
        return None
    appointments = context.get("appointments") or {}
    known_ids = {a["id"] for a in appointments.get("active", [])} | {a["id"] for a in appointments.get("recent_past", [])}
    if appointment_id_str not in known_ids:
        return None
    try:
        return uuid.UUID(appointment_id_str)
    except ValueError:
        return None


def _confirmation_extras(confirmation: dict | None, customer_name: str | None, language: str | None) -> str:
    """The email-level detail lines under a booking confirmation (who it's for, where, the check-in QR link, and — only
    when the confirmation email was really sent — a note saying so), from BookAppointmentTool._confirmation_info's real
    data. Empty when the tool supplied none, which keeps every other caller's message unchanged."""
    if not confirmation:
        return ""
    lines = []
    if customer_name:
        lines.append(render("booking_for", language, customer=customer_name))
    if confirmation["place"]:
        lines.append(render("booking_where", language, place=confirmation["place"]))
    # None when backend_base_url was refused (see qr_link_service.build_url) -- the
    # booking itself already succeeded, so this omits the QR line rather than ever
    # formatting a None into customer-facing text.
    if confirmation["checkin_qr_url"]:
        lines.append(render("booking_checkin_qr", language, url=confirmation["checkin_qr_url"]))
    if confirmation["email_to"]:
        lines.append(render("booking_email_note", language, email=confirmation["email_to"]))
    return "\n" + "\n".join(lines)


def _format_booking_result(
    result: dict, *, service: Service, tz: ZoneInfo, customer_name: str | None, language: str | None
) -> str:
    """The ONLY place a booking confirmation or failure sentence is composed —
    deliberately deterministic Python string formatting (via response_templates.
    render, Phase 25 — see its module docstring for why the scaffold text is
    translated but embedded data like service names/dates isn't), never LLM
    narration, off the tool's real result dict. This is what makes the
    master-plan rule ("the LLM must never be trusted to directly report
    booked") actually airtight rather than just a prompt instruction: nothing
    here can be influenced by anything the model wrote."""
    who = f", {customer_name}" if customer_name else ""
    if result["success"]:
        appointment = result["appointment"]
        when = _format_local(appointment["scheduled_at"], tz, language)
        payment = result.get("payment")
        extras = _confirmation_extras(result.get("confirmation"), customer_name, language)
        if payment is None:
            return render(
                "booking_success",
                language,
                who=who,
                service=service.name,
                when=when,
                duration=str(appointment["duration_minutes"]),
                id=appointment["confirmation_code"],
            ) + extras
        # Phase 44/47: a real Payment row exists (or the customer still has to pick a gateway) — the slot IS reserved,
        # but not yet paid for, so this reads as "reserved, pending your deposit", never "you're all set" (that
        # wording is kept for the payment-received message). See response_templates.TEMPLATES["booking_reserved_pay"].
        fields = dict(
            who=who, service=service.name, when=when, id=appointment["confirmation_code"], currency=payment["currency"],
            amount=str(payment["amount"]), remaining=str(payment["remaining"]),
        )
        if payment["payment_url"] is None:
            # the business offers both gateways and none is chosen yet: ask (see _payment_choice_turn)
            return render("booking_reserved_choose", language, **fields) + extras
        # payment["qr_url"] (payment_service.qr_page_url) can never be the refused-URL
        # None here specifically: it reads the exact same backend_base_url/environment
        # as payment["payment_url"] (payment_service.build_pay_qr... via the gateway's
        # own initiate_payment), which already succeeded moments earlier in this same
        # request -- those settings don't change mid-process, so if one was safe the
        # other is too. See qr_link_service.build_url's docstring for the case that IS
        # reachable (the check-in QR above, an independent call with no such guarantee).
        return render("booking_reserved_pay", language, link=payment["payment_url"], qr=payment["qr_url"], **fields) + extras

    message = result["message"].rstrip(".").lower()
    alternatives = result.get("alternative_slots") or []
    if alternatives:
        options = (
            ", ".join(_format_local(slot, tz) for slot in alternatives)
            if language in (None, ConversationLanguage.EN.value)
            else _format_slot_options(alternatives, tz, language)
        )
        return render(
            "booking_unavailable_with_alts", language, who=who, message=message, service=service.name, options=options
        )
    return render("booking_unavailable_no_alts", language, who=who, message=message, service=service.name)


# Phase 33: how many real slots to show back, and how many days ahead to
# search for them — a chat reply, not a slot-picker UI, same reasoning as
# BookAppointmentTool._alternatives (booking_tool.py), duplicated here rather
# than imported for the same reason booking_service._fresh_alternatives
# duplicates it: this is a small, self-contained piece of formatting logic,
# not worth a cross-module dependency for two integers.
_AVAILABILITY_SLOTS_COUNT = 5
_AVAILABILITY_SEARCH_DAYS = 7


def _service_bridge(service: Service, customer_message: str, previous_reply: str | None, language: str | None) -> str:
    """trekking-10: one line saying which service this booking goes through, when the customer never named it
    ("reserve a spot on the Annapurna Circuit" resolves to Trek Booking Consultation) -- otherwise the slot list
    replaces the model's reply and the bridge is lost. Once per service: skipped if our previous reply already named
    it. ponytail: literal name check, so paraphrases ("a cleaning") and every Devanagari message also get the
    (redundant but true) line; an LLM "asked for something else" flag is the upgrade if that proves annoying."""
    name = re.sub(r"\s*\(.*?\)", "", service.name).strip().lower()
    if name in customer_message.lower() or (previous_reply and service.name in previous_reply):
        return ""
    return render("booking_service_bridge", language, service=service.name, description=service.description or "").strip() + " "


def _keep_draft_price(template_reply: str, draft: str | None, services: list[Service]) -> str:
    """A fixed template (slot list, opening hours) replaces the model's draft, which dropped the other half of a
    two-question message: "Is Passport Photo available on Sunday? ani kati parcha?" got the slots but not the price
    (simulator 2026-10-01, photo/mixed). Keeps the draft's first sentence that names a service together with that
    service's real configured price, if the template doesn't already state a price."""
    if not draft or _PRICE_RE.search(template_reply):
        return template_reply
    for sentence in _SENTENCE_SPLIT_RE.split(draft):
        for _, amount in _PRICE_RE.findall(sentence):
            if any(
                s.name.lower() in sentence.lower() and float(s.price) and abs(float(amount.replace(",", "")) - float(s.price)) < 0.01
                for s in services
            ):
                return f"{sentence.strip()} {template_reply}"
    return template_reply


def _propose_available_slots(
    db: Session,
    *,
    business_id: uuid.UUID,
    service: Service,
    conversation: Conversation,
    tz: ZoneInfo,
    language: str | None,
    previous_reply: str | None = None,
    requested_time_unavailable: bool = False,
    customer_message: str = "",
) -> str:
    """Phase 33 — the ONLY place a "here's what's open" sentence is composed,
    same discipline as every other _format_*_result function: real,
    freshly-computed booking_service.get_available_slots data, never
    anything the LLM invented. Never books anything itself — the customer
    still has to pick one, which flows into the exact same booking-completion
    logic as any other explicitly-given date/time (see the dispatch branch
    below).

    If the customer already named a specific day (conversation.
    booking_draft_date, persisted by the normal draft-merge mechanism — see
    _merge_booking_draft) or a prior search already anchored one (this
    function's own booking_draft_search_anchor_date, see _effective_draft_
    date), the search starts there; otherwise it starts today. Either way
    this is a single get_available_slots call over one contiguous window —
    the earliest real slots it returns naturally answer both cases: if the
    requested day itself has openings, they're the first ones back; if not,
    the first slots back land on whatever the next real open day is, which
    is exactly the honest "nothing that day, but here's the next real
    opening" case the ticket requires. An empty result means genuinely no
    openings anywhere in the window — never presented as a silent empty
    list."""
    requested_date_str = _effective_draft_date(conversation)
    if requested_date_str and _is_valid_date_str(requested_date_str):
        search_start = datetime.strptime(requested_date_str, "%Y-%m-%d").date()
    else:
        search_start = datetime.now(tz).date()

    try:
        slots = booking_service.get_available_slots(
            db,
            business_id=business_id,
            service_id=service.id,
            staff_id=None,
            date_from=search_start,
            date_to=search_start + timedelta(days=_AVAILABILITY_SEARCH_DAYS),
        )
    except NotFoundError:
        slots = []

    unavailable_prefix = f"{render('requested_time_unavailable', language)} " if requested_time_unavailable else ""

    if not slots:
        return unavailable_prefix + render("availability_none_no_alts", language, service=service.name)

    # Phase 33b — real live testing found picking a shown option purely by time
    # ("10:30am works") unreliably re-stated the date back (an LLM judgment
    # call, not always made — see PHASE_STATUS.md). The date of the first real
    # slot just shown is something Python already knows for certain (it's what
    # was just searched and displayed) — persisting it here means the next
    # turn's merge/resolve completes correctly even if the LLM's own
    # extraction leaves `date` null, same "Python decides, LLM only observes"
    # discipline as every other persisted draft field.
    #
    # Real root-cause fix (PHASE_STATUS.md — the DATE-switch false positive
    # that originally forced date out of _merge_booking_draft's switch
    # detection): this write goes to booking_draft_search_anchor_date, NEVER
    # booking_draft_date — this is Python's own internal "here's what's
    # open" bookkeeping, not a customer commitment, even when it happens to
    # equal a date the customer separately did state. Keeping it in its own
    # column is what makes it safe to bring DATE back into switch detection
    # (see _merge_booking_draft): a real switch judgment now only ever
    # looks at booking_draft_date, which THIS function never touches.
    conversation.booking_draft_search_anchor_date = slots[0].astimezone(tz).strftime("%Y-%m-%d")

    shown_slots = slots[:_AVAILABILITY_SLOTS_COUNT]
    # Real conversation-quality audit finding (§50, "don't create an LLM call
    # for everything"): persist exactly the slots the customer is about to
    # see, as real UTC timestamps, so a bare-digit reply next turn
    # (_resolve_bare_digit_slot_pick) can resolve "2" to a real, known slot
    # deterministically instead of round-tripping through the LLM to guess
    # what "2" means. One-shot: handle_incoming_message clears this again
    # right after checking it on the very next turn, whether or not that
    # turn actually was a digit pick.
    conversation.booking_draft_proposed_slots = ",".join(
        slot.astimezone(ZoneInfo("UTC")).isoformat() for slot in shown_slots
    )

    options = _format_slot_options(shown_slots, tz, language)
    if requested_date_str and _is_valid_date_str(requested_date_str) and slots[0].astimezone(tz).date() != search_start:
        reply = render(
            "availability_none_with_next_day",
            language,
            service=service.name,
            requested=_format_date_only(requested_date_str, language),
            options=options,
        )
    else:
        reply = render("availability_options", language, service=service.name, options=options)
    reply = unavailable_prefix + reply
    # Live bug (2026-09-20): "Monday morning instead, does that work?" / "can you book that for me?" carry no specific
    # time, so the extraction keeps wants_availability=true and the identical list came back turn after turn (7+ times
    # in the 653 real conversations). The same list pasted again never moves the customer forward: when one of our
    # last two replies already showed exactly these times, point back at it and ask for the one missing piece -- which
    # time -- instead. (The slots stay persisted above, so a digit still works.)
    if options in (previous_reply or "") or already_sent(options, within=2):
        return unavailable_prefix + render("availability_refer_back", language)
    return _service_bridge(service, customer_message, previous_reply, language) + reply


_REPLY_HISTORY_LIMIT = 40


def _agent_reply_history(db: Session, conversation_id: uuid.UUID) -> list[str]:
    """Our last replies in this conversation, oldest first (the current turn's reply isn't persisted yet)."""
    rows = db.execute(
        select(Message.content)
        .where(Message.conversation_id == conversation_id, Message.sender_type == MessageSenderType.AGENT)
        .order_by(Message.created_at.desc())
        .limit(_REPLY_HISTORY_LIMIT)
    ).scalars().all()
    return [r for r in reversed(rows) if r]


def _customer_texts(db: Session, conversation_id: uuid.UUID, current: str) -> list[str]:
    rows = db.execute(
        select(Message.content)
        .where(Message.conversation_id == conversation_id, Message.sender_type == MessageSenderType.CUSTOMER)
        .order_by(Message.created_at.desc())
        .limit(_REPLY_HISTORY_LIMIT)
    ).scalars().all()
    return [current, *[r for r in rows if r]]


def _last_agent_reply(db: Session, conversation_id: uuid.UUID) -> str | None:
    """The most recent reply WE sent in this conversation (the current customer message is persisted only at the end
    of the turn, so at dispatch time this is still the previous turn's reply)."""
    return db.execute(
        select(Message.content)
        .where(Message.conversation_id == conversation_id, Message.sender_type == MessageSenderType.AGENT)
        .order_by(Message.created_at.desc())
        .limit(1)
    ).scalar_one_or_none()


# Root-cause fix for a confirmed missed_escalation bug (read-through of
# backend/data/regression/failure_log_batches/batch5_testchat_misc.json,
# conversation 7f72b8f1): a customer stuck in a non-progressing booking-confirmation
# loop (the agent repeating a near-identical reply turn after turn) called the agent
# "dumb" and still got no escalation. `_STUCK_LOOP_SIMILARITY` is the minimum
# difflib.SequenceMatcher ratio (case-insensitive) for two replies to count as "the same
# thing, reworded" -- calibrated against the real transcript's two near-duplicate replies
# ("Great — to confirm: ... Shall I check availability now?" / "I can help with that. You
# want a Teeth Cleaning ... shall I check availability now?").
_STUCK_LOOP_SIMILARITY = 0.5


def _is_stuck_in_a_loop(db: Session, conversation_id: uuid.UUID, drafted_reply: str) -> bool:
    """True when the reply about to be sent is substantially the same as EACH of the last
    two replies we already sent -- i.e. this would be the 3rd near-identical reply in a
    row, the deterministic, code-visible signal for "the agent has failed to resolve the
    same request repeatedly" (no NLP, no new persisted state -- just the real message
    history, same discipline as _last_agent_reply above).

    Requires the drafted reply to itself be a QUESTION: a real, repeated-but-successful
    deterministic confirmation (e.g. three separate "your confirmation is on its way"
    resend replies -- same real fixed template, same real inputs, correctly identical
    every time) is not a stuck loop, it's the agent doing its job three times in a row.
    Only "the agent is still asking, still not getting anywhere" repeats."""
    if "?" not in drafted_reply:
        return False
    recent = db.execute(
        select(Message.content)
        .where(Message.conversation_id == conversation_id, Message.sender_type == MessageSenderType.AGENT)
        .order_by(Message.created_at.desc())
        .limit(2)
    ).scalars().all()
    if len(recent) < 2:
        return False
    drafted_lower = drafted_reply.lower()
    return all(
        difflib.SequenceMatcher(None, drafted_lower, prior.lower()).ratio() >= _STUCK_LOOP_SIMILARITY
        for prior in recent
    )


# Root-cause fix for a confirmed missed_escalation bug (same read-through, conversation
# fb325df3): a customer described a 9/10 toothache with overnight swelling and asked to be
# seen ASAP, and got a plain "I'll need a way to reach you" with no urgency acknowledged at
# all. Deliberately keyword-based, same discipline as _CLOSED_WORDS/_DEPOSIT_WORDS
# (fact_validator.py) -- a real clinical triage classifier is a much larger, separate
# problem than this codebase takes on anywhere else.
# ponytail: keyword match, no tense/hypothetical detection ("if I ever have an emergency,
# can I message you?" also matches) -- erring toward over-escalating a described medical
# emergency is the right side to be wrong on. Deliberately excludes bare "bleeding"/
# "swelling" (routine procedure-info questions like "how much bleeding is normal after an
# extraction?" mention them without being an emergency) -- only an explicit urgency word or
# a stated pain intensity counts. Upgrade path: only if false escalations on hypothetical/
# past-tense mentions turn out to be a real, measured problem in practice.
#
# "asap"/"right now" are split out from the unambiguous words below (real transcript check,
# 597-case regression dataset: "I don't have money right now" / "I don't have to pay 1%
# right now" are ordinary payment-timing remarks, not emergencies) -- they only count
# alongside a real "come see me" request, never bare.
_EMERGENCY_STRONG_RE = re.compile(
    r"\b(emergency|severe pain|excruciating|unbearable pain|heavy bleeding|9/10|10/10)\b", re.I
)
_EMERGENCY_URGENCY_RE = re.compile(r"\b(asap|a\.s\.a\.p|right now)\b", re.I)
_EMERGENCY_WANTS_TO_BE_SEEN_RE = re.compile(r"\b(see me|come in|be seen|look at (it|me|this)|visit)\b", re.I)


def _is_medical_emergency(text: str) -> bool:
    if _EMERGENCY_STRONG_RE.search(text):
        return True
    return bool(_EMERGENCY_URGENCY_RE.search(text) and _EMERGENCY_WANTS_TO_BE_SEEN_RE.search(text))


# "talk to staff / a real person / someone from the team" in English, Roman Nepali and Devanagari. The doctor/guide
# is deliberately not a person here: "doctor sanga kura garne" is a consultation booking, not a handoff.
_HUMAN_NOUNS_EN = (
    r"(?:a |an |the |your |some )?(?:real |actual |live )?"
    r"(?:person|human|staff|agent|representative|rep|someone|somebody|team member|team|manager|receptionist|"
    r"operator|front desk)"
)
_HUMAN_REQUEST_RE = re.compile(
    rf"\b(?:talk|speak|chat)\s+(?:directly\s+)?(?:to|with)\s+{_HUMAN_NOUNS_EN}\b"
    rf"|\b(?:get|connect|transfer|put)\s+me\s+(?:through\s+)?(?:to\s+|with\s+)?{_HUMAN_NOUNS_EN}\b"
    r"|\b(?:staff|manche|manchhe|manxe|manis|human|person|kasai|kosai|team|manager)\s*(?:sanga|sang|sita)\s+"
    r"(?:direct\s+|sidhai\s+|sidhae\s+)?(?:kura|bolna|bolne|kurakani|contact|connect)"
    r"|(?:स्टाफ|कर्मचारी|मान्छे|मानिस|व्यक्ति|कसै|टिम|म्यानेजर)\s*(?:सँग|संग|सित)\s*(?:सिधै\s*|सीधै\s*|प्रत्यक्ष\s*)?"
    r"(?:कुरा|बोल्न|सम्पर्क)",
    re.I,
)


def _is_explicit_human_request(text: str) -> bool:
    return bool(_HUMAN_REQUEST_RE.search(text))


_BARE_DIGIT_RE = re.compile(r"^[1-9]$")


def _resolve_bare_digit_slot_pick(conversation: Conversation, content: str) -> datetime | None:
    """Real, scoped fix for the conversation-quality audit's §50 finding
    ("don't create an LLM call for everything"): when a slot list was just
    shown (_propose_available_slots persisted the real, exact slots into
    conversation.booking_draft_proposed_slots) and the customer's ENTIRE next
    message reduces to a single bare digit, that digit unambiguously means
    "the Nth option shown" — a real, already-known value, never worth a full
    LLM round trip to (mis)interpret. Deliberately narrow: only a message
    that IS just the digit, nothing else, counts — this never touches an
    ordinal WORD reply ("second one"), which already resolves correctly
    through the normal LLM path (real transcript evidence, PHASE_STATUS.md)
    and is left completely alone. Returns the real slot datetime for a valid
    in-range pick, or None for anything else (no proposed slots on file, an
    out-of-range digit, or a message that isn't a bare digit at all) — None
    always means "fall through to the normal LLM-classification path
    unchanged," never a guess."""
    if not conversation.booking_draft_proposed_slots:
        return None
    if not _BARE_DIGIT_RE.match(content.strip()):
        return None
    slots = [datetime.fromisoformat(s) for s in conversation.booking_draft_proposed_slots.split(",")]
    index = int(content.strip()) - 1
    if not (0 <= index < len(slots)):
        return None
    return slots[index]


def _format_group_booking_result(
    result: dict, *, services: list[Service], tz: ZoneInfo, customer_name: str | None, language: str | None
) -> str:
    """Same discipline as _format_booking_result, extended for N people: every
    line comes straight from the tool's real per-booking result, so a partial
    outcome is reported honestly (who's in, who isn't, and why) rather than
    collapsed into a single claim of success or failure."""
    services_by_id = {str(s.id): s for s in services}
    who = f", {customer_name}" if customer_name else ""

    def describe(booking: dict) -> str:
        people = " and ".join(booking["labels"])
        if booking["success"]:
            appointment = booking["appointment"]
            service = services_by_id.get(appointment["service_id"])
            service_name = service.name if service else "the service"
            when = _format_local(appointment["scheduled_at"], tz, language)
            return render(
                "group_line_success",
                language,
                people=people,
                service_name=service_name,
                when=when,
                duration=str(appointment["duration_minutes"]),
                id=appointment["confirmation_code"],
            )
        return render("group_line_fail", language, people=people, message=booking["message"].rstrip(".").lower())

    lines = "; ".join(describe(b) for b in result["bookings"])
    if result["success"]:
        intro = render("group_intro_success", language, who=who)
    elif result["all_or_nothing"]:
        intro = render("group_intro_all_or_nothing_fail", language, who=who)
    else:
        intro = render("group_intro_partial", language, who=who)
    return f"{intro} {lines}."


def _format_cancellation_result(result: dict, *, tz: ZoneInfo, customer_name: str | None, language: str | None) -> str:
    """Same discipline as _format_booking_result: the only place a cancellation
    confirmation or failure sentence is composed, off the tool's real result."""
    who = f", {customer_name}" if customer_name else ""
    if result["success"]:
        when = _format_local(result["appointment"]["scheduled_at"], tz, language)
        return render("cancellation_success", language, who=who, when=when)
    return render("cancellation_fail", language, who=who, message=result["message"].rstrip(".").lower())


def _format_reschedule_result(result: dict, *, tz: ZoneInfo, customer_name: str | None, language: str | None) -> str:
    who = f", {customer_name}" if customer_name else ""
    if result["success"]:
        when = _format_local(result["appointment"]["scheduled_at"], tz, language)
        return render("reschedule_success", language, who=who, when=when)
    return render("reschedule_fail", language, who=who, message=result["message"].rstrip(".").lower())


def _format_appointment_status_result(
    result: dict, *, tz: ZoneInfo, customer_name: str | None, language: str | None
) -> str:
    """The ONLY place an appointment-status answer is composed — deterministic
    Python reading AppointmentStatusTool's real, freshly-queried result, never
    the LLM's own reading of the conversation summary/memory. This is what
    makes "the real DB always wins over stale memory" airtight rather than a
    prompt instruction the model could still get wrong (see Phase 14's
    staleness-proof test)."""
    who = f", {customer_name}" if customer_name else ""
    active = result["active"]
    recent_past = result["recent_past"]

    def describe(a: dict) -> str:
        when = _format_local(datetime.fromisoformat(a["scheduled_at"]), tz, language)
        return render("status_describe", language, service=a["service"], when=when, id=a["confirmation_code"])

    if not active and not recent_past:
        return render("status_none", language, who=who)

    parts = []
    if not active:
        parts.append(render("status_no_active", language, who=who))
    elif len(active) == 1:
        parts.append(render("status_one_active", language, who=who, desc=describe(active[0]), status=active[0]["status"]))
    else:
        lines = "; ".join(describe(a) for a in active)
        parts.append(render("status_multi_active", language, who=who, n=str(len(active)), lines=lines))

    if recent_past:
        lines = "; ".join(f"{describe(a)} — {a['status']}" for a in recent_past)
        parts.append(render("status_recent_past", language, lines=lines))

    return " ".join(parts)


def _format_resend_result(result: dict, *, language: str | None) -> str:
    """The ONLY place a resend-confirmation reply is composed — deterministic Python reading ResendConfirmationTool's
    real result, same discipline as every other _format_*_result function (rule 13: the LLM never gets to claim this
    happened). Each delivery type reports honestly and independently: an email problem never hides a working QR link."""
    if result["rate_limited"]:
        return render("resend_rate_limited", language)
    if result.get("throttled"):
        return render("resend_send_failed", language)
    if result["message"]:
        return render("resend_fail", language, message=result["message"].rstrip(".").lower())

    channels = result["channels"]
    parts: list[str] = []
    email = channels.get("email")
    if email is not None:
        if email["status"] in ("sent", "simulated"):
            parts.append(render("resend_email_sent", language, to=email["to"]))
        elif email["status"] == "no_recipient":
            parts.append(render("resend_no_recipient", language, channels="email"))
        else:
            parts.append(render("resend_send_failed", language))
    chat = channels.get("chat")
    if chat is not None:
        if chat["status"] == "sent":
            parts.append(render("resend_qr_link", language, url=chat["url"]))
        else:
            parts.append(render("resend_send_failed", language))
    return "\n".join(parts) if parts else render("resend_send_failed", language)


def _resend_needs_front_desk(result: dict) -> str | None:
    """The real reason to open a HumanHandoff after a resend turn — or None. The rate-limited and send-failed replies
    both PROMISE "let me connect you with our front desk"; that promise must be backed by a real handoff row."""
    if result["rate_limited"]:
        return "Customer hit the confirmation/QR resend limit (3) for an appointment and was told to contact the front desk."
    if result.get("throttled"):
        return "Repeated confirmation/QR sends for an appointment failed; the customer was told to contact the front desk."
    if result["message"]:
        return None
    statuses = [c["status"] for c in result["channels"].values()]
    if statuses and not any(x in ("sent", "simulated") for x in statuses) and "failed" in statuses:
        return "Sending the customer's appointment confirmation/QR failed; the customer was told to contact the front desk."
    return None


def _off_topic_response(business: Business | None, language: str | None) -> str:
    """The ONLY place an off_topic decline is composed — deterministic Python,
    never the LLM's own drafted text for this turn. Real testing found the LLM
    answering a general-knowledge question with real historical information
    despite the system prompt's scope rule (rule 0 in intent.py); overriding
    here closes that gap completely rather than trusting the prompt alone a
    second time. Deliberately does NOT go through handoff_service — an
    out-of-scope question isn't something staff need to follow up on (see
    ConversationIntent.OFF_TOPIC's docstring)."""
    name = business.name if business else "this business"
    return render("off_topic", language, name=name)


def _emergency_response(business: Business | None, language: str | None) -> str:
    """The ONLY place a described-emergency reply is composed -- deterministic override,
    never the LLM's own drafted text (see the confirmed bug this fixes: a stated 9/10
    toothache with overnight swelling got a plain "I'll need a way to reach you" back, no
    urgency acknowledged at all). Minimum viable version per the read-through: an honest,
    direct instruction to call/visit the clinic right away -- no real "book an emergency
    slot" mechanism exists in this codebase to route this into instead. Always paired with
    a real HumanHandoff (see escalation_front_desk_reason below) so staff see it too."""
    # English reads "call us at 98...", Nepali "hamilai (98...) phone garnus" -- never an English "at" mid-Nepali.
    phone = ""
    if business and business.phone:
        phone = f" at {business.phone}" if language in (None, ConversationLanguage.EN.value) else f" ({business.phone})"
    return render("emergency_handoff", language, phone=phone)


# Real bug found live (Samaj Dental Clinic transcript): "mero email samratghimire01@gmail.com
# ho yes ma malai conformation ko mail send gardenu na" -- the email is embedded mid-sentence in
# a longer Romanized-Nepali/English message, and the LLM's own rule-14 extraction (intent.py)
# missed it, so the agent claimed "I don't have your email on record" in the SAME turn the
# customer gave it. An email address is mechanically, deterministically checkable -- never worth
# leaving entirely to an LLM judgment call when regex can answer for certain, same discipline as
# orchestrator._DEVANAGARI_RE below. Used only as a FALLBACK when the LLM's own extraction came
# back empty, never overriding a real extracted value.
_EMAIL_FALLBACK_RE = re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}")


def _fallback_extract_email(message: str) -> str | None:
    match = _EMAIL_FALLBACK_RE.search(message)
    return match.group(0) if match else None


def _resolve_contact_update(
    customer: Customer | None, contact_info_update: dict | None, raw_message: str = ""
) -> dict:
    """Re-diffs the LLM's candidate `contact_info_update` against the REAL
    current Customer row — never trusts the LLM's own claim about what's
    already on file (rule 14 in intent.py only asks it to try). A field is
    only included if the customer's Customer row genuinely doesn't already
    have that exact value. This is what makes UpdateContactInfoTool.run()
    only ever write real, actually-new information, and lets the caller
    detect "nothing to do" (empty dict) without invoking the tool at all.

    `raw_message` backstops a missed email with `_fallback_extract_email` (see its own
    comment) -- only when the LLM didn't already report one itself; a bogus regex match
    (an email-shaped false positive) is still caught by UpdateContactInfoTool's real
    `CustomerUpdate(EmailStr)` validation before anything is ever written."""
    if customer is None:
        return {}
    candidate = dict(contact_info_update or {})
    if not candidate.get("email"):
        fallback_email = _fallback_extract_email(raw_message)
        if fallback_email:
            candidate["email"] = fallback_email
    changed = {}
    for field, value in candidate.items():
        if value and value != getattr(customer, field, None):
            changed[field] = value
    return changed


def _format_contact_update_result(result: dict, language: str | None) -> str | None:
    """The ONLY place a contact-info-update or notification-resend
    confirmation is composed — deterministic Python off the tool's real
    result, same discipline as every other _format_*_result function in this
    file. This is the fix for the Phase 23 hallucination bug: the LLM is now
    forbidden (intent.py rule 13) from claiming this itself; this function is
    what actually tells the customer, and only when it's real. A resend is
    only ever mentioned when its real status is SENT/DELIVERED — a
    SIMULATED resend (no real provider configured) is deliberately NOT
    reported as success, same honesty discipline as Phase 13/15's
    SIMULATED-vs-SENT distinction: never tell a customer "you'll receive it"
    when nothing real was actually sent."""
    if not result.get("success") or not result.get("updated_fields"):
        return None
    parts = [render("contact_updated", language)]
    real_resends = [
        r for r in result.get("resends", [])
        if r["status"] in (NotificationStatus.SENT.value, NotificationStatus.DELIVERED.value)
    ]
    if real_resends:
        parts.append(render("contact_resent", language))
    return " ".join(parts)


_VALID_LANGUAGES = {v.value for v in ConversationLanguage}
# A reply that already tells the customer the team will follow up (handoff_addendum would only repeat it).
_TEAM_FOLLOWUP_RE = re.compile(
    r"\b(team|staff|doctor|manager)\b[^.?!\n]{0,60}(\b(contact|call|connect|jod|bhan|sodh|bujh|inform|khabar|share|get back|"
    r"follow up|reach out|phone|sampark)|सम्पर्क)"
    r"|\b(connect|jod)\w*\b[^.?!\n]{0,30}\b(team|staff)\b"
    r"|टिम[^।?!\n]{0,40}(सम्पर्क|खबर|सोध|भन)",
    re.IGNORECASE,
)
# Intents whose reply is the model's own free text (every other intent is replaced by a deterministic template).
_VOICE_PASS_INTENTS = frozenset({
    ConversationIntent.GREETING, ConversationIntent.GENERAL_QUESTION, ConversationIntent.SERVICE_QUESTION,
    ConversationIntent.PRICING_QUESTION, ConversationIntent.LOCATION, ConversationIntent.COMPLAINT,
    ConversationIntent.FOLLOW_UP, ConversationIntent.UNKNOWN,
})

# Phase 25: live testing found the LLM's own `message_language` self-report
# can anchor toward whatever language the prompt just told it the
# conversation is locked to, even for a customer message that visibly isn't
# in that script (e.g. a plain-English message got self-reported back as
# "ne_deva" once the conversation was already locked to Devanagari Nepali —
# real transcript in PHASE_STATUS.md Phase 25). Devanagari presence is the
# one part of this that's mechanically, deterministically checkable — never
# worth trusting an LLM judgment call for something regex can answer for
# certain — so a message containing ANY Devanagari character is always
# treated as "ne_deva" here, overriding the LLM's self-report outright.
# There's no equivalent deterministic check for "en" vs "ne_roman" vs
# "mixed" (all Latin script) — disambiguating those genuinely needs
# judgment, so that anchoring risk remains a documented, known limitation.
_DEVANAGARI_RE = re.compile(r"[ऀ-ॿ]")


def _knowledge_query_vector(content: str, query_vector: list[float]) -> list[float]:
    """Gap #7: a Devanagari message is translated to English before knowledge search (the KB is English and the
    embedding model can't bridge the scripts -- see intent.translate_for_search). Latin-script messages, and any
    translation failure, search with the original vector exactly as before. Style-exemplar retrieval keeps using the
    original-language `query_vector`; the reply language is untouched (the model already answers Nepali from English)."""
    if not _DEVANAGARI_RE.search(content):
        return query_vector
    try:
        english = translate_for_search(content)
        if english:
            return get_embedding_provider().embed([english])[0]
    except Exception:  # noqa: BLE001 -- best-effort: a failed translation must never cost the customer their reply
        logger.warning("knowledge query translation failed, searching the original text", exc_info=True)
    return query_vector


_WORD_RE = re.compile(r"[a-zA-Z]+")

# Urgent fix (real bug found live, PHASE_STATUS.md): Phase 25 already
# documented that the LLM's own message_language self-report can anchor to
# whatever the conversation is currently locked to, and that there is "no
# equivalent deterministic check for en vs ne_roman vs mixed" the way
# _DEVANAGARI_RE provides for Devanagari — flagged then as a known,
# deliberately-unmitigated limitation. Real live testing now shows this
# anchoring genuinely blocks the sustained-switch streak (Phase 25b) from
# ever firing for a customer who organically switches to substantial
# Romanized Nepali after a wrong English lock. This curated set of common,
# essentially Nepali-only function/particle words (drawn from this project's
# own real, already-verified live transcripts — Phase 25 §1/§4) is the
# second deterministic signal that postmortem floated: 2+ distinct matches
# is real, mechanical evidence of Romanized Nepali content that no anchoring
# bias can suppress, the same override philosophy as Devanagari. A single
# match is not enough (some overlap with English is possible for any one
# short token) — requiring 2 keeps false positives on genuine English
# sentences vanishingly unlikely.
_ROMAN_NEPALI_WORDS = {
    "cha", "chha", "chaina", "huncha", "hunchha", "garna", "garnu", "garne", "garchu", "garcha",
    "malai", "tapai", "tapaiko", "timro", "mero", "hamro", "paryo", "bhayo", "vayo",
    "sakchu", "sakincha", "dinuhos", "lagcha", "lagchha", "parcha", "parxa",
    "chahanchu", "chahanu", "kati", "kina", "kasari", "kaha", "kahile", "kun",
    "aaitabar", "sombar", "mangalbar", "budhabar", "bihibar", "sukrabar", "sanibar",
    "dhanyabad", "namaste", "kripaya", "ramro", "bhanuhos", "bhannuhos", "madat",
    "samaya", "ahile", "milcha", "maile", "arko", "malum", "madhyam", "chahincha",
    "huncha", "bujhe", "pugyo", "vaneko", "vannu",
    # Real gap found live (PHASE_STATUS.md conversation-quality audit): these
    # common spellings showed up in this project's own real transcripts
    # (28017051: "K xa", "Malai euta tooth dukheko xa") and in the source
    # spec's own "Roman Nepali is especially important" list, but were never
    # in this set — a conversation that OPENED with one of these would fail
    # to lock correctly. "xa"/"hunxa" are the same words as "cha"/"huncha"
    # spelled the other common way; the rest are additional real,
    # Nepali-only spoken contractions.
    "xa", "hunxa", "mildaina", "gardim", "gardai", "garda", "gardinu", "rakhdim",
    "bholi", "aja", "aaja", "hijo", "parsi", "aile", "hunuhuncha", "huss", "thik",
    # Phase 4 eval: "Nepal ko sabai vanda aglo jhil kun ho?", "guide le ekdam rude behave garyo, yesto ta hunu
    # bhayena ni" and "altitude sickness lagyo bhane k garne?" matched under 2 of the words above (and the LLM mislabels
    # them "ne_deva", discarded below), so the conversation never locked and the off-topic reply / handoff addendum came
    # back in English.
    "garyo", "bhayena", "vayena", "yesto", "testo", "ekdam", "hunu", "sabai", "vanda", "bhanda", "sanga", "gareko",
    "garera", "lagyo", "bhane", "vane",
    # Deliberately NOT added, despite appearing in the spec's own list:
    # - "chai" — collides with the English loanword "chai" (tea); the
    #   existing test test_resolve_message_language_roman_nepali_deterministic_
    #   override_beats_anchoring already asserts "Can I get a cha (chai tea)..."
    #   stays "en", which adding "chai" here would break.
    # - "okay"/"ok" — already deliberately excluded as ambiguous/no-signal
    #   (see _resolve_message_language: one word alone is no signal); these are common neutral
    #   English filler, not real Nepali evidence.
    # - bare "k" (half of "k xa") — a single letter, extremely common in
    #   English chat as "ok" shorthand; far too collision-prone even under
    #   the 2-match threshold.
    # "la" is added despite being a short, somewhat collision-prone token
    # (English "la la la", Singlish "la") because it's explicitly a real,
    # common Nepali particle this project's own spec calls out — the
    # existing 2-distinct-match requirement is the mitigation, same as every
    # other short token here.
    "la",
}


def _resolve_message_language(content: str, llm_reported: str | None) -> str | None:
    if _DEVANAGARI_RE.search(content):
        return ConversationLanguage.NE_DEVA.value

    words = _WORD_RE.findall(content)
    if not words or (len(words) == 1 and words[0].lower() not in _ROMAN_NEPALI_WORDS):
        # Too little real signal to decide anything from ("ok", "hi", "thanks", "price?", "👍") — never locks, never
        # counts toward (or against) an existing streak. Simulator 2026-10-01: one English word or an emoji must not
        # move a Nepali chat to English.
        return None

    # Distinct words, not occurrences -- "la la la" (an English interjection, not
    # Nepali) must not count as 2+ matches just by repeating one collision-prone
    # token (see _ROMAN_NEPALI_WORDS' own docstring above, which already assumed
    # "distinct" but the count here didn't actually dedupe until this fix).
    roman_signal_count = len({w.lower() for w in words if w.lower() in _ROMAN_NEPALI_WORDS})
    if roman_signal_count >= 2:
        return ConversationLanguage.NE_ROMAN.value

    if llm_reported == ConversationLanguage.NE_DEVA.value:
        # Live testing also caught the LLM claiming "ne_deva" for a message
        # that provably contains no Devanagari at all (the same anchoring
        # bias, the other direction) — never let a self-report the raw text
        # can't back up feed the lock. Treated as no signal, not guessed at
        # (see _DEVANAGARI_RE's docstring above).
        return None
    return llm_reported


def _resolve_locked_language(
    conversation: Conversation, message_language: str | None, explicit_switch_target: str | None = None
) -> str | None:
    """Deterministic, Python-side language lock (Phase 25) — mutates
    conversation.detected_language/language_switch_streak in place (persisted
    by the caller's later db.commit(), same identity-mapped-object pattern
    used for customer_row elsewhere in this file) and returns the language to
    use for THIS turn's own deterministic sentences and appended addenda.

    On the very first message with a clear signal, locks immediately and uses
    it the SAME turn — otherwise turn 1's own deterministic sentences (e.g.
    the contact-info gate) would fall back to English before anything was
    ever locked. Every later turn instead renders with the language the LLM
    itself was just told to write in (the lock as it stood BEFORE this
    message), and only updates the lock for the NEXT turn once a sustained
    streak of a different language crosses _LANGUAGE_LOCK_STREAK_THRESHOLD —
    never flips mid-turn, which would risk stitching two languages into one
    reply (an LLM-drafted sentence in the old language followed by a
    freshly-relocked deterministic addendum in the new one).

    Phase 25b: `explicit_switch_target` (classification.language_switch_request,
    the LLM's honest report that THIS message is an explicit, unambiguous
    "switch to X" request — never passive drift) bypasses ALL of the above
    the moment it's a valid language: the 3-consecutive-message streak
    threshold exists to protect against passive drift, not to make a customer
    repeat a direct request three times before being heard. Checked first, so
    it overrides even a still-unset lock or an in-progress passive streak."""
    if explicit_switch_target in _VALID_LANGUAGES:
        conversation.detected_language = explicit_switch_target
        conversation.language_switch_streak = 0
        return conversation.detected_language

    if message_language not in _VALID_LANGUAGES:
        return conversation.detected_language

    if conversation.detected_language is None:
        conversation.detected_language = message_language
        conversation.language_switch_streak = 0
        return conversation.detected_language

    language_for_this_turn = conversation.detected_language
    if message_language == conversation.detected_language:
        conversation.language_switch_streak = 0
    else:
        conversation.language_switch_streak += 1
        if conversation.language_switch_streak >= _LANGUAGE_LOCK_STREAK_THRESHOLD:
            conversation.detected_language = message_language
            conversation.language_switch_streak = 0
    return language_for_this_turn


# Bug found 2026-10-01 (test_language_session): "malai nepali ma bhannus na" in an English-locked chat only switched
# if the model also set language_switch_request; when it didn't, the passive 3-message streak kept the chat in English.
# Narrow on purpose: "Do you speak Nepali?" or "My Nepali is not good" is not a request to switch.
_SWITCH_VERBS = r"(?:reply|respond|answer|talk|speak|write|text|chat|continue|switch|say|tell|explain)"
_SWITCH_REQUEST_RES = [
    (re.compile(r"नेपाली\s*मा"), ConversationLanguage.NE_DEVA.value),
    (re.compile(rf"\bnepali\s*ma\b|\b{_SWITCH_VERBS}\b[^.?!]{{0,20}}\bin nepali\b|\bswitch to nepali\b", re.I),
     ConversationLanguage.NE_ROMAN.value),
    (re.compile(rf"\benglish\s*ma\b|\b{_SWITCH_VERBS}\b[^.?!]{{0,20}}\bin english\b|\bswitch to english\b", re.I),
     ConversationLanguage.EN.value),
]


def _explicit_switch_request(content: str) -> str | None:
    """Deterministic backstop for classification.language_switch_request: the language an explicit "reply in X"
    request asks for, else None."""
    return next((lang for pattern, lang in _SWITCH_REQUEST_RES if pattern.search(content)), None)


# Tone/language phase: common Hindi-only tokens that sometimes leak into a
# Nepali-locked reply (Nepali and Hindi are close enough that a model trained
# mostly on Hindi data drifts there) -- none of these collide with the
# English or Roman-Nepali vocabulary above, so a single match is enough
# signal, unlike _ROMAN_NEPALI_WORDS' 2-match bar.
_HINDI_LEAK_WORDS = {"hai", "hoga", "kya", "aap", "bahut", "accha", "nahi", "kaunsa"}
_HINDI_LEAK_PHRASE_RE = re.compile(r"\bke\s+liye\b", re.IGNORECASE)


def _contains_hindi_leak(text: str) -> bool:
    if _HINDI_LEAK_PHRASE_RE.search(text):
        return True
    return any(w.lower() in _HINDI_LEAK_WORDS for w in _WORD_RE.findall(text))


def _expected_response_language(
    conversation: Conversation,
    content: str,
    force_language: str | None,
    language_switch_request: str | None = None,
    llm_reported_message_language: str | None = None,
) -> str | None:
    """Non-mutating preview of the language this turn's `response` should be
    written in -- used both to seed the very first classify_and_respond call
    (before any lock exists) and by the post-generation check below. Mirrors
    _resolve_locked_language's own priority order exactly but never touches
    conversation.detected_language/language_switch_streak itself: that real
    mutation still happens later, after the takeover check, so an abandoned
    draft never silently moves the persisted lock."""
    if force_language:
        return force_language
    language_switch_request = language_switch_request or _explicit_switch_request(content)
    if language_switch_request in _VALID_LANGUAGES:
        return language_switch_request
    if conversation.detected_language:
        return conversation.detected_language
    resolved = _resolve_message_language(content, llm_reported_message_language)
    if resolved is None and not _DEVANAGARI_RE.search(content) and any(
        w.lower() in _ROMAN_NEPALI_WORDS for w in _WORD_RE.findall(content)
    ):
        # Simulator 2026-10-01: "namaste" / "namaste dai" (one Nepali word, below the 2-word lock bar) left the reply
        # language open and the model answered in Devanagari. A Nepali word in Latin letters gets a Latin-letter reply;
        # the lock itself still waits for a clear signal.
        return ConversationLanguage.NE_ROMAN.value
    return resolved


# Words only English has: a customer message with 3+ of these and no Nepali word is clearly English.
_ENGLISH_FUNCTION_WORDS = frozenset(
    "the a an is are am was were do does did how what when where which who why can could would will i you we my your "
    "it this that for of to in on at near with from much many".split()
)


def _nepali_word_count(text: str) -> int:
    return len({w.lower() for w in _WORD_RE.findall(text) if w.lower() in _ROMAN_NEPALI_WORDS})


def _is_clearly_english(text: str) -> bool:
    if _DEVANAGARI_RE.search(text) or _nepali_word_count(text):
        return False
    return sum(w.lower() in _ENGLISH_FUNCTION_WORDS for w in _WORD_RE.findall(text)) >= 3


def _response_language_mismatch(response_text: str, expected: str, customer_message: str = "") -> bool:
    """Post-generation check (tone/language phase): does the drafted reply
    actually match the language it was told to write in? Reuses the same
    deterministic signals as _resolve_message_language rather than trusting
    the model's own self-report, for the same anchoring-bias reasons."""
    if _contains_hindi_leak(response_text):
        return True
    has_devanagari = bool(_DEVANAGARI_RE.search(response_text))
    roman_count = _nepali_word_count(response_text)
    if expected == ConversationLanguage.MIXED.value:
        # A mixed customer accepts English, but not after a Nepali message: simulator barber "Hair Cut kati ho?" got a
        # pure English reply.
        customer_nepali = bool(_DEVANAGARI_RE.search(customer_message) or _nepali_word_count(customer_message))
        return customer_nepali and not has_devanagari and roman_count == 0
    if expected == ConversationLanguage.NE_DEVA.value:
        return not has_devanagari
    if expected == ConversationLanguage.NE_ROMAN.value:
        return has_devanagari or roman_count == 0
    if expected == ConversationLanguage.EN.value:
        # Same 2-match bar as _resolve_message_language's own Roman-Nepali check, so a
        # single collision-prone word (e.g. "la") never triggers a needless regenerate
        # on a genuine English reply.
        # on a genuine English reply. A clearly English message makes any Nepali word a mismatch: simulator it/switch_lang
        # "hello, how much is Laptop Diagnosis?" got "…ko price NPR 500 ho, ra karib 30 minute lagcha" (one listed word).
        return has_devanagari or roman_count >= (1 if _is_clearly_english(customer_message) else 2)
    return False


def _handle_provider_failure(
    db: Session,
    *,
    conversation: Conversation,
    business_id: uuid.UUID,
    conversation_id: uuid.UUID,
    content: str,
    external_message_id: str | None,
    force_language: str | None = None,
    business: Business | None = None,
    content_filtered: bool = False,
) -> dict:
    """Urgent fix (real 500 found live, PHASE_STATUS.md): the LLM/embedding
    provider call failed even after its own internal retries
    (app/llm/azure_openai.py's `_post`) — a real, live-captured transient DNS
    failure calling Azure, confirmed to resolve itself on a later retry, not a
    bug in what the customer sent. `handle_incoming_message` catches the
    narrow `RuntimeError` `_post` raises (nowhere else in this codebase
    raises that type) around ONLY the embed/search/classify calls and routes
    here rather than letting it become a raw, unhandled 500.

    The customer's real message is still persisted (never silently dropped —
    the exact failure mode this fix exists to avoid), a static, honest
    failure sentence is shown (no LLM is available to draft anything this
    turn, same discipline as `_off_topic_response`), and a REAL HumanHandoff
    is created — same producer, same anti-duplicate/race-safe insert
    `handoff_service` already uses for every other trigger, just a new,
    honestly-labeled reason (`is_provider_failure`, `_handoff_reason`) so
    staff reviewing handoffs later see the real cause, not a fabricated
    "customer asked for a human"."""
    language = force_language or conversation.detected_language
    # Azure's content filter refused the customer's message (simulator jailbreak got "trouble connecting" + a handoff):
    # the provider is fine, so decline it like any off-topic message -- no failure sentence, nothing for staff.
    intent = ConversationIntent.OFF_TOPIC if content_filtered else ConversationIntent.UNKNOWN
    if content_filtered:
        response_text = _off_topic_response(business, language)
    else:
        handoff_service.maybe_create_handoff(
            db, business_id=business_id, conversation_id=conversation_id,
            intent=intent, best_similarity=None, is_provider_failure=True,
        )
        response_text = f"{render('provider_failure', language)} {render('handoff_addendum', language)}"

    customer_message = Message(
        conversation_id=conversation_id,
        sender_type=MessageSenderType.CUSTOMER,
        content=content,
        detected_intent=intent.value,
        external_message_id=external_message_id,
    )
    db.add(customer_message)
    db.commit()
    db.refresh(customer_message)

    agent_message = Message(
        conversation_id=conversation_id, sender_type=MessageSenderType.AGENT, content=response_text
    )
    db.add(agent_message)
    db.commit()
    db.refresh(agent_message)

    logger.info(
        "orchestrated conversation turn: conversation_id=%s intent=%s tool_available=False",
        conversation_id, "content_filtered" if content_filtered else "provider_failure",
    )
    return {
        "intent": intent,
        "response": response_text,
        "customer_message_id": customer_message.id,
        "agent_message_id": agent_message.id,
        "detected_language": language,
    }


def _language_question_turn(
    db: Session, *, conversation: Conversation, business: Business, content: str, external_message_id: str | None
) -> dict | None:
    """Phase 16 -- "ask upfront" language mode, no LLM call. A NEW conversation (no messages yet) gets one short question as
    its first reply; the next message is read as the answer and locks the conversation's language. Returns the finished turn,
    or None to fall through to the normal flow (any other conversation state, or an answer that is really a question or names
    no single language -- the normal flow then locks from the message itself, exactly as automatic mode does)."""
    if not conversation.language_prompted:
        if db.scalar(select(func.count()).select_from(Message).where(Message.conversation_id == conversation.id)):
            return None  # started before the owner switched modes: leave it on automatic
        conversation.language_prompted = True
        response_text = render_language_question(business.name)
    else:
        choice = parse_language_choice(content)
        if choice is None:
            return None
        conversation.detected_language = choice
        conversation.language_switch_streak = 0
        response_text = render("language_chosen", choice)
    customer_message = Message(
        conversation_id=conversation.id,
        sender_type=MessageSenderType.CUSTOMER,
        content=content,
        detected_intent=ConversationIntent.UNKNOWN.value,
        external_message_id=external_message_id,
    )
    db.add(customer_message)
    db.commit()
    db.refresh(customer_message)
    agent_message = Message(conversation_id=conversation.id, sender_type=MessageSenderType.AGENT, content=response_text)
    db.add(agent_message)
    db.commit()
    db.refresh(agent_message)
    logger.info(
        "language mode ask: conversation_id=%s locked=%s", conversation.id, conversation.detected_language
    )
    return {
        "intent": ConversationIntent.UNKNOWN,
        "response": response_text,
        "customer_message_id": customer_message.id,
        "agent_message_id": agent_message.id,
        "detected_language": conversation.detected_language,
    }


_PAYMENT_PROVIDER_NAMES = {
    "esewa": re.compile(r"\be[\s\-]?sewa\b|[इई][\s\-]?सेवा", re.IGNORECASE),
    "khalti": re.compile(r"khalti|खल्ती|खल्टी", re.IGNORECASE),
}


def _named_payment_provider(text: str) -> str | None:
    """The one gateway a message names, or None if it names neither or both ("eSewa or Khalti?" is a question, not an
    answer)."""
    named = [name for name, pattern in _PAYMENT_PROVIDER_NAMES.items() if pattern.search(text)]
    return named[0] if len(named) == 1 else None


def _payment_choice_turn(
    db: Session, *, conversation: Conversation, business: Business, content: str,
    external_message_id: str | None, language: str | None,
) -> dict | None:
    """The customer's answer to "eSewa or Khalti?" (asked by _format_booking_result right after a booking) — no LLM call,
    same as the bare-digit slot pick: a message naming exactly one gateway, while a booking is waiting on that answer,
    creates the real payment request through that gateway and replies with its link and QR. Returns the finished turn, or
    None to fall through to the normal flow (nothing waiting, or the message doesn't clearly pick one)."""
    if conversation.payment_choice_appointment_id is None:
        return None
    provider_name = _named_payment_provider(content)
    if provider_name is None:
        return None
    appointment = db.get(Appointment, conversation.payment_choice_appointment_id)
    if appointment is None or appointment.business_id != business.id or not payment_service.awaits_provider_choice(db, appointment):
        conversation.payment_choice_appointment_id = None
        db.commit()
        return None
    payment = payment_service.choose_provider(
        db, appointment=appointment, provider_name=provider_name, conversation_id=conversation.id
    )
    if payment is None:
        return None  # not one of this business's gateways: leave the question open and let the normal flow answer
    conversation.payment_choice_appointment_id = None
    label = {"esewa": "eSewa", "khalti": "Khalti"}[provider_name]
    if payment.status.value != "pending" or not payment.payment_url:
        response_text = render("payment_link_failed", language, provider=label)
    else:
        response_text = render(
            "payment_link_chosen", language, provider=label, currency=payment.currency,
            amount=str(payment.amount), link=payment.payment_url,
        )
        # None when backend_base_url was refused (see payment_service.qr_page_url) --
        # the real payment link above already works, so this omits the QR line rather
        # than ever formatting a None into customer-facing text.
        qr = payment_service.qr_page_url(payment)
        if qr:
            response_text = f"{response_text}\n{render('payment_qr_line', language, qr=qr)}"
        booking_tool.queue_payment_request_email(db, appointment=appointment)
    customer_message = Message(
        conversation_id=conversation.id,
        sender_type=MessageSenderType.CUSTOMER,
        content=content,
        detected_intent=ConversationIntent.BOOKING.value,
        external_message_id=external_message_id,
    )
    db.add(customer_message)
    db.commit()
    db.refresh(customer_message)
    agent_message = Message(conversation_id=conversation.id, sender_type=MessageSenderType.AGENT, content=response_text)
    db.add(agent_message)
    db.commit()
    db.refresh(agent_message)
    logger.info(
        "payment provider chosen (no LLM call): conversation_id=%s provider=%s status=%s",
        conversation.id, provider_name, payment.status.value,
    )
    return {
        "intent": ConversationIntent.BOOKING,
        "response": response_text,
        "customer_message_id": customer_message.id,
        "agent_message_id": agent_message.id,
        "detected_language": conversation.detected_language,
    }


def _takeover_turn(
    db: Session,
    *,
    conversation: Conversation,
    content: str,
    external_message_id: str | None,
    intent: ConversationIntent | None = None,
) -> dict:
    """Phase 52: a staff member owns this conversation, so the AI stays silent. The customer's message is still stored (the
    inbox shows it, and it is never silently dropped) but nothing is drafted or sent: `response` is None and `agent_message_id`
    is None, which every channel caller treats as "send nothing". `intent` is set only when the LLM had already classified
    the message by the time takeover was noticed (the post-LLM checkpoint), else None."""
    customer_message = Message(
        conversation_id=conversation.id,
        sender_type=MessageSenderType.CUSTOMER,
        content=content,
        detected_intent=intent.value if intent is not None else None,
        external_message_id=external_message_id,
    )
    db.add(customer_message)
    db.commit()
    db.refresh(customer_message)
    logger.info(
        "human takeover active -- AI suppressed: conversation_id=%s classified_intent=%s",
        conversation.id,
        intent.value if intent is not None else None,
    )
    return {
        "intent": intent,
        "response": None,
        "customer_message_id": customer_message.id,
        "agent_message_id": None,
        "takeover": True,
        "detected_language": conversation.detected_language,
    }


def _deliver_reply(db: Session, result: dict, deliver) -> None:
    """Push the reply through the channel and record what happened on the AGENT message (delivery_status/detail) — until
    Phase 52 the send result was only ever logged. Runs while the caller still holds the ReplyLock."""
    try:
        detail = deliver(result["response"])
    except Exception:  # the adapters never raise; a bug in a custom `deliver` must not lose the stored reply
        logger.exception("deliver callback raised for conversation turn (agent_message_id=%s)", result.get("agent_message_id"))
        detail = "failed: unexpected error"
    message = db.get(Message, result["agent_message_id"])
    if message is not None:
        message.delivery_status = delivery.status_from_detail(detail)
        message.delivery_detail = detail[:255]
        db.commit()
    result["delivery_detail"] = detail


def handle_incoming_message(
    db: Session,
    *,
    conversation_id: uuid.UUID,
    business_id: uuid.UUID,
    content: str,
    external_message_id: str | None = None,
    force_language: str | None = None,
    deliver=None,
) -> dict | None:
    """One customer turn, plus (optionally) the delivery of the reply. See `_handle_turn` for the conversation logic.

    `deliver` (Phase 52): a callable `text -> status string` that pushes the reply to the customer's channel (the WhatsApp/
    Messenger/Instagram webhooks pass their adapter's send). The reply is delivered HERE, inside the per-conversation
    ReplyLock, rather than by the caller after this returns — that is what guarantees a staff claim can never commit between
    the AI's final takeover check and the message actually being sent (see takeover_service.ReplyLock). The website widget /
    voice / testing callers pass nothing: their "delivery" is the HTTP response itself."""
    reply_lock = takeover_service.ReplyLock(conversation_id)
    try:
        # Every fixed template rendered this turn picks a wording this chat hasn't seen yet (response_templates.render),
        # and _finalize_reply checks openings/endings against the same history.
        with reply_history(_agent_reply_history(db, conversation_id)):
            result = _handle_turn(
                db,
                conversation_id=conversation_id,
                business_id=business_id,
                content=content,
                external_message_id=external_message_id,
                force_language=force_language,
                reply_lock=reply_lock,
            )
        if result is not None and result.get("response") is not None and deliver is not None:
            # Every reply path holds the lock here (early branches: acquired at the locked checkpoint; the main flow and the
            # provider-failure path: at theirs). If one ever doesn't, take it now and re-check rather than send blind.
            if not reply_lock.held:
                logger.warning("reply path reached delivery without the reply lock: conversation_id=%s", conversation_id)
                reply_lock.acquire()
            if takeover_service.is_active(db, conversation_id=conversation_id):
                message = db.get(Message, result["agent_message_id"])
                if message is not None:
                    message.delivery_status, message.delivery_detail = delivery.SUPPRESSED, "a staff member took over"
                    db.commit()
                result["response"] = None
                result["takeover"] = True
            else:
                _deliver_reply(db, result, deliver)
        return result
    finally:
        reply_lock.release()


def _handle_turn(
    db: Session,
    *,
    conversation_id: uuid.UUID,
    business_id: uuid.UUID,
    content: str,
    external_message_id: str | None = None,
    force_language: str | None = None,
    reply_lock: "takeover_service.ReplyLock",
) -> dict | None:
    """The full orchestration flow for one customer message: load context (Phase
    7) -> knowledge search (Phase 6) -> classify intent + draft response + extract
    a candidate booking/cancellation/reschedule request (one LLM call) -> if it's
    resolvable against real data, run the matching real tool (Phase 10 booking,
    Phase 11 cancellation/reschedule) and OVERWRITE the response with a
    deterministic sentence built from its real result -> persist both messages ->
    return the result.

    `external_message_id` (Phase 22): optional, only ever supplied by a
    webhook-delivered channel (WhatsApp's real message id) that needs the
    real DB-level idempotency guarantee on Message.external_message_id — every
    prior caller (website widget, the direct testing endpoint) leaves this
    None, unaffected.

    `force_language` (Phase 43h): optional — only the widget's voice-message
    route passes this, and only when the customer's SPOKEN input was detected
    as Nepali (always "ne_roman"). Overrides both what the LLM is told to
    write in and every deterministic sentence THIS turn renders in, regardless
    of what conversation.detected_language's own Phase 25/25b lock says —
    never mutates the persisted lock itself, so a later TYPED message still
    sees exactly the lock it would have without this turn ever happening.
    None (every typed-text caller) means completely unchanged Phase 25b
    behavior.

    Returns None if the conversation doesn't exist / isn't this business's (the
    route turns that into a 404, same IDOR-safe pattern as every prior phase).
    """
    conversation = get_conversation(db, conversation_id=conversation_id, business_id=business_id)
    if conversation is None:
        return None

    # Phase 52 takeover checkpoints (three reads of the same column; only the two under the ReplyLock are authoritative):
    #   0. here, unlocked and cheap: a staff member already owns this conversation -> store the message, stay silent, and skip
    #      everything below including the summarization LLM call. Placed before EVERY branch.
    #   1. after context assembly, UNDER the ReplyLock: guards the early, non-LLM replies (premium test, language question,
    #      payment choice, bare-digit pick). The lock is dropped again before the multi-second LLM call.
    #   2. after the LLM call, UNDER the ReplyLock: guards the main flow — see below.
    if takeover_service.is_active(db, conversation_id=conversation_id):
        return _takeover_turn(db, conversation=conversation, content=content, external_message_id=external_message_id)

    # Urgent perf investigation (real 12-14s turns reported live): per-stage
    # wall-clock timing for one turn, logged as one structured line so it's
    # queryable the same way Phase 31's llm_duration_ms already is — never
    # printed inline/blocking, just wraps each stage that was a live suspect
    # (context assembly, knowledge search, the LLM call itself).
    _t0 = time.perf_counter()

    # Fold in anything that aged out since the last turn so this turn's context
    # stays bounded (Phase 7) rather than growing with every message.
    maybe_summarize_conversation(db, conversation_id=conversation_id, business_id=business_id)
    _t1 = time.perf_counter()
    context = assemble_context(db, conversation_id=conversation_id, business_id=business_id)
    _t2 = time.perf_counter()

    business = db.get(Business, business_id)

    reply_lock.acquire()
    if takeover_service.is_active(db, conversation_id=conversation_id):
        return _takeover_turn(db, conversation=conversation, content=content, external_message_id=external_message_id)

    # Phase 16: "ask upfront" businesses ask the customer's language on the first reply and lock to the answer. A voice turn
    # (force_language) already knows the language, so it never asks.
    if (
        business is not None
        and business.language_mode == LanguageMode.ASK
        and conversation.detected_language is None
        and not force_language
    ):
        asked = _language_question_turn(
            db, conversation=conversation, business=business, content=content, external_message_id=external_message_id
        )
        if asked is not None:
            return asked

    if business is not None:
        chosen = _payment_choice_turn(
            db, conversation=conversation, business=business, content=content,
            external_message_id=external_message_id, language=force_language or conversation.detected_language,
        )
        if chosen is not None:
            return chosen

    services = service_service.list_services(db, business_id=business_id)
    # Real conversation-quality spec-conformance finding (PHASE_STATUS.md): a
    # real "open cha?" (are you open?) question got "I don't have that
    # information" — real business hours exist (booking_service already
    # reads this exact table to compute real availability) but were never
    # shown to the LLM. Same real per-business list every other context
    # section here already uses (services, knowledge, appointments).
    hours = business_hours_service.list_hours(db, business_id=business_id)

    # Real conversation-quality audit finding (§50, "don't create an LLM call
    # for everything"): a bare-digit reply to a slot list just shown
    # ("2") is real, unambiguous, already-known data — resolve it
    # deterministically and skip the embedding call, the knowledge search,
    # AND the main classification LLM call entirely for this one turn (the
    # single most expensive stage on every other turn — see the real
    # per-stage timing data in the latency-diagnosis phase above). One-shot:
    # the proposed-slots hint is always cleared right here, whether or not
    # this turn actually consumed it, so a much-later, unrelated bare digit
    # can never be misread as a stale slot pick.
    picked_slot = _resolve_bare_digit_slot_pick(conversation, content) if business is not None else None
    # Phase 13: remember what the SYSTEM offered last turn BEFORE the one-shot clear below, so _merge_booking_draft can
    # tell "picked from the list I just showed" (not a switch) from "stated a different date on their own" (a switch).
    offered_last_turn = (
        [datetime.fromisoformat(x) for x in conversation.booking_draft_proposed_slots.split(",")]
        if conversation.booking_draft_proposed_slots else None
    )
    conversation.booking_draft_proposed_slots = None
    if picked_slot is not None and business is not None:
        tool = find_tool(ConversationIntent.BOOKING, business)
        service, _ = _resolve_booking_draft(conversation, services, business)
        if tool is not None and service is not None:
            customer_row = db.get(Customer, conversation.customer_id)
            tz = ZoneInfo(business.timezone)
            # Real bug found live via the spec-conformance eval (PHASE_STATUS.md):
            # this deterministic shortcut called tool.run() directly with NO
            # has_contact check at all — a customer could get a real
            # appointment booked from a bare digit reply without EVER giving a
            # phone number or email, silently bypassing the real Phase 24
            # business requirement ("never book a customer the business has no
            # way to reach"). The picked slot IS a genuine, explicit customer
            # choice, so it's safe to persist into the real booking_draft_date/
            # booking_draft_time fields (not the search-anchor fallback) —
            # exactly as if the customer had typed the date/time themselves —
            # and, if contact is still missing, render the same real contact
            # gate the normal LLM path would, still with zero LLM call.
            has_contact = bool(customer_row and (customer_row.phone or customer_row.email))
            if not has_contact:
                conversation.booking_draft_date = picked_slot.astimezone(tz).strftime("%Y-%m-%d")
                conversation.booking_draft_time = picked_slot.astimezone(tz).strftime("%H:%M")
                response_text = render_contact_gate(
                    _describe_known_booking_slots(
                        conversation, services, business, force_language or conversation.detected_language
                    ),
                    force_language or conversation.detected_language,
                )
                logger.info(
                    "bare-digit slot pick resolved but contact info missing -- gated, not booked: "
                    "conversation_id=%s",
                    conversation_id,
                )
            else:
                result = tool.run(
                    db,
                    business_id=business_id,
                    customer_id=conversation.customer_id,
                    service_id=service.id,
                    staff_id=None,
                    scheduled_at=picked_slot,
                    conversation_id=conversation.id,
                )
                response_text = _format_booking_result(
                    result,
                    service=service,
                    tz=tz,
                    customer_name=customer_row.known_name if customer_row else None,
                    language=force_language or conversation.detected_language,
                )
                _clear_booking_draft_after_attempt(conversation, result, picked_slot, tz)
                logger.info(
                    "book_appointment tool executed (deterministic bare-digit slot pick, no LLM call): "
                    "conversation_id=%s success=%s",
                    conversation_id,
                    result["success"],
                )
            customer_message = Message(
                conversation_id=conversation_id,
                sender_type=MessageSenderType.CUSTOMER,
                content=content,
                detected_intent=ConversationIntent.BOOKING.value,
                external_message_id=external_message_id,
            )
            db.add(customer_message)
            db.commit()
            db.refresh(customer_message)
            agent_message = Message(
                conversation_id=conversation_id, sender_type=MessageSenderType.AGENT, content=response_text
            )
            db.add(agent_message)
            db.commit()
            db.refresh(agent_message)
            return {
                "intent": ConversationIntent.BOOKING,
                "response": response_text,
                "customer_message_id": customer_message.id,
                "agent_message_id": agent_message.id,
                "detected_language": conversation.detected_language,
            }
        # Service no longer resolves (e.g. draft was reset) — the digit hint
        # was already cleared above, so this just falls through to the
        # normal LLM-classification path below like any other message.

    # Urgent fix (real 500 found live, PHASE_STATUS.md): `_post` (app/llm/
    # azure_openai.py) already retries transient provider failures internally
    # — this catches the case where even that retry budget is exhausted (a
    # genuine, if rare, real-world outage) so it never reaches the customer as
    # a raw 500. `RuntimeError` is raised nowhere else in this codebase, so
    # this can only ever catch a real LLM/embedding provider failure, never
    # mask an unrelated bug in knowledge search or classification itself.
    # Nothing below until checkpoint 2 may hold the ReplyLock: the embedding + LLM calls take seconds and a staff member must
    # be able to claim the conversation meanwhile (checkpoint 2 then discards the draft). Also end the transaction so no row
    # lock on the conversation survives into the LLM call.
    reply_lock.release()
    db.commit()
    try:
        _t3 = time.perf_counter()
        query_vector = get_embedding_provider().embed([content])[0]
        _t4 = time.perf_counter()
        knowledge_results = knowledge_service.filter_for_llm(
            knowledge_service.search_chunks(
                db, business_id=business_id, query_vector=_knowledge_query_vector(content, query_vector),
                top_k=KNOWLEDGE_TOP_K,
            )
        )
        # Computed once here and reused both by the grounding guard below and by
        # the handoff decision further down -- knowledge_results is never
        # reassigned in between, so one value serves both.
        best_similarity = max((similarity for _, _, similarity in knowledge_results), default=None)
        _t5 = time.perf_counter()
        # Phase 2 (style exemplars): retrieved once here, before intent is known (this
        # same call both classifies AND drafts -- see intent.py's own docstring for why a
        # second, intent-first call was rejected), and reused unchanged by every regen
        # call below. Reuses `query_vector` (already computed for knowledge search) --
        # zero extra embedding cost. Safe to inject into every intent's draft regardless
        # of tenant/turn: orchestrator.py's dispatch chain further down always overwrites
        # response_text with a deterministic response_templates.render(...) call for every
        # booking/cancellation/rescheduling/status/resend/hours/off_topic branch, which
        # never reads classification.response at all -- exemplar tone can only ever reach
        # the customer through the free-text intents where nudging tone is the point.
        pre_call_language = _expected_response_language(conversation, content, force_language)
        style_exemplars = style_exemplar_service.retrieve(
            db,
            business_id=business_id,
            business_type=business.business_type if business else None,
            language=pre_call_language or "en",
            query_vector=query_vector,
        )
        logger.info(
            "style exemplar retrieval: conversation_id=%s language=%s count=%d exemplars=%s",
            conversation_id, pre_call_language or "en", len(style_exemplars),
            [{"id": str(e.id), "intent": e.intent, "register": e.register, "text": e.text} for e in style_exemplars],
        )
        classification = classify_and_respond(
            business=business,
            context=context,
            knowledge_results=knowledge_results,
            customer_message=content,
            services=services,
            locked_language=pre_call_language,
            hours=hours,
            style_exemplars=style_exemplars,
        )
        # Saved now, before the grounding guard below (or anything else) can
        # replace classification.response -- the stuck-loop check further down
        # must see what the model itself kept drafting, not whatever
        # deterministic text this turn ends up sending the customer.
        _llm_drafted_response = classification.response
        _t6 = time.perf_counter()
        logger.info(
            "conversation turn stage timing",
            extra={
                "turn_summarize_ms": round((_t1 - _t0) * 1000, 1),
                "turn_context_assembly_ms": round((_t2 - _t1) * 1000, 1),
                "turn_embed_ms": round((_t4 - _t3) * 1000, 1),
                "turn_knowledge_search_ms": round((_t5 - _t4) * 1000, 1),
                "turn_llm_chat_ms": round((_t6 - _t5) * 1000, 1),
                "turn_total_pre_dispatch_ms": round((_t6 - _t0) * 1000, 1),
            },
        )

        # Tone/language phase: the one deterministic "what language should this turn's
        # reply be in" answer, computed once from this classification's own report and
        # reused below both to seed the fact-grounding retry's locked_language and to
        # drive the post-generation language check further down.
        expected_reply_language = _expected_response_language(
            conversation, content, force_language, classification.language_switch_request, classification.message_language,
        )

        # Fact grounding guard (read-through of backend/data/regression/failure_log_batches:
        # 23 unconfigured_fact + 4 invented_policy findings, incl. Samaj Dental Clinic's
        # recurring fabricated 20% deposit). The LLM is handed real config/knowledge every
        # turn but sometimes states something else anyway -- this checks the draft against
        # that SAME context before it ever reaches dispatch/the customer. Runs on every
        # intent's raw draft (cheap regex; a tool-dispatch intent below may still replace
        # response_text with its own deterministic, already-safe text -- validating it too
        # is harmless, never triggers). See fact_validator.check_response_facts.
        currency = business.currency if business and business.currency else "USD"
        hours_by_day = {h.day_of_week: h.closed for h in hours} if hours else None
        service_facts = [
            {"name": s.name, "price": s.price, "deposit_enabled": s.deposit_enabled, "deposit_percentage": s.deposit_percentage}
            for s in services
        ]
        # Includes the customer's own current message: a phone/email the customer just
        # volunteered THIS turn (read back correctly in the draft) isn't in `context`
        # yet (that snapshot predates this turn) -- confirmed false positive without this.
        knowledge_text = "\n".join(chunk.content for chunk, _doc, _sim in knowledge_results)
        known_text_parts = [knowledge_text, content]
        if business is not None:
            known_text_parts += [business.phone or "", business.address or "", business.email or ""]
        customer_ctx = context.get("customer") or {}
        known_text_parts += [str(customer_ctx.get("phone") or ""), str(customer_ctx.get("email") or "")]
        known_text = "\n".join(known_text_parts)
        fact_check_front_desk_reason = None
        violations = check_response_facts(
            classification.response, currency=currency, services=service_facts,
            hours_by_day=hours_by_day, known_text=known_text, knowledge_text=knowledge_text,
        )
        if violations:
            logger.warning(
                "drafted reply failed fact-grounding check, regenerating once: conversation_id=%s violations=%s",
                conversation_id, violations,
            )
            retry = classify_and_respond(
                business=business,
                context=context,
                knowledge_results=knowledge_results,
                customer_message=content,
                services=services,
                locked_language=expected_reply_language,
                hours=hours,
                flagged_claims=violations,
                style_exemplars=style_exemplars,
            )
            retry_violations = check_response_facts(
                retry.response, currency=currency, services=service_facts,
                hours_by_day=hours_by_day, known_text=known_text, knowledge_text=knowledge_text,
            )
            if not retry_violations:
                classification = retry
            else:
                logger.warning(
                    "fact-grounding regenerate still failed, falling back to honest template: "
                    "conversation_id=%s violations=%s",
                    conversation_id, retry_violations,
                )
                fallback_language = force_language or conversation.detected_language or classification.message_language
                classification = classification._replace(
                    response=render("unconfirmed_fact_fallback", fallback_language),
                    needs_human_handoff=True,
                )
                fact_check_front_desk_reason = (
                    "Drafted reply repeated an unconfirmed price/policy/hours/contact claim twice in a row."
                )

        # t-128: an explicit ask for a person sometimes came back general_question, and with no KB match the guard
        # below then answered "I don't want to guess". The model's own draft is kept; only the routing is corrected.
        if (
            classification.intent not in (ConversationIntent.HUMAN_HANDOFF, ConversationIntent.COMPLAINT)
            and _is_explicit_human_request(content)
        ):
            classification = classification._replace(intent=ConversationIntent.HUMAN_HANDOFF)

        # Free-text grounding guard: fact_validator above only catches specific
        # regex-detectable fabrications (price/phone/hours patterns); this
        # closes the gap for a GENERAL_QUESTION/SERVICE_QUESTION/
        # PRICING_QUESTION/LOCATION answer when retrieval found NOTHING above
        # knowledge_service.LLM_RELEVANCE_FLOOR (best_similarity is None here
        # means knowledge_results, already filtered by that real, evidenced
        # floor, came back empty) -- true "below-threshold retrieval", never a
        # model guess. Deliberately does NOT reuse handoff_service's own
        # (separate, looser) 0.5 similarity cutoff for this: live-tested, that
        # threshold sits inside the range real, correct top-1 matches score at
        # (e.g. a genuinely correct "Parking & Location" match scored 0.372,
        # below 0.5) -- fine as a tolerant side-channel signal for "maybe also
        # flag staff", but reusing it to REPLACE the customer-facing answer
        # produced real false positives on already-correct replies. A
        # retrieved-but-irrelevant chunk (similarity > 0 but not the right
        # passage) is a real, harder gap this does NOT close -- live-tested,
        # the model already declines those honestly on its own (see
        # PHASE_STATUS.md); only the fully-empty-retrieval case gets a hard,
        # non-negotiable code backstop instead of trusting that self-honesty.
        # Never applied to BUSINESS_HOURS, whose reply further down is always
        # the deterministic real-hours override, never the LLM's own
        # knowledge-derived text -- its retrieval similarity is meaningless
        # (hours live in a separate table, not the knowledge base).
        if (
            fact_check_front_desk_reason is None
            and classification.intent in (
                ConversationIntent.GENERAL_QUESTION,
                ConversationIntent.SERVICE_QUESTION,
                ConversationIntent.PRICING_QUESTION,
                ConversationIntent.LOCATION,
            )
            and best_similarity is None
            and classification.needs_human_handoff is not False
        ):
            logger.warning(
                "drafted reply for a %s had no grounded knowledge match, using honest fallback: "
                "conversation_id=%s best_similarity=%s",
                classification.intent.value, conversation_id, best_similarity,
            )
            fallback_language = force_language or conversation.detected_language or classification.message_language
            classification = classification._replace(
                response=render("unconfirmed_fact_fallback", fallback_language),
                needs_human_handoff=True,
            )
            found = f"{best_similarity:.2f}" if best_similarity is not None else "no knowledge base results"
            fact_check_front_desk_reason = (
                f"No sufficiently relevant knowledge found for a {classification.intent.value} "
                f"(best similarity: {found})."
            )

        # Style guard (step 1 of the human-likeness review): intent.py's system prompt
        # already SPECIFIES a banned-phrase list (rule 4), a one-question-per-turn rule
        # (rule 16), and per-category length budgets (rule 17) -- but a prompt rule is
        # "instructed, not guaranteed", same lesson as fact_validator/format_service_list.
        # This makes those three specific, already-agreed rules a real guarantee. Skipped
        # whenever fact-grounding above already replaced the response with the fixed,
        # correct-by-construction fallback template -- same skip condition the language
        # check below uses, and for the same reason (nothing left to check).
        if fact_check_front_desk_reason is None:
            style_violations = check_response_style(classification.response, intent=classification.intent.value)
            if style_violations:
                repaired = repair_response_style(classification.response, intent=classification.intent.value)
                if not check_response_style(repaired, intent=classification.intent.value):
                    logger.info(
                        "drafted reply repaired deterministically for style: conversation_id=%s violations=%s "
                        "raw_draft=%r repaired=%r",
                        conversation_id, style_violations, classification.response, repaired,
                    )
                    classification = classification._replace(response=repaired)
                else:
                    logger.warning(
                        "style repair alone didn't resolve it, regenerating once: conversation_id=%s violations=%s "
                        "raw_draft=%r",
                        conversation_id, style_violations, classification.response,
                    )
                    style_retry = classify_and_respond(
                        business=business,
                        context=context,
                        knowledge_results=knowledge_results,
                        customer_message=content,
                        services=services,
                        locked_language=expected_reply_language,
                        hours=hours,
                        flagged_style_issues=style_violations,
                        style_exemplars=style_exemplars,
                    )
                    retry_repaired = repair_response_style(style_retry.response, intent=style_retry.intent.value)
                    retry_fact_violations = check_response_facts(
                        style_retry.response, currency=currency, services=service_facts,
                        hours_by_day=hours_by_day, known_text=known_text, knowledge_text=knowledge_text,
                    )
                    if retry_fact_violations:
                        # The regenerate is a fresh, unvalidated draft -- a style nit never
                        # justifies shipping a fabricated price/deposit, so keep the draft that
                        # already passed fact-grounding above, style violation and all.
                        logger.warning(
                            "style regenerate failed fact-grounding, keeping the fact-checked draft: "
                            "conversation_id=%s violations=%s",
                            conversation_id, retry_fact_violations,
                        )
                    elif not check_response_style(retry_repaired, intent=style_retry.intent.value):
                        classification = style_retry._replace(response=retry_repaired)
                    else:
                        # Residual violation even after a regenerate + repair (e.g. a single
                        # sentence that alone exceeds its ceiling) -- send the best-effort
                        # repaired text rather than loop again; this is a style nit, not a
                        # fact error, so it never warrants a human handoff.
                        logger.warning(
                            "style violation persisted after regenerate, sending best-effort repair anyway: "
                            "conversation_id=%s",
                            conversation_id,
                        )
                        classification = style_retry._replace(response=retry_repaired)

        # Tone/language phase: post-generation check -- does the drafted reply (the
        # original draft, or the fact-grounding retry above) actually match the
        # language it was told to write in? Skipped once fact-grounding has already
        # replaced the response with the pre-rendered fallback template above, which
        # is correctly-languaged by construction. expected_reply_language can be None
        # (a first message too ambiguous to call) or "mixed" (no single script to
        # enforce) -- both are real "nothing to check" cases, not bugs.
        if (
            fact_check_front_desk_reason is None
            and expected_reply_language in _VALID_LANGUAGES
            and _response_language_mismatch(classification.response, expected_reply_language, content)
        ):
            logger.warning(
                "drafted reply in the wrong language, regenerating once: conversation_id=%s expected=%s",
                conversation_id, expected_reply_language,
            )
            language_retry = classify_and_respond(
                business=business,
                context=context,
                knowledge_results=knowledge_results,
                customer_message=content,
                services=services,
                locked_language=expected_reply_language,
                hours=hours,
                language_repair_target=expected_reply_language,
                style_exemplars=style_exemplars,
            )
            if _response_language_mismatch(language_retry.response, expected_reply_language, content):
                logger.warning(
                    "language regenerate still didn't match, using it anyway: conversation_id=%s expected=%s",
                    conversation_id, expected_reply_language,
                )
            classification = language_retry

        # The "speak" step (voice_pass.py): only for intents whose reply IS the model's free text (every dispatched
        # intent is overwritten by a deterministic template further down), only when the draft has a defect a native
        # reader notices, and only if the rewrite keeps every fact -- re-checked here by the same fact_validator and
        # language check the draft passed. Any doubt: the already-validated draft is sent.
        if fact_check_front_desk_reason is None and classification.intent in _VOICE_PASS_INTENTS:
            _tv = time.perf_counter()
            voiced, voice_info = revoice(
                classification.response,
                customer=content,
                language=expected_reply_language or classification.message_language,
                previous_reply=_last_agent_reply(db, conversation_id),
                exemplars=style_exemplars,
                protected=(
                    [business.name, business.persona_name or "", business.address or "", business.phone or ""]
                    if business else []
                ) + [s.name for s in services],
            )
            if voice_info.get("used"):
                late_violations = check_response_facts(
                    voiced, currency=currency, services=service_facts,
                    hours_by_day=hours_by_day, known_text=known_text, knowledge_text=knowledge_text,
                )
                if late_violations:
                    voice_info.update(used=False, rejected=f"fact check: {late_violations}")
                elif expected_reply_language in _VALID_LANGUAGES and _response_language_mismatch(
                    voiced, expected_reply_language, content
                ):
                    voice_info.update(used=False, rejected="wrong language")
                else:
                    classification = classification._replace(response=voiced)
            if voice_info.get("reasons"):
                logger.info(
                    "voice pass: conversation_id=%s used=%s reasons=%s rejected=%s ms=%.0f",
                    conversation_id, bool(voice_info.get("used")), voice_info.get("reasons"),
                    voice_info.get("rejected") or voice_info.get("error"), (time.perf_counter() - _tv) * 1000,
                )
    except RuntimeError as exc:
        content_filtered = isinstance(exc, ContentFilterError)
        if content_filtered:
            logger.info("content filter refused the turn; declining as off-topic: conversation_id=%s", conversation_id)
            force_language = _expected_response_language(conversation, content, force_language)
        else:
            logger.exception(
                "LLM/embedding provider call failed after internal retries; degrading gracefully: "
                "conversation_id=%s",
                conversation_id,
            )
        reply_lock.acquire()
        if takeover_service.is_active(db, conversation_id=conversation_id):
            return _takeover_turn(db, conversation=conversation, content=content, external_message_id=external_message_id)
        return _handle_provider_failure(
            db,
            conversation=conversation,
            business_id=business_id,
            conversation_id=conversation_id,
            content=content,
            external_message_id=external_message_id,
            force_language=force_language,
            business=business,
            content_filtered=content_filtered,
        )
    intent, response_text = classification.intent, classification.response

    # Phase 52 checkpoint 2: the LLM call above takes seconds, long enough for a staff member to reply and claim the
    # conversation. Take the ReplyLock, THEN re-read the column from the DB (not the stale ORM object) and, if a human has
    # taken over meanwhile, throw the AI's draft away. Deliberately BEFORE anything with a side effect (contact update,
    # booking, handoff row) so an abandoned draft never leaves a real appointment behind with no confirmation. The lock stays
    # held through the final commit AND the channel send (the caller's `deliver`), so a claim landing after this check waits
    # until the reply is out instead of racing it (see takeover_service.ReplyLock).
    db.commit()  # persist the turn's one-shot draft-state clear and drop any row lock BEFORE waiting on the advisory lock
    reply_lock.acquire()
    if takeover_service.is_active(db, conversation_id=conversation_id):
        return _takeover_turn(
            db, conversation=conversation, content=content, external_message_id=external_message_id, intent=intent
        )

    # Phase 25 urgent fix: real testing showed the agent drifting between
    # English/Devanagari Nepali/Roman Nepali within a single conversation —
    # `language` below is the ONE language every deterministic sentence in
    # this turn (dispatch branches, contact-update/handoff addenda) renders
    # in, resolved deterministically from the customer's message, never left
    # to the LLM to remember on its own. See _resolve_locked_language.
    #
    # Phase 43h: force_language (a voice turn whose SPOKEN input was detected
    # as Nepali) bypasses this resolution/lock-mutation step ENTIRELY, not
    # just its result — a voice transcript is real Devanagari text (Deepgram's
    # Nepali STT always transcribes to that script), and letting it feed
    # _resolve_message_language/_resolve_locked_language as-is would silently
    # shift conversation.detected_language to ne_deva off the back of one
    # voice turn, changing how a LATER TYPED message renders even though the
    # customer never typed anything Nepali. force_language is used only for
    # THIS turn's own rendering; the persisted lock — and every typed-text
    # caller, which never sets force_language — is completely untouched.
    if force_language:
        language = force_language
        is_explicit_language_switch = False
    else:
        message_language = _resolve_message_language(content, classification.message_language)
        if business is not None and business.language_mode == LanguageMode.ASK and conversation.detected_language:
            # Phase 16: the customer told us their language up front, so passive-drift detection is off in ask mode; only an
            # explicit "switch to X" request (below) moves the lock.
            message_language = None
        # Phase 25b: an explicit, unambiguous "switch to X" request (as opposed
        # to passive drift) overrides the lock immediately, this same turn —
        # see _resolve_locked_language's docstring.
        switch_request = classification.language_switch_request or _explicit_switch_request(content)
        if (
            switch_request == ConversationLanguage.NE_DEVA.value
            and not _DEVANAGARI_RE.search(content)
            and "devanagari" not in content.lower()
        ):
            # "nepali ma bhannus" typed in Latin letters asks for Nepali, not for the Devanagari script.
            switch_request = ConversationLanguage.NE_ROMAN.value
        is_explicit_language_switch = switch_request in _VALID_LANGUAGES
        language = _resolve_locked_language(conversation, message_language, switch_request)

    # Phase 23 urgent fix: a customer volunteering their name/email/phone
    # mid-conversation (e.g. an anonymous widget "Website Visitor" who never
    # had an email on file) is now backed by a REAL tool, not LLM narration.
    # Runs regardless of intent — contact info can be given mid-booking,
    # mid-follow-up, anywhere — which is why this isn't wired through
    # TOOL_REGISTRY's per-intent dispatch (see UpdateContactInfoTool's
    # docstring). `_resolve_contact_update` re-diffs against the REAL
    # Customer row (never the LLM's own claim of what's missing) before
    # anything is written.
    #
    # Phase 24 urgent fix: moved ahead of the booking dispatch below (was
    # previously applied only after it) so that contact info volunteered in
    # the SAME message as a booking request (e.g. "book me at 2pm, I'm John,
    # 555-1234") immediately satisfies the contact-info gate — `customer_row`
    # is the same identity-mapped object `UpdateContactInfoTool.run()` mutates
    # in-session, so `has_contact` below sees the fresh value with no refetch.
    customer_row = db.get(Customer, conversation.customer_id)
    contact_changes = _resolve_contact_update(customer_row, classification.contact_info_update, content)
    # Phase 14 SECURITY: a resend only ever goes to the contact details ALREADY on file. A different email/phone typed
    # into the same message as a resend request must not be saved (and so cannot become the destination): on a resend
    # turn the contact update is dropped and the customer is told to make it a separate request.
    resend_redirect_attempt = bool(contact_changes) and intent == ConversationIntent.RESEND_CONFIRMATION
    if resend_redirect_attempt:
        logger.warning(
            "resend_confirmation: ignored a contact_info_update on a resend turn (fields=%s) conversation_id=%s",
            sorted(contact_changes), conversation_id,
        )
        contact_changes = {}
    resend_front_desk_reason: str | None = None
    contact_sentence = None
    if contact_changes:
        contact_result = UpdateContactInfoTool().run(
            db, business_id=business_id, customer_id=conversation.customer_id, fields=contact_changes
        )
        # The reply's language, not just the lock: on a first message the lock can still be empty while the reply is
        # Nepali, and the sentence went out in English (simulator 2026-10-01, no_reask).
        contact_sentence = _format_contact_update_result(contact_result, language or expected_reply_language)
        logger.info(
            "update_contact_info: conversation_id=%s fields=%s resends=%d",
            conversation_id,
            list(contact_changes.keys()),
            len(contact_result.get("resends", [])),
        )

    # Phase 24 urgent fix: real testing showed a booking going through for a
    # customer the business has no real way to reach — never gate on `name`
    # (every Customer row always has one, even a channel placeholder like
    # "Website Visitor"/"WhatsApp Contact"); the real signal is a phone or
    # email actually on file, which is what a confirmation/reminder needs.
    has_contact = bool(customer_row and (customer_row.phone or customer_row.email))

    # Phase 24 urgent fix: real testing caught a second, real bug here — this
    # was previously read from `context` (a snapshot taken BEFORE this turn),
    # so a customer who gave their real name in the SAME message that also
    # got booked (e.g. "book me at 2pm, I'm Jamie") saw the placeholder
    # "Website Visitor" in their own booking confirmation instead of "Jamie".
    # `customer_row` reflects any update this turn already applied above, so
    # reading it fresh from there closes the gap.
    customer_name = customer_row.known_name if customer_row else None

    # Real bug found live (PHASE_STATUS.md, "§2.C confirmation ignored"): a
    # customer naming a service while it's still just a service_question
    # ("teeth whitening, how much is that?") — not yet a booking intent —
    # had that service silently discarded, because this merge used to run
    # only inside the intent==BOOKING branch below. The customer would then
    # give a date/time on a LATER, genuinely booking-intent turn, the draft
    # would persist that date/time but never the service, and once contact
    # info completed the draft, the customer had to re-supply a service
    # they'd already named turns ago. Exact same class of gap Phase 24
    # already fixed for contact info (see the contact-info resolution above,
    # which likewise runs "regardless of intent") — a customer can mention a
    # service in any intent's message, so this can't be gated on this turn's
    # classified intent either. Runs unconditionally, before dispatch, so
    # every branch below (contact gate, missing-slots, the off-intent
    # completion branch) sees the fully up-to-date draft. A no-op whenever
    # this turn's booking_request is null (the overwhelmingly common case
    # for non-booking turns), so this changes nothing for any turn that
    # doesn't actually name a slot.
    booking_request = classification.booking_request
    if (
        intent == ConversationIntent.BOOKING
        and booking_request is not None
        and (not booking_request.get("service") or _resolve_service_by_name(services, booking_request["service"]) is None)
    ):
        # the model left the service out, or wrote a name that is not exactly a real one ("Teeth Cleaning" for "Teeth Cleaning
        # (Scaling & Polishing)"): either way the draft would stay service-less, so use the service the customer literally named
        booking_request = _fill_missing_booking_service(
            services, booking_request, content, conversation.booking_draft_offered_service_id,
            this_turn_pick=(
                _resolve_service_by_name(services, classification.proposed_service or "")
                or _service_named_in(services, classification.response)
            ),
        )
    reschedule_request = classification.reschedule_request
    if business is not None:
        today_local = datetime.now(ZoneInfo(business.timezone)).date()
        if booking_request is not None:
            booking_request = _verify_weekday_date(
                booking_request, content, today_local, fill_missing=intent == ConversationIntent.BOOKING
            )
        if reschedule_request is not None:
            reschedule_request = _verify_weekday_date(reschedule_request, content, today_local)
    service_known_before_this_turn = conversation.booking_draft_service_id is not None
    draft_switches = _merge_booking_draft(
        conversation, services, booking_request,
        offered_slots=offered_last_turn, tz=ZoneInfo(business.timezone) if business is not None else None,
        language=language,
    )

    # Record whatever service THIS turn's response just recommended (rule 14b), so the
    # offered-service fallback above can resolve a plain "yes" on the customer's very next
    # message even though they never name a service themselves. Fully overwritten every
    # turn -- a one-shot hint, same discipline as booking_draft_proposed_slots -- so a stale
    # recommendation from several turns ago can never resurface once the conversation has
    # moved on. Must run AFTER the offered-service fallback above, which needs the value
    # THIS turn started with (last turn's recommendation), not this turn's new one.
    newly_offered_service = (
        _resolve_service_by_name(services, classification.proposed_service) if classification.proposed_service else None
    )
    conversation.booking_draft_offered_service_id = newly_offered_service.id if newly_offered_service else None

    # The LLM never mutates data itself: only tool.run() would, and only the
    # orchestrator calls it. Phase 10 registered BOOKING; Phase 11 registers
    # CANCELLATION and RESCHEDULING the same way — this dispatch and the
    # tools.py registry itself didn't need to change at all.
    tool = find_tool(intent, business)
    if (
        intent == ConversationIntent.BOOKING
        and tool is not None
        and classification.group_booking_request is not None
        and business is not None
    ):
        if not has_contact:
            response_text = render("booking_no_contact", language)
        else:
            people = []
            unresolved = False
            for person in classification.group_booking_request["people"]:
                service = _resolve_service_by_name(services, person["service"])
                scheduled_at = _resolve_booking_datetime(business, person["date"], person["time"])
                if service is None or scheduled_at is None:
                    unresolved = True
                    break
                people.append({"label": person["label"], "service_id": service.id, "staff_id": None, "scheduled_at": scheduled_at})
            if not unresolved:
                result = tool.run_group(
                    db,
                    business_id=business_id,
                    customer_id=conversation.customer_id,
                    people=people,
                    all_or_nothing=classification.group_booking_request["all_or_nothing"],
                    source_channel=conversation.channel,
                )
                response_text = _format_group_booking_result(
                    result, services=services, tz=ZoneInfo(business.timezone), customer_name=customer_name, language=language
                )
                logger.info(
                    "book_group_appointment tool executed: conversation_id=%s success=%s people=%d",
                    conversation_id,
                    result["success"],
                    len(people),
                )
            else:
                # Same discipline as the single-booking fallback below: never pass an
                # unresolved service/time to the tool, never reuse the LLM's
                # placeholder response text for this turn.
                response_text = render("group_booking_clarify", language)
    elif intent == ConversationIntent.BOOKING and tool is not None and classification.group_booking_request is None and business is not None:
        # Phase 25a: the merge itself now runs unconditionally above (real bug
        # fix, see its own comment) — slots the customer already gave must not
        # be lost while contact info is still missing, so once contact info
        # arrives the booking can proceed immediately using everything already
        # collected, never re-asking for service/date/time it already has.
        # Phase 33: a per-turn instruction, not a persisted slot — the LLM's
        # honest read of whether THIS message is asking to see real options
        # rather than naming a specific time (intent.py rule 9). Read fresh
        # off this turn's raw extraction, never stored on the conversation.
        wants_availability = bool(
            classification.booking_request and classification.booking_request.get("wants_availability")
        )
        # Real conversation-quality spec-conformance finding (PHASE_STATUS.md):
        # the contact-info gate used to fire BEFORE ever resolving the draft,
        # so a brand-new customer asking a purely informational "is teeth
        # cleaning available tomorrow?" got "give me your phone number" as
        # its first-ever reply — never an actual answer, directly against
        # the spec's own "answer the question first" principle. Showing real
        # availability or asking which service/date/time is still missing
        # are both read-only, zero-commitment steps (nothing is written,
        # nothing needs to reach the customer) — resolving the draft FIRST,
        # regardless of has_contact, and gating on contact ONLY at the real
        # moment of commitment (service AND scheduled_at both known, i.e.
        # about to actually call tool.run()) is the correct point for this
        # business requirement (Phase 24) to apply. `_describe_known_booking_
        # slots`/`render_contact_gate` are unchanged — only WHEN they're
        # reached moved.
        service, scheduled_at = _resolve_booking_draft(conversation, services, business)
        # Real bug, found via live-replay regression testing (PHASE_STATUS.md): the
        # contact-info gate below used to treat any resolved service+scheduled_at as
        # confirmed-pending-contact and say so ("Got it ... I just need your name and a
        # phone number") without ever checking the slot was real -- the ONLY place that
        # actually happened was create_appointment, gated behind has_contact, so a
        # customer with no contact info on file yet got a confident false "Got it" for a
        # slot (e.g. a day the tenant is configured closed) that would only turn out to
        # be invalid once they gave their contact info and the tool actually ran. This is
        # the same real-time check create_appointment itself uses (get_available_slots,
        # the single source of truth for "is this business open, and is this slot free" —
        # never re-implemented here), called BEFORE any confirmation-sounding reply is
        # generated, so an invalid slot is now caught at the same turn it's named,
        # regardless of whether contact info is present yet.
        same_day_slots = (
            booking_service.get_available_slots(
                db, business_id=business_id, service_id=service.id, staff_id=None,
                date_from=scheduled_at.date(), date_to=scheduled_at.date(),
            )
            if service is not None and scheduled_at is not None
            else []
        )
        if service is not None and scheduled_at is not None and scheduled_at not in same_day_slots:
            # _propose_available_slots reads booking_draft_date (via _effective_draft_date) to
            # know which day the customer actually asked about, so it must run BEFORE that's
            # cleared below -- clearing first would silently lose "the customer asked about
            # Sunday" and make the search fall back to today instead of reporting Sunday's
            # real unavailability with the correct next-opening alternatives.
            response_text = _propose_available_slots(
                db, business_id=business_id, service=service, conversation=conversation,
                tz=ZoneInfo(business.timezone), language=language, previous_reply=_last_agent_reply(db, conversation_id),
                customer_message=content,
                # The customer named this exact time -- it just failed the real
                # availability check above, so the reply must say so rather than
                # silently pivot straight to alternatives (real gap found in
                # test_conversation.py's booking-failure suite).
                requested_time_unavailable=True,
            )
            response_text = _keep_draft_price(response_text, classification.response, services)
            # Same partial-clear judgment as _clear_booking_draft_after_attempt's failure
            # path: the requested time is definitely invalid, and the date only survives if
            # that SAME day still has other real openings (in which case it's still exactly
            # what the customer asked about). When the day is fully closed/booked, clear the
            # date too -- but NEVER booking_draft_search_anchor_date: _propose_available_slots
            # just wrote a fresh one above (the real day it found alternatives on), and this is
            # deliberately the only state that must survive so the next turn's bare-time/
            # bare-digit slot pick resolves against those real alternatives instead of the
            # customer's already-proven-invalid date (see _effective_draft_date's priority and
            # _propose_available_slots's own docstring on this exact mechanism).
            conversation.booking_draft_time = None
            if not same_day_slots:
                conversation.booking_draft_date = None
        elif service is not None and scheduled_at is not None:
            # The real moment of commitment — about to actually write a
            # booking — is the ONLY place contact info is required.
            if not has_contact:
                response_text = render_contact_gate(_describe_known_booking_slots(conversation, services, business, language), language)
            else:
                result = tool.run(
                    db,
                    business_id=business_id,
                    customer_id=conversation.customer_id,
                    service_id=service.id,
                    staff_id=None,
                    scheduled_at=scheduled_at,
                    conversation_id=conversation.id,
                )
                response_text = _format_booking_result(
                    result, service=service, tz=ZoneInfo(business.timezone), customer_name=customer_name, language=language
                )
                # Phase 25a-2: on success the draft's one job is done, so it's
                # cleared exactly as before. On failure, only the part of the
                # draft this specific attempt actually invalidated is cleared
                # — see _clear_booking_draft_after_attempt's docstring for why
                # the service (and sometimes the date) survives a failed
                # attempt rather than being lost wholesale.
                _clear_booking_draft_after_attempt(conversation, result, scheduled_at, ZoneInfo(business.timezone))
                logger.info(
                    "book_appointment tool executed: conversation_id=%s success=%s",
                    conversation_id,
                    result["success"],
                )
        elif wants_availability and service is not None:
            # Phase 33: the customer wants to see real options rather than
            # guess a time — a real, un-invented list, never a booking
            # attempt (nothing is written here; the customer still has to
            # pick one, which flows into the branch above like any other
            # explicitly-given date/time). Only reachable when a service
            # is already known — an ambiguous "what's available" with no
            # service is handled by the missing-slots branch below
            # instead, same as it always has been. Never gated on contact —
            # showing real availability is read-only, zero-commitment.
            response_text = _propose_available_slots(
                db,
                business_id=business_id,
                service=service,
                conversation=conversation,
                tz=ZoneInfo(business.timezone),
                language=language,
                previous_reply=_last_agent_reply(db, conversation_id),
                customer_message=content,
            )
            response_text = _keep_draft_price(response_text, classification.response, services)
            logger.info(
                "propose_available_slots: conversation_id=%s service_id=%s",
                conversation_id,
                service.id,
            )
        else:
            # Never a vague "should I go ahead and book that?" — Python (not
            # the LLM) determines exactly which slot(s) are still missing
            # from the REAL persisted draft and asks for ONLY those. This is
            # what actually closes the infinite-confirmation-loop bug: the
            # customer-facing question is always driven by real state, never
            # by the LLM's own (potentially indefinitely hedging) judgment.
            # Never gated on contact — asking which service/date/time is
            # also read-only, zero-commitment.
            missing = _booking_draft_missing(conversation, service, scheduled_at)
            response_text = render_missing_slots(missing, language)
            if service is not None and not service_known_before_this_turn:
                # trekking-10 clarifier branch: same one-time bridge as the slot list, so "which date and time?" doesn't
                # silently replace the model's explanation of which service this booking goes through.
                response_text = _service_bridge(service, content, _last_agent_reply(db, conversation_id), language) + response_text
    elif contact_changes and has_contact and business is not None and _has_partial_booking_draft(conversation):
        # Phase 25a gap, found live: contact info can arrive on a turn the
        # LLM classifies as something OTHER than "booking" (real transcript,
        # PHASE_STATUS.md — "Sure, I'm Devon, devon@example.com" alone read
        # as follow_up, not booking) — if that's the exact missing piece for
        # an otherwise-complete draft, the booking must fire THIS turn, not
        # wait for the customer to say "yes" again and hope for a
        # reclassification. Deliberately narrow, so this can never hijack an
        # unrelated turn: only a REAL contact update THIS turn, on a draft
        # that already has at least one slot filled, reaches here at all —
        # and even then, only overrides response_text when the draft turns
        # out to actually be complete right now (checked below); otherwise
        # this turn's real intent already decided response_text above, and
        # it's left untouched.
        booking_tool = find_tool(ConversationIntent.BOOKING, business)
        service, scheduled_at = _resolve_booking_draft(conversation, services, business)
        if booking_tool is not None and service is not None and scheduled_at is not None:
            result = booking_tool.run(
                db,
                business_id=business_id,
                customer_id=conversation.customer_id,
                service_id=service.id,
                staff_id=None,
                scheduled_at=scheduled_at,
                conversation_id=conversation.id,
            )
            response_text = _format_booking_result(
                result, service=service, tz=ZoneInfo(business.timezone), customer_name=customer_name, language=language
            )
            _clear_booking_draft_after_attempt(conversation, result, scheduled_at, ZoneInfo(business.timezone))
            logger.info(
                "book_appointment tool executed (off-intent turn, contact info completed a pending draft): "
                "conversation_id=%s success=%s",
                conversation_id,
                result["success"],
            )
    elif intent == ConversationIntent.CANCELLATION and tool is not None and business is not None and classification.cancellation_request is not None:
        appointment_id = _resolve_known_appointment(context, classification.cancellation_request["appointment_id"])
        if appointment_id is not None:
            result = tool.run(db, business_id=business_id, customer_id=conversation.customer_id, appointment_id=appointment_id)
            response_text = _format_cancellation_result(result, tz=ZoneInfo(business.timezone), customer_name=customer_name, language=language)
            logger.info(
                "cancel_appointment tool executed: conversation_id=%s success=%s",
                conversation_id,
                result["success"],
            )
        else:
            # The LLM named an appointment_id that isn't in this customer's real
            # active/recent-past list — never pass an unresolved id to the tool.
            response_text = render("cancellation_clarify", language)
    elif intent == ConversationIntent.RESCHEDULING and tool is not None and business is not None and reschedule_request is not None:
        appointment_id = _resolve_known_appointment(context, reschedule_request["appointment_id"])
        scheduled_at = _resolve_booking_datetime(
            business, reschedule_request["date"], reschedule_request["time"]
        )
        if appointment_id is not None and scheduled_at is not None:
            result = tool.run(
                db,
                business_id=business_id,
                customer_id=conversation.customer_id,
                appointment_id=appointment_id,
                new_scheduled_at=scheduled_at,
            )
            response_text = _format_reschedule_result(result, tz=ZoneInfo(business.timezone), customer_name=customer_name, language=language)
            logger.info(
                "reschedule_appointment tool executed: conversation_id=%s success=%s",
                conversation_id,
                result["success"],
            )
        else:
            response_text = render("reschedule_clarify", language)
    elif intent == ConversationIntent.APPOINTMENT_STATUS and tool is not None:
        # No extraction/resolution step needed (unlike booking/cancel/reschedule):
        # the tool always succeeds — worst case it truthfully reports nothing on
        # file — so there's no "unresolved" fallback path here.
        result = tool.run(db, business_id=business_id, customer_id=conversation.customer_id)
        tz = ZoneInfo(business.timezone) if business is not None else ZoneInfo("UTC")
        response_text = _format_appointment_status_result(result, tz=tz, customer_name=customer_name, language=language)
        logger.info(
            "appointment_status tool executed: conversation_id=%s active=%d recent_past=%d",
            conversation_id,
            len(result["active"]),
            len(result["recent_past"]),
        )
    elif intent == ConversationIntent.RESEND_CONFIRMATION and tool is not None and classification.resend_request is not None:
        appointment_id = _resolve_known_appointment(context, classification.resend_request["appointment_id"])
        if appointment_id is not None:
            result = tool.run(
                db,
                business_id=business_id,
                customer_id=conversation.customer_id,
                appointment_id=appointment_id,
                channel=classification.resend_request["channel"],
                conversation_channel=conversation.channel,
            )
            response_text = _format_resend_result(result, language=language)
            resend_front_desk_reason = _resend_needs_front_desk(result)
            logger.info(
                "resend_confirmation tool executed: conversation_id=%s success=%s rate_limited=%s",
                conversation_id,
                result["success"],
                result["rate_limited"],
            )
        else:
            # Same discipline as cancellation/reschedule: never pass an
            # unresolved id to the tool.
            response_text = render("resend_clarify", language)
    elif intent == ConversationIntent.OFF_TOPIC:
        # Phase 24 urgent fix: deterministic override, never the LLM's own
        # drafted text — see _off_topic_response's docstring. Deliberately NOT
        # routed through handoff_service below (OFF_TOPIC is not in
        # _INFO_INTENTS), so this never creates a HumanHandoff.
        response_text = _off_topic_response(business, language)
    elif intent == ConversationIntent.BUSINESS_HOURS:
        # Root-cause fix (read-through of backend/data/regression/failure_log_batches:
        # Samaj Dental Clinic's Sunday-open hours repeatedly misstated as closed) --
        # deterministic override, never the LLM's own drafted text. See
        # describe_business_hours' docstring for the confirmed hallucination this
        # replaces (fact_validator.check_weekday_hours stays on as a safety net for
        # every OTHER intent that may still mention a day's hours in passing).
        response_text = _keep_draft_price(describe_business_hours(hours, language), classification.response, services)

    # Phase 14: the service list is LLM-composed and live testing showed it comes back as one long ";"/","-separated line
    # for some phrasings — put each real service on its own line (deterministic, reads the real service names; leaves
    # anything that isn't clearly a list untouched). Only for the intents whose reply is the LLM's own free text.
    if intent in (
        ConversationIntent.SERVICE_QUESTION, ConversationIntent.PRICING_QUESTION, ConversationIntent.GENERAL_QUESTION
    ):
        response_text = format_service_list(response_text, [service.name for service in services])

    # Phase 23 urgent fix: contact info volunteered THIS turn (resolved above,
    # ahead of the booking dispatch — see the Phase 24 note there) is appended
    # to whatever response_text ended up being — the LLM's own draft for a
    # non-dispatched intent, or a dispatch branch's deterministic sentence.
    if contact_sentence:
        # A booking confirmation is several lines ending in the check-in link: on the same line the sentence read as
        # part of the URL (simulator 2026-10-01, "...qr/abc123 Tapaiko contact details update garidiye.").
        joiner = "\n" if "\n" in response_text or response_text.rstrip().split(" ")[-1].startswith("http") else " "
        response_text = f"{response_text}{joiner}{contact_sentence}"
    if resend_redirect_attempt:
        response_text = f"{response_text}\n{render('resend_contact_change_ignored', language)}"

    # Real gap found live (PHASE_STATUS.md, "silent service switch"): a
    # genuine switch away from a different, already-known service/date/time
    # (never a first-time fill-in — see _merge_booking_draft) gets a brief,
    # factual mention folded in here, the same "append a real fact, never a
    # new question" discipline as contact_sentence/handoff_addendum above and
    # below. Applies regardless of which dispatch branch produced
    # response_text, same as those two.
    for old, new in draft_switches:
        response_text = f"{response_text} {render('booking_draft_switch', language, old=old, new=new)}"

    # Root-cause fix for two confirmed missed_escalation bugs (read-through of
    # backend/data/regression/failure_log_batches/batch5_testchat_misc.json) -- a
    # described medical emergency and a customer stuck in a non-progressing loop both got
    # no escalation, because neither signal is something the LLM's own intent
    # classification reliably catches (it missed both, live). Both checks are
    # deterministic and independent of `intent`, same discipline as
    # is_explicit_language_switch/is_provider_failure elsewhere in this function.
    # Checked against `content` (the emergency wording) / the model's own original
    # draft `_llm_drafted_response` (the loop) -- NOT `response_text`, which the
    # grounding guard above may already have replaced with a fixed, non-question
    # fallback for this turn; the loop signal is about what the model keeps
    # drafting, independent of what this turn ultimately sends the customer.
    is_medical_emergency = _is_medical_emergency(content)
    is_stuck_in_a_loop = _is_stuck_in_a_loop(db, conversation_id, _llm_drafted_response)
    if is_medical_emergency:
        response_text = _emergency_response(business, language)
    escalation_front_desk_reason = None
    if is_medical_emergency:
        escalation_front_desk_reason = (
            "Customer's message describes what sounds like a medical/dental emergency; told to call/visit directly."
        )
    elif is_stuck_in_a_loop:
        escalation_front_desk_reason = (
            "Customer's request has gone unresolved after several near-identical replies from the agent."
        )

    # Phase 19: real human-handoff producer — Phase 16 flagged that
    # HumanHandoff had zero producers anywhere in this codebase. This checks
    # the same real knowledge_results already computed above (never a second
    # search) against a hard relevance threshold for genuine info questions,
    # plus the explicit COMPLAINT/HUMAN_HANDOFF intents Phase 8 already
    # classifies but never acted on. When a real handoff is created (or an
    # already-open one for this conversation is reused — see
    # handoff_service's anti-duplicate logic), a deterministic sentence is
    # appended so the customer is honestly told a person will follow up —
    # never invented, never left as a silent escalation. This intentionally
    # does NOT touch/replace response_text otherwise: Phase 8's honest
    # "I don't know" guardrail and Phase 9's natural tone stay exactly as the
    # LLM drafted them.
    #
    # Phase 23 urgent fix: `llm_confirmed_answered` (classification's real
    # `needs_human_handoff is False`) can now suppress a false-positive
    # handoff for PRICING_QUESTION/SERVICE_QUESTION that were already fully
    # answered from the real Available services list — see
    # handoff_service._handoff_reason's docstring for the live-verified bug
    # this fixes (a correctly-answered $450/60min pricing question was
    # getting "I've also let our team know" appended for no real reason).
    #
    # Phase 25b urgent fix: a real bug found live — the LLM invented a false
    # capability gap ("I can connect you with a Nepali-speaking team member")
    # for a plain language-switch request and it created a real handoff. This
    # system is natively fluent in every locked-language option (see rule 7 in
    # intent.py), so a language switch is never a real reason to escalate to a
    # human. `is_explicit_language_switch` structurally excludes it here —
    # `_handoff_reason` returns None for it regardless of intent or
    # similarity, the same hard, non-prompt-dependent guard OFF_TOPIC already
    # gets by simply not being in the triggering intent sets.
    handoff = handoff_service.maybe_create_handoff(
        db,
        business_id=business_id,
        conversation_id=conversation_id,
        intent=intent,
        best_similarity=best_similarity,
        # A configured-hours reply is read straight off the BusinessHours rows (describe_business_hours), so knowledge
        # similarity says nothing about it: Phase 4 eval d-102 got the full hours list plus "let me check with our senior team".
        llm_confirmed_answered=(
            True if classification.needs_human_handoff is False or (intent == ConversationIntent.BUSINESS_HOURS and hours) else None
        ),
        is_language_switch_request=is_explicit_language_switch,
        # escalation_front_desk_reason (stated emergency / stuck loop) must outrank
        # fact_check_front_desk_reason (generic zero-knowledge-match backstop): an
        # emergency message very often ALSO fails to match any knowledge article, and
        # staff triage must see "possible medical/dental emergency," never a generic
        # "no knowledge found" reason, for the same case this system already root-caused
        # and fixed once (see the missed_escalation comment above) -- reversed here would
        # silently reintroduce it.
        front_desk_reason=resend_front_desk_reason or escalation_front_desk_reason or fact_check_front_desk_reason,
    )
    # The handoff row is still created for staff, but the addendum is skipped when the reply already tells the customer
    # the team will follow up: the honest fallback ("…have them follow up with you"), the emergency reply ("I've also flagged
    # this conversation for our team"), a resend "connect you with our front desk", or hours not on file ("let me connect
    # you with our team"). Phase 4 eval: these got the promise twice.
    reply_says_team_follows_up = bool(
        fact_check_front_desk_reason or resend_front_desk_reason or is_medical_emergency
        or intent == ConversationIntent.BUSINESS_HOURS
    )
    # Last step: the word bank (Romanized Nepali) and the no-repeat / stock-ending / same-opener guards. Wording only --
    # see reply_polish's docstring for why no fact can change here.
    protected_names = [service.name for service in services]
    if business is not None:
        protected_names += [business.name, business.persona_name or "", business.address or "", business.phone or ""]
    if customer_name:
        protected_names.append(customer_name)
    response_text, polish_changes = finalize_reply(
        response_text,
        language=language,
        previous_replies=_agent_reply_history(db, conversation_id),
        customer_texts=_customer_texts(db, conversation_id, content),
        protected=protected_names,
        intent=intent.value,
    )
    if polish_changes:
        logger.info("reply polished: conversation_id=%s changes=%s", conversation_id, polish_changes)
    # The model's own reply often already promises the follow-up ("ma team sanga connect garidinchu", "our team will
    # call you"); adding the fixed closer on top made every complaint/haggle reply end with the same double promise
    # (simulator: the top not_template pattern). The handoff row is still created for staff either way.
    # Checked on the polished text: the word bank swaps "sampark" -> "contact" (simulator lawyer/haggle got its own
    # "team le sampark garnuhunchha" plus the closer), so the check must read the words the customer will see.
    if handoff is not None and not reply_says_team_follows_up and not _TEAM_FOLLOWUP_RE.search(response_text):
        response_text = f"{response_text} {render('handoff_addendum', language)}"

    customer_message = Message(
        conversation_id=conversation_id,
        sender_type=MessageSenderType.CUSTOMER,
        content=content,
        # Phase 18: persist the real classification this turn already computed
        # above — needed so follow-up detection can later query "did this
        # conversation ever show real interest" from real historical data.
        detected_intent=intent.value,
        # Phase 22: real idempotency key for webhook-delivered channels. If
        # this duplicates an already-processed webhook, the unique constraint
        # on external_message_id raises IntegrityError here — the caller
        # (app.services.channels.whatsapp) catches that specifically and
        # treats it as "already handled," never as a real error.
        external_message_id=external_message_id,
    )
    db.add(customer_message)
    db.commit()
    db.refresh(customer_message)

    agent_message = Message(
        conversation_id=conversation_id, sender_type=MessageSenderType.AGENT, content=response_text
    )
    db.add(agent_message)
    db.commit()
    db.refresh(agent_message)

    logger.info(
        "orchestrated conversation turn: conversation_id=%s intent=%s tool_available=%s",
        conversation_id,
        intent.value,
        tool is not None,
    )

    return {
        "intent": intent,
        "response": response_text,
        "customer_message_id": customer_message.id,
        "agent_message_id": agent_message.id,
        # Phase 43b: the real, just-updated Phase 25 lock for THIS turn --
        # voice.py uses it to decide whether Aura TTS can actually speak the
        # reply (English) or has to fall back to a text-only Nepali reply
        # with a spoken caveat (see _TTS_LANGUAGES there).
        "detected_language": conversation.detected_language,
    }
