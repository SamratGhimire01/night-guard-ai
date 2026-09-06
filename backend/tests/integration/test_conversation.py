"""Phase 8 conversation orchestrator + Phase 10 booking tool wiring
(app/services/conversation/).

Stubbed ChatProvider/EmbeddingProvider for fast, free coverage of the wiring:
cross-tenant isolation, message persistence, the tool registry, intent/response
JSON parsing (including its fallback for malformed output), and — Phase 10 —
the booking tool actually writing to a real DB and the orchestrator building
its response from the tool's real result rather than the LLM's own text (both
the success and the hallucination-proof failure path, deterministically).
Real end-to-end acceptance (actual LLM calls, actual knowledge search, the
never-claims-a-booking and never-invents-info guardrails, and a real LLM-driven
booking) is verified manually against the real Azure/Foundry API and pasted
into PHASE_STATUS.md — that's deliberately not re-run on every `pytest tests/`
for the same reason Phase 6/7 gate their real-API tests: it costs real money
and isn't needed to prove the wiring is correct.
"""

import json
import uuid
from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

import pytest
from fastapi.testclient import TestClient

from app.db.database import SessionLocal
from app.db.models.appointment import Appointment, AppointmentStatus
from app.db.models.business import Business
from app.db.models.conversation import Conversation
from app.db.models.notification import NotificationStatus
from app.main import app
from app.schemas.conversation import ConversationIntent
from app.services import booking_service
from app.services.conversation.intent import _parse_response
from app.services.conversation.tools import TOOL_REGISTRY, find_tool

client = TestClient(app)


def _unique_email(label: str) -> str:
    return f"{label}-{uuid.uuid4().hex[:10]}@example.com"


def _auth_header(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


@pytest.fixture
def two_businesses():
    email_a = _unique_email("conv-a-owner")
    email_b = _unique_email("conv-b-owner")

    resp_a = client.post(
        "/api/v1/auth/register",
        json={"business_name": "Conv A", "timezone": "UTC", "email": email_a, "password": "correcthorse1"},
    )
    resp_b = client.post(
        "/api/v1/auth/register",
        json={"business_name": "Conv B", "timezone": "UTC", "email": email_b, "password": "correcthorse1"},
    )
    assert resp_a.status_code == 201, resp_a.text
    assert resp_b.status_code == 201, resp_b.text

    login_a = client.post("/api/v1/auth/login", json={"email": email_a, "password": "correcthorse1"})
    login_b = client.post("/api/v1/auth/login", json={"email": email_b, "password": "correcthorse1"})

    data = {
        "business_id_a": uuid.UUID(resp_a.json()["business_id"]),
        "business_id_b": uuid.UUID(resp_b.json()["business_id"]),
        "token_a": login_a.json()["access_token"],
        "token_b": login_b.json()["access_token"],
    }
    yield data

    with SessionLocal() as db:
        for business_id in (data["business_id_a"], data["business_id_b"]):
            business = db.get(Business, business_id)
            if business is not None:
                db.delete(business)
        db.commit()


def _create_customer(token: str, *, email: str | None = None, phone: str | None = None) -> uuid.UUID:
    payload = {"name": "Test Customer"}
    if email:
        payload["email"] = email
    if phone:
        payload["phone"] = phone
    resp = client.post("/api/v1/customers", headers=_auth_header(token), json=payload)
    assert resp.status_code == 201, resp.text
    return uuid.UUID(resp.json()["id"])


def _create_customer_with_contact(token: str) -> uuid.UUID:
    """Phase 24: the booking-dispatch tests need a customer the (new)
    contact-info gate lets through — a plain `_create_customer` deliberately
    stays contact-less by default so the cancellation/reschedule tests that
    assert on a real FAILED notification (no recipient on file) are
    unaffected."""
    return _create_customer(token, email=_unique_email("booking-contact"))


def _create_conversation(business_id: uuid.UUID, customer_id: uuid.UUID) -> uuid.UUID:
    with SessionLocal() as db:
        conversation = Conversation(business_id=business_id, customer_id=customer_id, channel="sms", status="open")
        db.add(conversation)
        db.commit()
        db.refresh(conversation)
        return conversation.id


class _StubChatProvider:
    def __init__(self, reply: str):
        self.reply = reply
        self.calls: list[list[dict[str, str]]] = []

    def chat(self, messages: list[dict[str, str]]) -> str:
        self.calls.append(messages)
        return self.reply


class _StubEmbeddingProvider:
    def embed(self, texts: list[str]) -> list[list[float]]:
        return [[0.01] * 1536 for _ in texts]


def _stub_providers(monkeypatch, reply: str) -> _StubChatProvider:
    import app.services.conversation.intent as intent_module
    import app.services.conversation.orchestrator as orchestrator_module

    chat_stub = _StubChatProvider(reply)
    monkeypatch.setattr(intent_module, "get_chat_provider", lambda: chat_stub)
    monkeypatch.setattr(orchestrator_module, "get_embedding_provider", lambda: _StubEmbeddingProvider())
    return chat_stub


# --- endpoint wiring, persistence, tenant isolation ---------------------------


def test_message_persisted_and_response_returned(two_businesses, monkeypatch):
    stub = _stub_providers(
        monkeypatch, json.dumps({"intent": "greeting", "response": "Hi there! How can I help?"})
    )
    business_id_a = two_businesses["business_id_a"]
    customer_id = _create_customer(two_businesses["token_a"])
    conversation_id = _create_conversation(business_id_a, customer_id)

    resp = client.post(
        f"/api/v1/conversations/{conversation_id}/messages",
        headers=_auth_header(two_businesses["token_a"]),
        json={"content": "Hi!"},
    )

    assert resp.status_code == 201, resp.text
    body = resp.json()
    assert body["intent"] == "greeting"
    assert body["response"] == "Hi there! How can I help?"
    assert len(stub.calls) == 1

    with SessionLocal() as db:
        from app.db.models.conversation import Message

        messages = list(
            db.query(Message).filter(Message.conversation_id == conversation_id).order_by(Message.created_at)
        )
    assert [m.content for m in messages] == ["Hi!", "Hi there! How can I help?"]
    assert [m.sender_type.value for m in messages] == ["customer", "agent"]


def test_cross_tenant_message_is_rejected(two_businesses, monkeypatch):
    _stub_providers(monkeypatch, json.dumps({"intent": "greeting", "response": "should never be reached"}))
    business_id_a = two_businesses["business_id_a"]
    customer_id = _create_customer(two_businesses["token_a"])
    conversation_id = _create_conversation(business_id_a, customer_id)

    resp = client.post(
        f"/api/v1/conversations/{conversation_id}/messages",
        headers=_auth_header(two_businesses["token_b"]),  # Business B, A's conversation_id
        json={"content": "let me in"},
    )

    assert resp.status_code == 404
    assert resp.json()["error"]["type"] == "not_found"

    with SessionLocal() as db:
        from app.db.models.conversation import Message

        count = db.query(Message).filter(Message.conversation_id == conversation_id).count()
    assert count == 0, "rejected cross-tenant request must not have written any message"


def test_unknown_conversation_id_is_rejected(two_businesses, monkeypatch):
    _stub_providers(monkeypatch, json.dumps({"intent": "greeting", "response": "unreachable"}))
    resp = client.post(
        f"/api/v1/conversations/{uuid.uuid4()}/messages",
        headers=_auth_header(two_businesses["token_a"]),
        json={"content": "hello?"},
    )
    assert resp.status_code == 404


# --- tool-calling scaffold ------------------------------------------------------


def test_tool_registry_has_booking_cancellation_rescheduling_and_status():
    """Phase 10 registered a real tool for BOOKING; Phase 11 adds real tools for
    CANCELLATION and RESCHEDULING; Phase 14 adds APPOINTMENT_STATUS the same
    way. No other intent has a tool, so the orchestrator's honesty guardrail
    (Phase 8/9) stays meaningful for those."""
    assert set(TOOL_REGISTRY) == {
        ConversationIntent.BOOKING,
        ConversationIntent.CANCELLATION,
        ConversationIntent.RESCHEDULING,
        ConversationIntent.APPOINTMENT_STATUS,
    }
    for intent in (
        ConversationIntent.BOOKING,
        ConversationIntent.CANCELLATION,
        ConversationIntent.RESCHEDULING,
        ConversationIntent.APPOINTMENT_STATUS,
    ):
        assert find_tool(intent) is not None
    for intent in set(ConversationIntent) - set(TOOL_REGISTRY):
        assert find_tool(intent) is None


# --- Phase 10: real booking tool wiring (stubbed LLM, real DB write) ------------


def _next_monday() -> date:
    today = date.today()
    days_ahead = (0 - today.weekday()) % 7 or 7
    return today + timedelta(days=days_ahead)


def _setup_booking_business(token: str) -> uuid.UUID:
    """Mon-Sat 9am-5pm (UTC), one 30-min $50 'Cleaning' service. Returns its id."""
    days = [{"day_of_week": d, "open_time": "09:00:00", "close_time": "17:00:00"} for d in range(6)]
    days.append({"day_of_week": 6, "closed": True})
    resp = client.put("/api/v1/business/hours", json={"days": days}, headers=_auth_header(token))
    assert resp.status_code == 200, resp.text

    resp = client.post(
        "/api/v1/services",
        json={"name": "Cleaning", "price": "50.00", "duration_minutes": 30},
        headers=_auth_header(token),
    )
    assert resp.status_code == 201, resp.text
    return uuid.UUID(resp.json()["id"])


def _booking_reply(service: str, iso_date: str, iso_time: str, response: str = "Let me check that.") -> str:
    return json.dumps(
        {
            "intent": "booking",
            "response": response,
            "booking_request": {"service": service, "date": iso_date, "time": iso_time},
        }
    )


def test_booking_tool_creates_real_appointment_and_response_reflects_it(two_businesses, monkeypatch):
    """The orchestrator must call the real tool and build its response from the
    REAL DB result, not the LLM's free-text guess ("Let me check that.")."""
    token_a = two_businesses["token_a"]
    business_id_a = two_businesses["business_id_a"]
    service_id = _setup_booking_business(token_a)
    customer_id = _create_customer_with_contact(token_a)
    conversation_id = _create_conversation(business_id_a, customer_id)
    target_date = _next_monday()

    _stub_providers(monkeypatch, _booking_reply("Cleaning", target_date.isoformat(), "14:00"))

    resp = client.post(
        f"/api/v1/conversations/{conversation_id}/messages",
        headers=_auth_header(token_a),
        json={"content": "Can I get a cleaning next Monday at 2pm?"},
    )
    assert resp.status_code == 201, resp.text
    body = resp.json()

    # The LLM's own placeholder text ("Let me check that.") must NOT be what the
    # customer sees — the real appointment id it never saw must be.
    assert "Let me check that." not in body["response"]

    with SessionLocal() as db:
        from app.db.models.appointment import Appointment

        appointments = list(
            db.query(Appointment).filter(Appointment.business_id == business_id_a).all()
        )
    assert len(appointments) == 1, "the tool must have made a real DB write"
    real_appointment = appointments[0]
    assert str(real_appointment.id) in body["response"], "the response must quote the REAL booking ID from the DB"
    assert real_appointment.service_id == service_id
    assert real_appointment.scheduled_at.hour == 14


def test_booking_tool_failure_is_never_reported_as_success(two_businesses, monkeypatch):
    """Hallucination-proof test: force a real tool failure (the slot is already
    taken) and confirm the customer-facing response honestly reflects that —
    never a fabricated 'you're booked' claim — because the response is built
    from the tool's real result dict, not LLM narration."""
    token_a = two_businesses["token_a"]
    business_id_a = two_businesses["business_id_a"]
    service_id = _setup_booking_business(token_a)
    customer_id = _create_customer_with_contact(token_a)
    conversation_id = _create_conversation(business_id_a, customer_id)
    target_date = _next_monday()

    with SessionLocal() as db:
        from zoneinfo import ZoneInfo

        from app.services import booking_service

        already_booked_at = target_date
        from datetime import datetime

        scheduled_at = datetime(
            already_booked_at.year, already_booked_at.month, already_booked_at.day, 14, 0, tzinfo=ZoneInfo("UTC")
        )
        booking_service.create_appointment(
            db,
            business_id=business_id_a,
            customer_id=customer_id,
            service_id=service_id,
            staff_id=None,
            scheduled_at=scheduled_at,
        )

    _stub_providers(
        monkeypatch,
        _booking_reply(
            "Cleaning", target_date.isoformat(), "14:00", response="You're all set for 2pm Monday!"
        ),
    )

    resp = client.post(
        f"/api/v1/conversations/{conversation_id}/messages",
        headers=_auth_header(token_a),
        json={"content": "Can I get a cleaning next Monday at 2pm?"},
    )
    assert resp.status_code == 201, resp.text
    body = resp.json()

    # The LLM's own text falsely claimed success — the real response must not.
    lowered = body["response"].lower()
    assert "you're all set" not in lowered
    assert "isn't available" in lowered or "not available" in lowered

    with SessionLocal() as db:
        from app.db.models.appointment import Appointment

        count = db.query(Appointment).filter(Appointment.business_id == business_id_a).count()
    assert count == 1, "the failed second attempt must not have written a second row"


def test_booking_falls_back_to_clarifying_when_service_name_unresolvable(two_businesses, monkeypatch):
    """The LLM claimed enough info, but the service name doesn't match anything
    real — Python must never guess which service was meant, and must never call
    the tool with an unresolved parameter."""
    token_a = two_businesses["token_a"]
    business_id_a = two_businesses["business_id_a"]
    _setup_booking_business(token_a)
    customer_id = _create_customer_with_contact(token_a)
    conversation_id = _create_conversation(business_id_a, customer_id)
    target_date = _next_monday()

    _stub_providers(monkeypatch, _booking_reply("Root Canal", target_date.isoformat(), "14:00"))

    resp = client.post(
        f"/api/v1/conversations/{conversation_id}/messages",
        headers=_auth_header(token_a),
        json={"content": "book me a root canal next monday at 2"},
    )
    assert resp.status_code == 201, resp.text
    body = resp.json()
    assert "which service" in body["response"].lower()

    with SessionLocal() as db:
        from app.db.models.appointment import Appointment

        count = db.query(Appointment).filter(Appointment.business_id == business_id_a).count()
    assert count == 0, "an unresolved service must never reach the tool"


# --- Phase 12: real group-booking tool wiring (stubbed LLM, real DB write) -----


def _setup_second_service(token: str) -> uuid.UUID:
    resp = client.post(
        "/api/v1/services",
        json={"name": "Consultation", "price": "30.00", "duration_minutes": 20},
        headers=_auth_header(token),
    )
    assert resp.status_code == 201, resp.text
    return uuid.UUID(resp.json()["id"])


def _group_booking_reply(people: list[dict], all_or_nothing: bool, response: str = "Let me check on that for everyone.") -> str:
    return json.dumps(
        {
            "intent": "booking",
            "response": response,
            "group_booking_request": {"people": people, "all_or_nothing": all_or_nothing},
        }
    )


def test_group_booking_tool_creates_shared_appointment_with_participants(two_businesses, monkeypatch):
    """Two people, same service and time — must cluster into ONE real Appointment
    row with two real AppointmentParticipant rows, and the response must quote
    the real booking ID, not the LLM's placeholder text."""
    token_a = two_businesses["token_a"]
    business_id_a = two_businesses["business_id_a"]
    service_id = _setup_booking_business(token_a)
    customer_id = _create_customer_with_contact(token_a)
    conversation_id = _create_conversation(business_id_a, customer_id)
    target_date = _next_monday()

    _stub_providers(
        monkeypatch,
        _group_booking_reply(
            [
                {"label": "Jordan", "service": "Cleaning", "date": target_date.isoformat(), "time": "14:00"},
                {"label": "Spouse", "service": "Cleaning", "date": target_date.isoformat(), "time": "14:00"},
            ],
            all_or_nothing=False,
        ),
    )

    resp = client.post(
        f"/api/v1/conversations/{conversation_id}/messages",
        headers=_auth_header(token_a),
        json={"content": "Book me and my wife for cleanings next Monday at 2pm."},
    )
    assert resp.status_code == 201, resp.text
    body = resp.json()
    assert "Let me check on that for everyone." not in body["response"]

    with SessionLocal() as db:
        from app.db.models.appointment import Appointment, AppointmentParticipant

        appointments = db.query(Appointment).filter(Appointment.business_id == business_id_a).all()
        assert len(appointments) == 1, "the same slot for both people must be ONE Appointment row"
        appointment = appointments[0]
        assert appointment.service_id == service_id
        assert appointment.group_booking_id is not None
        participants = (
            db.query(AppointmentParticipant).filter(AppointmentParticipant.appointment_id == appointment.id).all()
        )
    assert sorted(p.name for p in participants) == ["Jordan", "Spouse"]
    assert str(appointment.id) in body["response"], "the response must quote the REAL booking ID from the DB"


def test_group_booking_hallucination_proof_partial_failure_is_never_reported_as_full_success(
    two_businesses, monkeypatch
):
    """Force one of two people's requested slot to already be taken, then have
    the (stubbed) LLM's own text falsely claim everyone is booked. The real
    response must honestly reflect the partial outcome — never claim both
    succeeded, and never silently drop the one that failed."""
    token_a = two_businesses["token_a"]
    business_id_a = two_businesses["business_id_a"]
    service_id = _setup_booking_business(token_a)
    customer_id = _create_customer_with_contact(token_a)
    conversation_id = _create_conversation(business_id_a, customer_id)
    target_date = _next_monday()

    with SessionLocal() as db:
        taken_at = datetime(target_date.year, target_date.month, target_date.day, 15, 0, tzinfo=ZoneInfo("UTC"))
        booking_service.create_appointment(
            db,
            business_id=business_id_a,
            customer_id=_create_customer(token_a),
            service_id=service_id,
            staff_id=None,
            scheduled_at=taken_at,
        )

    _stub_providers(
        monkeypatch,
        _group_booking_reply(
            [
                {"label": "Jordan", "service": "Cleaning", "date": target_date.isoformat(), "time": "14:00"},
                {"label": "Spouse", "service": "Cleaning", "date": target_date.isoformat(), "time": "15:00"},
            ],
            all_or_nothing=False,
            response="Great news, you're both all set!",
        ),
    )

    resp = client.post(
        f"/api/v1/conversations/{conversation_id}/messages",
        headers=_auth_header(token_a),
        json={"content": "Book me at 2pm and my spouse at 3pm next Monday for cleanings."},
    )
    assert resp.status_code == 201, resp.text
    lowered = resp.json()["response"].lower()
    assert "you're both all set" not in lowered, "the LLM's false full-success claim must never reach the customer"
    assert "jordan" in lowered and "spouse" in lowered, "both people must be mentioned, not just the successful one"
    assert "not booked" in lowered or "not available" in lowered

    with SessionLocal() as db:
        from app.db.models.appointment import Appointment

        rows = (
            db.query(Appointment)
            .filter(Appointment.business_id == business_id_a, Appointment.customer_id == customer_id)
            .all()
        )
    assert len(rows) == 1, "only Jordan's real successful booking may exist — Spouse's failed attempt wrote nothing"
    assert rows[0].scheduled_at.hour == 14


def test_group_booking_all_or_nothing_books_nothing_when_one_slot_unavailable(two_businesses, monkeypatch):
    token_a = two_businesses["token_a"]
    business_id_a = two_businesses["business_id_a"]
    _setup_booking_business(token_a)
    consult_id = _setup_second_service(token_a)
    customer_id = _create_customer_with_contact(token_a)
    conversation_id = _create_conversation(business_id_a, customer_id)
    target_date = _next_monday()

    with SessionLocal() as db:
        taken_at = datetime(target_date.year, target_date.month, target_date.day, 10, 0, tzinfo=ZoneInfo("UTC"))
        booking_service.create_appointment(
            db,
            business_id=business_id_a,
            customer_id=_create_customer(token_a),
            service_id=consult_id,
            staff_id=None,
            scheduled_at=taken_at,
        )

    _stub_providers(
        monkeypatch,
        _group_booking_reply(
            [
                {"label": "Jordan", "service": "Cleaning", "date": target_date.isoformat(), "time": "09:00"},
                {"label": "Spouse", "service": "Consultation", "date": target_date.isoformat(), "time": "10:00"},
            ],
            all_or_nothing=True,
            response="You're both booked!",
        ),
    )

    resp = client.post(
        f"/api/v1/conversations/{conversation_id}/messages",
        headers=_auth_header(token_a),
        json={"content": "Book me a cleaning at 9am and my spouse a consultation at 10am, all or nothing please."},
    )
    assert resp.status_code == 201, resp.text
    lowered = resp.json()["response"].lower()
    assert "you're both booked" not in lowered
    assert "didn't book anyone" in lowered or "wasn't able to get everyone" in lowered

    with SessionLocal() as db:
        from app.db.models.appointment import Appointment

        rows = (
            db.query(Appointment)
            .filter(Appointment.business_id == business_id_a, Appointment.customer_id == customer_id)
            .all()
        )
    assert rows == [], "all-or-nothing must write nothing when even one person's slot is unavailable"


def test_group_booking_falls_back_to_clarifying_when_a_persons_service_is_unresolvable(two_businesses, monkeypatch):
    token_a = two_businesses["token_a"]
    business_id_a = two_businesses["business_id_a"]
    _setup_booking_business(token_a)
    customer_id = _create_customer_with_contact(token_a)
    conversation_id = _create_conversation(business_id_a, customer_id)
    target_date = _next_monday()

    _stub_providers(
        monkeypatch,
        _group_booking_reply(
            [
                {"label": "Jordan", "service": "Cleaning", "date": target_date.isoformat(), "time": "14:00"},
                {"label": "Spouse", "service": "Root Canal", "date": target_date.isoformat(), "time": "14:00"},
            ],
            all_or_nothing=False,
        ),
    )

    resp = client.post(
        f"/api/v1/conversations/{conversation_id}/messages",
        headers=_auth_header(token_a),
        json={"content": "Book me and my spouse next Monday at 2pm."},
    )
    assert resp.status_code == 201, resp.text
    assert "make sure i get everyone booked" in resp.json()["response"].lower()

    with SessionLocal() as db:
        from app.db.models.appointment import Appointment

        count = db.query(Appointment).filter(Appointment.business_id == business_id_a).count()
    assert count == 0, "an unresolved person's service must block the WHOLE group, never book only the resolved ones"


# --- Phase 11: real cancellation tool wiring (stubbed LLM, real DB write) -------


def _cancellation_reply(appointment_id: str | None, response: str = "Sure, I'll take care of that.") -> str:
    return json.dumps(
        {
            "intent": "cancellation",
            "response": response,
            "cancellation_request": {"appointment_id": appointment_id} if appointment_id else None,
        }
    )


def _reschedule_reply(
    appointment_id: str | None, iso_date: str, iso_time: str, response: str = "Let me check that."
) -> str:
    return json.dumps(
        {
            "intent": "rescheduling",
            "response": response,
            "reschedule_request": (
                {"appointment_id": appointment_id, "date": iso_date, "time": iso_time} if appointment_id else None
            ),
        }
    )


def test_cancellation_tool_cancels_real_appointment_and_response_reflects_it(two_businesses, monkeypatch):
    """The orchestrator must call the real tool and build its response from the
    REAL DB result, not the LLM's own placeholder text."""
    token_a = two_businesses["token_a"]
    business_id_a = two_businesses["business_id_a"]
    service_id = _setup_booking_business(token_a)
    customer_id = _create_customer(token_a)
    conversation_id = _create_conversation(business_id_a, customer_id)
    target_date = _next_monday()

    with SessionLocal() as db:
        appointment = booking_service.create_appointment(
            db,
            business_id=business_id_a,
            customer_id=customer_id,
            service_id=service_id,
            staff_id=None,
            scheduled_at=datetime(target_date.year, target_date.month, target_date.day, 14, 0, tzinfo=ZoneInfo("UTC")),
        )
        appointment_id = appointment.id

    _stub_providers(monkeypatch, _cancellation_reply(str(appointment_id)))

    resp = client.post(
        f"/api/v1/conversations/{conversation_id}/messages",
        headers=_auth_header(token_a),
        json={"content": "Please cancel my appointment."},
    )
    assert resp.status_code == 201, resp.text
    body = resp.json()
    assert "cancelled" in body["response"].lower()
    assert "Sure, I'll take care of that." not in body["response"]

    with SessionLocal() as db:
        row = db.get(Appointment, appointment_id)
    assert row.status == AppointmentStatus.CANCELLED

    with SessionLocal() as db:
        from app.db.models.notification import Notification

        notifications = db.query(Notification).filter(Notification.appointment_id == appointment_id).all()
    # Phase 13: booking now also queues its own booking_confirmed Notification,
    # alongside this cancellation's appointment_cancelled one.
    cancel_notifications = [n for n in notifications if n.event_type == "appointment_cancelled"]
    assert len(cancel_notifications) == 1
    # cancel_appointment dispatches this inline for real. This test's customer
    # has no email on file, so FAILED is the honest real outcome, not QUEUED
    # forever — proves dispatch actually ran, not just that a row exists.
    assert cancel_notifications[0].status == NotificationStatus.FAILED


def test_cancellation_hallucination_proof_already_cancelled(two_businesses, monkeypatch):
    """Hallucination-proof test: the LLM claims success while asking to cancel an
    appointment that's already cancelled — the real tool must honestly report
    failure, and the response must reflect that, never the LLM's false claim."""
    token_a = two_businesses["token_a"]
    business_id_a = two_businesses["business_id_a"]
    service_id = _setup_booking_business(token_a)
    customer_id = _create_customer(token_a)
    conversation_id = _create_conversation(business_id_a, customer_id)
    target_date = _next_monday()

    with SessionLocal() as db:
        appointment = booking_service.create_appointment(
            db,
            business_id=business_id_a,
            customer_id=customer_id,
            service_id=service_id,
            staff_id=None,
            scheduled_at=datetime(target_date.year, target_date.month, target_date.day, 14, 0, tzinfo=ZoneInfo("UTC")),
        )
        appointment_id = appointment.id
        booking_service.cancel_appointment(db, business_id=business_id_a, appointment_id=appointment_id)

    _stub_providers(
        monkeypatch, _cancellation_reply(str(appointment_id), response="All done, that's cancelled now!")
    )

    resp = client.post(
        f"/api/v1/conversations/{conversation_id}/messages",
        headers=_auth_header(token_a),
        json={"content": "Please cancel my appointment again."},
    )
    assert resp.status_code == 201, resp.text
    lowered = resp.json()["response"].lower()
    assert "all done" not in lowered
    assert "already" in lowered and "cancel" in lowered


def test_cancellation_ambiguous_appointments_asks_for_clarification(two_businesses, monkeypatch):
    """A customer with 2+ active appointments asks to cancel without specifying
    which — the orchestrator must never guess: no tool call happens, and the
    LLM's own clarifying question is what the customer sees."""
    token_a = two_businesses["token_a"]
    business_id_a = two_businesses["business_id_a"]
    service_id = _setup_booking_business(token_a)
    customer_id = _create_customer(token_a)
    conversation_id = _create_conversation(business_id_a, customer_id)
    target_date = _next_monday()

    with SessionLocal() as db:
        for hour in (10, 14):
            booking_service.create_appointment(
                db,
                business_id=business_id_a,
                customer_id=customer_id,
                service_id=service_id,
                staff_id=None,
                scheduled_at=datetime(
                    target_date.year, target_date.month, target_date.day, hour, 0, tzinfo=ZoneInfo("UTC")
                ),
            )

    clarifying_question = "You have two upcoming appointments — which one would you like to cancel?"
    _stub_providers(monkeypatch, _cancellation_reply(None, response=clarifying_question))

    resp = client.post(
        f"/api/v1/conversations/{conversation_id}/messages",
        headers=_auth_header(token_a),
        json={"content": "Can you cancel my appointment?"},
    )
    assert resp.status_code == 201, resp.text
    assert resp.json()["response"] == clarifying_question

    with SessionLocal() as db:
        statuses = {
            a.status
            for a in db.query(Appointment).filter(Appointment.business_id == business_id_a).all()
        }
    assert statuses == {AppointmentStatus.CONFIRMED}, "neither appointment may be touched when ambiguous"


# --- Phase 11: real reschedule tool wiring (stubbed LLM, real DB write) ---------


def test_reschedule_tool_moves_real_appointment_and_response_reflects_it(two_businesses, monkeypatch):
    token_a = two_businesses["token_a"]
    business_id_a = two_businesses["business_id_a"]
    service_id = _setup_booking_business(token_a)
    customer_id = _create_customer(token_a)
    conversation_id = _create_conversation(business_id_a, customer_id)
    target_date = _next_monday()

    with SessionLocal() as db:
        appointment = booking_service.create_appointment(
            db,
            business_id=business_id_a,
            customer_id=customer_id,
            service_id=service_id,
            staff_id=None,
            scheduled_at=datetime(target_date.year, target_date.month, target_date.day, 10, 0, tzinfo=ZoneInfo("UTC")),
        )
        appointment_id = appointment.id

    _stub_providers(monkeypatch, _reschedule_reply(str(appointment_id), target_date.isoformat(), "15:00"))

    resp = client.post(
        f"/api/v1/conversations/{conversation_id}/messages",
        headers=_auth_header(token_a),
        json={"content": "Can you move my appointment to 3pm instead?"},
    )
    assert resp.status_code == 201, resp.text
    body = resp.json()
    assert "moved" in body["response"].lower()
    assert "Let me check that." not in body["response"]

    with SessionLocal() as db:
        row = db.get(Appointment, appointment_id)
    assert row.scheduled_at.hour == 15
    assert row.status == AppointmentStatus.CONFIRMED


def test_reschedule_hallucination_proof_target_slot_already_taken(two_businesses, monkeypatch):
    """Hallucination-proof test: the LLM claims success while the requested new
    slot is genuinely already taken by someone else — the real tool must
    honestly report failure."""
    token_a = two_businesses["token_a"]
    business_id_a = two_businesses["business_id_a"]
    service_id = _setup_booking_business(token_a)
    customer_id = _create_customer(token_a)
    other_customer_id = _create_customer(token_a)
    conversation_id = _create_conversation(business_id_a, customer_id)
    target_date = _next_monday()

    with SessionLocal() as db:
        appointment = booking_service.create_appointment(
            db,
            business_id=business_id_a,
            customer_id=customer_id,
            service_id=service_id,
            staff_id=None,
            scheduled_at=datetime(target_date.year, target_date.month, target_date.day, 10, 0, tzinfo=ZoneInfo("UTC")),
        )
        appointment_id = appointment.id
        booking_service.create_appointment(
            db,
            business_id=business_id_a,
            customer_id=other_customer_id,
            service_id=service_id,
            staff_id=None,
            scheduled_at=datetime(target_date.year, target_date.month, target_date.day, 15, 0, tzinfo=ZoneInfo("UTC")),
        )

    _stub_providers(
        monkeypatch,
        _reschedule_reply(str(appointment_id), target_date.isoformat(), "15:00", response="Done, moved to 3pm!"),
    )

    resp = client.post(
        f"/api/v1/conversations/{conversation_id}/messages",
        headers=_auth_header(token_a),
        json={"content": "Move my appointment to 3pm please."},
    )
    assert resp.status_code == 201, resp.text
    lowered = resp.json()["response"].lower()
    assert "done, moved" not in lowered
    assert "couldn't reschedule" in lowered or "not available" in lowered

    with SessionLocal() as db:
        row = db.get(Appointment, appointment_id)
    assert row.scheduled_at.hour == 10, "the failed reschedule must not have moved the original appointment"


# --- Phase 11 regression: appointment times shown to the LLM use business-local time --


def test_format_appointments_converts_utc_to_business_local_time():
    """Phase 11 real bug, found live: the model correctly listed two distinct
    real appointments during an ambiguous-cancellation clarification but
    misstated one's local time (said 3:00 PM for an appointment actually at
    11:00 AM America/New_York), because the appointment list handed to the
    LLM was built from the raw UTC ISO string with no timezone conversion.
    Fixed by threading the business's ZoneInfo through _build_user_prompt ->
    _format_appointments. This directly exercises that conversion — an
    appointment stored at 15:00 UTC must read as 11:00 AM in a UTC-4 business,
    never 3:00 PM."""
    from app.services.conversation.intent import _format_appointments

    appointment_id = uuid.uuid4()
    appointments = [
        {
            "id": str(appointment_id),
            "service": "Root Canal",
            "scheduled_at": "2026-09-08T15:00:00+00:00",
            "status": "confirmed",
        }
    ]

    formatted = _format_appointments("Customer's active/upcoming appointments", appointments, ZoneInfo("America/New_York"))

    assert formatted is not None
    assert "11:00 AM" in formatted, f"expected business-local 11:00 AM, got: {formatted!r}"
    assert "3:00 PM" not in formatted, "must never show the raw UTC hour unconverted"


# --- intent/response JSON parsing -----------------------------------------------


def test_parse_response_valid_json():
    result = _parse_response('{"intent": "pricing_question", "response": "It costs $50."}')
    assert result.intent == ConversationIntent.PRICING_QUESTION
    assert result.response == "It costs $50."
    assert result.booking_request is None
    assert result.cancellation_request is None
    assert result.reschedule_request is None


def test_parse_response_strips_markdown_code_fence():
    raw = '```json\n{"intent": "greeting", "response": "Hello!"}\n```'
    result = _parse_response(raw)
    assert result.intent == ConversationIntent.GREETING
    assert result.response == "Hello!"


def test_parse_response_falls_back_gracefully_on_malformed_output():
    result = _parse_response("Sorry, I'm not sure how to format that as JSON but here's my answer.")
    assert result.intent == ConversationIntent.UNKNOWN
    assert "answer" in result.response
    assert result.booking_request is None


def test_parse_response_falls_back_on_invalid_intent_value():
    result = _parse_response('{"intent": "not_a_real_intent", "response": "hi"}')
    assert result.intent == ConversationIntent.UNKNOWN


def test_parse_response_extracts_valid_booking_request():
    raw = (
        '{"intent": "booking", "response": "Let me check.", '
        '"booking_request": {"service": "Cleaning", "date": "2026-09-10", "time": "14:00"}}'
    )
    result = _parse_response(raw)
    assert result.intent == ConversationIntent.BOOKING
    assert result.booking_request == {
        "service": "Cleaning", "date": "2026-09-10", "time": "14:00", "wants_availability": False,
    }


def test_parse_response_extracts_partial_booking_request_with_nulls_for_missing_fields():
    """Phase 25a: a booking_request with only SOME fields present is now a
    normal partial extraction (orchestrator._merge_booking_draft accumulates
    it across turns) — no longer treated as malformed/discarded, which was
    the old, incomplete-extraction-triggers-a-loop behavior."""
    raw = '{"intent": "booking", "response": "hi", "booking_request": {"service": "Cleaning"}}'
    assert _parse_response(raw).booking_request == {
        "service": "Cleaning", "date": None, "time": None, "wants_availability": False,
    }


def test_parse_response_booking_request_missing_key_entirely_is_none():
    raw = '{"intent": "booking", "response": "hi"}'
    assert _parse_response(raw).booking_request is None


def test_parse_response_booking_request_all_null_is_a_valid_empty_dict():
    """A plain confirmation ("yes") that adds nothing new is expected to
    still emit an all-null booking_request, not None — see intent.py rule 9's
    few-shot example."""
    raw = (
        '{"intent": "booking", "response": "Great!", '
        '"booking_request": {"service": null, "date": null, "time": null}}'
    )
    assert _parse_response(raw).booking_request == {
        "service": None, "date": None, "time": None, "wants_availability": False,
    }


def test_parse_response_extracts_wants_availability_true():
    """Phase 33: an under-specified booking ask ("what times do you have")
    signals wants_availability so the orchestrator can show real slots
    instead of asking the customer to guess a time."""
    raw = (
        '{"intent": "booking", "response": "Let me check.", "booking_request": '
        '{"service": "Cleaning", "date": null, "time": null, "wants_availability": true}}'
    )
    assert _parse_response(raw).booking_request == {
        "service": "Cleaning", "date": None, "time": None, "wants_availability": True,
    }


def test_parse_response_extracts_valid_cancellation_request():
    raw = (
        '{"intent": "cancellation", "response": "Sure.", '
        '"cancellation_request": {"appointment_id": "abc-123"}}'
    )
    result = _parse_response(raw)
    assert result.intent == ConversationIntent.CANCELLATION
    assert result.cancellation_request == {"appointment_id": "abc-123"}


def test_parse_response_null_cancellation_request_when_ambiguous():
    raw = '{"intent": "cancellation", "response": "Which one?", "cancellation_request": null}'
    assert _parse_response(raw).cancellation_request is None


def test_parse_response_extracts_valid_reschedule_request():
    raw = (
        '{"intent": "rescheduling", "response": "Let me check.", '
        '"reschedule_request": {"appointment_id": "abc-123", "date": "2026-09-12", "time": "10:00"}}'
    )
    result = _parse_response(raw)
    assert result.intent == ConversationIntent.RESCHEDULING
    assert result.reschedule_request == {"appointment_id": "abc-123", "date": "2026-09-12", "time": "10:00"}


def test_parse_response_ignores_malformed_reschedule_request():
    raw = '{"intent": "rescheduling", "response": "hi", "reschedule_request": {"appointment_id": "abc-123"}}'
    assert _parse_response(raw).reschedule_request is None


def test_parse_response_extracts_valid_group_booking_request():
    raw = (
        '{"intent": "booking", "response": "Checking.", "group_booking_request": {"people": ['
        '{"label": "Jordan", "service": "Cleaning", "date": "2026-09-07", "time": "14:00"}, '
        '{"label": "Spouse", "service": "Cleaning", "date": "2026-09-07", "time": "14:00"}], '
        '"all_or_nothing": true}}'
    )
    result = _parse_response(raw)
    assert result.intent == ConversationIntent.BOOKING
    assert result.booking_request is None
    assert result.group_booking_request == {
        "people": [
            {"label": "Jordan", "service": "Cleaning", "date": "2026-09-07", "time": "14:00"},
            {"label": "Spouse", "service": "Cleaning", "date": "2026-09-07", "time": "14:00"},
        ],
        "all_or_nothing": True,
    }


def test_parse_response_group_booking_defaults_all_or_nothing_false_when_omitted():
    raw = (
        '{"intent": "booking", "response": "Checking.", "group_booking_request": {"people": ['
        '{"label": "Jordan", "service": "Cleaning", "date": "2026-09-07", "time": "14:00"}, '
        '{"label": "Spouse", "service": "Cleaning", "date": "2026-09-07", "time": "14:00"}]}}'
    )
    assert _parse_response(raw).group_booking_request["all_or_nothing"] is False


def test_parse_response_ignores_group_booking_request_with_fewer_than_two_people():
    raw = (
        '{"intent": "booking", "response": "hi", "group_booking_request": {"people": ['
        '{"label": "Jordan", "service": "Cleaning", "date": "2026-09-07", "time": "14:00"}]}}'
    )
    assert _parse_response(raw).group_booking_request is None


def test_parse_response_ignores_group_booking_request_with_incomplete_person():
    raw = (
        '{"intent": "booking", "response": "hi", "group_booking_request": {"people": ['
        '{"label": "Jordan", "service": "Cleaning", "date": "2026-09-07", "time": "14:00"}, '
        '{"label": "Spouse", "service": null, "date": "2026-09-07", "time": "14:00"}]}}'
    )
    assert _parse_response(raw).group_booking_request is None


# --- Phase 24 urgent fix: booking blocked without real contact info -----------


def test_booking_blocked_when_customer_has_no_contact_info(two_businesses, monkeypatch):
    """A customer with no phone/email on file (the default `_create_customer`)
    must NOT get a real booking — the business would have no way to confirm
    it. No Appointment row, no HumanHandoff (this is a gate, not an escalation),
    and the deterministic ask-for-contact sentence, never the LLM's own text."""
    token_a = two_businesses["token_a"]
    business_id_a = two_businesses["business_id_a"]
    _setup_booking_business(token_a)
    customer_id = _create_customer(token_a)  # no phone, no email
    conversation_id = _create_conversation(business_id_a, customer_id)
    target_date = _next_monday()

    _stub_providers(
        monkeypatch, _booking_reply("Cleaning", target_date.isoformat(), "14:00", response="You're all set!")
    )

    resp = client.post(
        f"/api/v1/conversations/{conversation_id}/messages",
        headers=_auth_header(token_a),
        json={"content": "Can I get a cleaning next Monday at 2pm?"},
    )
    assert resp.status_code == 201, resp.text
    body = resp.json()
    assert "you're all set" not in body["response"].lower()
    assert "phone number or email" in body["response"].lower()

    with SessionLocal() as db:
        from app.db.models.appointment import Appointment
        from app.db.models.handoff import HumanHandoff

        assert db.query(Appointment).filter(Appointment.business_id == business_id_a).count() == 0
        assert db.query(HumanHandoff).filter(HumanHandoff.business_id == business_id_a).count() == 0


def test_group_booking_blocked_when_customer_has_no_contact_info(two_businesses, monkeypatch):
    token_a = two_businesses["token_a"]
    business_id_a = two_businesses["business_id_a"]
    _setup_booking_business(token_a)
    customer_id = _create_customer(token_a)  # no phone, no email
    conversation_id = _create_conversation(business_id_a, customer_id)
    target_date = _next_monday()

    _stub_providers(
        monkeypatch,
        _group_booking_reply(
            [
                {"label": "Jordan", "service": "Cleaning", "date": target_date.isoformat(), "time": "14:00"},
                {"label": "Spouse", "service": "Cleaning", "date": target_date.isoformat(), "time": "14:00"},
            ],
            all_or_nothing=False,
            response="You're both booked!",
        ),
    )

    resp = client.post(
        f"/api/v1/conversations/{conversation_id}/messages",
        headers=_auth_header(token_a),
        json={"content": "Book me and my wife for cleanings next Monday at 2pm."},
    )
    assert resp.status_code == 201, resp.text
    body = resp.json()
    assert "you're both booked" not in body["response"].lower()
    assert "phone number or email" in body["response"].lower()

    with SessionLocal() as db:
        from app.db.models.appointment import Appointment

        assert db.query(Appointment).filter(Appointment.business_id == business_id_a).count() == 0


def test_booking_proceeds_when_contact_info_given_in_same_message(two_businesses, monkeypatch):
    """Contact info volunteered in THIS SAME message (e.g. "book me at 2pm,
    I'm Jordan, jordan@example.com") must immediately satisfy the gate — no
    need to ask-then-retry across two turns."""
    token_a = two_businesses["token_a"]
    business_id_a = two_businesses["business_id_a"]
    service_id = _setup_booking_business(token_a)
    customer_id = _create_customer(token_a)  # no phone, no email yet
    conversation_id = _create_conversation(business_id_a, customer_id)
    target_date = _next_monday()

    reply = json.dumps(
        {
            "intent": "booking",
            "response": "Let me get that booked.",
            "booking_request": {"service": "Cleaning", "date": target_date.isoformat(), "time": "14:00"},
            "contact_info_update": {"name": None, "email": "jordan@example.com", "phone": None},
        }
    )
    _stub_providers(monkeypatch, reply)

    resp = client.post(
        f"/api/v1/conversations/{conversation_id}/messages",
        headers=_auth_header(token_a),
        json={"content": "Can I get a cleaning next Monday at 2pm? I'm Jordan, jordan@example.com"},
    )
    assert resp.status_code == 201, resp.text
    body = resp.json()
    assert "phone number or email" not in body["response"].lower()

    with SessionLocal() as db:
        from app.db.models.appointment import Appointment
        from app.db.models.customer import Customer

        appointments = db.query(Appointment).filter(Appointment.business_id == business_id_a).all()
        assert len(appointments) == 1, "the gate must not have blocked a booking with contact info in the same turn"
        assert appointments[0].service_id == service_id
        assert db.get(Customer, customer_id).email == "jordan@example.com"


def test_booking_asks_again_after_gate_when_customer_still_gives_no_contact(two_businesses, monkeypatch):
    """A second turn where the customer still hasn't given contact info must
    keep being gated — never a one-time check that then trusts the session."""
    token_a = two_businesses["token_a"]
    business_id_a = two_businesses["business_id_a"]
    _setup_booking_business(token_a)
    customer_id = _create_customer(token_a)
    conversation_id = _create_conversation(business_id_a, customer_id)
    target_date = _next_monday()

    _stub_providers(monkeypatch, _booking_reply("Cleaning", target_date.isoformat(), "14:00"))
    resp = client.post(
        f"/api/v1/conversations/{conversation_id}/messages",
        headers=_auth_header(token_a),
        json={"content": "Can I get a cleaning next Monday at 2pm?"},
    )
    assert "phone number or email" in resp.json()["response"].lower()

    _stub_providers(monkeypatch, _booking_reply("Cleaning", target_date.isoformat(), "14:00"))
    resp = client.post(
        f"/api/v1/conversations/{conversation_id}/messages",
        headers=_auth_header(token_a),
        json={"content": "Just book it please."},
    )
    assert "phone number or email" in resp.json()["response"].lower()

    with SessionLocal() as db:
        from app.db.models.appointment import Appointment

        assert db.query(Appointment).filter(Appointment.business_id == business_id_a).count() == 0


# --- Phase 24 urgent fix: business-scope boundary (off_topic) -----------------


# --- Urgent fix: real 500 on provider failure -> graceful degradation --------


def _stub_failing_embedding_provider(monkeypatch):
    """Simulates the real, live-captured failure mode: `_post` (app/llm/
    azure_openai.py) exhausts its own internal retry budget and raises
    RuntimeError — this is what the orchestrator's safety net must catch,
    not a raw exception straight from httpx."""
    import app.services.conversation.orchestrator as orchestrator_module

    class _FailingEmbeddingProvider:
        def embed(self, texts):
            raise RuntimeError("LLM provider request failed: ConnectError")

    monkeypatch.setattr(orchestrator_module, "get_embedding_provider", lambda: _FailingEmbeddingProvider())


def test_provider_failure_degrades_gracefully_never_a_raw_500(two_businesses, monkeypatch):
    """The exact real bug: the embedding call fails after its own internal
    retries (RuntimeError, never a raw httpx exception once azure_openai._post
    is fixed) — the endpoint must still return 201 with an honest message, the
    customer's real message must still be persisted (never silently dropped),
    and a REAL HumanHandoff must be created — never a bare 500."""
    token_a = two_businesses["token_a"]
    business_id_a = two_businesses["business_id_a"]
    customer_id = _create_customer(token_a)
    conversation_id = _create_conversation(business_id_a, customer_id)

    _stub_failing_embedding_provider(monkeypatch)

    resp = client.post(
        f"/api/v1/conversations/{conversation_id}/messages",
        headers=_auth_header(token_a),
        json={"content": "sunnu na mero teeth ali ali dukhay ko 2 din vayo check garau nai parxara?"},
    )
    assert resp.status_code == 201, resp.text
    body = resp.json()
    assert body["intent"] == "unknown"
    assert "trouble connecting" in body["response"].lower()
    assert "let our team know" in body["response"].lower()

    with SessionLocal() as db:
        from app.db.models.conversation import Message
        from app.db.models.handoff import HumanHandoff

        messages = list(
            db.query(Message).filter(Message.conversation_id == conversation_id).order_by(Message.created_at)
        )
        assert [m.content for m in messages] == [
            "sunnu na mero teeth ali ali dukhay ko 2 din vayo check garau nai parxara?",
            body["response"],
        ]
        assert [m.sender_type.value for m in messages] == ["customer", "agent"]

        handoffs = list(db.query(HumanHandoff).filter(HumanHandoff.conversation_id == conversation_id))
        assert len(handoffs) == 1
        assert "provider" in handoffs[0].reason.lower()
        assert handoffs[0].status == "open"


def test_provider_failure_renders_in_the_already_locked_language(two_businesses, monkeypatch):
    """The static failure sentence must still respect an already-locked
    conversation language — never silently reverting to English mid-
    conversation just because the LLM itself is unreachable."""
    token_a = two_businesses["token_a"]
    business_id_a = two_businesses["business_id_a"]
    customer_id = _create_customer(token_a)
    conversation_id = _create_conversation(business_id_a, customer_id)

    with SessionLocal() as db:
        conversation = db.get(Conversation, conversation_id)
        conversation.detected_language = "ne_roman"
        db.commit()

    _stub_failing_embedding_provider(monkeypatch)

    resp = client.post(
        f"/api/v1/conversations/{conversation_id}/messages",
        headers=_auth_header(token_a),
        json={"content": "kehi bhannu paryo"},
    )
    assert resp.status_code == 201, resp.text
    assert "connect garna samasya" in resp.json()["response"].lower()


def test_handoff_reason_provider_failure_takes_priority_unconditionally():
    """Direct check of the structural guard (handoff_service._handoff_reason):
    `is_provider_failure` must produce a reason regardless of intent, and
    must never be silently overridden by the language-switch exclusion or any
    other signal."""
    from app.services.handoff_service import _handoff_reason

    reason = _handoff_reason(
        intent=ConversationIntent.UNKNOWN,
        best_similarity=None,
        llm_confirmed_answered=None,
        is_provider_failure=True,
    )
    assert reason is not None
    assert "provider" in reason.lower()

    # Even for an intent that would otherwise never trigger a handoff on its
    # own (OFF_TOPIC isn't in COMPLAINT/HUMAN_HANDOFF/_INFO_INTENTS).
    reason2 = _handoff_reason(
        intent=ConversationIntent.OFF_TOPIC,
        best_similarity=None,
        llm_confirmed_answered=None,
        is_provider_failure=True,
    )
    assert reason2 is not None


def test_off_topic_intent_declines_deterministically_and_creates_no_handoff(two_businesses, monkeypatch):
    """Even if the (stubbed, adversarial) LLM's own `response` actually answers
    the off-topic question, the customer must never see that text — the
    orchestrator's deterministic override is the only thing that reaches them
    — and this must never create a HumanHandoff (it's out-of-scope, not an
    unanswered business question)."""
    token_a = two_businesses["token_a"]
    business_id_a = two_businesses["business_id_a"]
    customer_id = _create_customer(token_a)
    conversation_id = _create_conversation(business_id_a, customer_id)

    hallucinated_history_answer = (
        "America was reached by European explorers when Christopher Columbus's expedition "
        "landed in the Caribbean in 1492."
    )
    _stub_providers(
        monkeypatch,
        json.dumps({"intent": "off_topic", "response": hallucinated_history_answer, "needs_human_handoff": False}),
    )

    resp = client.post(
        f"/api/v1/conversations/{conversation_id}/messages",
        headers=_auth_header(token_a),
        json={"content": "Random question — how was America discovered?"},
    )
    assert resp.status_code == 201, resp.text
    body = resp.json()
    assert body["intent"] == "off_topic"
    assert "columbus" not in body["response"].lower()
    assert "1492" not in body["response"]
    assert "is there something about that i can help with" in body["response"].lower()

    with SessionLocal() as db:
        from app.db.models.handoff import HumanHandoff

        assert db.query(HumanHandoff).filter(HumanHandoff.business_id == business_id_a).count() == 0


def test_off_topic_intent_uses_business_name_in_decline(two_businesses, monkeypatch):
    token_a = two_businesses["token_a"]
    business_id_a = two_businesses["business_id_a"]
    customer_id = _create_customer(token_a)
    conversation_id = _create_conversation(business_id_a, customer_id)

    _stub_providers(
        monkeypatch,
        json.dumps({"intent": "off_topic", "response": "irrelevant stubbed text", "needs_human_handoff": False}),
    )

    resp = client.post(
        f"/api/v1/conversations/{conversation_id}/messages",
        headers=_auth_header(token_a),
        json={"content": "Who won the last election?"},
    )
    assert resp.status_code == 201, resp.text
    assert "Conv A" in resp.json()["response"]


# --- Phase 25 urgent fix: locked per-conversation language/script -------------


def test_language_lock_set_from_first_message_and_used_in_deterministic_sentence(two_businesses, monkeypatch):
    """The very first message with a clear signal locks Conversation.
    detected_language immediately, and that SAME turn's deterministic
    sentence (never LLM-drafted text) already reflects it."""
    token_a = two_businesses["token_a"]
    business_id_a = two_businesses["business_id_a"]
    customer_id = _create_customer(token_a)
    conversation_id = _create_conversation(business_id_a, customer_id)

    _stub_providers(
        monkeypatch,
        json.dumps(
            {
                "intent": "off_topic",
                "response": "irrelevant stubbed text",
                "needs_human_handoff": False,
                "message_language": "ne_roman",
            }
        ),
    )
    resp = client.post(
        f"/api/v1/conversations/{conversation_id}/messages",
        headers=_auth_header(token_a),
        json={"content": "Timro rashifal ke ho?"},
    )
    assert resp.status_code == 201, resp.text
    # ne_roman off_topic template, never the English one, never the LLM's own stubbed text.
    assert "sanga related kura haru" in resp.json()["response"]
    assert "irrelevant stubbed text" not in resp.json()["response"]

    with SessionLocal() as db:
        conversation = db.get(Conversation, conversation_id)
        assert conversation.detected_language == "ne_roman"
        assert conversation.language_switch_streak == 0


def test_language_lock_persists_across_turns_for_a_different_deterministic_sentence(two_businesses, monkeypatch):
    """Once locked on turn 1, an UNRELATED deterministic sentence on turn 2
    (the booking-no-contact-info gate) must already render in that same
    locked language — never re-guessed, never left in English."""
    token_a = two_businesses["token_a"]
    business_id_a = two_businesses["business_id_a"]
    _setup_booking_business(token_a)
    customer_id = _create_customer(token_a)
    conversation_id = _create_conversation(business_id_a, customer_id)
    target_date = _next_monday()

    _stub_providers(
        monkeypatch,
        json.dumps(
            {
                "intent": "greeting",
                "response": "Namaste!",
                "needs_human_handoff": False,
                "message_language": "ne_roman",
            }
        ),
    )
    resp = client.post(
        f"/api/v1/conversations/{conversation_id}/messages",
        headers=_auth_header(token_a),
        json={"content": "Namaste!"},
    )
    assert resp.status_code == 201, resp.text

    reply = json.dumps(
        {
            "intent": "booking",
            "response": "should never be shown — contact-info gate must override this",
            "booking_request": {"service": "Cleaning", "date": target_date.isoformat(), "time": "14:00"},
        }
    )
    _stub_providers(monkeypatch, reply)
    resp = client.post(
        f"/api/v1/conversations/{conversation_id}/messages",
        headers=_auth_header(token_a),
        json={"content": "Can I book a cleaning next Monday at 2pm?"},
    )
    assert resp.status_code == 201, resp.text
    # Phase 25a-2: the gate is dynamic — since this turn's booking_request is
    # fully specified, the ne_roman "booking_gate_with_progress" template
    # renders (not the "nothing known yet" booking_no_contact one), and it
    # must still be in the locked language, never English.
    body = resp.json()["response"]
    assert "Lock garna malai tapaiko naam ra phone number wa email chahincha" in body
    assert "Cleaning" in body

    with SessionLocal() as db:
        conversation = db.get(Conversation, conversation_id)
        assert conversation.detected_language == "ne_roman"


def test_resolve_message_language_devanagari_deterministic_override():
    """Direct, deterministic check of the Devanagari script guard (Phase 25)
    — found live: the LLM's own `message_language` self-report can anchor to
    whatever the conversation is already locked to, even for a message that
    provably isn't in that script. Devanagari presence is the one part of
    this that's mechanically checkable, so it always overrides positively
    (real script beats any LLM claim) and suppresses a false positive claim
    (an unbacked "ne_deva" self-report is dropped to no signal, never
    trusted and never guessed at) — see orchestrator._resolve_message_language."""
    from app.services.conversation.orchestrator import _resolve_message_language

    assert _resolve_message_language("नमस्ते", "en") == "ne_deva"
    assert _resolve_message_language("नमस्ते", None) == "ne_deva"
    assert _resolve_message_language("What are your business hours?", "ne_deva") is None
    assert _resolve_message_language("Namaste, kasto cha?", "ne_deva") is None
    assert _resolve_message_language("What are your business hours?", "en") == "en"
    assert _resolve_message_language("Namaste, kasto cha?", "ne_roman") == "ne_roman"
    assert _resolve_message_language("some text", None) is None


def test_resolve_locked_language_ignores_one_off_drift_but_relocks_after_sustained_streak():
    """Direct, deterministic check of the streak-based lock (Phase 25) — a
    single differing message must never flip the lock, but
    _LANGUAGE_LOCK_STREAK_THRESHOLD consecutive differing messages must."""
    from types import SimpleNamespace

    from app.services.conversation.orchestrator import _LANGUAGE_LOCK_STREAK_THRESHOLD, _resolve_locked_language

    conversation = SimpleNamespace(detected_language=None, language_switch_streak=0)

    # First clear signal locks immediately and is used the same turn.
    assert _resolve_locked_language(conversation, "ne_roman") == "ne_roman"
    assert conversation.detected_language == "ne_roman"

    # A single differing message never flips it — still renders as the old lock.
    assert _resolve_locked_language(conversation, "en") == "ne_roman"
    assert conversation.detected_language == "ne_roman"
    assert conversation.language_switch_streak == 1

    # Matching the lock again resets the streak.
    assert _resolve_locked_language(conversation, "ne_roman") == "ne_roman"
    assert conversation.language_switch_streak == 0

    # A sustained streak of the SAME different language, up to the threshold,
    # actually relocks — but only takes effect for the turn AFTER it crosses.
    for i in range(_LANGUAGE_LOCK_STREAK_THRESHOLD - 1):
        language_used = _resolve_locked_language(conversation, "en")
        assert language_used == "ne_roman", f"turn {i}: must still render in the old lock"
        assert conversation.detected_language == "ne_roman"

    language_used = _resolve_locked_language(conversation, "en")
    assert language_used == "ne_roman", "the turn that crosses the threshold still renders in the OLD lock"
    assert conversation.detected_language == "en", "but the lock itself has now moved for the NEXT turn"
    assert conversation.language_switch_streak == 0

    # And the next turn actually uses the new lock.
    assert _resolve_locked_language(conversation, "en") == "en"


# --- Phase 25b urgent fix: explicit language-switch override + self-awareness -


def test_resolve_locked_language_explicit_switch_overrides_immediately_bypassing_streak():
    """Direct, deterministic check: an explicit switch request (as opposed to
    passive drift) must NOT wait for the 3-consecutive-message streak — it
    overrides the lock on the very turn it's reported, even mid-streak."""
    from types import SimpleNamespace

    from app.services.conversation.orchestrator import _resolve_locked_language

    conversation = SimpleNamespace(detected_language="ne_roman", language_switch_streak=0)

    # One passive-drift message starts building a streak, same as before.
    assert _resolve_locked_language(conversation, "en") == "ne_roman"
    assert conversation.language_switch_streak == 1

    # An explicit switch request on the very next turn overrides immediately —
    # used THIS turn, streak reset, regardless of the in-progress streak above.
    assert _resolve_locked_language(conversation, "en", explicit_switch_target="en") == "en"
    assert conversation.detected_language == "en"
    assert conversation.language_switch_streak == 0

    # Also overrides an unset lock immediately (first-message case).
    fresh = SimpleNamespace(detected_language=None, language_switch_streak=0)
    assert _resolve_locked_language(fresh, "ne_roman", explicit_switch_target="ne_roman") == "ne_roman"
    assert fresh.detected_language == "ne_roman"

    # An invalid/absent target is a no-op — falls through to normal drift logic.
    assert _resolve_locked_language(conversation, "en", explicit_switch_target=None) == "en"
    assert _resolve_locked_language(conversation, "en", explicit_switch_target="not_a_language") == "en"


def test_handoff_reason_structurally_excludes_language_switch_regardless_of_intent():
    """Direct check of the structural (not just prompted) exclusion: even a
    COMPLAINT/HUMAN_HANDOFF intent, or an info-intent with zero knowledge
    similarity and needs_human_handoff=True, must never produce a handoff
    reason when is_language_switch_request=True."""
    from app.services.handoff_service import _handoff_reason

    for intent in (
        ConversationIntent.COMPLAINT,
        ConversationIntent.HUMAN_HANDOFF,
        ConversationIntent.GENERAL_QUESTION,
        ConversationIntent.PRICING_QUESTION,
    ):
        assert (
            _handoff_reason(
                intent=intent,
                best_similarity=0.0,
                llm_confirmed_answered=False,
                is_language_switch_request=True,
            )
            is None
        )

    # Sanity: without the flag, these same inputs DO produce a reason (proves
    # the test above is actually exercising the guard, not a no-op path).
    assert (
        _handoff_reason(intent=ConversationIntent.COMPLAINT, best_similarity=0.0, llm_confirmed_answered=False)
        is not None
    )


def test_explicit_language_switch_overrides_lock_same_turn_and_creates_no_handoff(two_businesses, monkeypatch):
    """Full pipeline: a conversation already locked to Roman Nepali, customer
    explicitly asks to switch to English — the very next response must use
    the new lock immediately (not wait 3 turns), the DB must show
    detected_language updated on this exact turn, and no HumanHandoff may be
    created even though the LLM's own drafted response reads like a language
    question the knowledge base has no chunk for."""
    token_a = two_businesses["token_a"]
    business_id_a = two_businesses["business_id_a"]
    customer_id = _create_customer(token_a)
    conversation_id = _create_conversation(business_id_a, customer_id)

    with SessionLocal() as db:
        conversation = db.get(Conversation, conversation_id)
        conversation.detected_language = "ne_roman"
        conversation.language_switch_streak = 0
        db.commit()

    _stub_providers(
        monkeypatch,
        json.dumps(
            {
                "intent": "general_question",
                "response": "Of course! Switching to English now — how can I help?",
                "needs_human_handoff": False,
                "message_language": "en",
                "language_switch_request": "en",
            }
        ),
    )
    resp = client.post(
        f"/api/v1/conversations/{conversation_id}/messages",
        headers=_auth_header(token_a),
        json={"content": "Can we just switch to English please?"},
    )
    assert resp.status_code == 201, resp.text
    assert "Switching to English" in resp.json()["response"]

    with SessionLocal() as db:
        conversation = db.get(Conversation, conversation_id)
        assert conversation.detected_language == "en"
        assert conversation.language_switch_streak == 0

        from app.db.models.handoff import HumanHandoff

        assert db.query(HumanHandoff).filter(HumanHandoff.conversation_id == conversation_id).count() == 0


def test_passive_single_word_drift_does_not_override_lock_or_create_handoff(two_businesses, monkeypatch):
    """Regression / distinction check: a single stray English word mid-Nepali
    conversation (no `language_switch_request`) must NOT flip the lock — only
    an explicit switch request does. Proves the two paths are genuinely
    distinct, not accidentally over-broad."""
    token_a = two_businesses["token_a"]
    business_id_a = two_businesses["business_id_a"]
    customer_id = _create_customer(token_a)
    conversation_id = _create_conversation(business_id_a, customer_id)

    with SessionLocal() as db:
        conversation = db.get(Conversation, conversation_id)
        conversation.detected_language = "ne_roman"
        conversation.language_switch_streak = 0
        db.commit()

    _stub_providers(
        monkeypatch,
        json.dumps(
            {
                "intent": "follow_up",
                "response": "Swagat cha! Aru kehi sahayog chahiyo bhane bhanuhos.",
                "needs_human_handoff": False,
                "message_language": "en",
                "language_switch_request": None,
            }
        ),
    )
    resp = client.post(
        f"/api/v1/conversations/{conversation_id}/messages",
        headers=_auth_header(token_a),
        json={"content": "thanks!"},
    )
    assert resp.status_code == 201, resp.text

    with SessionLocal() as db:
        conversation = db.get(Conversation, conversation_id)
        assert conversation.detected_language == "ne_roman"
        assert conversation.language_switch_streak == 1


def test_explicit_language_switch_reverse_direction_nepali(two_businesses, monkeypatch):
    """Same mechanism, the other direction: English-locked conversation,
    explicit request to switch to Nepali — the very next response is already
    in Nepali, and detected_language updates on this exact turn."""
    token_a = two_businesses["token_a"]
    business_id_a = two_businesses["business_id_a"]
    customer_id = _create_customer(token_a)
    conversation_id = _create_conversation(business_id_a, customer_id)

    with SessionLocal() as db:
        conversation = db.get(Conversation, conversation_id)
        conversation.detected_language = "en"
        conversation.language_switch_streak = 0
        db.commit()

    _stub_providers(
        monkeypatch,
        json.dumps(
            {
                "intent": "general_question",
                "response": "Pakka, ma Nepali ma kura garna sakchu! Kehi sodhna man lagcha?",
                "needs_human_handoff": False,
                "message_language": "en",
                "language_switch_request": "ne_roman",
            }
        ),
    )
    resp = client.post(
        f"/api/v1/conversations/{conversation_id}/messages",
        headers=_auth_header(token_a),
        json={"content": "Can we talk in Nepali from now on?"},
    )
    assert resp.status_code == 201, resp.text
    assert "Nepali ma kura garna sakchu" in resp.json()["response"]

    with SessionLocal() as db:
        conversation = db.get(Conversation, conversation_id)
        assert conversation.detected_language == "ne_roman"

        from app.db.models.handoff import HumanHandoff

        assert db.query(HumanHandoff).filter(HumanHandoff.conversation_id == conversation_id).count() == 0


# --- Phase 25a urgent fix: persisted booking-draft slot tracking --------------


def _partial_booking_reply(
    *,
    service: str | None = None,
    date: str | None = None,
    time: str | None = None,
    wants_availability: bool = False,
    response: str = "ok",
) -> str:
    return json.dumps(
        {
            "intent": "booking",
            "response": response,
            "booking_request": {
                "service": service, "date": date, "time": time, "wants_availability": wants_availability,
            },
        }
    )


def test_booking_draft_accumulates_across_turns_and_books_once_complete(two_businesses, monkeypatch):
    """The exact shape of the reported infinite-loop bug: service, then a
    date, then a time, given in three SEPARATE turns — each turn's stubbed
    LLM output only ever contains the ONE new field, exactly like a real
    partial extraction. Must book on the turn that completes the triple,
    with no extra confirmation round-trip."""
    token_a = two_businesses["token_a"]
    business_id_a = two_businesses["business_id_a"]
    service_id = _setup_booking_business(token_a)
    customer_id = _create_customer_with_contact(token_a)
    conversation_id = _create_conversation(business_id_a, customer_id)
    target_date = _next_monday()

    _stub_providers(monkeypatch, _partial_booking_reply(service="Cleaning", response="Sure — what date and time?"))
    resp = client.post(
        f"/api/v1/conversations/{conversation_id}/messages",
        headers=_auth_header(token_a),
        json={"content": "I'd like to book a cleaning."},
    )
    assert resp.status_code == 201, resp.text
    assert "what date" in resp.json()["response"].lower()
    assert "which service" not in resp.json()["response"].lower()

    _stub_providers(monkeypatch, _partial_booking_reply(date=target_date.isoformat(), response="Got it."))
    resp = client.post(
        f"/api/v1/conversations/{conversation_id}/messages",
        headers=_auth_header(token_a),
        json={"content": "Next Monday."},
    )
    assert resp.status_code == 201, resp.text
    assert "what time" in resp.json()["response"].lower()
    assert "which service" not in resp.json()["response"].lower()
    assert "what date" not in resp.json()["response"].lower(), "must never re-ask for a slot already filled"

    with SessionLocal() as db:
        from app.db.models.appointment import Appointment

        assert db.query(Appointment).filter(Appointment.business_id == business_id_a).count() == 0

    _stub_providers(monkeypatch, _partial_booking_reply(time="14:00", response="One moment."))
    resp = client.post(
        f"/api/v1/conversations/{conversation_id}/messages",
        headers=_auth_header(token_a),
        json={"content": "2pm works."},
    )
    assert resp.status_code == 201, resp.text
    body = resp.json()
    assert "One moment." not in body["response"]

    with SessionLocal() as db:
        from app.db.models.appointment import Appointment

        appointments = db.query(Appointment).filter(Appointment.business_id == business_id_a).all()
        assert len(appointments) == 1, "must book on the turn that completes the triple — no extra confirmation turn"
        assert appointments[0].service_id == service_id
        assert appointments[0].scheduled_at.hour == 14
        assert str(appointments[0].id) in body["response"]

        conversation = db.get(Conversation, conversation_id)
        assert conversation.booking_draft_service_id is None
        assert conversation.booking_draft_date is None
        assert conversation.booking_draft_time is None


def test_booking_draft_redundant_confirmation_does_not_loop_or_double_book(two_businesses, monkeypatch):
    """Explicit re-confirmations ("yes") after the draft is already complete
    must not create a second booking or re-ask anything — the draft is
    cleared the instant it's used, so a stray extra "yes" after booking finds
    nothing left to act on."""
    token_a = two_businesses["token_a"]
    business_id_a = two_businesses["business_id_a"]
    _setup_booking_business(token_a)
    customer_id = _create_customer_with_contact(token_a)
    conversation_id = _create_conversation(business_id_a, customer_id)
    target_date = _next_monday()

    _stub_providers(monkeypatch, _booking_reply("Cleaning", target_date.isoformat(), "14:00"))
    resp = client.post(
        f"/api/v1/conversations/{conversation_id}/messages",
        headers=_auth_header(token_a),
        json={"content": "book me a cleaning next monday at 2pm"},
    )
    assert resp.status_code == 201, resp.text

    with SessionLocal() as db:
        from app.db.models.appointment import Appointment

        assert db.query(Appointment).filter(Appointment.business_id == business_id_a).count() == 1

    # A redundant "yes" with nothing new extracted must not re-book.
    _stub_providers(monkeypatch, _partial_booking_reply(response="Great!"))
    resp = client.post(
        f"/api/v1/conversations/{conversation_id}/messages",
        headers=_auth_header(token_a),
        json={"content": "yes"},
    )
    assert resp.status_code == 201, resp.text

    with SessionLocal() as db:
        from app.db.models.appointment import Appointment

        assert db.query(Appointment).filter(Appointment.business_id == business_id_a).count() == 1, (
            "a stray confirmation after the draft was already used must never create a second appointment"
        )


def test_booking_draft_survives_contact_gate_then_books_once_contact_given(two_businesses, monkeypatch):
    """Slots given before contact info must not be lost — once contact info
    arrives (even with no new slot info in that same message), the booking
    must proceed immediately using what was already collected."""
    token_a = two_businesses["token_a"]
    business_id_a = two_businesses["business_id_a"]
    service_id = _setup_booking_business(token_a)
    customer_id = _create_customer(token_a)  # no phone, no email
    conversation_id = _create_conversation(business_id_a, customer_id)
    target_date = _next_monday()

    _stub_providers(monkeypatch, _booking_reply("Cleaning", target_date.isoformat(), "14:00"))
    resp = client.post(
        f"/api/v1/conversations/{conversation_id}/messages",
        headers=_auth_header(token_a),
        json={"content": "book me a cleaning next monday at 2pm"},
    )
    assert resp.status_code == 201, resp.text
    assert "phone number or email" in resp.json()["response"].lower()

    with SessionLocal() as db:
        from app.db.models.appointment import Appointment

        assert db.query(Appointment).filter(Appointment.business_id == business_id_a).count() == 0

    reply = json.dumps(
        {
            "intent": "booking",
            "response": "Thanks!",
            "booking_request": {"service": None, "date": None, "time": None},
            "contact_info_update": {"name": "Jamie Rivera", "email": "jamie@example.com", "phone": None},
        }
    )
    _stub_providers(monkeypatch, reply)
    resp = client.post(
        f"/api/v1/conversations/{conversation_id}/messages",
        headers=_auth_header(token_a),
        json={"content": "I'm Jamie Rivera, jamie@example.com"},
    )
    assert resp.status_code == 201, resp.text
    body = resp.json()
    assert "phone number or email" not in body["response"].lower()

    with SessionLocal() as db:
        from app.db.models.appointment import Appointment

        appointments = db.query(Appointment).filter(Appointment.business_id == business_id_a).all()
        assert len(appointments) == 1, "the slots given before contact info must not have been lost"
        assert appointments[0].service_id == service_id
        assert str(appointments[0].id) in body["response"]


def test_booking_draft_correction_uses_latest_value_not_stale_one(two_businesses, monkeypatch):
    """Customer gives a time, then changes their mind BEFORE the booking
    actually fires (the contact-info gate is what keeps this one pending
    across turns, same real gate Phase 24 added) — the corrected value must
    be what actually gets booked, not the stale first one."""
    token_a = two_businesses["token_a"]
    business_id_a = two_businesses["business_id_a"]
    _setup_booking_business(token_a)
    customer_id = _create_customer(token_a)  # no phone, no email yet
    conversation_id = _create_conversation(business_id_a, customer_id)
    target_date = _next_monday()

    _stub_providers(monkeypatch, _booking_reply("Cleaning", target_date.isoformat(), "10:00"))
    resp = client.post(
        f"/api/v1/conversations/{conversation_id}/messages",
        headers=_auth_header(token_a),
        json={"content": "Book me a cleaning next Monday at 10am."},
    )
    assert resp.status_code == 201, resp.text
    assert "phone number or email" in resp.json()["response"].lower()

    _stub_providers(monkeypatch, _partial_booking_reply(time="11:00", response="Sure, updating that."))
    resp = client.post(
        f"/api/v1/conversations/{conversation_id}/messages",
        headers=_auth_header(token_a),
        json={"content": "Actually, make it 11am instead."},
    )
    assert resp.status_code == 201, resp.text
    assert "phone number or email" in resp.json()["response"].lower(), "still gated — contact info not given yet"

    with SessionLocal() as db:
        from app.db.models.appointment import Appointment

        assert db.query(Appointment).filter(Appointment.business_id == business_id_a).count() == 0

    reply = json.dumps(
        {
            "intent": "booking",
            "response": "Thanks!",
            "booking_request": {"service": None, "date": None, "time": None},
            "contact_info_update": {"name": "Jamie Rivera", "email": "jamie@example.com", "phone": None},
        }
    )
    _stub_providers(monkeypatch, reply)
    resp = client.post(
        f"/api/v1/conversations/{conversation_id}/messages",
        headers=_auth_header(token_a),
        json={"content": "I'm Jamie Rivera, jamie@example.com"},
    )
    assert resp.status_code == 201, resp.text

    with SessionLocal() as db:
        from app.db.models.appointment import Appointment

        appointments = db.query(Appointment).filter(Appointment.business_id == business_id_a).all()
        assert len(appointments) == 1
        assert appointments[0].scheduled_at.hour == 11, "the corrected time must be used, not the stale 10am"


def test_booking_missing_slots_message_asks_only_for_what_is_actually_missing(two_businesses, monkeypatch):
    """When only the service is known, the response must ask for date/time
    but never re-ask which service — and vice versa when only date+time are
    known but the service name didn't resolve."""
    token_a = two_businesses["token_a"]
    business_id_a = two_businesses["business_id_a"]
    _setup_booking_business(token_a)
    customer_id = _create_customer_with_contact(token_a)
    conversation_id = _create_conversation(business_id_a, customer_id)
    target_date = _next_monday()

    _stub_providers(monkeypatch, _partial_booking_reply(service="Cleaning"))
    resp = client.post(
        f"/api/v1/conversations/{conversation_id}/messages",
        headers=_auth_header(token_a),
        json={"content": "I want a cleaning."},
    )
    body = resp.json()["response"].lower()
    assert "what date" in body and "what time" in body
    assert "which service" not in body

    conversation_id_2 = _create_conversation(business_id_a, customer_id)
    _stub_providers(monkeypatch, _partial_booking_reply(date=target_date.isoformat(), time="14:00"))
    resp = client.post(
        f"/api/v1/conversations/{conversation_id_2}/messages",
        headers=_auth_header(token_a),
        json={"content": "Next Monday at 2pm."},
    )
    body = resp.json()["response"].lower()
    assert "which service" in body
    assert "what date" not in body and "what time" not in body


def test_booking_completes_when_contact_info_arrives_on_an_off_intent_turn(two_businesses, monkeypatch):
    """Real bug found live: contact info can arrive on a turn the LLM
    classifies as something other than "booking" (e.g. a bare "I'm Devon,
    devon@example.com" reads as follow_up) — if that's the exact missing
    piece for an otherwise-complete draft, the booking must still fire THIS
    turn rather than leave the LLM's own hedging text standing."""
    token_a = two_businesses["token_a"]
    business_id_a = two_businesses["business_id_a"]
    service_id = _setup_booking_business(token_a)
    customer_id = _create_customer(token_a)  # no phone, no email yet
    conversation_id = _create_conversation(business_id_a, customer_id)
    target_date = _next_monday()

    _stub_providers(monkeypatch, _booking_reply("Cleaning", target_date.isoformat(), "14:00"))
    resp = client.post(
        f"/api/v1/conversations/{conversation_id}/messages",
        headers=_auth_header(token_a),
        json={"content": "Can I book a cleaning next Monday at 2pm?"},
    )
    assert resp.status_code == 201, resp.text
    assert "phone number or email" in resp.json()["response"].lower()

    # This turn is classified as follow_up, NOT booking — the LLM's own text
    # is a hedge ("Would you like me to go ahead and book...?") that must
    # never reach the customer once contact info completes the draft.
    reply = json.dumps(
        {
            "intent": "follow_up",
            "response": "Would you like me to go ahead and book that?",
            "contact_info_update": {"name": "Devon Clarke", "email": "devon.clarke@example.com", "phone": None},
            "needs_human_handoff": False,
        }
    )
    _stub_providers(monkeypatch, reply)
    resp = client.post(
        f"/api/v1/conversations/{conversation_id}/messages",
        headers=_auth_header(token_a),
        json={"content": "Sure, I'm Devon Clarke, devon.clarke@example.com"},
    )
    assert resp.status_code == 201, resp.text
    body = resp.json()
    assert "would you like me to go ahead" not in body["response"].lower()

    with SessionLocal() as db:
        from app.db.models.appointment import Appointment

        appointments = db.query(Appointment).filter(Appointment.business_id == business_id_a).all()
        assert len(appointments) == 1, "must book off the pending draft even though this turn wasn't classified as booking"
        assert appointments[0].service_id == service_id
        assert str(appointments[0].id) in body["response"]


def test_off_intent_contact_update_does_not_hijack_unrelated_turn_without_a_pending_draft(two_businesses, monkeypatch):
    """The off-intent completion path must never fire when there's no
    partial draft to complete — an ordinary contact-info update on an
    unrelated turn must behave exactly as it always has."""
    token_a = two_businesses["token_a"]
    business_id_a = two_businesses["business_id_a"]
    _setup_booking_business(token_a)
    customer_id = _create_customer(token_a)
    conversation_id = _create_conversation(business_id_a, customer_id)

    reply = json.dumps(
        {
            "intent": "follow_up",
            "response": "Thanks, Devon!",
            "contact_info_update": {"name": "Devon Clarke", "email": "devon.clarke@example.com", "phone": None},
            "needs_human_handoff": False,
        }
    )
    _stub_providers(monkeypatch, reply)
    resp = client.post(
        f"/api/v1/conversations/{conversation_id}/messages",
        headers=_auth_header(token_a),
        json={"content": "Oh, I'm Devon Clarke, devon.clarke@example.com"},
    )
    assert resp.status_code == 201, resp.text
    assert "Thanks, Devon!" in resp.json()["response"]

    with SessionLocal() as db:
        from app.db.models.appointment import Appointment

        assert db.query(Appointment).filter(Appointment.business_id == business_id_a).count() == 0


# --- Phase 25a-2 urgent fix: dynamic contact-gate + failure-aware draft clearing --


def test_contact_gate_reflects_accumulated_draft_and_changes_every_turn(two_businesses, monkeypatch):
    """Real adversarial testing found the contact-info gate repeating one
    identical static sentence across many turns while service/date/time
    contradicted and changed underneath it. This is the direct regression
    test: three separate corrections, all before contact info is given, each
    turn's gate sentence must be DIFFERENT from the last and must contain the
    latest value — never the same static sentence twice in a row."""
    token_a = two_businesses["token_a"]
    business_id_a = two_businesses["business_id_a"]
    _setup_booking_business(token_a)
    customer_id = _create_customer(token_a)  # no phone, no email
    conversation_id = _create_conversation(business_id_a, customer_id)
    target_date = _next_monday()
    later_date = target_date + timedelta(days=1)

    _stub_providers(monkeypatch, _partial_booking_reply(service="Cleaning", response="Sure."))
    resp = client.post(
        f"/api/v1/conversations/{conversation_id}/messages",
        headers=_auth_header(token_a),
        json={"content": "I'd like to book a cleaning."},
    )
    body_1 = resp.json()["response"]
    assert "phone number or email" in body_1.lower()
    assert "Cleaning" in body_1

    _stub_providers(monkeypatch, _partial_booking_reply(date=target_date.isoformat(), response="Got it."))
    resp = client.post(
        f"/api/v1/conversations/{conversation_id}/messages",
        headers=_auth_header(token_a),
        json={"content": "Next Monday."},
    )
    body_2 = resp.json()["response"]
    assert body_2 != body_1, "must not repeat the identical sentence once new info was given"
    assert "Cleaning" in body_2, "the service given earlier must not be lost"
    assert "phone number or email" in body_2.lower()

    with SessionLocal() as db:
        conversation = db.get(Conversation, conversation_id)
        assert conversation.booking_draft_date == target_date.isoformat()

    _stub_providers(monkeypatch, _partial_booking_reply(date=later_date.isoformat(), response="Sure, updating."))
    resp = client.post(
        f"/api/v1/conversations/{conversation_id}/messages",
        headers=_auth_header(token_a),
        json={"content": "Actually, make it the day after instead."},
    )
    body_3 = resp.json()["response"]
    assert body_3 != body_2, "the corrected date must change the gate sentence, not repeat the old one"
    assert "Cleaning" in body_3

    with SessionLocal() as db:
        conversation = db.get(Conversation, conversation_id)
        assert conversation.booking_draft_date == later_date.isoformat(), "the corrected date must be what's persisted"
        assert conversation.booking_draft_time is None

    _stub_providers(monkeypatch, _partial_booking_reply(time="15:00", response="Noted."))
    resp = client.post(
        f"/api/v1/conversations/{conversation_id}/messages",
        headers=_auth_header(token_a),
        json={"content": "3pm works."},
    )
    body_4 = resp.json()["response"]
    assert body_4 != body_3, "adding the time must change the gate sentence again"
    assert "3:00 PM" in body_4
    assert "phone number or email" in body_4.lower()

    with SessionLocal() as db:
        from app.db.models.appointment import Appointment

        assert db.query(Appointment).filter(Appointment.business_id == business_id_a).count() == 0, (
            "no contact info was ever given — nothing should have booked yet"
        )
        conversation = db.get(Conversation, conversation_id)
        assert conversation.booking_draft_time == "15:00"


def test_contact_gate_with_nothing_known_yet_uses_plain_static_sentence(two_businesses, monkeypatch):
    """When truly nothing has been given yet, the gate still uses the plain
    "nothing known yet" wording — there's nothing real to acknowledge, so a
    fabricated "Got it — ..." with an empty summary would be worse, not
    better."""
    token_a = two_businesses["token_a"]
    business_id_a = two_businesses["business_id_a"]
    _setup_booking_business(token_a)
    customer_id = _create_customer(token_a)
    conversation_id = _create_conversation(business_id_a, customer_id)

    _stub_providers(monkeypatch, _partial_booking_reply(response="Sure, one moment."))
    resp = client.post(
        f"/api/v1/conversations/{conversation_id}/messages",
        headers=_auth_header(token_a),
        json={"content": "I'd like to book something."},
    )
    assert "Before I can get that booked" in resp.json()["response"]


def test_booking_failure_preserves_service_and_same_day_alternative_preserves_date(two_businesses, monkeypatch):
    """Real bug found live: a failed booking attempt (the requested time is
    already taken) was clearing the ENTIRE draft, forcing the customer to
    re-state the service. Since a real, same-day alternative slot exists
    (the business is open all day, only 2pm is taken), the date is correct
    and unaffected by the failure too — only the time needs re-specifying."""
    token_a = two_businesses["token_a"]
    business_id_a = two_businesses["business_id_a"]
    service_id = _setup_booking_business(token_a)
    customer_id = _create_customer_with_contact(token_a)
    conversation_id = _create_conversation(business_id_a, customer_id)
    target_date = _next_monday()

    with SessionLocal() as db:
        scheduled_at = datetime(target_date.year, target_date.month, target_date.day, 14, 0, tzinfo=ZoneInfo("UTC"))
        booking_service.create_appointment(
            db,
            business_id=business_id_a,
            customer_id=customer_id,
            service_id=service_id,
            staff_id=None,
            scheduled_at=scheduled_at,
        )

    _stub_providers(monkeypatch, _booking_reply("Cleaning", target_date.isoformat(), "14:00"))
    resp = client.post(
        f"/api/v1/conversations/{conversation_id}/messages",
        headers=_auth_header(token_a),
        json={"content": "Can I get a cleaning next Monday at 2pm?"},
    )
    assert resp.status_code == 201, resp.text
    lowered = resp.json()["response"].lower()
    assert "isn't available" in lowered or "not available" in lowered

    with SessionLocal() as db:
        conversation = db.get(Conversation, conversation_id)
        assert conversation.booking_draft_service_id == service_id, "the service was never actually invalid"
        assert conversation.booking_draft_date == target_date.isoformat(), (
            "a real same-day alternative exists, so the date is still valid — must survive the failure"
        )
        assert conversation.booking_draft_time is None, "the specific failed time must be cleared"

    # The customer only needs to give a new time — service AND date survive.
    _stub_providers(monkeypatch, _partial_booking_reply(time="10:00", response="Sure, checking 10am."))
    resp = client.post(
        f"/api/v1/conversations/{conversation_id}/messages",
        headers=_auth_header(token_a),
        json={"content": "How about 10am instead?"},
    )
    assert resp.status_code == 201, resp.text
    body = resp.json()

    with SessionLocal() as db:
        from app.db.models.appointment import Appointment

        appointments = db.query(Appointment).filter(Appointment.business_id == business_id_a).all()
        booked = [a for a in appointments if a.scheduled_at.hour == 10]
        assert len(booked) == 1, "must book using the SURVIVING service+date plus only the newly given time"
        assert booked[0].service_id == service_id
        assert str(booked[0].id) in body["response"]


def test_booking_failure_on_a_fully_closed_day_clears_date_too(two_businesses, monkeypatch):
    """When the requested day has NO real availability at all (a closed day),
    keeping the date after the failure would silently re-present an invalid
    day as if it still held — the date must be cleared too, while the
    service (never actually invalid) still survives."""
    token_a = two_businesses["token_a"]
    business_id_a = two_businesses["business_id_a"]
    service_id = _setup_booking_business(token_a)  # Sunday (day_of_week 6) is closed
    customer_id = _create_customer_with_contact(token_a)
    conversation_id = _create_conversation(business_id_a, customer_id)

    today = date.today()
    days_ahead = (6 - today.weekday()) % 7 or 7
    closed_sunday = today + timedelta(days=days_ahead)

    _stub_providers(monkeypatch, _booking_reply("Cleaning", closed_sunday.isoformat(), "14:00"))
    resp = client.post(
        f"/api/v1/conversations/{conversation_id}/messages",
        headers=_auth_header(token_a),
        json={"content": "Can I get a cleaning this Sunday at 2pm?"},
    )
    assert resp.status_code == 201, resp.text
    lowered = resp.json()["response"].lower()
    assert "isn't available" in lowered or "not available" in lowered

    with SessionLocal() as db:
        conversation = db.get(Conversation, conversation_id)
        assert conversation.booking_draft_service_id == service_id, "the service was never actually invalid"
        assert conversation.booking_draft_date is None, "the whole day is closed — must not be silently kept"
        assert conversation.booking_draft_time is None


# --- Phase 33: dynamic available-slot display ----------------------------------


def test_wants_availability_shows_real_slots_instead_of_asking_for_a_time(two_businesses, monkeypatch):
    """The core Phase 33 fix: an under-specified booking ask (service known,
    no time given, LLM reports wants_availability) must show a real,
    freshly-computed slot list instead of asking the customer to guess a
    time — and must never itself write a booking."""
    token_a = two_businesses["token_a"]
    business_id_a = two_businesses["business_id_a"]
    _setup_booking_business(token_a)
    customer_id = _create_customer_with_contact(token_a)
    conversation_id = _create_conversation(business_id_a, customer_id)
    target_date = _next_monday()

    _stub_providers(
        monkeypatch,
        _partial_booking_reply(service="Cleaning", date=target_date.isoformat(), wants_availability=True),
    )
    resp = client.post(
        f"/api/v1/conversations/{conversation_id}/messages",
        headers=_auth_header(token_a),
        json={"content": "What times do you have for a cleaning on Monday?"},
    )
    assert resp.status_code == 201, resp.text
    body = resp.json()["response"]
    assert "9:00 AM" in body, body  # first real open slot -- business opens 9am, nothing else booked
    assert "Cleaning" in body
    assert "what date" not in body.lower() and "what time" not in body.lower()

    with SessionLocal() as db:
        assert db.query(Appointment).filter(Appointment.business_id == business_id_a).count() == 0, (
            "proposing real options must never itself write a booking"
        )


def test_wants_availability_without_a_known_service_asks_for_service_first(two_businesses, monkeypatch):
    """Never show a slot list for an ambiguous "what's available" with no
    service context — ask for the service first, reusing the exact same
    missing-slot mechanism as any other incomplete draft."""
    token_a = two_businesses["token_a"]
    business_id_a = two_businesses["business_id_a"]
    _setup_booking_business(token_a)
    customer_id = _create_customer_with_contact(token_a)
    conversation_id = _create_conversation(business_id_a, customer_id)

    _stub_providers(monkeypatch, _partial_booking_reply(wants_availability=True))
    resp = client.post(
        f"/api/v1/conversations/{conversation_id}/messages",
        headers=_auth_header(token_a),
        json={"content": "What times do you have available?"},
    )
    assert resp.status_code == 201, resp.text
    body = resp.json()["response"].lower()
    assert "which service" in body

    with SessionLocal() as db:
        assert db.query(Appointment).filter(Appointment.business_id == business_id_a).count() == 0


def test_wants_availability_on_a_closed_day_offers_the_next_real_opening(two_businesses, monkeypatch):
    """Edge case required by the ticket: a fully closed/booked day must never
    be answered with a silent empty list or an invented slot — an honest
    statement plus the next REAL available day."""
    token_a = two_businesses["token_a"]
    business_id_a = two_businesses["business_id_a"]
    _setup_booking_business(token_a)  # Sunday (day_of_week 6) is closed
    customer_id = _create_customer_with_contact(token_a)
    conversation_id = _create_conversation(business_id_a, customer_id)

    today = date.today()
    days_ahead = (6 - today.weekday()) % 7 or 7
    closed_sunday = today + timedelta(days=days_ahead)

    _stub_providers(
        monkeypatch,
        _partial_booking_reply(service="Cleaning", date=closed_sunday.isoformat(), wants_availability=True),
    )
    resp = client.post(
        f"/api/v1/conversations/{conversation_id}/messages",
        headers=_auth_header(token_a),
        json={"content": "Do you have anything open this Sunday for a cleaning?"},
    )
    assert resp.status_code == 201, resp.text
    body = resp.json()["response"].lower()
    assert "nothing open" in body
    assert "next real opening" in body
    assert "sunday" in body  # honestly names the requested (closed) day
    assert "monday" in body  # the real next open day's slots are offered instead

    with SessionLocal() as db:
        assert db.query(Appointment).filter(Appointment.business_id == business_id_a).count() == 0


def test_wants_availability_then_picking_a_shown_slot_books_correctly(two_businesses, monkeypatch):
    """Acceptance criterion: a customer who picks one of the proposed options
    must flow into the exact same booking-completion logic as any other
    explicitly-given date/time (Phase 25a) — not a parallel mechanism."""
    token_a = two_businesses["token_a"]
    business_id_a = two_businesses["business_id_a"]
    service_id = _setup_booking_business(token_a)
    customer_id = _create_customer_with_contact(token_a)
    conversation_id = _create_conversation(business_id_a, customer_id)
    target_date = _next_monday()

    _stub_providers(
        monkeypatch,
        _partial_booking_reply(service="Cleaning", date=target_date.isoformat(), wants_availability=True),
    )
    resp = client.post(
        f"/api/v1/conversations/{conversation_id}/messages",
        headers=_auth_header(token_a),
        json={"content": "What times do you have Monday for a cleaning?"},
    )
    assert resp.status_code == 201, resp.text
    assert "9:00 AM" in resp.json()["response"]

    _stub_providers(
        monkeypatch, _booking_reply("Cleaning", target_date.isoformat(), "09:00", response="Great choice!")
    )
    resp = client.post(
        f"/api/v1/conversations/{conversation_id}/messages",
        headers=_auth_header(token_a),
        json={"content": "9am works for me."},
    )
    assert resp.status_code == 201, resp.text
    body = resp.json()
    assert "9:00 AM" in body["response"]

    with SessionLocal() as db:
        appointments = db.query(Appointment).filter(Appointment.business_id == business_id_a).all()
        assert len(appointments) == 1
        assert appointments[0].service_id == service_id
        assert appointments[0].scheduled_at.hour == 9
        assert str(appointments[0].id) in body["response"]


def test_wants_availability_never_overrides_an_already_complete_draft(two_businesses, monkeypatch):
    """Defensive/regression: if a specific date+time is fully given, booking
    must fire immediately regardless of wants_availability — this phase only
    ever proposes slots when a time is genuinely missing, never instead of an
    already-resolvable booking attempt."""
    token_a = two_businesses["token_a"]
    business_id_a = two_businesses["business_id_a"]
    service_id = _setup_booking_business(token_a)
    customer_id = _create_customer_with_contact(token_a)
    conversation_id = _create_conversation(business_id_a, customer_id)
    target_date = _next_monday()

    reply = json.dumps(
        {
            "intent": "booking",
            "response": "Let me check.",
            "booking_request": {
                "service": "Cleaning", "date": target_date.isoformat(), "time": "09:00",
                "wants_availability": True,
            },
        }
    )
    _stub_providers(monkeypatch, reply)
    resp = client.post(
        f"/api/v1/conversations/{conversation_id}/messages",
        headers=_auth_header(token_a),
        json={"content": "Book me a cleaning Monday at 9am, and also, what other times are open?"},
    )
    assert resp.status_code == 201, resp.text
    assert "you're all set" in resp.json()["response"].lower()

    with SessionLocal() as db:
        appointments = db.query(Appointment).filter(Appointment.business_id == business_id_a).all()
        assert len(appointments) == 1
        assert appointments[0].service_id == service_id


def test_wants_availability_absent_in_older_stubbed_reply_keeps_old_missing_slots_behavior(two_businesses, monkeypatch):
    """Backward-compatibility guard: a booking_request that predates this
    field (no `wants_availability` key at all) must parse as False and fall
    back to exactly the pre-Phase-33 "ask what's missing" behavior — this is
    what keeps every Phase 25a/25a-2 fixture (written before this field
    existed) passing unmodified."""
    token_a = two_businesses["token_a"]
    business_id_a = two_businesses["business_id_a"]
    _setup_booking_business(token_a)
    customer_id = _create_customer_with_contact(token_a)
    conversation_id = _create_conversation(business_id_a, customer_id)

    reply = json.dumps(
        {"intent": "booking", "response": "Sure.", "booking_request": {"service": "Cleaning"}}
    )
    _stub_providers(monkeypatch, reply)
    resp = client.post(
        f"/api/v1/conversations/{conversation_id}/messages",
        headers=_auth_header(token_a),
        json={"content": "I want a cleaning."},
    )
    assert resp.status_code == 201, resp.text
    body = resp.json()["response"].lower()
    assert "what date" in body and "what time" in body
