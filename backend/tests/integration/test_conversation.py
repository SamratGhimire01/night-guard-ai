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


def _create_customer(token: str) -> uuid.UUID:
    resp = client.post(
        "/api/v1/customers", headers=_auth_header(token), json={"name": "Test Customer"}
    )
    assert resp.status_code == 201, resp.text
    return uuid.UUID(resp.json()["id"])


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


def test_tool_registry_has_booking_cancellation_and_rescheduling():
    """Phase 10 registered a real tool for BOOKING; Phase 11 adds real tools for
    CANCELLATION and RESCHEDULING the same way. No other intent has a tool, so
    the orchestrator's honesty guardrail (Phase 8/9) stays meaningful for those."""
    assert set(TOOL_REGISTRY) == {
        ConversationIntent.BOOKING,
        ConversationIntent.CANCELLATION,
        ConversationIntent.RESCHEDULING,
    }
    for intent in (ConversationIntent.BOOKING, ConversationIntent.CANCELLATION, ConversationIntent.RESCHEDULING):
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
    customer_id = _create_customer(token_a)
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
    customer_id = _create_customer(token_a)
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
    customer_id = _create_customer(token_a)
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
    customer_id = _create_customer(token_a)
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
    customer_id = _create_customer(token_a)
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
    customer_id = _create_customer(token_a)
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
    customer_id = _create_customer(token_a)
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
    assert result.booking_request == {"service": "Cleaning", "date": "2026-09-10", "time": "14:00"}


def test_parse_response_ignores_malformed_booking_request():
    raw = '{"intent": "booking", "response": "hi", "booking_request": {"service": "Cleaning"}}'
    assert _parse_response(raw).booking_request is None


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
