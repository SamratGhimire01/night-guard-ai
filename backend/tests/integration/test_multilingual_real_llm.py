"""Real-LLM, real-API conversation-quality regression suite — consolidates
what was previously scattered across manual, one-off transcripts pasted into
PHASE_STATUS.md (Phase 9's tone eval, Phase 25/25b's language-lock live
verification) into one repeatable, gated pytest file.

Covers the master plan's explicit test-case list: English, Nepali
(Devanagari), Romanized Nepali, code-mixed Nepali/English, emotional/
frustrated, repeated questions, family/group booking, follow-up recall, and
rescheduling.

SKIPPED BY DEFAULT — same discipline as test_memory.py::test_summarization_real_api.
Every case here hits the real, configured Azure OpenAI chat + embeddings API
(real cost, real latency, ~1-2 minutes total), so it is never part of the
default `pytest tests/` run. Run explicitly:

    RUN_REAL_LLM_TESTS=1 python -m pytest tests/integration/test_multilingual_real_llm.py -v -s

Tone/style quality itself is inherently subjective (Phase 9's own framing) —
this file does NOT attempt to automate a tone judgment. What it DOES assert,
mechanically, per the master plan's own explicit failure modes:
  - the conversation never crashes on any of these inputs (no 500)
  - the customer's language/script is mirrored back and the persisted
    `Conversation.detected_language` lands where expected (Phase 25)
  - a repeated question is answered again, never with "as I mentioned"/
    "like I said before" (Phase 9 rule 5)
  - a frustrated customer's response never contains the master plan's own
    named bad examples of boilerplate over-apology (Phase 9 rule 4)
  - a family/group booking produces the real, correct number of Appointment
    rows at the real requested times (Phase 12)
  - a fact stated earlier in the conversation (a real, server-known price)
    is recalled correctly later, not re-invented (Phase 7/8 memory)
  - a reschedule request actually moves the real appointment's real DB row
    (Phase 11)
Every response is also printed in full (run with -s) for a human to read for
tone, the same "paste the real transcript" discipline every prior phase used
— this file makes that transcript repeatable instead of one-off.
"""

import os
import re
import uuid
from datetime import date, timedelta

import pytest
from fastapi.testclient import TestClient

import app.api.routes.widget as widget_module
from app.core.rate_limit import WIDGET_IP_MAX_ATTEMPTS, WIDGET_SESSION_MAX_ATTEMPTS, WIDGET_WINDOW_SECONDS, RateLimiter
from app.db.database import SessionLocal
from app.db.models.appointment import Appointment
from app.db.models.business import Business
from app.db.models.conversation import Conversation
from app.main import app

pytestmark = pytest.mark.skipif(
    not os.environ.get("RUN_REAL_LLM_TESTS"),
    reason="hits the real chat + embedding LLM; run explicitly with RUN_REAL_LLM_TESTS=1",
)

client = TestClient(app)

_DEVANAGARI_RE = re.compile(r"[ऀ-ॿ]")

# Phase 9's own named examples of the boilerplate this system must never produce.
_FORBIDDEN_BOILERPLATE = (
    "i understand how frustrating that is",
    "i'm deeply sorry that you're experiencing this unfortunate inconvenience",
    "as i mentioned earlier",
    "like i said before",
)


def _unique_email(label: str) -> str:
    return f"{label}-{uuid.uuid4().hex[:10]}@example.com"


def _auth_header(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


def _next_weekday(target_weekday: int) -> date:
    today = date.today()
    days_ahead = (target_weekday - today.weekday()) % 7 or 7
    return today + timedelta(days=days_ahead)


@pytest.fixture(autouse=True)
def _fresh_rate_limiters(monkeypatch):
    """Real per-test isolation — a real multi-turn conversation across 9
    test functions must never trip the widget's own real IP/session
    limiters (Phase 21/29), which are process-wide singletons."""
    monkeypatch.setattr(
        widget_module, "widget_ip_rate_limiter", RateLimiter(max_attempts=WIDGET_IP_MAX_ATTEMPTS, window_seconds=WIDGET_WINDOW_SECONDS)
    )
    monkeypatch.setattr(
        widget_module,
        "widget_session_rate_limiter",
        RateLimiter(max_attempts=WIDGET_SESSION_MAX_ATTEMPTS, window_seconds=WIDGET_WINDOW_SECONDS),
    )


@pytest.fixture
def business():
    """A real registered business, Mon-Sat 9am-5pm UTC (Sunday closed), one
    real $90/30min 'Teeth Cleaning' service — the same shape of business
    every Phase 23-25c live transcript used."""
    email = _unique_email("multilingual-eval")
    resp = client.post(
        "/api/v1/auth/register",
        json={"business_name": "Multilingual Eval Dental", "timezone": "UTC", "email": email, "password": "correcthorse1"},
    )
    assert resp.status_code == 201, resp.text
    business_id = resp.json()["business_id"]
    token = client.post("/api/v1/auth/login", json={"email": email, "password": "correcthorse1"}).json()["access_token"]

    days = [{"day_of_week": d, "open_time": "09:00:00", "close_time": "17:00:00"} for d in range(6)]
    days.append({"day_of_week": 6, "closed": True})
    assert client.put("/api/v1/business/hours", json={"days": days}, headers=_auth_header(token)).status_code == 200

    service = client.post(
        "/api/v1/services",
        json={"name": "Teeth Cleaning", "price": "90.00", "duration_minutes": 30},
        headers=_auth_header(token),
    )
    assert service.status_code == 201, service.text

    yield {"business_id": business_id, "token": token, "service_price": "90"}

    with SessionLocal() as db:
        b = db.get(Business, uuid.UUID(business_id))
        if b is not None:
            db.delete(b)
        db.commit()


def _say(business_id: str, content: str, session_token: str | None = None) -> dict:
    resp = client.post(
        f"/api/v1/widget/{business_id}/messages",
        json={"content": content, **({"session_token": session_token} if session_token else {})},
    )
    assert resp.status_code == 200, resp.text
    return resp.json()


def _print_turn(customer: str, agent_reply: str) -> None:
    print(f"\nCustomer: {customer!r}\nAssistant: {agent_reply!r}")


# --- 1. English (baseline) --------------------------------------------------


def test_english_pricing_question(business):
    reply = _say(business["business_id"], "Hi, how much is a teeth cleaning?")
    _print_turn("Hi, how much is a teeth cleaning?", reply["response"])
    assert business["service_price"] in reply["response"], "the real price must appear, not an invented one"


# --- 2. Nepali (Devanagari) --------------------------------------------------


def test_nepali_devanagari_pricing_question(business):
    message = "नमस्ते, तपाईंको क्लिनिकमा क्लिनिङको लागि कति लाग्छ?"
    reply = _say(business["business_id"], message)
    _print_turn(message, reply["response"])
    assert business["service_price"] in reply["response"]
    assert _DEVANAGARI_RE.search(reply["response"]), "a Devanagari question must get a Devanagari answer"

    with SessionLocal() as db:
        conversation = db.query(Conversation).filter(Conversation.business_id == uuid.UUID(business["business_id"])).one()
        assert conversation.detected_language == "ne_deva"


# --- 3. Romanized Nepali -----------------------------------------------------


def test_romanized_nepali_pricing_question(business):
    message = "Namaste, tapaiko cleaning ko lagi kati parcha?"
    reply = _say(business["business_id"], message)
    _print_turn(message, reply["response"])
    assert business["service_price"] in reply["response"]
    assert not _DEVANAGARI_RE.search(reply["response"]), "Romanized Nepali must not switch script"

    with SessionLocal() as db:
        conversation = db.query(Conversation).filter(Conversation.business_id == uuid.UUID(business["business_id"])).one()
        # Phase 25's own documented, known limitation: unlike Devanagari
        # (mechanically detectable, forced deterministically), the
        # en/ne_roman/mixed three-way Latin-script split relies entirely on
        # the LLM's self-report, which is genuinely non-deterministic message
        # to message (confirmed directly: 3 identical direct calls to
        # classify_and_respond for this exact message returned "ne_roman"
        # twice and "ne_deva" once, despite the raw text being pure Latin
        # script). `_resolve_message_language` correctly nulls out an
        # unbacked "ne_deva" claim here, which can legitimately leave no
        # lock at all on a single turn. What must NEVER happen is locking to
        # the WRONG language outright (en, or a surviving ne_deva) —that's
        # what this asserts against.
        assert conversation.detected_language in (None, "ne_roman", "mixed"), (
            f"got {conversation.detected_language!r} — a Romanized-Nepali message must never "
            "lock to English or a surviving Devanagari claim"
        )


# --- 4. Code-mixed Nepali/English -------------------------------------------


def test_code_mixed_pricing_question(business):
    message = "Hello, mero tooth mai dukheko cha, cleaning ko price kati ho?"
    reply = _say(business["business_id"], message)
    _print_turn(message, reply["response"])
    assert business["service_price"] in reply["response"]
    assert not _DEVANAGARI_RE.search(reply["response"])

    with SessionLocal() as db:
        conversation = db.query(Conversation).filter(Conversation.business_id == uuid.UUID(business["business_id"])).one()
        # Same documented Latin-script self-report ambiguity as the Romanized
        # case above — None is an acceptable "no confident signal" outcome;
        # locking to English or a surviving Devanagari claim is not.
        assert conversation.detected_language in (None, "mixed", "ne_roman"), (
            f"got {conversation.detected_language!r} — a code-mixed message must never lock "
            "to English or a surviving Devanagari claim"
        )


# --- 5. Emotional / frustrated -----------------------------------------------


def test_frustrated_customer_gets_no_boilerplate_over_apology(business):
    message = "This is the third time I have called about this! No one ever calls me back. I am so frustrated with this clinic."
    reply = _say(business["business_id"], message)
    _print_turn(message, reply["response"])
    lowered = reply["response"].lower()
    for phrase in _FORBIDDEN_BOILERPLATE:
        assert phrase not in lowered, f"forbidden boilerplate phrase resurfaced: {phrase!r}"


# --- 6. Repeated questions ----------------------------------------------------


def test_repeated_question_never_says_as_i_mentioned(business):
    first = _say(business["business_id"], "What are your hours?")
    _print_turn("What are your hours?", first["response"])
    second = _say(business["business_id"], "Sorry, what were your hours again?", session_token=first["session_token"])
    _print_turn("Sorry, what were your hours again?", second["response"])
    lowered = second["response"].lower()
    for phrase in _FORBIDDEN_BOILERPLATE:
        assert phrase not in lowered, f"forbidden boilerplate phrase resurfaced: {phrase!r}"


# --- 7. Family / group booking ------------------------------------------------


def test_family_group_booking_creates_real_appointments_for_both_people(business):
    day = _next_weekday(0)  # next Monday, always open per the fixture's hours
    message = (
        f"Hi, I'd like to book two teeth cleanings for {day.strftime('%A, %B %-d')} — "
        "one for me at 9am and one for my spouse at 10am. My name is Jordan Lee, "
        "email jordan.lee@example.com, and my spouse is Alex Lee."
    )
    reply = _say(business["business_id"], message)
    _print_turn(message, reply["response"])

    with SessionLocal() as db:
        rows = db.query(Appointment).filter(Appointment.business_id == uuid.UUID(business["business_id"])).all()
    hours_booked = sorted(a.scheduled_at.hour for a in rows)
    assert hours_booked == [9, 10], (
        f"expected two real appointments at 9am and 10am, got hours={hours_booked} "
        f"(response was: {reply['response']!r})"
    )


# --- 8. Follow-up recall ------------------------------------------------------


def test_follow_up_recall_of_a_fact_stated_earlier(business):
    first = _say(business["business_id"], "How much is a teeth cleaning?")
    _print_turn("How much is a teeth cleaning?", first["response"])
    assert business["service_price"] in first["response"]

    second = _say(business["business_id"], "Sorry, remind me — what was that price again?", session_token=first["session_token"])
    _print_turn("Sorry, remind me — what was that price again?", second["response"])
    assert business["service_price"] in second["response"], "must recall the REAL price stated earlier, never a different one"


# --- 9. Rescheduling -----------------------------------------------------------


def test_reschedule_moves_the_real_appointment(business):
    day = _next_weekday(1)  # next Tuesday
    book = _say(
        business["business_id"],
        f"Book me a teeth cleaning for {day.strftime('%A, %B %-d')} at 9am. "
        "I'm Taylor Kim, email taylor.kim@example.com.",
    )
    _print_turn("(booking message)", book["response"])

    with SessionLocal() as db:
        appointment = db.query(Appointment).filter(Appointment.business_id == uuid.UUID(business["business_id"])).one()
        original_hour = appointment.scheduled_at.hour
    assert original_hour == 9, f"setup failed — booking didn't land at 9am (response: {book['response']!r})"

    reschedule = _say(
        business["business_id"],
        "Actually, can you move my appointment to 2pm the same day instead?",
        session_token=book["session_token"],
    )
    _print_turn("Actually, can you move my appointment to 2pm the same day instead?", reschedule["response"])

    with SessionLocal() as db:
        appointment = db.query(Appointment).filter(Appointment.business_id == uuid.UUID(business["business_id"])).one()
        moved_hour = appointment.scheduled_at.hour
    assert moved_hour == 14, (
        f"expected the real appointment to move to 2pm (hour=14), still at hour={moved_hour} "
        f"(response was: {reschedule['response']!r})"
    )
