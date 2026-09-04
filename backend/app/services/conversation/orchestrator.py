import logging
import uuid
from datetime import datetime
from zoneinfo import ZoneInfo

from sqlalchemy.orm import Session

from app.db.models.business import Business
from app.db.models.conversation import Message, MessageSenderType
from app.db.models.service import Service
from app.llm import get_embedding_provider
from app.memory import assemble_context
from app.memory.conversations import get_conversation
from app.memory.summarization import maybe_summarize_conversation
from app.schemas.conversation import ConversationIntent
from app.services import knowledge_service, service_service
from app.services.conversation import appointment_tools  # noqa: F401  registers CANCELLATION/RESCHEDULING tools
from app.services.conversation import booking_tool  # noqa: F401  registers the BOOKING tool
from app.services.conversation.intent import classify_and_respond
from app.services.conversation.tools import find_tool

logger = logging.getLogger(__name__)

KNOWLEDGE_TOP_K = 3

_BOOKING_CLARIFY_FALLBACK = (
    "Sorry, I want to make sure I get this right — could you tell me exactly which "
    "service, and the date and time you'd like?"
)
_GROUP_BOOKING_CLARIFY_FALLBACK = (
    "Sorry, I want to make sure I get everyone booked correctly — could you confirm the "
    "exact service, date, and time for each person?"
)
_CANCELLATION_CLARIFY_FALLBACK = (
    "Sorry, I want to make sure I cancel the right one — could you tell me which "
    "appointment (service and date) you'd like to cancel?"
)
_RESCHEDULE_CLARIFY_FALLBACK = (
    "Sorry, I want to make sure I get this right — which appointment would you like to "
    "move, and to what new date and time?"
)


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


def _format_booking_result(result: dict, *, service: Service, tz: ZoneInfo, customer_name: str | None) -> str:
    """The ONLY place a booking confirmation or failure sentence is composed —
    deliberately deterministic Python string formatting, not LLM narration, off
    the tool's real result dict. This is what makes the master-plan rule ("the
    LLM must never be trusted to directly report booked") actually airtight
    rather than just a prompt instruction: nothing here can be influenced by
    anything the model wrote."""
    who = f", {customer_name}" if customer_name else ""
    if result["success"]:
        appointment = result["appointment"]
        when = _format_local(appointment["scheduled_at"], tz)
        return (
            f"You're all set{who}! I've booked {service.name} for {when} "
            f"({appointment['duration_minutes']} min). Your booking ID is {appointment['id']}."
        )

    alternatives = result.get("alternative_slots") or []
    if alternatives:
        options = ", ".join(_format_local(slot, tz) for slot in alternatives)
        return (
            f"That time isn't available anymore{who} — {result['message'].rstrip('.').lower()}. "
            f"Here are some other openings for {service.name}: {options}. Would any of those work?"
        )
    return (
        f"That time isn't available anymore{who} — {result['message'].rstrip('.').lower()}. "
        f"I don't see any other openings for {service.name} in the next week — would you like me "
        f"to connect you with our team instead?"
    )


def _format_group_booking_result(
    result: dict, *, services: list[Service], tz: ZoneInfo, customer_name: str | None
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
            return (
                f"{people}: {service_name} on {when} ({appointment['duration_minutes']} min, "
                f"booking ID {appointment['id']})"
            )
        return f"{people}: not booked — {booking['message'].rstrip('.').lower()}"

    lines = "; ".join(describe(b) for b in result["bookings"])
    if result["success"]:
        intro = f"You're all set{who}! Here's what I booked:"
    elif result["all_or_nothing"]:
        intro = f"I wasn't able to get everyone in{who}, and since you wanted it all together, I didn't book anyone yet:"
    else:
        intro = f"Here's where things stand{who} — some went through, some didn't:"
    return f"{intro} {lines}."


def _format_cancellation_result(result: dict, *, tz: ZoneInfo, customer_name: str | None) -> str:
    """Same discipline as _format_booking_result: the only place a cancellation
    confirmation or failure sentence is composed, off the tool's real result."""
    who = f", {customer_name}" if customer_name else ""
    if result["success"]:
        when = _format_local(result["appointment"]["scheduled_at"], tz)
        return f"Done{who} — your appointment on {when} has been cancelled."
    return f"I couldn't cancel that{who} — {result['message'].rstrip('.').lower()}."


def _format_reschedule_result(result: dict, *, tz: ZoneInfo, customer_name: str | None) -> str:
    who = f", {customer_name}" if customer_name else ""
    if result["success"]:
        when = _format_local(result["appointment"]["scheduled_at"], tz)
        return f"All set{who} — your appointment has been moved to {when}."
    return f"I couldn't reschedule that{who} — {result['message'].rstrip('.').lower()}."


def _format_appointment_status_result(result: dict, *, tz: ZoneInfo, customer_name: str | None) -> str:
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
        return f"{a['service']} on {when} (booking ID {a['id']})"

    if not active and not recent_past:
        return f"You don't have any appointments on file with us right now{who}."

    parts = []
    if not active:
        parts.append(f"You don't have any upcoming appointments right now{who}.")
    elif len(active) == 1:
        parts.append(f"You have one upcoming appointment{who}: {describe(active[0])}, status: {active[0]['status']}.")
    else:
        lines = "; ".join(describe(a) for a in active)
        parts.append(f"You have {len(active)} upcoming appointments{who}: {lines}.")

    if recent_past:
        lines = "; ".join(f"{describe(a)} — {a['status']}" for a in recent_past)
        parts.append(f"Also on file (most recent): {lines}.")

    return " ".join(parts)


def handle_incoming_message(
    db: Session, *, conversation_id: uuid.UUID, business_id: uuid.UUID, content: str
) -> dict | None:
    """The full orchestration flow for one customer message: load context (Phase
    7) -> knowledge search (Phase 6) -> classify intent + draft response + extract
    a candidate booking/cancellation/reschedule request (one LLM call) -> if it's
    resolvable against real data, run the matching real tool (Phase 10 booking,
    Phase 11 cancellation/reschedule) and OVERWRITE the response with a
    deterministic sentence built from its real result -> persist both messages ->
    return the result.

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
    )
    intent, response_text = classification.intent, classification.response
    customer_name = (context or {}).get("customer", {}).get("name") if context else None

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
                result, services=services, tz=ZoneInfo(business.timezone), customer_name=customer_name
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
            response_text = _GROUP_BOOKING_CLARIFY_FALLBACK
    elif intent == ConversationIntent.BOOKING and tool is not None and classification.booking_request is not None and business is not None:
        service = _resolve_service_by_name(services, classification.booking_request["service"])
        scheduled_at = _resolve_booking_datetime(
            business, classification.booking_request["date"], classification.booking_request["time"]
        )
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
                result, service=service, tz=ZoneInfo(business.timezone), customer_name=customer_name
            )
            logger.info(
                "book_appointment tool executed: conversation_id=%s success=%s",
                conversation_id,
                result["success"],
            )
        else:
            # The LLM believed it had enough info but Python couldn't resolve the
            # service name or parse the date/time — never silently proceed on an
            # unresolved slot, and never reuse the LLM's placeholder response text
            # for this turn (it was written assuming the tool would run).
            response_text = _BOOKING_CLARIFY_FALLBACK
    elif intent == ConversationIntent.CANCELLATION and tool is not None and business is not None and classification.cancellation_request is not None:
        appointment_id = _resolve_known_appointment(context, classification.cancellation_request["appointment_id"])
        if appointment_id is not None:
            result = tool.run(db, business_id=business_id, customer_id=conversation.customer_id, appointment_id=appointment_id)
            response_text = _format_cancellation_result(result, tz=ZoneInfo(business.timezone), customer_name=customer_name)
            logger.info(
                "cancel_appointment tool executed: conversation_id=%s success=%s",
                conversation_id,
                result["success"],
            )
        else:
            # The LLM named an appointment_id that isn't in this customer's real
            # active/recent-past list — never pass an unresolved id to the tool.
            response_text = _CANCELLATION_CLARIFY_FALLBACK
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
            response_text = _format_reschedule_result(result, tz=ZoneInfo(business.timezone), customer_name=customer_name)
            logger.info(
                "reschedule_appointment tool executed: conversation_id=%s success=%s",
                conversation_id,
                result["success"],
            )
        else:
            response_text = _RESCHEDULE_CLARIFY_FALLBACK
    elif intent == ConversationIntent.APPOINTMENT_STATUS and tool is not None:
        # No extraction/resolution step needed (unlike booking/cancel/reschedule):
        # the tool always succeeds — worst case it truthfully reports nothing on
        # file — so there's no "unresolved" fallback path here.
        result = tool.run(db, business_id=business_id, customer_id=conversation.customer_id)
        tz = ZoneInfo(business.timezone) if business is not None else ZoneInfo("UTC")
        response_text = _format_appointment_status_result(result, tz=tz, customer_name=customer_name)
        logger.info(
            "appointment_status tool executed: conversation_id=%s active=%d recent_past=%d",
            conversation_id,
            len(result["active"]),
            len(result["recent_past"]),
        )

    customer_message = Message(
        conversation_id=conversation_id, sender_type=MessageSenderType.CUSTOMER, content=content
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
