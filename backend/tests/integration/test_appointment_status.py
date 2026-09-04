"""Phase 14 — appointment status (app/services/conversation/appointment_tools.py's
AppointmentStatusTool, orchestrator.py's _format_appointment_status_result).

Stubbed ChatProvider/EmbeddingProvider throughout, same discipline as
test_conversation.py — this file proves the deterministic tool/formatter
mechanism (real DB, real appointment rows) fast and for free. The real,
unstubbed end-to-end proof (an actual LLM classifying "when is my
appointment?" as appointment_status, including the staleness scenario against
a genuinely LLM-generated summary) is run manually against the live server and
pasted into PHASE_STATUS.md, same pattern as every prior phase's real-API
acceptance section.
"""

import json
import uuid
from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

import pytest
from fastapi.testclient import TestClient

from app.db.database import SessionLocal
from app.db.models.appointment import AppointmentStatus
from app.db.models.business import Business
from app.db.models.conversation import Conversation
from app.main import app
from app.services import booking_service
from app.services.conversation.appointment_tools import AppointmentStatusTool

client = TestClient(app)


def _unique_email(label: str) -> str:
    return f"{label}-{uuid.uuid4().hex[:10]}@example.com"


def _auth_header(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


def _next_weekday(target_weekday: int) -> date:
    today = date.today()
    days_ahead = (target_weekday - today.weekday()) % 7
    days_ahead = days_ahead or 7
    return today + timedelta(days=days_ahead)


class _StubChatProvider:
    def __init__(self, reply: str):
        self.reply = reply

    def chat(self, messages: list[dict[str, str]]) -> str:
        return self.reply


class _StubEmbeddingProvider:
    def embed(self, texts: list[str]) -> list[list[float]]:
        return [[0.01] * 1536 for _ in texts]


def _stub_providers(monkeypatch, reply: str):
    import app.services.conversation.intent as intent_module
    import app.services.conversation.orchestrator as orchestrator_module

    chat_stub = _StubChatProvider(reply)
    monkeypatch.setattr(intent_module, "get_chat_provider", lambda: chat_stub)
    monkeypatch.setattr(orchestrator_module, "get_embedding_provider", lambda: _StubEmbeddingProvider())
    return chat_stub


def _status_reply(response: str = "Let me check that for you.") -> str:
    return json.dumps({"intent": "appointment_status", "response": response})


@pytest.fixture
def two_businesses():
    email_a = _unique_email("status-a-owner")
    email_b = _unique_email("status-b-owner")
    resp_a = client.post(
        "/api/v1/auth/register",
        json={"business_name": "Status A", "timezone": "UTC", "email": email_a, "password": "correcthorse1"},
    )
    resp_b = client.post(
        "/api/v1/auth/register",
        json={"business_name": "Status B", "timezone": "UTC", "email": email_b, "password": "correcthorse1"},
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


def _setup_booking_business(token: str) -> uuid.UUID:
    days = [{"day_of_week": d, "open_time": "09:00:00", "close_time": "17:00:00"} for d in range(6)]
    days.append({"day_of_week": 6, "closed": True})
    assert client.put("/api/v1/business/hours", json={"days": days}, headers=_auth_header(token)).status_code == 200
    resp = client.post(
        "/api/v1/services", json={"name": "Cleaning", "price": "50.00", "duration_minutes": 30}, headers=_auth_header(token)
    )
    assert resp.status_code == 201, resp.text
    return uuid.UUID(resp.json()["id"])


def _create_customer(token: str, name: str = "Jordan Lee") -> uuid.UUID:
    resp = client.post("/api/v1/customers", json={"name": name}, headers=_auth_header(token))
    assert resp.status_code == 201, resp.text
    return uuid.UUID(resp.json()["id"])


def _create_conversation(business_id: uuid.UUID, customer_id: uuid.UUID) -> uuid.UUID:
    with SessionLocal() as db:
        conversation = Conversation(business_id=business_id, customer_id=customer_id, channel="sms", status="open")
        db.add(conversation)
        db.commit()
        db.refresh(conversation)
        return conversation.id


def test_status_reports_no_appointments_at_all(two_businesses, monkeypatch):
    token_a = two_businesses["token_a"]
    business_id_a = two_businesses["business_id_a"]
    _setup_booking_business(token_a)
    customer_id = _create_customer(token_a)
    conversation_id = _create_conversation(business_id_a, customer_id)

    _stub_providers(monkeypatch, _status_reply())
    resp = client.post(
        f"/api/v1/conversations/{conversation_id}/messages",
        headers=_auth_header(token_a),
        json={"content": "Do I have anything booked?"},
    )
    assert resp.status_code == 201, resp.text
    body = resp.json()
    assert body["intent"] == "appointment_status"
    assert "don't have any appointments" in body["response"].lower()
    assert "Let me check that for you." not in body["response"], "must be overwritten, never the LLM's placeholder"


def test_status_reports_one_active_appointment_matching_real_db_row(two_businesses, monkeypatch):
    token_a = two_businesses["token_a"]
    business_id_a = two_businesses["business_id_a"]
    service_id = _setup_booking_business(token_a)
    customer_id = _create_customer(token_a)
    conversation_id = _create_conversation(business_id_a, customer_id)
    when = datetime.combine(_next_weekday(0), datetime.min.time()).replace(hour=14, tzinfo=ZoneInfo("UTC"))

    with SessionLocal() as db:
        appointment = booking_service.create_appointment(
            db, business_id=business_id_a, customer_id=customer_id, service_id=service_id, staff_id=None, scheduled_at=when
        )
        appointment_id = appointment.id

    _stub_providers(monkeypatch, _status_reply())
    resp = client.post(
        f"/api/v1/conversations/{conversation_id}/messages",
        headers=_auth_header(token_a),
        json={"content": "When is my appointment?"},
    )
    assert resp.status_code == 201, resp.text
    response_text = resp.json()["response"]
    assert str(appointment_id) in response_text
    assert "Cleaning" in response_text
    assert "confirmed" in response_text.lower()

    with SessionLocal() as db:
        row = booking_service.get_appointment(db, business_id=business_id_a, appointment_id=appointment_id)
    assert row.status == AppointmentStatus.CONFIRMED


def test_status_lists_all_multiple_active_appointments(two_businesses, monkeypatch):
    token_a = two_businesses["token_a"]
    business_id_a = two_businesses["business_id_a"]
    service_id = _setup_booking_business(token_a)
    customer_id = _create_customer(token_a)
    conversation_id = _create_conversation(business_id_a, customer_id)
    when1 = datetime.combine(_next_weekday(0), datetime.min.time()).replace(hour=10, tzinfo=ZoneInfo("UTC"))
    when2 = datetime.combine(_next_weekday(1), datetime.min.time()).replace(hour=11, tzinfo=ZoneInfo("UTC"))

    with SessionLocal() as db:
        a1 = booking_service.create_appointment(
            db, business_id=business_id_a, customer_id=customer_id, service_id=service_id, staff_id=None, scheduled_at=when1
        )
        a2 = booking_service.create_appointment(
            db, business_id=business_id_a, customer_id=customer_id, service_id=service_id, staff_id=None, scheduled_at=when2
        )
        id1, id2 = a1.id, a2.id

    _stub_providers(monkeypatch, _status_reply())
    resp = client.post(
        f"/api/v1/conversations/{conversation_id}/messages",
        headers=_auth_header(token_a),
        json={"content": "What appointments do I have coming up?"},
    )
    assert resp.status_code == 201, resp.text
    response_text = resp.json()["response"]
    assert str(id1) in response_text, "first appointment must not be dropped"
    assert str(id2) in response_text, "second appointment must not be dropped"
    assert "2 upcoming appointments" in response_text


def test_status_reflects_real_cancellation_not_stale_confirmed(two_businesses, monkeypatch):
    """The core Phase 14 mechanism check: cancel via a DIFFERENT path than the
    status question itself (direct booking_service call, exactly like a
    cancellation made through another channel), then ask status in the SAME
    conversation with a stale summary already claiming it's confirmed — the
    real DB status must win."""
    token_a = two_businesses["token_a"]
    business_id_a = two_businesses["business_id_a"]
    service_id = _setup_booking_business(token_a)
    customer_id = _create_customer(token_a)
    conversation_id = _create_conversation(business_id_a, customer_id)
    when = datetime.combine(_next_weekday(2), datetime.min.time()).replace(hour=10, tzinfo=ZoneInfo("UTC"))

    with SessionLocal() as db:
        appointment = booking_service.create_appointment(
            db, business_id=business_id_a, customer_id=customer_id, service_id=service_id, staff_id=None, scheduled_at=when
        )
        appointment_id = appointment.id
        # A stale conversation summary claiming the appointment is confirmed —
        # simulates a real Phase 7 summary generated BEFORE the cancellation
        # below. The formatter must never read this at all.
        conversation = db.get(Conversation, conversation_id)
        conversation.summary = (
            f"The customer booked a Cleaning appointment (id {appointment_id}) for "
            f"{when.isoformat()}, confirmed."
        )
        db.commit()

        # Cancelled via a different channel/request than the status question.
        booking_service.cancel_appointment(db, business_id=business_id_a, appointment_id=appointment_id)

    _stub_providers(monkeypatch, _status_reply())
    resp = client.post(
        f"/api/v1/conversations/{conversation_id}/messages",
        headers=_auth_header(token_a),
        json={"content": "What's the status of my appointment?"},
    )
    assert resp.status_code == 201, resp.text
    response_text = resp.json()["response"]
    assert "cancelled" in response_text.lower()
    assert "confirmed" not in response_text.lower(), "must not repeat the stale summary's claim"


def test_status_tool_never_reads_conversation_summary():
    """Even more directly than the end-to-end test above: AppointmentStatusTool
    takes no summary/context argument at all — it is architecturally incapable
    of being influenced by stale summary text, not just prompted not to use it."""
    import inspect

    sig = inspect.signature(AppointmentStatusTool.run)
    assert "context" not in sig.parameters
    assert "summary" not in sig.parameters


def test_status_query_is_cross_tenant_scoped_even_when_id_is_named_in_chat(two_businesses, monkeypatch):
    """Business B's customer mentions Business A's real appointment id directly
    in the chat message text — the tool must never do an id-based lookup at
    all, so this can't leak Business A's data regardless of what's said."""
    token_a = two_businesses["token_a"]
    token_b = two_businesses["token_b"]
    business_id_a = two_businesses["business_id_a"]
    business_id_b = two_businesses["business_id_b"]
    service_id_a = _setup_booking_business(token_a)
    customer_id_a = _create_customer(token_a)
    when = datetime.combine(_next_weekday(3), datetime.min.time()).replace(hour=10, tzinfo=ZoneInfo("UTC"))
    with SessionLocal() as db:
        appointment_a = booking_service.create_appointment(
            db, business_id=business_id_a, customer_id=customer_id_a, service_id=service_id_a, staff_id=None, scheduled_at=when
        )
        appointment_a_id = appointment_a.id

    _setup_booking_business(token_b)
    customer_id_b = _create_customer(token_b, name="Someone Else")
    conversation_id_b = _create_conversation(business_id_b, customer_id_b)

    _stub_providers(monkeypatch, _status_reply())
    resp = client.post(
        f"/api/v1/conversations/{conversation_id_b}/messages",
        headers=_auth_header(token_b),
        json={"content": f"What's the status of appointment {appointment_a_id}?"},
    )
    assert resp.status_code == 201, resp.text
    response_text = resp.json()["response"]
    assert str(appointment_a_id) not in response_text
    assert "don't have any appointments" in response_text.lower()
