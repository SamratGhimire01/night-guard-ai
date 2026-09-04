import logging
import re
import uuid
from datetime import datetime
from zoneinfo import ZoneInfo

from sqlalchemy.orm import Session

from app.db.models.business import Business
from app.db.models.conversation import Conversation, Message, MessageSenderType
from app.db.models.customer import Customer
from app.db.models.notification import NotificationStatus
from app.db.models.service import Service
from app.llm import get_embedding_provider
from app.memory import assemble_context
from app.memory.conversations import get_conversation
from app.memory.summarization import maybe_summarize_conversation
from app.schemas.conversation import ConversationIntent, ConversationLanguage
from app.services import handoff_service, knowledge_service, service_service
from app.services.conversation import appointment_tools  # noqa: F401  registers CANCELLATION/RESCHEDULING tools
from app.services.conversation import booking_tool  # noqa: F401  registers the BOOKING tool
from app.services.conversation.contact_tool import UpdateContactInfoTool
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


def _merge_booking_draft(conversation: Conversation, services: list[Service], booking_request: dict | None) -> None:
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
    booking_draft's job, not the model's."""
    if not booking_request:
        return
    service_name = booking_request.get("service")
    if service_name:
        service = _resolve_service_by_name(services, service_name)
        if service is not None:
            conversation.booking_draft_service_id = service.id
    date_str = booking_request.get("date")
    if date_str and _is_valid_date_str(date_str):
        conversation.booking_draft_date = date_str
    time_str = booking_request.get("time")
    if time_str and _is_valid_time_str(time_str):
        conversation.booking_draft_time = time_str


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
    if conversation.booking_draft_date and conversation.booking_draft_time:
        scheduled_at = _resolve_booking_datetime(business, conversation.booking_draft_date, conversation.booking_draft_time)
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

    date_str, time_str = conversation.booking_draft_date, conversation.booking_draft_time
    when = None
    if date_str and time_str:
        dt = _resolve_booking_datetime(business, date_str, time_str)
        if dt is not None:
            when = _format_local(dt, ZoneInfo(business.timezone))
    if when is None and date_str and _is_valid_date_str(date_str):
        when = datetime.strptime(date_str, "%Y-%m-%d").strftime("%A, %B %-d")
    elif when is None and time_str and _is_valid_time_str(time_str):
        when = datetime.strptime(time_str, "%H:%M").strftime("%-I:%M %p")

    parts = [p for p in (service.name if service else None, when) if p]
    return ", ".join(parts) if parts else None


def _booking_draft_missing(conversation: Conversation, service: Service | None, scheduled_at: datetime | None) -> list[str]:
    missing = []
    if service is None:
        missing.append("service")
    if scheduled_at is None:
        if not conversation.booking_draft_date:
            missing.append("date")
        if not conversation.booking_draft_time:
            missing.append("time")
        if conversation.booking_draft_date and conversation.booking_draft_time:
            # Both individually well-formed (format-validated at merge time)
            # but failed to resolve together — should not happen in practice,
            # but never silently treat as complete: ask for both again
            # rather than guess which one was actually the problem.
            missing.extend(["date", "time"])
    return missing


def _clear_booking_draft(conversation: Conversation) -> None:
    conversation.booking_draft_service_id = None
    conversation.booking_draft_date = None
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
        return render(
            "booking_success",
            language,
            who=who,
            service=service.name,
            when=when,
            duration=str(appointment["duration_minutes"]),
            id=str(appointment["id"]),
        )

    message = result["message"].rstrip(".").lower()
    alternatives = result.get("alternative_slots") or []
    if alternatives:
        options = ", ".join(_format_local(slot, tz) for slot in alternatives)
        return render(
            "booking_unavailable_with_alts", language, who=who, message=message, service=service.name, options=options
        )
    return render("booking_unavailable_no_alts", language, who=who, message=message, service=service.name)


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


def _resolve_message_language(content: str, llm_reported: str | None) -> str | None:
    if _DEVANAGARI_RE.search(content):
        return ConversationLanguage.NE_DEVA.value
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
    language = conversation.detected_language
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
    }


def handle_incoming_message(
    db: Session,
    *,
    conversation_id: uuid.UUID,
    business_id: uuid.UUID,
    content: str,
    external_message_id: str | None = None,
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

    Returns None if the conversation doesn't exist / isn't this business's (the
    route turns that into a 404, same IDOR-safe pattern as every prior phase).
    """
    conversation = get_conversation(db, conversation_id=conversation_id, business_id=business_id)
    if conversation is None:
        return None

    # Fold in anything that aged out since the last turn so this turn's context
    # stays bounded (Phase 7) rather than growing with every message.
    maybe_summarize_conversation(db, conversation_id=conversation_id, business_id=business_id)
    context = assemble_context(db, conversation_id=conversation_id, business_id=business_id)

    business = db.get(Business, business_id)
    services = service_service.list_services(db, business_id=business_id)

    # Urgent fix (real 500 found live, PHASE_STATUS.md): `_post` (app/llm/
    # azure_openai.py) already retries transient provider failures internally
    # — this catches the case where even that retry budget is exhausted (a
    # genuine, if rare, real-world outage) so it never reaches the customer as
    # a raw 500. `RuntimeError` is raised nowhere else in this codebase, so
    # this can only ever catch a real LLM/embedding provider failure, never
    # mask an unrelated bug in knowledge search or classification itself.
    try:
        query_vector = get_embedding_provider().embed([content])[0]
        knowledge_results = knowledge_service.search_chunks(
            db, business_id=business_id, query_vector=query_vector, top_k=KNOWLEDGE_TOP_K
        )
        classification = classify_and_respond(
            business=business,
            context=context,
            knowledge_results=knowledge_results,
            customer_message=content,
            services=services,
            locked_language=conversation.detected_language,
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
        )
    intent, response_text = classification.intent, classification.response

    # Phase 25 urgent fix: real testing showed the agent drifting between
    # English/Devanagari Nepali/Roman Nepali within a single conversation —
    # `language` below is the ONE language every deterministic sentence in
    # this turn (dispatch branches, contact-update/handoff addenda) renders
    # in, resolved deterministically from the customer's message, never left
    # to the LLM to remember on its own. See _resolve_locked_language.
    message_language = _resolve_message_language(content, classification.message_language)
    # Phase 25b: an explicit, unambiguous "switch to X" request (as opposed to
    # passive drift) overrides the lock immediately, this same turn — see
    # _resolve_locked_language's docstring.
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
        # Phase 25a: merge happens BEFORE the contact-info gate, unconditionally
        # — slots the customer already gave must not be lost while contact info
        # is still missing, so once contact info arrives the booking can proceed
        # immediately using everything already collected, never re-asking for
        # service/date/time it already has.
        _merge_booking_draft(conversation, services, classification.booking_request)
        if not has_contact:
            # Phase 25a-2: dynamic — reflects whatever the draft already has
            # (service/date/time accumulated across turns), never the same
            # static sentence regardless of real progress. See
            # _describe_known_booking_slots / render_contact_gate.
            response_text = render_contact_gate(_describe_known_booking_slots(conversation, services, business), language)
        else:
            service, scheduled_at = _resolve_booking_draft(conversation, services, business)
            if service is not None and scheduled_at is not None:
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
            else:
                # Never a vague "should I go ahead and book that?" — Python (not
                # the LLM) determines exactly which slot(s) are still missing
                # from the REAL persisted draft and asks for ONLY those. This is
                # what actually closes the infinite-confirmation-loop bug: the
                # customer-facing question is always driven by real state, never
                # by the LLM's own (potentially indefinitely hedging) judgment.
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
    elif intent == ConversationIntent.OFF_TOPIC:
        # Phase 24 urgent fix: deterministic override, never the LLM's own
        # drafted text — see _off_topic_response's docstring. Deliberately NOT
        # routed through handoff_service below (OFF_TOPIC is not in
        # _INFO_INTENTS), so this never creates a HumanHandoff.
        response_text = _off_topic_response(business, language)

    # Phase 23 urgent fix: contact info volunteered THIS turn (resolved above,
    # ahead of the booking dispatch — see the Phase 24 note there) is appended
    # to whatever response_text ended up being — the LLM's own draft for a
    # non-dispatched intent, or a dispatch branch's deterministic sentence.
    if contact_sentence:
        response_text = f"{response_text} {contact_sentence}"

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
    }
