import logging
import re
import time
import uuid
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from sqlalchemy.orm import Session

from app.core.entitlements import ensure_plan
from app.core.exceptions import NotFoundError, PlanRequiredError
from app.db.models.business import Business, BusinessPlan
from app.db.models.conversation import Conversation, Message, MessageSenderType
from app.db.models.customer import Customer
from app.db.models.notification import NotificationStatus
from app.db.models.service import Service
from app.llm import get_embedding_provider
from app.memory import assemble_context
from app.memory.conversations import get_conversation
from app.memory.summarization import maybe_summarize_conversation
from app.schemas.conversation import ConversationIntent, ConversationLanguage
from app.services import booking_service, business_hours_service, handoff_service, knowledge_service, service_service
from app.services.conversation import appointment_tools  # noqa: F401  registers CANCELLATION/RESCHEDULING tools
from app.services.conversation import booking_tool  # noqa: F401  registers the BOOKING tool
from app.services.conversation.contact_tool import UpdateContactInfoTool
from app.services.conversation.formatting import format_service_list
from app.services.conversation.intent import classify_and_respond
from app.services.conversation.response_templates import render, render_contact_gate, render_missing_slots
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


def _resolve_service_by_name(services: list[Service], name: str) -> Service | None:
    """Exact (case-insensitive) match only — the LLM is told to copy the name
    verbatim from the real list it was given, so a fuzzy/partial match would only
    paper over a genuine ambiguity. No match (including >1, which can't actually
    happen with unique names but is handled the same way as no match) means "not
    enough information yet", never a guess."""
    matches = [s for s in services if s.name.strip().lower() == name.strip().lower()]
    return matches[0] if len(matches) == 1 else None


def _resolve_booking_datetime(business: Business, date_str: str, time_str: str) -> datetime | None:
    try:
        tz = ZoneInfo(business.timezone)
        naive = datetime.strptime(f"{date_str} {time_str}", "%Y-%m-%d %H:%M")
        return naive.replace(tzinfo=tz)
    except (ValueError, KeyError):
        return None


def _format_local(dt: datetime, tz: ZoneInfo) -> str:
    return dt.astimezone(tz).strftime("%A, %B %-d at %-I:%M %p")


def _format_slot_options(slots: list[datetime], tz: ZoneInfo) -> str:
    """The slot-list body of "here's what's open". When EVERY slot is on the same real local date, the date is stated
    once and only times follow ("Monday, September 21 at 9:00 AM, 9:15 AM, 9:30 AM") instead of repeating the full date
    before each time. If the slots span more than one real date, each keeps its own full date — dropping it there would
    make the list ambiguous. A single slot is identical to _format_local (unchanged)."""
    local = [slot.astimezone(tz) for slot in slots]
    if len({slot.date() for slot in local}) == 1:
        return f"{local[0].strftime('%A, %B %-d')} at " + ", ".join(slot.strftime("%-I:%M %p") for slot in local)
    return ", ".join(_format_local(slot, tz) for slot in slots)


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


def _format_date_only(date_str: str) -> str:
    return datetime.strptime(date_str, "%Y-%m-%d").strftime("%A, %B %-d")


def _format_time_only(time_str: str) -> str:
    return datetime.strptime(time_str, "%H:%M").strftime("%-I:%M %p")


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


def _merge_booking_draft(
    conversation: Conversation,
    services: list[Service],
    booking_request: dict | None,
    offered_slots: list[datetime] | None = None,
    tz: ZoneInfo | None = None,
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
            switches.append((_format_date_only(conversation.booking_draft_date), _format_date_only(date_str)))
        conversation.booking_draft_date = date_str

    if time_str and _is_valid_time_str(time_str) and time_str != conversation.booking_draft_time:
        if conversation.booking_draft_time is not None and not is_pick:
            switches.append((_format_time_only(conversation.booking_draft_time), _format_time_only(time_str)))
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


def _describe_known_booking_slots(conversation: Conversation, services: list[Service], business: Business) -> str | None:
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
            when = _format_local(dt, ZoneInfo(business.timezone))
    if when is None and date_str and _is_valid_date_str(date_str):
        when = _format_date_only(date_str)
    elif when is None and time_str and _is_valid_time_str(time_str):
        when = datetime.strptime(time_str, "%H:%M").strftime("%-I:%M %p")

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
        when = _format_local(appointment["scheduled_at"], tz)
        text = render(
            "booking_success",
            language,
            who=who,
            service=service.name,
            when=when,
            duration=str(appointment["duration_minutes"]),
            id=str(appointment["id"]),
        )
        payment = result.get("payment")
        if payment is not None:
            # Phase 44: a real Payment row exists for this booking — state
            # the real deposit/remainder honestly, never silently omitted.
            # See response_templates.TEMPLATES["payment_deposit_required"]'s
            # own comment for why this is never a bare number.
            text = f"{text} {render('payment_deposit_required', language, percentage=str(payment['percentage']), currency=payment['currency'], amount=str(payment['amount']), remaining=str(payment['remaining']), link=payment['payment_url'])}"
        return text

    message = result["message"].rstrip(".").lower()
    alternatives = result.get("alternative_slots") or []
    if alternatives:
        options = ", ".join(_format_local(slot, tz) for slot in alternatives)
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


def _propose_available_slots(
    db: Session,
    *,
    business_id: uuid.UUID,
    service: Service,
    conversation: Conversation,
    tz: ZoneInfo,
    language: str | None,
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

    if not slots:
        return render("availability_none_no_alts", language, service=service.name)

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

    options = _format_slot_options(shown_slots, tz)
    if requested_date_str and _is_valid_date_str(requested_date_str) and slots[0].astimezone(tz).date() != search_start:
        return render(
            "availability_none_with_next_day",
            language,
            service=service.name,
            requested=_format_date_only(requested_date_str),
            options=options,
        )
    return render("availability_options", language, service=service.name, options=options)


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
            when = _format_local(appointment["scheduled_at"], tz)
            return render(
                "group_line_success",
                language,
                people=people,
                service_name=service_name,
                when=when,
                duration=str(appointment["duration_minutes"]),
                id=str(appointment["id"]),
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
        when = _format_local(result["appointment"]["scheduled_at"], tz)
        return render("cancellation_success", language, who=who, when=when)
    return render("cancellation_fail", language, who=who, message=result["message"].rstrip(".").lower())


def _format_reschedule_result(result: dict, *, tz: ZoneInfo, customer_name: str | None, language: str | None) -> str:
    who = f", {customer_name}" if customer_name else ""
    if result["success"]:
        when = _format_local(result["appointment"]["scheduled_at"], tz)
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
        when = _format_local(datetime.fromisoformat(a["scheduled_at"]), tz)
        return render("status_describe", language, service=a["service"], when=when, id=str(a["id"]))

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
    if chat is not None and chat["status"] == "sent":
        parts.append(render("resend_qr_link", language, url=chat["url"]))
    return "\n".join(parts) if parts else render("resend_send_failed", language)


def _resend_needs_front_desk(result: dict) -> str | None:
    """The real reason to open a HumanHandoff after a resend turn — or None. The rate-limited and send-failed replies
    both PROMISE "let me connect you with our front desk"; that promise must be backed by a real handoff row."""
    if result["rate_limited"]:
        return "Customer hit the confirmation/QR resend limit (3) for an appointment and was told to contact the front desk."
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


def _resolve_contact_update(customer: Customer | None, contact_info_update: dict | None) -> dict:
    """Re-diffs the LLM's candidate `contact_info_update` against the REAL
    current Customer row — never trusts the LLM's own claim about what's
    already on file (rule 14 in intent.py only asks it to try). A field is
    only included if the customer's Customer row genuinely doesn't already
    have that exact value. This is what makes UpdateContactInfoTool.run()
    only ever write real, actually-new information, and lets the caller
    detect "nothing to do" (empty dict) without invoking the tool at all."""
    if not contact_info_update or customer is None:
        return {}
    changed = {}
    for field, value in contact_info_update.items():
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

# Urgent fix (real bug found live, PHASE_STATUS.md): a customer's first
# message being a short, generic, cross-language-ambiguous greeting ("hlo",
# "hi", "hey"...) was getting a confident message_language self-report from
# the LLM (often "en", since these are English-alphabet fillers) that then
# locked the WHOLE conversation the instant it arrived — _resolve_locked_
# language locks immediately on the first clear signal, with no concept of
# "too little real signal to decide yet". None of these tokens carries any
# real evidence of which language the customer actually wants; a real
# Nepali/Romanized-Nepali greeting ("namaste", "dhanyabad", ...) is
# deliberately NOT in this set, since that IS real signal. Only applies when
# the message reduces to exactly this ONE token — "hi, cleaning ko price?"
# still carries real content and is unaffected.
_AMBIGUOUS_GREETING_TOKENS = {
    "hi", "hlo", "hllo", "hello", "hey", "heya", "heyy", "yo", "yoo", "sup", "hola", "hii", "oi", "ok", "okay",
}
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
    # Deliberately NOT added, despite appearing in the spec's own list:
    # - "chai" — collides with the English loanword "chai" (tea); the
    #   existing test test_resolve_message_language_roman_nepali_deterministic_
    #   override_beats_anchoring already asserts "Can I get a cha (chai tea)..."
    #   stays "en", which adding "chai" here would break.
    # - "okay"/"ok" — already deliberately excluded as ambiguous/no-signal
    #   (see _AMBIGUOUS_GREETING_TOKENS above); these are common neutral
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
    if len(words) == 1 and words[0].lower() in _AMBIGUOUS_GREETING_TOKENS:
        # Too little real signal to decide anything from — never locks,
        # never counts toward (or against) an existing streak.
        return None

    roman_signal_count = sum(1 for w in words if w.lower() in _ROMAN_NEPALI_WORDS)
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


def _handle_provider_failure(
    db: Session,
    *,
    conversation: Conversation,
    business_id: uuid.UUID,
    conversation_id: uuid.UUID,
    content: str,
    external_message_id: str | None,
    force_language: str | None = None,
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
    handoff_service.maybe_create_handoff(
        db, business_id=business_id, conversation_id=conversation_id,
        intent=ConversationIntent.UNKNOWN, best_similarity=None, is_provider_failure=True,
    )
    response_text = f"{render('provider_failure', language)} {render('handoff_addendum', language)}"

    customer_message = Message(
        conversation_id=conversation_id,
        sender_type=MessageSenderType.CUSTOMER,
        content=content,
        detected_intent=ConversationIntent.UNKNOWN.value,
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
        "orchestrated conversation turn: conversation_id=%s intent=provider_failure tool_available=False",
        conversation_id,
    )
    return {
        "intent": ConversationIntent.UNKNOWN,
        "response": response_text,
        "customer_message_id": customer_message.id,
        "agent_message_id": agent_message.id,
        "detected_language": language,
    }


# Phase 34 — a deliberately synthetic, literal trigger phrase, matched BEFORE
# the real knowledge-search/LLM-classification call (skipped entirely for
# this path, so a test doesn't cost a real API call or risk the LLM
# misclassifying it). No real premium feature exists in this codebase yet
# to gate for real (see app/api/routes/premium_test.py, the HTTP-layer twin
# of this same proof) — this is the "usable ... inside the conversation
# orchestrator's tool logic" half of the acceptance criteria: it calls the
# exact same `ensure_plan` the FastAPI `require_plan` dependency calls,
# proving one real gating function backs both surfaces, not two. Remove this
# once a real premium feature exists to demonstrate the mechanism instead —
# see PHASE_STATUS.md Phase 34.
_PREMIUM_TEST_TRIGGER = "test premium feature"


def _handle_premium_test_message(
    db: Session,
    *,
    business: Business | None,
    conversation_id: uuid.UUID,
    content: str,
    external_message_id: str | None,
) -> dict:
    try:
        ensure_plan(business, BusinessPlan.PREMIUM)
        response_text = "Premium feature executed."
    except PlanRequiredError as exc:
        response_text = f"This feature isn't available on your current plan. {exc.message}"

    customer_message = Message(
        conversation_id=conversation_id,
        sender_type=MessageSenderType.CUSTOMER,
        content=content,
        detected_intent=ConversationIntent.UNKNOWN.value,
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
        "intent": ConversationIntent.UNKNOWN,
        "response": response_text,
        "customer_message_id": customer_message.id,
        "agent_message_id": agent_message.id,
        # Phase 34's synthetic test trigger never loads a real Conversation
        # here -- no lock to report, and voice.py's TTS-language routing
        # already treats None as "speak it in English."
        "detected_language": None,
    }


def handle_incoming_message(
    db: Session,
    *,
    conversation_id: uuid.UUID,
    business_id: uuid.UUID,
    content: str,
    external_message_id: str | None = None,
    force_language: str | None = None,
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

    if content.strip().lower() == _PREMIUM_TEST_TRIGGER:
        return _handle_premium_test_message(
            db,
            business=business,
            conversation_id=conversation_id,
            content=content,
            external_message_id=external_message_id,
        )

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
        tool = find_tool(ConversationIntent.BOOKING)
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
                    _describe_known_booking_slots(conversation, services, business),
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
                )
                response_text = _format_booking_result(
                    result,
                    service=service,
                    tz=tz,
                    customer_name=customer_row.name if customer_row else None,
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
    try:
        _t3 = time.perf_counter()
        query_vector = get_embedding_provider().embed([content])[0]
        _t4 = time.perf_counter()
        knowledge_results = knowledge_service.filter_for_llm(
            knowledge_service.search_chunks(
                db, business_id=business_id, query_vector=query_vector, top_k=KNOWLEDGE_TOP_K
            )
        )
        _t5 = time.perf_counter()
        classification = classify_and_respond(
            business=business,
            context=context,
            knowledge_results=knowledge_results,
            customer_message=content,
            services=services,
            locked_language=force_language or conversation.detected_language,
            hours=hours,
        )
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
    except RuntimeError:
        logger.exception(
            "LLM/embedding provider call failed after internal retries; degrading gracefully: "
            "conversation_id=%s",
            conversation_id,
        )
        return _handle_provider_failure(
            db,
            conversation=conversation,
            business_id=business_id,
            conversation_id=conversation_id,
            content=content,
            external_message_id=external_message_id,
            force_language=force_language,
        )
    intent, response_text = classification.intent, classification.response

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
        # Phase 25b: an explicit, unambiguous "switch to X" request (as opposed
        # to passive drift) overrides the lock immediately, this same turn —
        # see _resolve_locked_language's docstring.
        is_explicit_language_switch = classification.language_switch_request in _VALID_LANGUAGES
        language = _resolve_locked_language(conversation, message_language, classification.language_switch_request)

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
    contact_changes = _resolve_contact_update(customer_row, classification.contact_info_update)
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
        contact_sentence = _format_contact_update_result(contact_result, language)
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
    customer_name = customer_row.name if customer_row else None

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
    draft_switches = _merge_booking_draft(
        conversation, services, classification.booking_request,
        offered_slots=offered_last_turn, tz=ZoneInfo(business.timezone) if business is not None else None,
    )

    # The LLM never mutates data itself: only tool.run() would, and only the
    # orchestrator calls it. Phase 10 registered BOOKING; Phase 11 registers
    # CANCELLATION and RESCHEDULING the same way — this dispatch and the
    # tools.py registry itself didn't need to change at all.
    tool = find_tool(intent)
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
        if service is not None and scheduled_at is not None:
            # The real moment of commitment — about to actually write a
            # booking — is the ONLY place contact info is required.
            if not has_contact:
                response_text = render_contact_gate(_describe_known_booking_slots(conversation, services, business), language)
            else:
                result = tool.run(
                    db,
                    business_id=business_id,
                    customer_id=conversation.customer_id,
                    service_id=service.id,
                    staff_id=None,
                    scheduled_at=scheduled_at,
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
            )
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
        booking_tool = find_tool(ConversationIntent.BOOKING)
        service, scheduled_at = _resolve_booking_draft(conversation, services, business)
        if booking_tool is not None and service is not None and scheduled_at is not None:
            result = booking_tool.run(
                db,
                business_id=business_id,
                customer_id=conversation.customer_id,
                service_id=service.id,
                staff_id=None,
                scheduled_at=scheduled_at,
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
    elif intent == ConversationIntent.RESCHEDULING and tool is not None and business is not None and classification.reschedule_request is not None:
        appointment_id = _resolve_known_appointment(context, classification.reschedule_request["appointment_id"])
        scheduled_at = _resolve_booking_datetime(
            business, classification.reschedule_request["date"], classification.reschedule_request["time"]
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
        response_text = f"{response_text} {contact_sentence}"
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
    best_similarity = max((similarity for _, _, similarity in knowledge_results), default=None)
    handoff = handoff_service.maybe_create_handoff(
        db,
        business_id=business_id,
        conversation_id=conversation_id,
        intent=intent,
        best_similarity=best_similarity,
        llm_confirmed_answered=(True if classification.needs_human_handoff is False else None),
        is_language_switch_request=is_explicit_language_switch,
        front_desk_reason=resend_front_desk_reason,
    )
    if handoff is not None:
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
