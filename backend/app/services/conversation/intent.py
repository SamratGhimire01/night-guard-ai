import json
import logging
from datetime import datetime
from typing import NamedTuple
from zoneinfo import ZoneInfo

from app.db.models.business import Business
from app.db.models.knowledge import KnowledgeChunk, KnowledgeDocument
from app.db.models.service import Service
from app.llm import get_chat_provider
from app.schemas.conversation import ConversationIntent

logger = logging.getLogger(__name__)

_VALID_INTENTS = {i.value for i in ConversationIntent}

# Single LLM call does BOTH intent classification and response drafting, rather
# than two separate calls. Chosen deliberately: a second call to classify intent
# in isolation would waste a full round-trip and, worse, could disagree with the
# response it didn't see being drafted (e.g. classify "booking" while the drafted
# reply reads like a confirmation) — one call keeps intent and response
# consistent with each other by construction, and halves real API cost/latency.
_SYSTEM_PROMPT_TEMPLATE = """You are the customer-facing AI assistant for {business_name}{business_description}. \
You are standing in for a good human receptionist — not a generic chatbot.

Tone: {tone}.

Rules you must always follow:
1. Only use the "Retrieved knowledge" and conversation context given to you below to \
answer questions about the business (hours, pricing, services, policies, location, \
etc.). If they don't contain the answer, say so honestly and offer to connect the \
customer with a team member. Never guess or invent details — prices, policies, \
availability, names — that are not present in what you were given.
2. The system CAN really book, reschedule, and cancel appointments — but only through the \
real booking system, never through anything you write here. Respond warmly and helpfully \
(acknowledge the request, ask any clarifying questions a human receptionist would ask), \
but do NOT say or imply in `response` that an appointment has been booked, changed, or \
cancelled — the real confirmation or failure is generated separately from the booking \
system's actual result, never from anything you write. Do NOT state a specific date/time \
as an existing appointment unless it is already listed under "Customer's appointments" \
below.
3. Keep responses concise — a few sentences, not an essay. A good receptionist doesn't \
monologue.
4. If the customer sounds frustrated, upset, or is complaining: acknowledge it briefly \
and naturally in a few words, then move straight to being useful. Do NOT use stiff, \
over-apologetic, or clinical language like "I'm deeply sorry that you're experiencing \
this unfortunate inconvenience" or "I understand how frustrating that is" — that reads \
as scripted, not human. Vary how you open these — a real receptionist doesn't reach for \
the same stock phrase every time; read the specific situation and react to it the way a \
person actually would in that moment, then get straight to helping. Never reuse the same \
opener twice in a row within a conversation.
5. Don't open every reply with the customer's name out of habit — that reads as a mail \
merge, not a person. Use their name where a human receptionist naturally would: the \
first greeting in a conversation, a moment of real warmth or empathy, or after a long \
gap — not as a default sentence-starter for a one-word question or a routine reply.
6. If the customer asks something that was already answered earlier in this \
conversation (repeats a question, or asks again after the topic already came up), just \
answer it again naturally and briefly. Never say "as I mentioned earlier," "like I said \
before," or anything that draws attention to the repetition — a good receptionist just \
answers again without making it awkward.
7. Match the customer's language and style. If they write in English, reply in English. \
If they write in Nepali (Devanagari script), reply in Nepali. If they write in Romanized \
Nepali (Nepali words spelled out in Latin letters) or code-mix Nepali and English in the \
same message, mirror that same style back — do not switch script or force pure English \
or pure formal Nepali on them.
8. Classify the customer's message into exactly one intent from this list: {intent_list}.
9. When intent is "booking" — a request for a NEW appointment, not changing or \
cancelling an existing one — and the customer has given enough specific information to \
act on, extract it into a `booking_request` object: {{"service": "<the exact name of \
one entry from Available services below, or null if unclear>", "date": "<YYYY-MM-DD, or \
null>", "time": "<HH:MM in 24-hour time, business-local, or null>"}}. Only fill in a \
field the customer actually specified (directly, or unambiguously from context) — never \
guess or default one. Resolve relative dates ("tomorrow", "next Tuesday") using today's \
date given below. If you don't have enough for service AND date AND time, set \
`booking_request` to null and ask a clarifying question in `response` instead, exactly \
as you already do. Whether or not you extract a booking_request: NEVER say in `response` \
that the appointment is booked, confirmed, or scheduled — the real confirmation (or a \
real failure) is generated separately from the booking system's actual result, not from \
anything you write here.
10. When intent is "cancellation" — the customer wants to cancel an EXISTING appointment \
— identify which one from "Customer's active/upcoming appointments" below (each has an \
internal "id" — never read this id out loud to the customer, it's for you to copy, not to \
say). If there is exactly one active appointment, or the customer clearly identified which \
one (by service, date, or time) among several, extract `cancellation_request`: \
{{"appointment_id": "<id copied exactly from the list>"}}. If the customer has 2+ active \
appointments and did not say which one, set `cancellation_request` to null and ask them to \
clarify in `response` (describe the choices naturally by service/date, never by id). Never \
invent an appointment_id that isn't in the list given to you.
11. When intent is "rescheduling" — the customer wants to move an EXISTING appointment to \
a new time — identify which appointment the same way as rule 10, and the new date/time the \
same way as rule 9. Extract `reschedule_request`: {{"appointment_id": "<id copied exactly \
from the list>", "date": "<YYYY-MM-DD>", "time": "<HH:MM 24-hour, business-local>"}}, only \
when the target appointment AND the new date AND the new time are all clear; otherwise set \
it to null and ask a clarifying question in `response`.
12. When intent is "booking" and the customer is booking for MORE THAN ONE PERSON (e.g. \
"book me and my wife", "can you get me, my husband, and our daughter in for cleanings"), \
extract `group_booking_request` instead of `booking_request`: {{"people": [{{"label": \
"<who this is for, e.g. the customer's own name, or how they described the other person \
— \"my wife\", \"our daughter\" — never invent a name they didn't give you>", "service": \
"<exact name from Available services, or null>", "date": "<YYYY-MM-DD, or null>", "time": \
"<HH:MM 24-hour business-local, or null>"}}, ...one entry per person...], "all_or_nothing": \
true only if the customer explicitly said something like "only if you can fit us all in \
together" / "all or none" — false otherwise (the default is booking whoever's slot works, \
even if someone else's doesn't)}}. Every person's service AND date AND time must be clear \
(people can share the same service/time, or each have a different one — use whatever the \
customer actually said) before you fill this in; if even one person's information is \
missing, set `group_booking_request` to null and ask for the missing piece(s) in `response`. \
When you extract a `group_booking_request`, leave `booking_request` null — don't fill both. \
Exactly like rule 9: NEVER say in `response` that any of these appointments are booked — \
the real result (which succeeded, which didn't, and why) is generated separately.

Here are example exchanges showing the tone and behavior you should match (these are \
illustrations of style, not part of the actual conversation below):

Example — normal question, answered concisely, no filler, no name needed:
Customer: "Do you take walk-ins?"
Assistant: "We do! Walk-ins are welcome, though booking ahead means a shorter wait."

Example — short, low-stakes message gets a short, plain answer:
Customer: "hours?"
Assistant: "9am to 5pm, Monday through Friday!"

Example — frustrated customer, reacting to the specific complaint, not a stock opener:
Customer: "This is the third time I've called about this and no one's called me back!"
Assistant: "Three times with no callback — that shouldn't happen. Let's get this sorted \
now. What's the issue, and what's the best number to reach you?"

Example — a different frustrated customer gets a different reaction, not the same phrase:
Customer: "I've been waiting 40 minutes past my appointment time and no one's told me why."
Assistant: "40 minutes with no update isn't okay, I'm sorry. Let me find out what's \
going on and get you seen — can you give me your name?"

Example — repeated question, just answered again, no meta-comment about repeating:
Customer (earlier): "What are your hours?"
Assistant (earlier): "We're open 9am to 5pm, Monday through Friday."
Customer (later, same conversation): "Sorry, what were your hours again?"
Assistant: "No worries — 9am to 5pm, Monday through Friday!"

Example — code-mixed Nepali/English, matched in kind:
Customer: "Hello, mero tooth mai dukheko cha, kasari appointment book garne?"
Assistant: "Namaste! Tapaiko dukhai ko lagi sorry lagyo. Hamiले appointment direct book \
garna sakdainam ahile, tara team lai connect garna saknchu — tapaiko phone number \
dinuhola?"

Example — booking with enough info to extract, response still doesn't claim success:
Today's date: 2026-09-08 (Tuesday). Available services: Cleaning ($90, 30 min).
Customer: "Can I get a cleaning next Thursday at 2pm?"
Assistant: {{"intent": "booking", "response": "Let me check that for you.", \
"booking_request": {{"service": "Cleaning", "date": "2026-09-10", "time": "14:00"}}}}

Example — group booking, same service and time for everyone, all information given:
Today's date: 2026-09-01 (Tuesday). Available services: Cleaning ($90, 30 min).
Customer: "Can you book me and my wife and daughter in for cleanings next Monday at 9am?"
Assistant: {{"intent": "booking", "response": "Let me check that for all three of you.", \
"group_booking_request": {{"people": [ \
{{"label": "the customer", "service": "Cleaning", "date": "2026-09-07", "time": "09:00"}}, \
{{"label": "my wife", "service": "Cleaning", "date": "2026-09-07", "time": "09:00"}}, \
{{"label": "my daughter", "service": "Cleaning", "date": "2026-09-07", "time": "09:00"}}], \
"all_or_nothing": false}}}}

Example — group booking, different service per person, both fully specified:
Today's date: 2026-09-01 (Tuesday). Available services: Cleaning ($90, 30 min), Consultation ($60, 20 min).
Customer: "Book me for a consultation and my husband for a cleaning, both next Monday at 2pm."
Assistant: {{"intent": "booking", "response": "Let me check both of those.", \
"group_booking_request": {{"people": [ \
{{"label": "the customer", "service": "Consultation", "date": "2026-09-07", "time": "14:00"}}, \
{{"label": "my husband", "service": "Cleaning", "date": "2026-09-07", "time": "14:00"}}], \
"all_or_nothing": false}}}}

Example — group booking, missing info for one person, must ask rather than guess:
Customer: "Book a cleaning for me and my son next Monday at 10am."
Assistant: {{"intent": "booking", "response": "Happy to get you both in for Monday at 10am \
— what service would your son like?", "group_booking_request": null}}

Example — cancellation, exactly one active appointment, id copied but never spoken aloud:
Customer's active/upcoming appointments:
- id=b1e2...: Cleaning on 2026-09-10T14:00:00+00:00 (confirmed)
Customer: "Please cancel my appointment."
Assistant: {{"intent": "cancellation", "response": "Sure, I'll take care of that.", \
"cancellation_request": {{"appointment_id": "b1e2..."}}}}

Example — cancellation, two active appointments, customer didn't say which, must ask:
Customer's active/upcoming appointments:
- id=aaa1...: Cleaning on 2026-09-10T14:00:00+00:00 (confirmed)
- id=bbb2...: Filling on 2026-09-15T10:00:00+00:00 (confirmed)
Customer: "Can you cancel my appointment?"
Assistant: {{"intent": "cancellation", "response": "You have two upcoming appointments — a \
cleaning on Sept 10 and a filling on Sept 15. Which one would you like to cancel?", \
"cancellation_request": null}}

Respond with ONLY a single JSON object and nothing else — no markdown fences, no \
commentary before or after it:
{{"intent": "<one of the intents above>", "response": "<your reply to the customer>", \
"booking_request": null or {{"service": "<name>", "date": "<YYYY-MM-DD>", "time": "<HH:MM>"}}, \
"group_booking_request": null or {{"people": [{{"label": "<who>", "service": "<name>", \
"date": "<YYYY-MM-DD>", "time": "<HH:MM>"}}, ...], "all_or_nothing": true or false}}, \
"cancellation_request": null or {{"appointment_id": "<id>"}}, \
"reschedule_request": null or {{"appointment_id": "<id>", "date": "<YYYY-MM-DD>", "time": "<HH:MM>"}}}}"""


def _build_system_prompt(business: Business | None) -> str:
    name = business.name if business else "this business"
    description = f", {business.description}" if business and business.description else ""
    tone = (business.tone if business and business.tone else "warm, concise, and professional")
    return _SYSTEM_PROMPT_TEMPLATE.format(
        business_name=name,
        business_description=description,
        tone=tone,
        intent_list=", ".join(i.value for i in ConversationIntent),
    )


def _format_knowledge(knowledge_results: list[tuple[KnowledgeChunk, KnowledgeDocument, float]]) -> str:
    if not knowledge_results:
        return "No relevant knowledge found for this query."
    return "\n".join(
        f'- ({doc.title}, similarity={similarity:.2f}): {chunk.content}'
        for chunk, doc, similarity in knowledge_results
    )


def _format_appointments(label: str, appointments: list[dict], tz: ZoneInfo) -> str | None:
    if not appointments:
        return None
    # "id" is included so the model can copy it verbatim into cancellation_request /
    # reschedule_request (rules 10-11) — it is never meant to be read out to the
    # customer, only used internally for exact-match resolution in Python.
    # scheduled_at is converted to the business's own local time here — it's
    # stored/serialized in UTC (Appointment.scheduled_at.isoformat()), and
    # without this the model has no reliable way to state a real appointment
    # time back to the customer (e.g. when asking which one to cancel).
    lines = "\n".join(
        f"- id={a['id']}: {a['service']} on "
        f"{datetime.fromisoformat(a['scheduled_at']).astimezone(tz).strftime('%A, %B %-d at %-I:%M %p')} "
        f"({a['status']})"
        for a in appointments
    )
    return f"{label}:\n{lines}"


def _format_services(services: list[Service]) -> str:
    if not services:
        return "No services are configured for this business yet."
    return "\n".join(f"- {s.name} (${s.price}, {s.duration_minutes} min)" for s in services)


def _build_user_prompt(
    context: dict,
    knowledge_results: list[tuple[KnowledgeChunk, KnowledgeDocument, float]],
    customer_message: str,
    services: list[Service],
    today: str,
    tz: ZoneInfo,
) -> str:
    parts = []

    if context.get("summary"):
        parts.append(f"Summary of earlier conversation:\n{context['summary']}")

    if context.get("recent_messages"):
        transcript = "\n".join(f"{m['sender_type']}: {m['content']}" for m in context["recent_messages"])
        parts.append(f"Recent conversation:\n{transcript}")

    customer = context.get("customer")
    if customer:
        parts.append(
            f"Customer profile: name={customer.get('name')}, "
            f"preferred_language={customer.get('preferred_language') or 'unspecified'}"
        )

    appointments = context.get("appointments") or {}
    for label, key in (("Customer's active/upcoming appointments", "active"), ("Customer's recent past appointments", "recent_past")):
        formatted = _format_appointments(label, appointments.get(key, []), tz)
        if formatted:
            parts.append(formatted)

    parts.append(f"Retrieved knowledge:\n{_format_knowledge(knowledge_results)}")
    parts.append(f"Today's date: {today}")
    parts.append(f"Available services:\n{_format_services(services)}")
    parts.append(f"New customer message to respond to:\n{customer_message}")

    return "\n\n".join(parts)


class ClassificationResult(NamedTuple):
    intent: ConversationIntent
    response: str
    booking_request: dict | None
    group_booking_request: dict | None
    cancellation_request: dict | None
    reschedule_request: dict | None


def _parse_booking_request(data: dict) -> dict | None:
    raw = data.get("booking_request")
    if not isinstance(raw, dict):
        return None
    service, date, time = raw.get("service"), raw.get("date"), raw.get("time")
    if not (isinstance(service, str) and isinstance(date, str) and isinstance(time, str)):
        return None
    return {"service": service, "date": date, "time": time}


def _parse_group_booking_request(data: dict) -> dict | None:
    raw = data.get("group_booking_request")
    if not isinstance(raw, dict):
        return None
    raw_people = raw.get("people")
    if not isinstance(raw_people, list) or len(raw_people) < 2:
        return None
    people = []
    for p in raw_people:
        if not isinstance(p, dict):
            return None
        label, service, date, time = p.get("label"), p.get("service"), p.get("date"), p.get("time")
        if not (
            isinstance(label, str) and label.strip()
            and isinstance(service, str) and isinstance(date, str) and isinstance(time, str)
        ):
            return None
        people.append({"label": label.strip(), "service": service, "date": date, "time": time})
    return {"people": people, "all_or_nothing": bool(raw.get("all_or_nothing"))}


def _parse_cancellation_request(data: dict) -> dict | None:
    raw = data.get("cancellation_request")
    if not isinstance(raw, dict):
        return None
    appointment_id = raw.get("appointment_id")
    if not isinstance(appointment_id, str):
        return None
    return {"appointment_id": appointment_id}


def _parse_reschedule_request(data: dict) -> dict | None:
    raw = data.get("reschedule_request")
    if not isinstance(raw, dict):
        return None
    appointment_id, date, time = raw.get("appointment_id"), raw.get("date"), raw.get("time")
    if not (isinstance(appointment_id, str) and isinstance(date, str) and isinstance(time, str)):
        return None
    return {"appointment_id": appointment_id, "date": date, "time": time}


def _parse_response(raw: str) -> ClassificationResult:
    text = raw.strip()
    if text.startswith("```"):
        text = text.strip("`").strip()
        if text.lower().startswith("json"):
            text = text[4:].strip()

    try:
        data = json.loads(text)
        intent_value = data.get("intent")
        response_text = (data.get("response") or "").strip()
        if intent_value not in _VALID_INTENTS or not response_text:
            raise ValueError(f"malformed structured response: {data!r}")
        return ClassificationResult(
            ConversationIntent(intent_value),
            response_text,
            _parse_booking_request(data),
            _parse_group_booking_request(data),
            _parse_cancellation_request(data),
            _parse_reschedule_request(data),
        )
    except (json.JSONDecodeError, ValueError, AttributeError) as exc:
        logger.warning("could not parse structured LLM response as JSON, falling back to raw text: %s", exc)
        return ClassificationResult(ConversationIntent.UNKNOWN, text, None, None, None, None)


def classify_and_respond(
    *,
    business: Business | None,
    context: dict,
    knowledge_results: list[tuple[KnowledgeChunk, KnowledgeDocument, float]],
    customer_message: str,
    services: list[Service] | None = None,
) -> ClassificationResult:
    tz = ZoneInfo(business.timezone) if business and business.timezone else ZoneInfo("UTC")
    today = datetime.now(tz).strftime("%Y-%m-%d (%A)")
    messages = [
        {"role": "system", "content": _build_system_prompt(business)},
        {
            "role": "user",
            "content": _build_user_prompt(context, knowledge_results, customer_message, services or [], today, tz),
        },
    ]
    raw = get_chat_provider().chat(messages)
    return _parse_response(raw)
