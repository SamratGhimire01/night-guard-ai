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
from datetime import date, datetime, time, timedelta
from zoneinfo import ZoneInfo

import pytest
from fastapi.testclient import TestClient

from app.db.database import SessionLocal
from app.db.models.appointment import Appointment, AppointmentStatus
from app.db.models.business import Business, BusinessHours
from app.db.models.conversation import Conversation
from app.db.models.customer import Customer
from app.db.models.notification import NotificationStatus
from app.db.models.service import Service
from app.main import app
from app.schemas.conversation import ConversationIntent
from app.services import booking_service, service_service
from app.services.conversation.intent import _format_hours, _parse_response
from app.services.conversation.response_templates import render
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


def test_tool_registry_has_booking_cancellation_rescheduling_status_and_resend():
    """Phase 10 registered a real tool for BOOKING; Phase 11 adds real tools for
    CANCELLATION and RESCHEDULING; Phase 14 adds APPOINTMENT_STATUS; the
    Gmail/WhatsApp resend phase adds RESEND_CONFIRMATION, all the same way.
    No other intent has a tool, so the orchestrator's honesty guardrail
    (Phase 8/9) stays meaningful for those."""
    assert set(TOOL_REGISTRY) == {
        ConversationIntent.BOOKING,
        ConversationIntent.CANCELLATION,
        ConversationIntent.RESCHEDULING,
        ConversationIntent.APPOINTMENT_STATUS,
        ConversationIntent.RESEND_CONFIRMATION,
    }
    for intent in (
        ConversationIntent.BOOKING,
        ConversationIntent.CANCELLATION,
        ConversationIntent.RESCHEDULING,
        ConversationIntent.APPOINTMENT_STATUS,
        ConversationIntent.RESEND_CONFIRMATION,
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
    assert real_appointment.confirmation_code in body["response"], "the response must quote the REAL booking ID from the DB"
    assert real_appointment.service_id == service_id
    assert real_appointment.scheduled_at.hour == 14


def test_booking_confirmation_omits_the_checkin_qr_line_when_backend_url_is_refused(two_businesses, monkeypatch):
    """Dev-tunnel/production-URL safety net (see app.core.public_url): the booking
    itself must still succeed even when the check-in QR link can't be safely built --
    and the reply must never literally contain the word "None" where the link would
    have gone (a real risk of naively formatting a refused/None URL into the template)."""
    from app.core.config import settings

    token_a = two_businesses["token_a"]
    business_id_a = two_businesses["business_id_a"]
    service_id = _setup_booking_business(token_a)
    customer_id = _create_customer_with_contact(token_a)
    conversation_id = _create_conversation(business_id_a, customer_id)
    target_date = _next_monday()

    monkeypatch.setattr(settings, "environment", "production")
    monkeypatch.setattr(settings, "backend_base_url", "https://unfiltrated-sharla-futile.ngrok-free.dev")
    _stub_providers(monkeypatch, _booking_reply("Cleaning", target_date.isoformat(), "14:00"))

    resp = client.post(
        f"/api/v1/conversations/{conversation_id}/messages",
        headers=_auth_header(token_a),
        json={"content": "Can I get a cleaning next Monday at 2pm?"},
    )
    assert resp.status_code == 201, resp.text
    body = resp.json()
    assert "None" not in body["response"]
    assert "/qr/" not in body["response"]

    with SessionLocal() as db:
        from app.db.models.appointment import Appointment

        appointments = list(db.query(Appointment).filter(Appointment.business_id == business_id_a).all())
    assert len(appointments) == 1, "the booking itself must still succeed"


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
    assert body["response"].startswith(render("requested_time_unavailable", "en"))

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
    assert appointment.confirmation_code in body["response"], "the response must quote the REAL booking ID from the DB"


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


# --- real resend-confirmation tool wiring (Gmail/WhatsApp QR resend, rate-limited) ---


def _resend_reply(appointment_id: str | None, channel: str | None = None, response: str = "Sure, one moment.") -> str:
    return json.dumps(
        {
            "intent": "resend_confirmation",
            "response": response,
            "resend_request": {"appointment_id": appointment_id, "channel": channel} if appointment_id else None,
        }
    )


def test_resend_confirmation_wiring_reports_real_result_not_llm_text(two_businesses, monkeypatch):
    """Same rule-13 discipline as every other tool: the orchestrator must call
    the real tool and build its response from the REAL result, never the
    LLM's own drafted claim that something was sent."""
    token_a = two_businesses["token_a"]
    business_id_a = two_businesses["business_id_a"]
    service_id = _setup_booking_business(token_a)
    customer_id = _create_customer(token_a)  # no email/phone on file
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

    _stub_providers(
        monkeypatch, _resend_reply(str(appointment_id), channel="email", response="Sending that now!")
    )

    resp = client.post(
        f"/api/v1/conversations/{conversation_id}/messages",
        headers=_auth_header(token_a),
        json={"content": "Can you resend my confirmation email?"},
    )
    assert resp.status_code == 201, resp.text
    lowered = resp.json()["response"].lower()
    assert "sending that now" not in lowered, "the LLM's own drafted completion claim must never survive"
    assert "email" in lowered  # honest report: no email on file for this customer

    with SessionLocal() as db:
        row = db.get(Appointment, appointment_id)
    assert row.confirmation_resend_count == 1, "a real, attempted request must still consume the abuse-guard cap"


def test_resend_confirmation_refuses_for_cancelled_appointment(two_businesses):
    """There's nothing to resend for an appointment that's no longer real —
    same 'never book/act on a dead appointment' discipline as the
    cancellation/reschedule hallucination-proof tests, and must never consume
    the real rate-limit cap for a request that never actually sent anything."""
    from app.services.conversation.appointment_tools import ResendConfirmationTool

    token_a = two_businesses["token_a"]
    business_id_a = two_businesses["business_id_a"]
    service_id = _setup_booking_business(token_a)
    customer_id = _create_customer(token_a)
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

    with SessionLocal() as db:
        result = ResendConfirmationTool().run(
            db,
            business_id=business_id_a,
            customer_id=customer_id,
            appointment_id=appointment_id,
            channel="email",
            conversation_channel="widget",
        )
    assert result["success"] is False
    assert result["rate_limited"] is False
    assert "cancelled" in result["message"].lower()

    with SessionLocal() as db:
        row = db.get(Appointment, appointment_id)
    assert row.confirmation_resend_count == 0, "a refused resend must never consume the real abuse-guard cap"


def test_resend_confirmation_atomic_cap_enforced_after_three_attempts(two_businesses):
    """Same 'the guarantee lives in one SQL statement's WHERE clause' claim
    discipline as reminder_sent_at/checked_in_at (app/db/models/appointment.py):
    a 4th real attempt must be refused, and the real counter must never
    exceed 3 no matter how many times this is called."""
    from app.services.conversation.appointment_tools import ResendConfirmationTool

    token_a = two_businesses["token_a"]
    business_id_a = two_businesses["business_id_a"]
    service_id = _setup_booking_business(token_a)
    customer_id = _create_customer(token_a)  # no email/phone -> fast, no real network call
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

    rate_limited_flags = []
    for _ in range(4):
        with SessionLocal() as db:
            result = ResendConfirmationTool().run(
                db,
                business_id=business_id_a,
                customer_id=customer_id,
                appointment_id=appointment_id,
                channel="email",
                conversation_channel="widget",
            )
        rate_limited_flags.append(result["rate_limited"])

    assert rate_limited_flags == [False, False, False, True], "only the 4th real attempt should be rate-limited"

    with SessionLocal() as db:
        row = db.get(Appointment, appointment_id)
    assert row.confirmation_resend_count == 3, "the real counter must never exceed the cap"


def test_resend_whatsapp_channel_now_answers_with_a_qr_link_and_never_calls_the_meta_media_api(two_businesses, monkeypatch):
    """Phase 14: "QR in chat" is a plain link to the QR page (signed, expiring), NOT the Meta Media API image-upload
    flow. An explicit "whatsapp" channel therefore means "answer here in the chat"; nothing is uploaded or pushed to
    any destination, and the tool must never even touch the adapter's image sender."""
    import app.services.channels.whatsapp as whatsapp_module
    from app.services import qr_link_service
    from app.services.conversation.appointment_tools import ResendConfirmationTool

    token_a, business_id_a = two_businesses["token_a"], two_businesses["business_id_a"]
    service_id = _setup_booking_business(token_a)
    customer_id = _create_customer(token_a, phone="9800000000")
    appointment_id = _book_appointment(business_id_a, customer_id, service_id)

    def _must_not_be_called(self, **kwargs):
        raise AssertionError("the Meta Media API image upload must no longer be used for a resend")

    monkeypatch.setattr(whatsapp_module.WhatsAppChannelAdapter, "send_image_message", _must_not_be_called)
    monkeypatch.setattr(whatsapp_module.WhatsAppChannelAdapter, "send_message", _must_not_be_called)

    with SessionLocal() as db:
        result = ResendConfirmationTool().run(
            db, business_id=business_id_a, customer_id=customer_id, appointment_id=appointment_id,
            channel="whatsapp", conversation_channel="widget",
        )
    assert set(result["channels"]) == {"chat"}
    chat = result["channels"]["chat"]
    assert chat["status"] == "sent" and "/qr/" in chat["url"]
    assert qr_link_service.verify_token(chat["url"].rsplit("/qr/", 1)[1]) == appointment_id


def test_resend_chat_link_refused_in_production_with_a_dev_tunnel_url_reports_failed_not_a_dead_link(
    two_businesses, monkeypatch
):
    """Dev-tunnel/production-URL safety net (see app.core.public_url): a resend must
    never hand the customer a link built from a refused backend_base_url -- the chat
    channel reports "failed" (the same real status _resend_needs_front_desk already
    watches for) rather than "sent" with a link nobody can actually reach."""
    from app.core.config import settings
    from app.services.conversation.appointment_tools import ResendConfirmationTool

    token_a, business_id_a = two_businesses["token_a"], two_businesses["business_id_a"]
    service_id = _setup_booking_business(token_a)
    customer_id = _create_customer(token_a, phone="9800000001")
    appointment_id = _book_appointment(business_id_a, customer_id, service_id)

    monkeypatch.setattr(settings, "environment", "production")
    monkeypatch.setattr(settings, "backend_base_url", "https://unfiltrated-sharla-futile.ngrok-free.dev")

    with SessionLocal() as db:
        result = ResendConfirmationTool().run(
            db, business_id=business_id_a, customer_id=customer_id, appointment_id=appointment_id,
            channel="whatsapp", conversation_channel="widget",
        )
    chat = result["channels"]["chat"]
    assert chat["status"] == "failed"
    assert chat["url"] is None


def test_resend_confirmation_resolve_channels():
    """Pure channel-resolution logic, no I/O. "email" = the on-file email; "chat" = the QR link in this conversation.
    "both" = both; the LLM's "whatsapp" (or nothing, on a chat channel) means "answer here"; email is the default only
    where there's no chat to answer in."""
    from app.services.conversation.appointment_tools import ResendConfirmationTool

    resolve = ResendConfirmationTool._resolve_channels
    assert resolve("both", None) == {"email", "chat"}
    assert resolve("email", "whatsapp") == {"email"}
    assert resolve("whatsapp", None) == {"chat"}
    assert resolve("chat", "widget") == {"chat"}
    for chat_channel in ("whatsapp", "messenger", "instagram", "website"):
        assert resolve(None, chat_channel) == {"chat"}
    assert resolve(None, "sms") == {"email"}
    assert resolve(None, "widget") == {"email"}, "'widget' is not a real conversation channel value; the widget stores 'website'"
    assert resolve(None, None) == {"email"}


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
    assert result.resend_request is None


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


def test_parse_response_extracts_valid_resend_request():
    raw = (
        '{"intent": "resend_confirmation", "response": "Sure.", '
        '"resend_request": {"appointment_id": "abc-123", "channel": "whatsapp"}}'
    )
    result = _parse_response(raw)
    assert result.intent == ConversationIntent.RESEND_CONFIRMATION
    assert result.resend_request == {"appointment_id": "abc-123", "channel": "whatsapp"}


def test_parse_response_resend_request_channel_defaults_to_none_when_omitted():
    raw = '{"intent": "resend_confirmation", "response": "Sure.", "resend_request": {"appointment_id": "abc-123"}}'
    assert _parse_response(raw).resend_request == {"appointment_id": "abc-123", "channel": None}


def test_parse_response_ignores_invalid_resend_channel():
    raw = (
        '{"intent": "resend_confirmation", "response": "Sure.", '
        '"resend_request": {"appointment_id": "abc-123", "channel": "carrier_pigeon"}}'
    )
    assert _parse_response(raw).resend_request == {"appointment_id": "abc-123", "channel": None}


def test_parse_response_null_resend_request_when_ambiguous():
    raw = '{"intent": "resend_confirmation", "response": "Which one?", "resend_request": null}'
    assert _parse_response(raw).resend_request is None


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
    trusted and never guessed at) — see orchestrator._resolve_message_language.

    "Namaste, kasto cha?" now resolves to "ne_roman" regardless of the false
    "ne_deva" claim (was `None` before the urgent fix below added real
    Romanized-Nepali detection — this is a strict improvement, not a
    regression: the message genuinely IS Romanized Nepali, previously
    discarded as "no signal" only because the old code had no way to
    recognize it)."""
    from app.services.conversation.orchestrator import _resolve_message_language

    assert _resolve_message_language("नमस्ते", "en") == "ne_deva"
    assert _resolve_message_language("नमस्ते", None) == "ne_deva"
    assert _resolve_message_language("What are your business hours?", "ne_deva") is None
    assert _resolve_message_language("Namaste, kasto cha?", "ne_deva") == "ne_roman"
    assert _resolve_message_language("What are your business hours?", "en") == "en"
    assert _resolve_message_language("Namaste, kasto cha?", "ne_roman") == "ne_roman"
    assert _resolve_message_language("some text", None) is None


def test_resolve_message_language_ambiguous_greeting_is_no_signal_not_a_lock():
    """Urgent fix (real bug found live, PHASE_STATUS.md): a customer's first
    message being a short, generic greeting ("hlo") must never establish a
    confident language lock — there's too little real signal in it,
    regardless of what the LLM confidently self-reports. A real Nepali/
    Romanized-Nepali greeting ("namaste") is NOT swallowed by this guard —
    that IS real signal, deliberately excluded from the ambiguous set."""
    from app.services.conversation.orchestrator import _resolve_message_language

    assert _resolve_message_language("hlo", "en") is None
    assert _resolve_message_language("hi", "ne_roman") is None
    assert _resolve_message_language("Hey!", "en") is None  # punctuation stripped, still just one token
    assert _resolve_message_language("ok", "en") is None
    assert _resolve_message_language("namaste", "ne_roman") == "ne_roman"  # real signal, not swallowed
    assert _resolve_message_language("hi, cleaning ko price kati ho?", "ne_roman") == "ne_roman"  # real content present


def test_resolve_message_language_roman_nepali_deterministic_override_beats_anchoring():
    """Urgent fix (real bug found live, PHASE_STATUS.md): Phase 25 documented
    the LLM's message_language self-report can anchor to the CURRENT lock
    even when the raw text doesn't back it up, and flagged (but didn't fix)
    the lack of an equivalent deterministic check for en/ne_roman/mixed. This
    proves the new curated-word override actually breaks that anchoring: a
    message containing 2+ real Romanized-Nepali words is forced to
    "ne_roman" even when the LLM keeps (wrongly) self-reporting "en"."""
    from app.services.conversation.orchestrator import _resolve_message_language

    # The anchoring bug itself: LLM says "en" despite substantial real
    # Nepali content, because the conversation is currently locked to "en".
    assert _resolve_message_language("Malai tapaiko cleaning ko price kati ho?", "en") == "ne_roman"
    assert _resolve_message_language("Aaitabar bihana dherai ramro huncha malai", "en") == "ne_roman"
    # A single incidental match must NOT override — needs real, sustained evidence.
    assert _resolve_message_language("Can I get a cha (chai tea) after my appointment?", "en") == "en"
    # Genuine English with zero matches is completely unaffected.
    assert _resolve_message_language("What time do you open on Friday?", "en") == "en"


def test_resolve_message_language_covers_common_spellings_found_in_real_transcripts():
    """Real gap found in the conversation-quality audit (PHASE_STATUS.md): a
    conversation OPENING with one of these common spellings (real examples
    from this project's own live transcripts, e.g. "K xa", "Malai euta tooth
    dukheko xa") got zero deterministic Roman-Nepali signal before this word
    list was extended. Same override-beats-anchoring shape as the test
    above, just proving the newly-added spellings actually work."""
    from app.services.conversation.orchestrator import _resolve_message_language

    assert _resolve_message_language("Malai euta tooth dukheko xa", "en") == "ne_roman"
    assert _resolve_message_language("Bholi aaja ko appointment book gardim", "en") == "ne_roman"
    assert _resolve_message_language("Huss, thik cha la", "en") == "ne_roman"
    # The deliberately-excluded English loanword must still NOT trigger on
    # its own (single incidental match, and "chai" was never added).
    assert _resolve_message_language("Can I get a chai after my appointment?", "en") == "en"


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


def test_hlo_then_genuine_roman_nepali_relocks_within_a_few_messages_not_stuck_in_english():
    """End-to-end reproduction of the exact real bug reported live: a
    customer's first message is a short, ambiguous greeting ("hlo") that
    used to establish a false, confident English lock instantly — and then
    never correctly re-detected Nepali even after several genuine Romanized-
    Nepali messages, because the LLM's own message_language self-report kept
    anchoring to whatever the conversation was already locked to (Phase 25's
    own documented, previously-unmitigated limitation).

    Combines both real fixes: (1) "hlo" is too little signal to lock
    anything (_resolve_message_language's ambiguous-greeting guard), so the
    conversation correctly stays unlocked rather than falsely pinning to
    English; (2) once genuine, substantial Romanized Nepali messages arrive,
    the curated-word deterministic override reports "ne_roman" even if an
    anchored LLM would have kept claiming "en" — reaching the lock within a
    couple of real messages, never "stuck in English indefinitely"."""
    from types import SimpleNamespace

    from app.services.conversation.orchestrator import _resolve_locked_language, _resolve_message_language

    conversation = SimpleNamespace(detected_language=None, language_switch_streak=0)

    # Turn 1: "hlo" — even if an LLM confidently self-reports "en" for this
    # (exactly the real bug), the deterministic guard must drop it to no
    # signal, so nothing locks yet.
    message_language = _resolve_message_language("hlo", "en")
    assert message_language is None
    language = _resolve_locked_language(conversation, message_language)
    assert conversation.detected_language is None, "must NOT have locked to English from a bare greeting"
    assert language is None

    # Turn 2: a real, substantial Romanized-Nepali message. Simulates the
    # worst case of the anchoring bug: the LLM has nothing to anchor to yet
    # (no lock exists), but even if it still mis-self-reported "en" here, the
    # curated-word override must correctly force "ne_roman" from the real
    # content — and this becomes the lock immediately (first clear signal).
    message_language = _resolve_message_language("Malai tapaiko cleaning ko price kati ho?", "en")
    assert message_language == "ne_roman"
    language = _resolve_locked_language(conversation, message_language)
    assert conversation.detected_language == "ne_roman"
    assert language == "ne_roman"

    # Turn 3: another genuine Nepali message — stays locked, streak stays 0,
    # confirming this isn't a fluke single-turn override.
    message_language = _resolve_message_language("Aaitabar bihana dherai ramro huncha malai", "ne_roman")
    language = _resolve_locked_language(conversation, message_language)
    assert conversation.detected_language == "ne_roman"
    assert language == "ne_roman"
    assert conversation.language_switch_streak == 0

    # A single later stray English message must still not flip the new,
    # correctly-established Nepali lock — the passive-drift streak
    # protection (Phase 25) applies here exactly as it always did.
    assert _resolve_locked_language(conversation, "en") == "ne_roman"
    assert conversation.detected_language == "ne_roman"


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


# --- Tone/language phase: post-generation language check + Hindi-leak guard -


def test_contains_hindi_leak_detects_common_tokens_but_not_lookalikes():
    """Regression set for the new Hindi-leak regex: Nepali and Hindi are close
    enough that a model trained mostly on Hindi data sometimes drifts there
    even when correctly told to write Nepali. These specific tokens don't
    collide with real English or Roman-Nepali vocabulary, so a single match
    is enough signal (unlike _ROMAN_NEPALI_WORDS' 2-match bar)."""
    from app.services.conversation.orchestrator import _contains_hindi_leak

    assert _contains_hindi_leak("Aapka appointment kal hai") is True
    assert _contains_hindi_leak("Yeh price ke liye discount nahi hai") is True
    assert _contains_hindi_leak("Kya aap bahut jaldi aa sakte hain?") is True
    # Genuine English and genuine Roman Nepali must never false-positive.
    assert _contains_hindi_leak("Your appointment is tomorrow at 6 PM.") is False
    assert _contains_hindi_leak("Tapaiko appointment bholi 6 baje cha.") is False
    # Adversarial: emoji-only and empty text are simply "no leak found".
    assert _contains_hindi_leak("😊") is False
    assert _contains_hindi_leak("") is False


def test_response_language_mismatch_flags_wrong_script_and_hindi_leak():
    """Regression set for the new post-generation check (tone/language phase)
    — orchestrator._response_language_mismatch decides whether a DRAFTED
    reply needs to be regenerated, using the same deterministic signals as
    _resolve_message_language rather than trusting the model's own claim."""
    from app.schemas.conversation import ConversationLanguage
    from app.services.conversation.orchestrator import _response_language_mismatch

    en = ConversationLanguage.EN.value
    ne_deva = ConversationLanguage.NE_DEVA.value
    ne_roman = ConversationLanguage.NE_ROMAN.value
    mixed = ConversationLanguage.MIXED.value

    # Correct script/language for each lock: no mismatch.
    assert _response_language_mismatch("We're open until 7 PM today.", en) is False
    assert _response_language_mismatch("नमस्ते, आज ७ बजे सम्म खुला छ।", ne_deva) is False
    assert _response_language_mismatch("Aaja 7 baje samma khula cha.", ne_roman) is False
    assert _response_language_mismatch("Sure, that works! Milcha.", mixed) is False

    # Wrong script/language for the lock: real mismatches.
    assert _response_language_mismatch("We're open until 7 PM today.", ne_deva) is True
    assert _response_language_mismatch("नमस्ते, आज खुला छ।", en) is True
    assert _response_language_mismatch("We are open until 7 PM today.", ne_roman) is True

    # A genuine English reply under an English lock must not false-positive just
    # because of one collision-prone word — same 2-match bar as the real detector.
    assert _response_language_mismatch("La la la, sure thing!", en) is False

    # Hindi leak is checked regardless of the target language, including "mixed".
    assert _response_language_mismatch("Aapka appointment kal hai.", en) is True
    assert _response_language_mismatch("Aapka appointment kal hai.", ne_roman) is True
    assert _response_language_mismatch("Aapka appointment kal hai.", mixed) is True

    # Adversarial: an emoji-only reply has no Nepali signal, which is exactly
    # correct under an English lock (not flagged) -- but IS a real mismatch
    # under a Nepali lock (no Nepali content at all is worth one regenerate,
    # same as a literally empty draft would be).
    assert _response_language_mismatch("😊", en) is False
    assert _response_language_mismatch("😊", ne_roman) is True
    assert _response_language_mismatch("", ne_roman) is True


def test_expected_response_language_mirrors_lock_priority_without_mutating():
    """Regression set for the new non-mutating preview used both to seed the
    very first classify_and_respond call (before any lock exists) and by the
    post-generation check — must return exactly what _resolve_locked_language
    WOULD return, without ever touching conversation.detected_language or
    language_switch_streak itself (that real mutation stays exactly where it
    was, after the takeover check further down in process_incoming_message)."""
    from types import SimpleNamespace

    from app.services.conversation.orchestrator import _expected_response_language

    # force_language (a voice turn) always wins, regardless of any lock.
    forced = SimpleNamespace(detected_language="en", language_switch_streak=0)
    assert _expected_response_language(forced, "kehi text", "ne_deva") == "ne_deva"
    assert forced.detected_language == "en", "must never mutate the conversation"

    # An explicit switch request wins over an existing lock, same turn.
    locked = SimpleNamespace(detected_language="ne_roman", language_switch_streak=0)
    assert _expected_response_language(locked, "let's talk in English", None, "en") == "en"
    assert locked.detected_language == "ne_roman", "preview only -- the real lock hasn't moved yet"

    # An existing lock (no switch request) wins over the raw message's own script.
    assert _expected_response_language(locked, "What time do you open?", None, None) == "ne_roman"

    # No lock yet: falls back to deterministic detection of the raw message —
    # pure Devanagari, pure Roman Nepali (2+ curated words), and pure English
    # each resolve correctly with zero LLM signal available yet.
    fresh = SimpleNamespace(detected_language=None, language_switch_streak=0)
    assert _expected_response_language(fresh, "नमस्ते", None) == "ne_deva"
    assert _expected_response_language(fresh, "Malai tapaiko price kati ho?", None) == "ne_roman"
    # Plain English with no LLM report yet (seeding the very first call, before
    # classification exists) is a deliberate "no signal" -- the deterministic
    # engine only ever confidently declares Nepali; English falls back to the
    # LLM's own report, same as _resolve_message_language always has.
    assert _expected_response_language(fresh, "What are your hours?", None) is None
    # Once a classification exists, its message_language self-report fills that gap.
    assert _expected_response_language(
        fresh, "What are your hours?", None, llm_reported_message_language="en"
    ) == "en"
    # Adversarial: an ambiguous/short first message has no signal at all -- None,
    # not a guess, exactly like _resolve_message_language's own ambiguous-greeting guard.
    assert _expected_response_language(fresh, "ok", None) is None
    assert fresh.detected_language is None, "must never mutate on a preview call"


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
        assert appointments[0].confirmation_code in body["response"]

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


def test_bare_digit_reply_to_shown_slots_books_deterministically_without_an_llm_call(two_businesses, monkeypatch):
    """Real, scoped fix for the conversation-quality audit's §50 finding
    ("don't create an LLM call for everything"): once a real slot list has
    been shown (conversation.booking_draft_proposed_slots), a bare-digit
    reply like "2" is real, unambiguous, already-known data — it must
    resolve directly in Python to that exact slot and book it, never
    round-tripping through the LLM to (mis)interpret what "2" means."""
    token_a = two_businesses["token_a"]
    business_id_a = two_businesses["business_id_a"]
    service_id = _setup_booking_business(token_a)
    customer_id = _create_customer_with_contact(token_a)
    conversation_id = _create_conversation(business_id_a, customer_id)

    day_start = datetime.combine(_next_monday(), datetime.min.time(), tzinfo=ZoneInfo("UTC"))
    slot_1 = day_start + timedelta(hours=9)
    slot_2 = day_start + timedelta(hours=9, minutes=15)
    with SessionLocal() as db:
        conversation = db.get(Conversation, conversation_id)
        conversation.booking_draft_service_id = service_id
        conversation.booking_draft_proposed_slots = ",".join([slot_1.isoformat(), slot_2.isoformat()])
        db.commit()

    # A malicious/broken stub reply proves the LLM is never even called —
    # if the deterministic path failed and fell through, this stub's
    # malformed intent would surface as ConversationIntent.UNKNOWN, not
    # "booking", which the assertions below would catch.
    stub = _stub_providers(monkeypatch, json.dumps({"intent": "not_a_real_intent", "response": "unreachable"}))
    resp = client.post(
        f"/api/v1/conversations/{conversation_id}/messages",
        headers=_auth_header(token_a),
        json={"content": "2"},
    )
    assert resp.status_code == 201, resp.text
    assert len(stub.calls) == 0, "a bare-digit slot pick must never call the LLM"
    body = resp.json()
    assert body["intent"] == "booking"

    with SessionLocal() as db:
        from app.db.models.appointment import Appointment

        appointments = db.query(Appointment).filter(Appointment.business_id == business_id_a).all()
        assert len(appointments) == 1, "must book the SECOND shown slot (digit 2), not the first"
        assert appointments[0].service_id == service_id
        assert appointments[0].scheduled_at == slot_2

        conversation = db.get(Conversation, conversation_id)
        assert conversation.booking_draft_proposed_slots is None, "the one-shot hint must be cleared after use"


def test_bare_digit_slot_pick_never_books_without_contact_info(two_businesses, monkeypatch):
    """Real, serious bug found live via the spec-conformance eval
    (PHASE_STATUS.md): the deterministic bare-digit shortcut called
    tool.run() directly with NO has_contact check at all — a customer could
    get a real appointment booked from a bare "2" without ever giving a
    phone number or email, silently bypassing the real Phase 24 business
    requirement. With no contact info on file, a bare-digit pick must NOT
    book — it must render the real contact gate (zero LLM call either way),
    and the picked slot's date/time must be preserved so a follow-up with
    contact info completes the SAME slot, not a re-ask."""
    token_a = two_businesses["token_a"]
    business_id_a = two_businesses["business_id_a"]
    service_id = _setup_booking_business(token_a)
    customer_id = _create_customer(token_a)  # deliberately NO phone, NO email
    conversation_id = _create_conversation(business_id_a, customer_id)

    day_start = datetime.combine(_next_monday(), datetime.min.time(), tzinfo=ZoneInfo("UTC"))
    slot_1 = day_start + timedelta(hours=9)
    slot_2 = day_start + timedelta(hours=9, minutes=15)
    with SessionLocal() as db:
        conversation = db.get(Conversation, conversation_id)
        conversation.booking_draft_service_id = service_id
        conversation.booking_draft_proposed_slots = ",".join([slot_1.isoformat(), slot_2.isoformat()])
        db.commit()

    stub = _stub_providers(monkeypatch, json.dumps({"intent": "not_a_real_intent", "response": "unreachable"}))
    resp = client.post(
        f"/api/v1/conversations/{conversation_id}/messages",
        headers=_auth_header(token_a),
        json={"content": "2"},
    )
    assert resp.status_code == 201, resp.text
    assert len(stub.calls) == 0, "resolving/gating a bare-digit slot pick must never call the LLM"
    body = resp.json()
    assert "phone number or email" in body["response"].lower()

    with SessionLocal() as db:
        from app.db.models.appointment import Appointment

        assert db.query(Appointment).filter(Appointment.business_id == business_id_a).count() == 0, (
            "must NEVER book without real contact info on file"
        )
        conversation = db.get(Conversation, conversation_id)
        assert conversation.booking_draft_date == slot_2.astimezone(ZoneInfo("UTC")).strftime("%Y-%m-%d")
        assert conversation.booking_draft_time == "09:15", "the picked slot's time must survive for a follow-up to complete"

    # A follow-up giving contact info now completes the SAME picked slot.
    reply = json.dumps(
        {
            "intent": "follow_up",
            "response": "Thanks!",
            "booking_request": {"service": None, "date": None, "time": None},
            "contact_info_update": {"name": "Priya", "email": "priya@example.com", "phone": None},
        }
    )
    _stub_providers(monkeypatch, reply)
    resp = client.post(
        f"/api/v1/conversations/{conversation_id}/messages",
        headers=_auth_header(token_a),
        json={"content": "I'm Priya, priya@example.com"},
    )
    assert resp.status_code == 201, resp.text

    with SessionLocal() as db:
        from app.db.models.appointment import Appointment

        appointments = db.query(Appointment).filter(Appointment.business_id == business_id_a).all()
        assert len(appointments) == 1, "the originally-picked slot must be what finally books"
        assert appointments[0].scheduled_at == slot_2


def test_ordinal_word_slot_pick_still_falls_through_to_the_llm_path_unaffected(two_businesses, monkeypatch):
    """Companion to the bare-digit fix above: an ORDINAL WORD reply ("second
    one") must be completely unaffected by the new deterministic path — real
    transcript evidence (PHASE_STATUS.md) shows this already resolves
    correctly through the LLM today, so it must keep going through the LLM,
    not get mis-swept into the bare-digit shortcut."""
    token_a = two_businesses["token_a"]
    business_id_a = two_businesses["business_id_a"]
    service_id = _setup_booking_business(token_a)
    customer_id = _create_customer_with_contact(token_a)
    conversation_id = _create_conversation(business_id_a, customer_id)
    target_date = _next_monday()

    day_start = datetime.combine(target_date, datetime.min.time(), tzinfo=ZoneInfo("UTC"))
    slot_1 = day_start + timedelta(hours=9)
    slot_2 = day_start + timedelta(hours=9, minutes=15)
    with SessionLocal() as db:
        conversation = db.get(Conversation, conversation_id)
        conversation.booking_draft_service_id = service_id
        conversation.booking_draft_proposed_slots = ",".join([slot_1.isoformat(), slot_2.isoformat()])
        db.commit()

    stub = _stub_providers(
        monkeypatch, _partial_booking_reply(date=target_date.isoformat(), time="09:15", response="Sure.")
    )
    resp = client.post(
        f"/api/v1/conversations/{conversation_id}/messages",
        headers=_auth_header(token_a),
        json={"content": "the second one please"},
    )
    assert resp.status_code == 201, resp.text
    assert len(stub.calls) == 1, "an ordinal-word reply is not a bare digit and must still go through the LLM"

    with SessionLocal() as db:
        from app.db.models.appointment import Appointment

        appointments = db.query(Appointment).filter(Appointment.business_id == business_id_a).all()
        assert len(appointments) == 1
        assert appointments[0].scheduled_at == slot_2


def test_genuine_service_switch_is_acknowledged_not_silent(two_businesses, monkeypatch):
    """Real bug found live (PHASE_STATUS.md, "silent service switch"): real
    transcript this session — a customer named Dental Consultation, gave
    contact info for it, then said "cleaning rakhau la" (let's do cleaning
    instead) and the system silently switched with zero acknowledgment
    anywhere. The first mention of a service must NOT be treated as a
    switch (nothing to acknowledge yet); a SECOND, DIFFERENT service named
    later must be."""
    token_a = two_businesses["token_a"]
    business_id_a = two_businesses["business_id_a"]
    _setup_booking_business(token_a)
    resp = client.post(
        "/api/v1/services",
        json={"name": "Consultation", "price": "20.00", "duration_minutes": 15},
        headers=_auth_header(token_a),
    )
    assert resp.status_code == 201, resp.text
    customer_id = _create_customer_with_contact(token_a)
    conversation_id = _create_conversation(business_id_a, customer_id)

    # First mention — nothing to switch FROM yet, no acknowledgment expected.
    _stub_providers(monkeypatch, _partial_booking_reply(service="Consultation", response="Sure."))
    resp = client.post(
        f"/api/v1/conversations/{conversation_id}/messages",
        headers=_auth_header(token_a),
        json={"content": "book a consultation"},
    )
    assert resp.status_code == 201, resp.text
    assert "instead of" not in resp.json()["response"], "a first-time service mention is not a switch"

    # A genuinely DIFFERENT service named next — must be acknowledged.
    _stub_providers(monkeypatch, _partial_booking_reply(service="Cleaning", response="Sure."))
    resp = client.post(
        f"/api/v1/conversations/{conversation_id}/messages",
        headers=_auth_header(token_a),
        json={"content": "actually let's do cleaning instead"},
    )
    assert resp.status_code == 201, resp.text
    body = resp.json()["response"]
    assert "Cleaning instead of Consultation" in body, body

    with SessionLocal() as db:
        conversation = db.get(Conversation, conversation_id)
        services = {s.name: s.id for s in service_service.list_services(db, business_id=business_id_a)}
        assert conversation.booking_draft_service_id == services["Cleaning"], "the draft must hold the NEW service"


def test_repeating_the_same_service_again_is_not_treated_as_a_switch(two_businesses, monkeypatch):
    """A customer restating the SAME service they already gave (e.g.
    confirming it back) must never be misread as a switch — only a genuinely
    DIFFERENT value counts."""
    token_a = two_businesses["token_a"]
    business_id_a = two_businesses["business_id_a"]
    _setup_booking_business(token_a)
    customer_id = _create_customer_with_contact(token_a)
    conversation_id = _create_conversation(business_id_a, customer_id)

    _stub_providers(monkeypatch, _partial_booking_reply(service="Cleaning", response="Sure."))
    resp = client.post(
        f"/api/v1/conversations/{conversation_id}/messages",
        headers=_auth_header(token_a),
        json={"content": "book a cleaning"},
    )
    assert resp.status_code == 201, resp.text

    _stub_providers(monkeypatch, _partial_booking_reply(service="Cleaning", response="Sure."))
    resp = client.post(
        f"/api/v1/conversations/{conversation_id}/messages",
        headers=_auth_header(token_a),
        json={"content": "yes, cleaning"},
    )
    assert resp.status_code == 201, resp.text
    assert "instead of" not in resp.json()["response"]


def test_first_real_date_after_an_availability_search_is_not_a_false_switch(two_businesses, monkeypatch):
    """Real bug caught by re-running the Phase 2 eval set after adding the
    switch acknowledgment: _propose_available_slots writes conversation.
    booking_draft_date directly, as an internal "search from here" default
    when the customer hasn't stated a date yet — that's never a customer
    commitment. Root-caused and properly fixed (not just excluded) by
    giving that internal bookkeeping its own real column,
    booking_draft_search_anchor_date, so booking_draft_date itself is
    written ONLY by _merge_booking_draft from a genuine customer-stated
    value — see that column's own docstring in db/models/conversation.py.
    A customer's FIRST real date, given right after an availability search,
    must NOT be reported as "switching from" that internal anchor."""
    token_a = two_businesses["token_a"]
    business_id_a = two_businesses["business_id_a"]
    _setup_booking_business(token_a)
    customer_id = _create_customer_with_contact(token_a)
    conversation_id = _create_conversation(business_id_a, customer_id)
    target_date = _next_monday()

    # No date given yet -> _propose_available_slots runs and auto-sets
    # booking_draft_search_anchor_date to its own internal search-start
    # default -- booking_draft_date itself must stay untouched by this.
    _stub_providers(monkeypatch, _partial_booking_reply(service="Cleaning", wants_availability=True))
    resp = client.post(
        f"/api/v1/conversations/{conversation_id}/messages",
        headers=_auth_header(token_a),
        json={"content": "what times do you have for a cleaning?"},
    )
    assert resp.status_code == 201, resp.text

    with SessionLocal() as db:
        conversation = db.get(Conversation, conversation_id)
        assert conversation.booking_draft_date is None, "an availability search must never set the real customer date"
        assert conversation.booking_draft_search_anchor_date is not None, "the search anchor itself must be set"

    # The customer's FIRST real date -- must not be reported as a switch.
    _stub_providers(monkeypatch, _partial_booking_reply(date=target_date.isoformat(), response="Sure."))
    resp = client.post(
        f"/api/v1/conversations/{conversation_id}/messages",
        headers=_auth_header(token_a),
        json={"content": "next monday"},
    )
    assert resp.status_code == 201, resp.text
    assert "instead of" not in resp.json()["response"], resp.json()["response"]

    with SessionLocal() as db:
        conversation = db.get(Conversation, conversation_id)
        assert conversation.booking_draft_date == target_date.isoformat(), "the real customer date must now be set"


def test_genuine_date_switch_is_now_acknowledged(two_businesses, monkeypatch):
    """Real root-cause fix, not just the earlier exclusion: once
    booking_draft_date is exclusively customer-stated (see the test above),
    a genuine mid-draft date correction — the customer explicitly stating a
    DIFFERENT date than one they already explicitly stated — is safe to
    acknowledge again, the same way service/time switches already are."""
    token_a = two_businesses["token_a"]
    business_id_a = two_businesses["business_id_a"]
    _setup_booking_business(token_a)
    customer_id = _create_customer_with_contact(token_a)
    conversation_id = _create_conversation(business_id_a, customer_id)
    monday = _next_monday()
    tuesday = monday + timedelta(days=1)

    _stub_providers(monkeypatch, _partial_booking_reply(date=monday.isoformat(), time="14:00", response="Sure."))
    resp = client.post(
        f"/api/v1/conversations/{conversation_id}/messages",
        headers=_auth_header(token_a),
        json={"content": "book me next monday at 2pm"},  # names no service: this test wants a draft the stub leaves service-less
    )
    assert resp.status_code == 201, resp.text

    _stub_providers(monkeypatch, _partial_booking_reply(date=tuesday.isoformat(), response="Sure."))
    resp = client.post(
        f"/api/v1/conversations/{conversation_id}/messages",
        headers=_auth_header(token_a),
        json={"content": "wait, make it tuesday instead"},
    )
    assert resp.status_code == 201, resp.text
    body = resp.json()["response"]
    assert "instead of" in body, body

    with SessionLocal() as db:
        conversation = db.get(Conversation, conversation_id)
        assert conversation.booking_draft_date == tuesday.isoformat()


# --- Phase 13 (2026-09-19 series): picking a SYSTEM-OFFERED alternative is not a customer "switch" --------


def _closed_sunday_and_monday() -> tuple[date, date]:
    """The business from _setup_booking_business is closed Sundays; returns the next Sunday and the Monday after it."""
    today = date.today()
    sunday = today + timedelta(days=(6 - today.weekday()) % 7 or 7)
    return sunday, sunday + timedelta(days=1)


def _customer_asks_for_closed_sunday_and_system_offers_monday(token_a, business_id_a, monkeypatch):
    """The exact real conversation: "bholi" (a closed Sunday) -> the SYSTEM says nothing is open that day and offers
    Monday's real slots. Returns (conversation_id, sunday, monday). Customer deliberately has NO contact info, like the
    real reproduction (so the next turn renders the contact gate, which is where the switch addendum was appended)."""
    _setup_booking_business(token_a)
    customer_id = _create_customer(token_a)
    conversation_id = _create_conversation(business_id_a, customer_id)
    sunday, monday = _closed_sunday_and_monday()
    _stub_providers(monkeypatch, _partial_booking_reply(service="Cleaning", date=sunday.isoformat(), wants_availability=True))
    resp = client.post(
        f"/api/v1/conversations/{conversation_id}/messages",
        headers=_auth_header(token_a),
        json={"content": "book a cleaning tomorrow"},
    )
    assert resp.status_code == 201, resp.text
    body = resp.json()["response"]
    assert "9:00 AM" in body and _format_date_for_test(monday) in body, f"system must offer Monday's slots: {body}"
    with SessionLocal() as db:
        conversation = db.get(Conversation, conversation_id)
        assert conversation.booking_draft_date == sunday.isoformat(), "the customer's own stated date"
        assert conversation.booking_draft_proposed_slots, "the offered list must be persisted for the next turn"
    return conversation_id, sunday, monday


def _format_date_for_test(d: date) -> str:
    return d.strftime("%A, %B ") + str(d.day)


def test_picking_the_systems_offered_alternative_day_is_not_reported_as_a_switch(two_businesses, monkeypatch):
    """Real bug caught live: the customer asked for a closed Sunday, the SYSTEM offered Monday's slots, the customer
    picked "first one" — and the reply appended "Sunday, ... instead of Monday, ..." (Phase 5's switch acknowledgment),
    restating a change the customer never initiated. The new date came from the system's own offered list."""
    token_a, business_id_a = two_businesses["token_a"], two_businesses["business_id_a"]
    conversation_id, sunday, monday = _customer_asks_for_closed_sunday_and_system_offers_monday(token_a, business_id_a, monkeypatch)

    _stub_providers(monkeypatch, _partial_booking_reply(date=monday.isoformat(), time="09:00", response="Sure."))
    resp = client.post(
        f"/api/v1/conversations/{conversation_id}/messages", headers=_auth_header(token_a), json={"content": "first one"}
    )
    assert resp.status_code == 201, resp.text
    body = resp.json()["response"]
    assert "instead of" not in body, f"redundant switch acknowledgment: {body}"
    assert _format_date_for_test(monday) in body and _format_date_for_test(sunday) not in body, body
    with SessionLocal() as db:
        conversation = db.get(Conversation, conversation_id)
        assert conversation.booking_draft_date == monday.isoformat()
        assert conversation.booking_draft_time == "09:00"


def test_picking_an_offered_slot_by_time_only_resolves_to_the_offered_day_not_the_closed_one(two_businesses, monkeypatch):
    """Second real shape seen live: the LLM extracted only the picked slot's TIME ("first one" -> 09:00, date null).
    The draft still held the customer's stated CLOSED Sunday, so the reply confirmed "Sunday ... 9:00 AM" — a day the
    system itself had just said has no availability. A pick from the offered list must resolve to that slot's day."""
    token_a, business_id_a = two_businesses["token_a"], two_businesses["business_id_a"]
    conversation_id, sunday, monday = _customer_asks_for_closed_sunday_and_system_offers_monday(token_a, business_id_a, monkeypatch)

    _stub_providers(monkeypatch, _partial_booking_reply(time="09:00", response="Sure."))
    resp = client.post(
        f"/api/v1/conversations/{conversation_id}/messages", headers=_auth_header(token_a), json={"content": "first one"}
    )
    assert resp.status_code == 201, resp.text
    body = resp.json()["response"]
    assert "instead of" not in body, body
    assert _format_date_for_test(monday) in body and _format_date_for_test(sunday) not in body, body
    with SessionLocal() as db:
        conversation = db.get(Conversation, conversation_id)
        assert conversation.booking_draft_date == monday.isoformat(), "must not stay on the closed day"


def test_customer_stating_a_date_the_system_did_not_offer_is_still_acknowledged_as_a_switch(two_businesses, monkeypatch):
    """The original Phase 5 behavior must survive: after the system offered Monday, the customer independently asks for
    Tuesday — a date that is NOT in the offered list — a real, customer-initiated change of the stated date."""
    token_a, business_id_a = two_businesses["token_a"], two_businesses["business_id_a"]
    conversation_id, sunday, monday = _customer_asks_for_closed_sunday_and_system_offers_monday(token_a, business_id_a, monkeypatch)
    tuesday = monday + timedelta(days=1)

    _stub_providers(monkeypatch, _partial_booking_reply(date=tuesday.isoformat(), response="Sure."))
    resp = client.post(
        f"/api/v1/conversations/{conversation_id}/messages", headers=_auth_header(token_a), json={"content": "actually tuesday"}
    )
    assert resp.status_code == 201, resp.text
    assert "instead of" in resp.json()["response"], resp.json()["response"]
    with SessionLocal() as db:
        assert db.get(Conversation, conversation_id).booking_draft_date == tuesday.isoformat()


def test_genuine_switch_away_from_an_offered_and_confirmed_working_date_is_acknowledged(two_businesses, monkeypatch):
    """The literal case from the ticket: Monday is already the working date AND its slot list was just shown; then the
    customer says "actually let's do Tuesday instead". Tuesday is not in the offered list, so this is the customer
    changing their mind — must still be acknowledged (Phase 5)."""
    token_a, business_id_a = two_businesses["token_a"], two_businesses["business_id_a"]
    _setup_booking_business(token_a)
    conversation_id = _create_conversation(business_id_a, _create_customer(token_a))
    monday = _next_monday()
    tuesday = monday + timedelta(days=1)

    _stub_providers(monkeypatch, _partial_booking_reply(service="Cleaning", date=monday.isoformat(), wants_availability=True))
    resp = client.post(
        f"/api/v1/conversations/{conversation_id}/messages", headers=_auth_header(token_a), json={"content": "cleaning on monday, what's open?"}
    )
    assert resp.status_code == 201, resp.text
    assert "9:00 AM" in resp.json()["response"]

    _stub_providers(monkeypatch, _partial_booking_reply(date=tuesday.isoformat(), response="Sure."))
    resp = client.post(
        f"/api/v1/conversations/{conversation_id}/messages", headers=_auth_header(token_a), json={"content": "actually let's do tuesday instead"}
    )
    assert resp.status_code == 201, resp.text
    body = resp.json()["response"]
    assert "instead of" in body, body
    assert _format_date_for_test(monday) in body and _format_date_for_test(tuesday) in body, body


def test_an_offered_list_only_counts_for_the_very_next_turn(two_businesses, monkeypatch):
    """One-shot, like the bare-digit hint: if an unrelated turn happens after the system's offer, a later message stating
    the offered day is the customer's own (later) choice again — no longer "picking from the list just shown"."""
    token_a, business_id_a = two_businesses["token_a"], two_businesses["business_id_a"]
    conversation_id, sunday, monday = _customer_asks_for_closed_sunday_and_system_offers_monday(token_a, business_id_a, monkeypatch)

    _stub_providers(monkeypatch, json.dumps({"intent": "general_question", "response": "We are on Main Street."}))
    resp = client.post(
        f"/api/v1/conversations/{conversation_id}/messages", headers=_auth_header(token_a), json={"content": "where are you located?"}
    )
    assert resp.status_code == 201, resp.text
    with SessionLocal() as db:
        assert not db.get(Conversation, conversation_id).booking_draft_proposed_slots, "cleared by the unrelated turn"

    _stub_providers(monkeypatch, _partial_booking_reply(date=monday.isoformat(), response="Sure."))
    resp = client.post(
        f"/api/v1/conversations/{conversation_id}/messages", headers=_auth_header(token_a), json={"content": "monday then"}
    )
    assert resp.status_code == 201, resp.text
    assert "instead of" in resp.json()["response"], resp.json()["response"]


def _utc(d: date, hour: int, minute: int = 0) -> datetime:
    return datetime.combine(d, time(hour, minute), tzinfo=ZoneInfo("UTC"))


def test_merge_booking_draft_unit_offered_slot_pick_vs_customer_stated_change():
    """Direct unit coverage of the distinction inside orchestrator._merge_booking_draft (no DB, no LLM)."""
    from app.services.conversation.orchestrator import _merge_booking_draft

    utc = ZoneInfo("UTC")
    sunday, monday = _closed_sunday_and_monday()
    tuesday = monday + timedelta(days=1)
    offered = [_utc(monday, 9), _utc(monday, 9, 15), _utc(tuesday, 9)]

    def fresh(date_str=None, time_str=None):
        return Conversation(booking_draft_date=date_str, booking_draft_time=time_str)

    # date + time exactly matching an offered slot: a pick, no switches, draft updated.
    c = fresh(sunday.isoformat())
    assert _merge_booking_draft(c, [], {"date": monday.isoformat(), "time": "09:15"}, offered_slots=offered, tz=utc) == []
    assert (c.booking_draft_date, c.booking_draft_time) == (monday.isoformat(), "09:15")

    # time only, unique in the offered list (09:15 exists on one day): resolves the date from the offered slot.
    c = fresh(sunday.isoformat())
    assert _merge_booking_draft(c, [], {"date": None, "time": "09:15"}, offered_slots=offered, tz=utc) == []
    assert (c.booking_draft_date, c.booking_draft_time) == (monday.isoformat(), "09:15")

    # time only but ambiguous (09:00 is offered on Monday AND Tuesday): must NOT guess a day.
    c = fresh(sunday.isoformat())
    assert _merge_booking_draft(c, [], {"date": None, "time": "09:00"}, offered_slots=offered, tz=utc) == []
    assert c.booking_draft_date == sunday.isoformat(), "ambiguous pick: the date is left alone, never guessed"

    # a date that is NOT one of the offered days: customer-initiated -> still a switch.
    c = fresh(monday.isoformat())
    wednesday = monday + timedelta(days=2)
    sw = _merge_booking_draft(c, [], {"date": wednesday.isoformat(), "time": None}, offered_slots=offered, tz=utc)
    assert len(sw) == 1 and c.booking_draft_date == wednesday.isoformat()

    # date + time where the PAIR was not offered (Monday 14:00): customer-chosen time -> not a pick.
    c = fresh(sunday.isoformat())
    sw = _merge_booking_draft(c, [], {"date": monday.isoformat(), "time": "14:00"}, offered_slots=offered, tz=utc)
    assert len(sw) == 1, "a slot that was never offered is the customer's own choice"

    # nothing offered: exactly the pre-existing behavior.
    c = fresh(sunday.isoformat())
    assert len(_merge_booking_draft(c, [], {"date": monday.isoformat(), "time": None})) == 1


def test_fill_missing_booking_service_unit_offered_service_fallback():
    """Direct unit coverage of orchestrator._fill_missing_booking_service (no DB, no LLM).

    Real bug found live (Samaj Dental Clinic transcript): the ASSISTANT itself proposed
    "Dental Consultation" answering a customer's question, the customer replied with a plain
    affirmative ("hunxa garau garau" -- yes, do it) naming no service of its own, and the draft
    stayed service-less -- the agent re-asked "which service?" as if it had never proposed one."""
    from app.services.conversation.orchestrator import _fill_missing_booking_service

    consultation = Service(id=uuid.uuid4(), name="Dental Consultation", price=500, duration_minutes=20)
    cleaning = Service(id=uuid.uuid4(), name="Teeth Cleaning", price=1500, duration_minutes=30)
    services = [consultation, cleaning]
    empty_request = {"service": None, "date": None, "time": None, "wants_availability": False}

    # The customer's own message names no service, but the conversation's PREVIOUS turn offered
    # one -> filled from the offer, exactly the fix for the confirmed bug.
    filled = _fill_missing_booking_service(services, empty_request, "hunxa garau garau", consultation.id)
    assert filled["service"] == "Dental Consultation"

    # A service the customer DID literally name in this message always wins over the offer.
    filled = _fill_missing_booking_service(services, empty_request, "book me a teeth cleaning", consultation.id)
    assert filled["service"] == "Teeth Cleaning"

    # No offer pending and nothing named in this message -> left untouched.
    filled = _fill_missing_booking_service(services, empty_request, "hunxa garau garau", None)
    assert filled["service"] is None

    # An offered_service_id that no longer resolves to a real, currently-configured service
    # (e.g. deleted since it was offered) is silently ignored, never a crash.
    filled = _fill_missing_booking_service(services, empty_request, "hunxa garau garau", uuid.uuid4())
    assert filled["service"] is None


def test_resolve_contact_update_unit_email_fallback():
    """Direct unit coverage of orchestrator._resolve_contact_update's deterministic email
    fallback (no DB, no LLM).

    Real bug found live (Samaj Dental Clinic transcript): "mero email samratghimire01@gmail.com
    ho yes ma malai conformation ko mail send gardenu na" -- a real email embedded mid-sentence
    in a longer Romanized-Nepali/English message. The LLM's own rule-14 extraction (intent.py)
    missed it entirely (contact_info_update stayed null), and the agent claimed "I don't have
    your email on record" in the SAME turn the customer had just given it."""
    from app.services.conversation.orchestrator import _resolve_contact_update

    customer = Customer(email=None, phone=None, name="Website Visitor")

    # The LLM extracted nothing, but the raw message has a real embedded email -> the
    # deterministic fallback catches it.
    changed = _resolve_contact_update(
        customer, None, "mero email samratghimire01@gmail.com ho yes ma malai conformation ko mail send gardenu na"
    )
    assert changed == {"email": "samratghimire01@gmail.com"}

    # The LLM's own extraction, when present, is never overridden by the fallback.
    changed = _resolve_contact_update(customer, {"email": "explicit@example.com"}, "my email is fallback@example.com")
    assert changed == {"email": "explicit@example.com"}

    # No email anywhere (LLM null, message has none) -> no-op.
    assert _resolve_contact_update(customer, None, "just saying hi") == {}

    # A value already on file, even if restated, is not reported as a change.
    on_file_customer = Customer(email="same@example.com", phone=None, name="Jamie")
    assert _resolve_contact_update(on_file_customer, None, "my email is same@example.com") == {}


def test_service_named_on_a_non_booking_intent_turn_is_not_lost(two_businesses, monkeypatch):
    """Real bug found live (PHASE_STATUS.md, "§2.C confirmation ignored"): a
    customer naming a service while the message was classified as
    `service_question` (not yet `booking`) had that service silently
    discarded — `_merge_booking_draft` used to run only inside the
    `intent == BOOKING` dispatch branch, so a later booking-intent turn that
    only supplied date/time completed with the service still missing and
    re-asked for it, even though the customer had already named it. Exact
    same class of gap Phase 24 already fixed for contact info arriving on a
    non-booking-intent turn — the merge itself must not be gated on this
    turn's classified intent."""
    token_a = two_businesses["token_a"]
    business_id_a = two_businesses["business_id_a"]
    service_id = _setup_booking_business(token_a)
    customer_id = _create_customer_with_contact(token_a)
    conversation_id = _create_conversation(business_id_a, customer_id)
    target_date = _next_monday()

    # Turn 1: the customer only asks ABOUT a service (classified
    # service_question, not booking) but the LLM confidently names which one
    # in booking_request anyway — intent.py rule 9 asks for this regardless
    # of the classified intent, precisely so this information isn't lost.
    _stub_providers(
        monkeypatch,
        json.dumps(
            {
                "intent": "service_question",
                "response": "Cleaning is $50 and takes 30 minutes.",
                "booking_request": {
                    "service": "Cleaning", "date": None, "time": None, "wants_availability": False,
                },
            }
        ),
    )
    resp = client.post(
        f"/api/v1/conversations/{conversation_id}/messages",
        headers=_auth_header(token_a),
        json={"content": "how much is a cleaning?"},
    )
    assert resp.status_code == 201, resp.text
    assert resp.json()["intent"] == "service_question"

    with SessionLocal() as db:
        conversation = db.get(Conversation, conversation_id)
        assert conversation.booking_draft_service_id == service_id, (
            "a service named on a non-booking-intent turn must still reach the persisted draft"
        )

    # Turn 2: a real booking-intent turn gives only date+time — must book
    # immediately using the service from turn 1, never re-ask which service.
    _stub_providers(
        monkeypatch, _partial_booking_reply(date=target_date.isoformat(), time="14:00", response="One moment.")
    )
    resp = client.post(
        f"/api/v1/conversations/{conversation_id}/messages",
        headers=_auth_header(token_a),
        json={"content": "next monday at 2pm"},
    )
    assert resp.status_code == 201, resp.text
    assert "which service" not in resp.json()["response"].lower()

    with SessionLocal() as db:
        from app.db.models.appointment import Appointment

        appointments = db.query(Appointment).filter(Appointment.business_id == business_id_a).all()
        assert len(appointments) == 1, "must book using the service named on the earlier non-booking-intent turn"
        assert appointments[0].service_id == service_id


def test_bare_affirmative_completes_booking_for_a_service_the_assistant_itself_proposed(two_businesses, monkeypatch):
    """Smoke check reproducing the real Samaj Dental Clinic transcript end to end against the real
    orchestrator: the customer asks what a "doctor consultation" is called, the ASSISTANT names one
    specific real service while answering (not yet a booking request), and the customer's next
    message is a plain affirmative naming no service of its own. Before this fix, the draft stayed
    service-less and the agent re-asked "which service?" as if nothing had ever been proposed."""
    token_a = two_businesses["token_a"]
    business_id_a = two_businesses["business_id_a"]
    service_id = _setup_booking_business(token_a)  # "Cleaning" per _setup_booking_business
    customer_id = _create_customer_with_contact(token_a)
    conversation_id = _create_conversation(business_id_a, customer_id)

    # Turn 1: a real service_question -- the assistant answers by naming ONE specific real
    # service, reported via `proposed_service` (intent.py rule 14b), not as a booking_request.
    _stub_providers(
        monkeypatch,
        json.dumps(
            {
                "intent": "service_question",
                "response": "That would normally be our Cleaning service. Want me to book it?",
                "proposed_service": "Cleaning",
            }
        ),
    )
    resp = client.post(
        f"/api/v1/conversations/{conversation_id}/messages",
        headers=_auth_header(token_a),
        json={"content": "what's it called when I just want to talk to someone?"},
    )
    assert resp.status_code == 201, resp.text

    with SessionLocal() as db:
        conversation = db.get(Conversation, conversation_id)
        assert conversation.booking_draft_offered_service_id == service_id
        assert conversation.booking_draft_service_id is None, "not yet accepted -- just offered"

    # Turn 2: a plain affirmative, exactly like the real transcript ("awh hunxa garau garau") --
    # the LLM extracts a bare confirmation with no service of its own, same as intent.py rule 9
    # documents for "yes".
    _stub_providers(
        monkeypatch,
        json.dumps(
            {
                "intent": "booking",
                "response": "Sure thing.",
                "booking_request": {"service": None, "date": None, "time": None, "wants_availability": False},
            }
        ),
    )
    resp = client.post(
        f"/api/v1/conversations/{conversation_id}/messages",
        headers=_auth_header(token_a),
        json={"content": "awh hunxa garau garau"},
    )
    assert resp.status_code == 201, resp.text
    assert "which service" not in resp.json()["response"].lower(), (
        "must not re-ask which service -- the customer just accepted the one the assistant proposed"
    )

    with SessionLocal() as db:
        conversation = db.get(Conversation, conversation_id)
        assert conversation.booking_draft_service_id == service_id, (
            "the offered service must be adopted into the real draft once the customer says yes to it"
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
        assert appointments[0].confirmation_code in body["response"]


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
        assert appointments[0].confirmation_code in body["response"]


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


def test_missing_slots_question_reflects_accumulated_draft_and_changes_every_turn(two_businesses, monkeypatch):
    """Real adversarial testing found the (then-)contact-info gate repeating
    one identical static sentence across many turns while service/date/time
    contradicted and changed underneath it. Real spec-conformance finding
    (PHASE_STATUS.md): the contact-info gate itself now only fires once
    service+date+time are ALL resolved (asking what's missing, or showing
    availability, is read-only and must never be blocked on contact info —
    a brand-new customer asking about a service deserves a real answer
    before being asked how to reach them). This is the direct regression
    test, updated for that real fix: three separate corrections, all before
    contact info is given, each turn's MISSING-SLOTS question must be
    DIFFERENT from the last and must ask for only what's still missing —
    never the same static sentence twice in a row, and the contact gate
    itself must not appear until the draft is actually complete."""
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
    assert "phone number or email" not in body_1.lower(), "asking what's missing must not require contact info"
    assert "what date" in body_1.lower() and "what time" in body_1.lower()

    _stub_providers(monkeypatch, _partial_booking_reply(date=target_date.isoformat(), response="Got it."))
    resp = client.post(
        f"/api/v1/conversations/{conversation_id}/messages",
        headers=_auth_header(token_a),
        json={"content": "Next Monday."},
    )
    body_2 = resp.json()["response"]
    assert body_2 != body_1, "must not repeat the identical sentence once new info was given"
    assert "what time" in body_2.lower()
    assert "what date" not in body_2.lower(), "the date already given must not be asked for again"
    assert "phone number or email" not in body_2.lower()

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
    assert "what time" in body_3.lower()

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
    assert body_4 != body_3, "the draft is now complete -- the contact gate must appear, a real, different sentence"
    assert "3:00 PM" in body_4
    assert "phone number or email" in body_4.lower(), "the draft is complete -- NOW the real commitment point requires contact info"

    with SessionLocal() as db:
        from app.db.models.appointment import Appointment

        assert db.query(Appointment).filter(Appointment.business_id == business_id_a).count() == 0, (
            "no contact info was ever given — nothing should have booked yet"
        )
        conversation = db.get(Conversation, conversation_id)
        assert conversation.booking_draft_time == "15:00"


def test_contact_gate_only_reached_once_draft_is_actually_complete(two_businesses, monkeypatch):
    """Real spec-conformance fix (PHASE_STATUS.md): the contact-info gate
    must never be the customer's first-ever reply just for asking an
    informational question — it's the deterministic missing-slots question
    (booking_clarify) that fires when truly nothing is known yet, never a
    demand for contact info before anything else has even been discussed."""
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
    body = resp.json()["response"]
    assert "phone number or email" not in body.lower()
    assert "which service" in body.lower()


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
    assert resp.json()["response"].startswith(render("requested_time_unavailable", "en"))

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
        assert booked[0].confirmation_code in body["response"]


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
    assert resp.json()["response"].startswith(render("requested_time_unavailable", "en"))

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


def test_wants_availability_shown_even_with_no_contact_info_yet(two_businesses, monkeypatch):
    """Real spec-conformance fix (PHASE_STATUS.md): a brand-new customer with
    NO contact info on file asking "is a cleaning available tomorrow?" must
    get a REAL answer (the actual availability), not a demand for their
    phone number — showing availability is read-only and must never be
    gated on contact info. The contact-info gate itself is still real and
    still enforced, just at the correct point (see the booking-completion
    test below)."""
    token_a = two_businesses["token_a"]
    business_id_a = two_businesses["business_id_a"]
    _setup_booking_business(token_a)
    customer_id = _create_customer(token_a)  # deliberately NO phone, NO email
    conversation_id = _create_conversation(business_id_a, customer_id)
    target_date = _next_monday()

    _stub_providers(
        monkeypatch,
        _partial_booking_reply(service="Cleaning", date=target_date.isoformat(), wants_availability=True),
    )
    resp = client.post(
        f"/api/v1/conversations/{conversation_id}/messages",
        headers=_auth_header(token_a),
        json={"content": "is a cleaning available Monday?"},
    )
    assert resp.status_code == 201, resp.text
    body = resp.json()["response"]
    assert "9:00 AM" in body, body
    assert "phone number or email" not in body.lower(), "showing real availability must never require contact info first"

    with SessionLocal() as db:
        assert db.query(Appointment).filter(Appointment.business_id == business_id_a).count() == 0


def test_contact_gate_fires_only_once_booking_is_actually_ready_to_write(two_businesses, monkeypatch):
    """Companion to the test above: once the draft is FULLY resolved
    (service + date + time all known) and the real booking is about to
    actually be written, contact info IS still required — the fix only
    moved WHEN the gate applies, it didn't remove the real business
    requirement (Phase 24) behind it."""
    token_a = two_businesses["token_a"]
    business_id_a = two_businesses["business_id_a"]
    _setup_booking_business(token_a)
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
        assert db.query(Appointment).filter(Appointment.business_id == business_id_a).count() == 0, (
            "no contact info was ever given — nothing should have booked"
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
        assert appointments[0].confirmation_code in body["response"]


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


# --- Real bug fix: business's real currency, never a hardcoded "$" -------------


def test_available_services_prompt_uses_the_business_real_currency_not_a_hardcoded_dollar(
    two_businesses, monkeypatch
):
    """Real bug found live: `intent._format_services` hardcoded a literal "$"
    in the "Available services" list injected into the LLM's prompt every
    turn, regardless of what currency the business actually prices in — a
    Nepali business's real NPR prices were silently presented to the model as
    dollars. `Business.currency` (new field) is now threaded through
    `classify_and_respond` -> `_build_user_prompt` -> `_format_services`, so
    the real prompt reflects the business's own real currency."""
    token_a = two_businesses["token_a"]
    business_id_a = two_businesses["business_id_a"]
    _setup_booking_business(token_a)
    resp = client.patch(
        "/api/v1/business/me", headers=_auth_header(token_a), json={"currency": "NPR"}
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["currency"] == "NPR"

    customer_id = _create_customer(token_a)
    conversation_id = _create_conversation(business_id_a, customer_id)
    stub = _stub_providers(
        monkeypatch, json.dumps({"intent": "pricing_question", "response": "It's NPR 50."})
    )
    resp = client.post(
        f"/api/v1/conversations/{conversation_id}/messages",
        headers=_auth_header(token_a),
        json={"content": "How much is a cleaning?"},
    )
    assert resp.status_code == 201, resp.text

    real_prompt_sent_to_llm = stub.calls[0][1]["content"]
    assert "NPR 50.00" in real_prompt_sent_to_llm, real_prompt_sent_to_llm
    assert "$50.00" not in real_prompt_sent_to_llm


def test_available_services_prompt_defaults_to_usd_for_a_business_that_never_set_currency(
    two_businesses, monkeypatch
):
    """Backward-compatibility: every pre-existing business defaulted to USD on
    migration (see the real migration's `server_default='USD'`) — this proves
    that default actually reaches the real prompt unchanged, not just the DB
    column, for a business that never touched the new field."""
    token_a = two_businesses["token_a"]
    business_id_a = two_businesses["business_id_a"]
    _setup_booking_business(token_a)
    customer_id = _create_customer(token_a)
    conversation_id = _create_conversation(business_id_a, customer_id)
    stub = _stub_providers(
        monkeypatch, json.dumps({"intent": "pricing_question", "response": "It's $50."})
    )
    resp = client.post(
        f"/api/v1/conversations/{conversation_id}/messages",
        headers=_auth_header(token_a),
        json={"content": "How much is a cleaning?"},
    )
    assert resp.status_code == 201, resp.text

    real_prompt_sent_to_llm = stub.calls[0][1]["content"]
    assert "USD 50.00" in real_prompt_sent_to_llm, real_prompt_sent_to_llm


# --- urgent fix: real live loop, agent re-asking an already-answered question --


def test_system_prompt_forbids_reasking_an_already_answered_clarifying_question(two_businesses, monkeypatch):
    """Real, live bug (PHASE_STATUS.md — Samaj Dental Clinic, real conversation
    id=1ad85833-7e44-44fa-b4f7-b420b91e054b, 2026-09-16): the agent kept
    re-asking "WhatsApp or email?" for an eSewa-QR-delivery channel over and
    over, even after the customer had already answered it more than once,
    spread across several turns and phrased differently each time
    ("What app ma vaya hunxa", later "tei whatsapp number ma pathaunu k").
    Reproduced live against the real Azure OpenAI deployment before this fix
    and re-verified after it — both real transcripts are pasted into
    PHASE_STATUS.md, not asserted here, for the same reason this file's own
    module docstring gives for every other real-LLM-behavior claim: an exact
    LLM reply is flaky to pin in an automated suite and isn't what proves the
    wiring correct. This intent ("follow_up") has no Phase 25a-style
    deterministic draft — response_text is the LLM's own free text verbatim
    — so the ONLY thing that can stop the re-ask is the system prompt
    instruction plus the model actually being shown the customer's prior
    answer. What IS deterministic wiring, and what this guards against
    silently regressing: (1) the anti-re-ask rule is actually present in the
    system prompt sent to the model, and (2) the customer's already-given
    answer is actually present in the "Recent conversation" transcript the
    model is shown — without both, the model has neither the instruction nor
    the information it needs to honor it."""
    token_a = two_businesses["token_a"]
    business_id_a = two_businesses["business_id_a"]
    customer_id = _create_customer(token_a)
    conversation_id = _create_conversation(business_id_a, customer_id)

    with SessionLocal() as db:
        from app.db.models.conversation import Message, MessageSenderType

        db.add(
            Message(
                conversation_id=conversation_id,
                sender_type=MessageSenderType.AGENT,
                content="QR WhatsApp ma pathaun ki email ma pathaun?",
            )
        )
        db.add(
            Message(
                conversation_id=conversation_id,
                sender_type=MessageSenderType.CUSTOMER,
                content="What app ma vaya hunxa",
            )
        )
        db.commit()

    stub = _stub_providers(
        monkeypatch, json.dumps({"intent": "follow_up", "response": "Thik cha, WhatsApp ma pathaunchu."})
    )
    resp = client.post(
        f"/api/v1/conversations/{conversation_id}/messages",
        headers=_auth_header(token_a),
        json={"content": "Ho, tei whatsapp number ma nai pathaunu"},
    )
    assert resp.status_code == 201, resp.text

    system_prompt = stub.calls[0][0]["content"]
    assert "do NOT ask it again" in system_prompt
    assert "locked in, permanently, for this conversation" in system_prompt

    user_prompt = stub.calls[0][1]["content"]
    assert "What app ma vaya hunxa" in user_prompt, "the customer's already-given answer must reach the model"


def test_format_hours_real_weekly_schedule():
    """Real spec-conformance fix (PHASE_STATUS.md, "open cha?" got 'I don't
    have that information' even though real business hours exist in the DB
    — they were never shown to the LLM). Pure formatting-logic test against
    real BusinessHours rows, same day_of_week convention (0=Monday) already
    used by booking_service.get_available_slots."""
    hours = [
        BusinessHours(business_id=uuid.uuid4(), day_of_week=0, closed=False, open_time=time(9, 0), close_time=time(18, 0)),
        BusinessHours(business_id=uuid.uuid4(), day_of_week=5, closed=True, open_time=None, close_time=None),
    ]
    formatted = _format_hours(hours)
    assert "Monday: 9:00 AM - 6:00 PM" in formatted
    assert "Saturday: Closed" in formatted
    # A day with no row at all (never configured) must read as Closed, not
    # silently vanish from the list or crash.
    assert "Sunday: Closed" in formatted
    assert _format_hours([]) == "No business hours are configured for this business yet."


def test_real_business_hours_reach_the_system_prompt(two_businesses, monkeypatch):
    """Real, live wiring check: the actual configured business hours (set
    via the real /api/v1/business/hours endpoint, same as _setup_booking_
    business does) must appear in what's actually sent to the LLM — the
    deterministic half of the fix; only a real live LLM call proves the
    model actually uses it (see PHASE_STATUS.md's real before/after)."""
    token_a = two_businesses["token_a"]
    business_id_a = two_businesses["business_id_a"]
    _setup_booking_business(token_a)  # Mon-Sat 9am-5pm, Sun closed
    customer_id = _create_customer(token_a)
    conversation_id = _create_conversation(business_id_a, customer_id)

    stub = _stub_providers(monkeypatch, json.dumps({"intent": "business_hours", "response": "We're open 9-5 Mon-Fri."}))
    resp = client.post(
        f"/api/v1/conversations/{conversation_id}/messages",
        headers=_auth_header(token_a),
        json={"content": "are you open today?"},
    )
    assert resp.status_code == 201, resp.text

    user_prompt = stub.calls[0][1]["content"]
    assert "Business hours" in user_prompt
    assert "9:00 AM - 5:00 PM" in user_prompt


def test_system_prompt_tells_the_llm_a_clarifying_question_is_not_a_handoff_case(two_businesses, monkeypatch):
    """Real bug found live (PHASE_STATUS.md, "handoff_addendum false-firing on
    clarifying questions"): a real conversation this session had the agent
    ask a perfectly reasonable clarifying question ("do you mean gum
    thickness or tooth width?") and STILL get a real HumanHandoff created
    and "I've also let our team know..." appended, because rule 15's own
    no-handoff examples never mentioned "I'm asking a clarifying question I
    can resolve myself" — only real-LLM testing can prove the model actually
    changes behavior (see the real before/after transcripts in
    PHASE_STATUS.md), but this guards the deterministic half: the new
    wording is actually present in what gets sent to the model."""
    token_a = two_businesses["token_a"]
    business_id_a = two_businesses["business_id_a"]
    customer_id = _create_customer(token_a)
    conversation_id = _create_conversation(business_id_a, customer_id)

    stub = _stub_providers(
        monkeypatch,
        json.dumps(
            {
                "intent": "service_question",
                "response": "Do you mean X or Y?",
                "needs_human_handoff": False,
            }
        ),
    )
    resp = client.post(
        f"/api/v1/conversations/{conversation_id}/messages",
        headers=_auth_header(token_a),
        json={"content": "k garda thick hola"},
    )
    assert resp.status_code == 201, resp.text

    system_prompt = stub.calls[0][0]["content"]
    assert "asking the customer a clarifying question" in system_prompt
    assert "not something that needs a human" in system_prompt


def test_handoff_service_still_fires_for_genuinely_unanswered_questions():
    """Companion to the test above: the clarifying-question wording change is
    prompt-only — it must not weaken the actual deterministic handoff
    mechanism (handoff_service._handoff_reason) itself. A genuine low-
    similarity info-question the LLM does NOT confirm as answered must still
    produce a real handoff reason, unchanged."""
    from app.services.handoff_service import _handoff_reason
    from app.schemas.conversation import ConversationIntent

    reason = _handoff_reason(
        intent=ConversationIntent.GENERAL_QUESTION, best_similarity=0.28, llm_confirmed_answered=None
    )
    assert reason is not None
    assert "0.28" in reason


def test_is_medical_emergency_needs_a_seen_request_alongside_a_bare_urgency_word():
    """Regression guard for a real false-positive found while building the emergency
    detector against the full 597-case regression dataset: "asap"/"right now" alone are
    too generic (payment-timing remarks like "I don't have money right now" use them too)
    -- they only count paired with an actual "come see me" request. An unambiguous word
    (9/10, "emergency", ...) always counts alone."""
    from app.services.conversation.orchestrator import _is_medical_emergency

    assert not _is_medical_emergency("I don't have money right now")
    assert not _is_medical_emergency("I don't have to pay 1% right now")
    assert _is_medical_emergency("I chipped my tooth badly and it's bleeding, can someone see me right now?")
    assert _is_medical_emergency("Mero emergency ho k garne hola")
    assert _is_medical_emergency("REALLY bad toothache (like a 9/10) -- swelling too. Can someone see me ASAP??")


def test_stated_medical_emergency_gets_an_urgent_override_and_a_real_handoff(two_businesses, monkeypatch):
    """Root-cause fix for a confirmed missed_escalation bug (read-through of
    backend/data/regression/failure_log_batches/batch5_testchat_misc.json, conversation
    fb325df3): a stated 9/10 toothache with overnight swelling got a plain "I'll need a
    way to reach you", no urgency acknowledged, no escalation at all -- because nothing in
    the LLM's own intent classification reliably catches a described medical emergency."""
    from app.db.models.handoff import HumanHandoff

    token_a, business_id_a = two_businesses["token_a"], two_businesses["business_id_a"]
    customer_id = _create_customer(token_a)
    conversation_id = _create_conversation(business_id_a, customer_id)

    _stub_providers(
        monkeypatch, json.dumps({"intent": "general_question", "response": "Sure, I can help you book that."})
    )
    body = _say(
        token_a,
        conversation_id,
        "Hi!!! I have a REALLY bad toothache (like a 9/10) since yesterday night — swelling too. "
        "Can someone see me ASAP?? Also do you guys accept walk-ins or do I need to book first??",
    )
    lowered = body.lower()
    assert "call us" in lowered or "visit us" in lowered
    assert "sure, i can help you book" not in lowered, "the LLM's own drafted text must never be used for a stated emergency"
    with SessionLocal() as db:
        handoffs = db.query(HumanHandoff).filter(HumanHandoff.conversation_id == conversation_id).all()
        assert len(handoffs) == 1 and handoffs[0].resolved_at is None
        assert "emergency" in handoffs[0].reason.lower()


def test_stuck_in_a_repeating_confirmation_loop_gets_a_real_handoff(two_businesses, monkeypatch):
    """Root-cause fix for a confirmed missed_escalation bug (same read-through, conversation
    7f72b8f1): a customer stuck in a non-progressing booking-confirmation loop -- the agent
    repeating a near-identical reply turn after turn -- called the agent "dumb" and still
    got no escalation."""
    from app.db.models.conversation import Message, MessageSenderType
    from app.db.models.handoff import HumanHandoff

    token_a, business_id_a = two_businesses["token_a"], two_businesses["business_id_a"]
    customer_id = _create_customer(token_a)
    conversation_id = _create_conversation(business_id_a, customer_id)

    prior_reply = (
        "Great — to confirm: you'd like a Teeth Cleaning at 11:00 on the next available morning. "
        "Shall I check availability now?"
    )
    with SessionLocal() as db:
        for _ in range(2):
            db.add(Message(conversation_id=conversation_id, sender_type=MessageSenderType.AGENT, content=prior_reply))
        db.commit()

    _stub_providers(
        monkeypatch,
        json.dumps(
            {
                "intent": "general_question",
                "response": (
                    "I can help with that. You want a Teeth Cleaning at 11:00 on the next available morning — "
                    "shall I check availability now?"
                ),
            }
        ),
    )
    _say(token_a, conversation_id, "yes you dumb")
    with SessionLocal() as db:
        handoffs = db.query(HumanHandoff).filter(HumanHandoff.conversation_id == conversation_id).all()
        assert len(handoffs) == 1 and handoffs[0].resolved_at is None
        assert "unresolved" in handoffs[0].reason.lower()


def test_a_fresh_reply_that_merely_resembles_earlier_ones_does_not_falsely_escalate(two_businesses, monkeypatch):
    """Companion to the loop test above: two prior replies that happen to share SOME words
    with a genuinely different new answer must never falsely trip the stuck-loop guard --
    only real, substantial near-duplication (see _is_stuck_in_a_loop's docstring) does."""
    from app.db.models.conversation import Message, MessageSenderType
    from app.db.models.handoff import HumanHandoff

    token_a, business_id_a = two_businesses["token_a"], two_businesses["business_id_a"]
    customer_id = _create_customer(token_a)
    conversation_id = _create_conversation(business_id_a, customer_id)

    with SessionLocal() as db:
        for content in ("Sure, what service would you like?", "We offer Teeth Cleaning and Root Canal."):
            db.add(Message(conversation_id=conversation_id, sender_type=MessageSenderType.AGENT, content=content))
        db.commit()

    _stub_providers(
        monkeypatch,
        json.dumps(
            {
                "intent": "general_question",
                "response": "We're open 9am-6pm, Monday to Friday.",
                "needs_human_handoff": False,  # isolates the stuck-loop guard from the unrelated low-similarity path
            }
        ),
    )
    _say(token_a, conversation_id, "what are your hours?")
    with SessionLocal() as db:
        assert db.query(HumanHandoff).filter(HumanHandoff.conversation_id == conversation_id).count() == 0


# =====================================================================================================================
# Phase 14 (2026-09-19 series): formatting fixes + rate-limited resend (email / QR-in-email / QR-link-in-chat)
# =====================================================================================================================
import re  # noqa: E402
import threading  # noqa: E402


def _book_appointment(business_id: uuid.UUID, customer_id: uuid.UUID, service_id: uuid.UUID, *, hour: int = 14) -> uuid.UUID:
    target = _next_monday()
    with SessionLocal() as db:
        return booking_service.create_appointment(
            db, business_id=business_id, customer_id=customer_id, service_id=service_id, staff_id=None,
            scheduled_at=datetime(target.year, target.month, target.day, hour, 0, tzinfo=ZoneInfo("UTC")),
        ).id


class _CapturingEmailProvider:
    """Stubs ONLY the network: the REAL dispatch chain runs and resolves the recipient itself, so `recipients` is the
    address a real send would actually have gone to."""

    def __init__(self):
        self.recipients: list[str] = []

    def send(self, *, to, subject, body, html_body=None, attachments=None, inline_images=None, credentials=None):
        self.recipients.append(to)
        return "250 message accepted for delivery"


def _capture_email(monkeypatch) -> _CapturingEmailProvider:
    from app.services.notifications import dispatch_service

    fake = _CapturingEmailProvider()
    monkeypatch.setitem(dispatch_service._PROVIDERS, "email", fake)
    return fake


def _resend_llm_reply(appointment_id, *, channel=None, contact_info_update=None, intent="resend_confirmation") -> str:
    payload = {"intent": intent, "response": "Sure, one moment."}
    if appointment_id is not None:
        payload["resend_request"] = {"appointment_id": str(appointment_id), "channel": channel}
    if contact_info_update:
        payload["contact_info_update"] = contact_info_update
    return json.dumps(payload)


def _say(token, conversation_id, text):
    resp = client.post(
        f"/api/v1/conversations/{conversation_id}/messages", headers=_auth_header(token), json={"content": text}
    )
    assert resp.status_code == 201, resp.text
    return resp.json()["response"]


# ---------------------------------------------------------------- formatting 2: the date is stated once ---------


def test_slot_options_state_one_date_once_and_keep_dates_when_they_differ():
    from app.services.conversation.orchestrator import _format_local, _format_slot_options

    utc = ZoneInfo("UTC")
    monday = _next_monday()
    same_day = [datetime.combine(monday, time(9, m), tzinfo=utc) for m in (0, 15, 30, 45)]
    out = _format_slot_options(same_day, utc)
    assert out == f"{monday.strftime('%A, %B ')}{monday.day} at 9:00 AM, 9:15 AM, 9:30 AM, 9:45 AM"
    assert out.count(monday.strftime("%B")) == 1, "the date must be stated exactly once"

    # a single slot is byte-identical to the pre-existing single-slot format
    assert _format_slot_options(same_day[:1], utc) == _format_local(same_day[0], utc)

    # slots on DIFFERENT real dates: every slot keeps its own full date (dropping it would be ambiguous)
    tuesday = monday + timedelta(days=1)
    mixed = [datetime.combine(monday, time(16, 30), tzinfo=utc), datetime.combine(tuesday, time(9, 0), tzinfo=utc)]
    assert _format_slot_options(mixed, utc) == ", ".join(_format_local(x, utc) for x in mixed)


def test_slot_options_compare_local_dates_not_utc_dates():
    """Two slots on different UTC dates can be the same LOCAL date (and vice versa): what the customer sees decides."""
    from app.services.conversation.orchestrator import _format_local, _format_slot_options

    ny = ZoneInfo("America/New_York")
    # 23:30Z and 02:00Z(+1 day) are 19:30 and 22:00 on the SAME New York date
    same_local = [datetime(2026, 9, 20, 23, 30, tzinfo=ZoneInfo("UTC")), datetime(2026, 9, 21, 2, 0, tzinfo=ZoneInfo("UTC"))]
    assert _format_slot_options(same_local, ny) == "Sunday, September 20 at 7:30 PM, 10:00 PM"
    # 03:00Z and 05:00Z (same UTC date) are 23:00 Sep 20 and 01:00 Sep 21 in New York: different local dates
    diff_local = [datetime(2026, 9, 21, 3, 0, tzinfo=ZoneInfo("UTC")), datetime(2026, 9, 21, 5, 0, tzinfo=ZoneInfo("UTC"))]
    assert _format_slot_options(diff_local, ny) == ", ".join(_format_local(x, ny) for x in diff_local)


def test_real_orchestrator_slot_list_states_the_date_once(two_businesses, monkeypatch):
    token_a, business_id_a = two_businesses["token_a"], two_businesses["business_id_a"]
    _setup_booking_business(token_a)
    conversation_id = _create_conversation(business_id_a, _create_customer_with_contact(token_a))
    monday = _next_monday()
    _stub_providers(monkeypatch, _partial_booking_reply(service="Cleaning", date=monday.isoformat(), wants_availability=True))
    body = _say(token_a, conversation_id, "what's open on monday for a cleaning?")
    date_text = f"{monday.strftime('%A, %B ')}{monday.day}"
    assert body.count(date_text) == 1, body
    assert "9:00 AM, 9:15 AM, 9:30 AM, 9:45 AM, 10:00 AM" in body, body


# ---------------------------------------------------------------- formatting 1: service list on its own lines ----

_SVC_NAMES = ["Teeth Cleaning", "Tooth Filling", "Root Canal", "Teeth Whitening", "Dental Consultation", "Braces Checkup"]
# REAL outputs captured live from the running backend before this fix (Phase 14 reproduction).
_REAL_LLM_SEMICOLONS = (
    "We offer the following services: Teeth Cleaning (USD 1500.00, 30 min); Tooth Filling (USD 2500.00, 45 min); "
    "Root Canal (USD 9000.00, 90 min); Teeth Whitening (USD 6000.00, 45 min); Dental Consultation (USD 500.00, "
    "20 min); and Braces Checkup (USD 1200.00, 30 min)."
)
_REAL_LLM_DASHES = (
    "We offer: Teeth Cleaning — USD 1500.00 (30 min); Tooth Filling — USD 2500.00 (45 min); Root Canal — USD 9000.00 "
    "(90 min); Teeth Whitening — USD 6000.00 (45 min); Dental Consultation — USD 500.00 (20 min); Braces Checkup — "
    "USD 1200.00 (30 min)."
)
_REAL_LLM_COMMAS_NEPALI = (
    "Hami le yeta services dinchhau: Teeth Cleaning (USD 1500.00, 30 min), Tooth Filling (USD 2500.00, 45 min), Root "
    "Canal (USD 9000.00, 90 min), Teeth Whitening (USD 6000.00, 45 min), Dental Consultation (USD 500.00, 20 min), "
    "ani Braces Checkup (USD 1200.00, 30 min). Kun ko lagi appointment book garna mancha?"
)


def test_format_service_list_puts_each_real_service_on_its_own_line_for_all_real_captured_shapes():
    from app.services.conversation.formatting import format_service_list

    out = format_service_list(_REAL_LLM_SEMICOLONS, _SVC_NAMES)
    assert out == (
        "We offer the following services:\n- Teeth Cleaning (USD 1500.00, 30 min)\n- Tooth Filling (USD 2500.00, 45 min)\n"
        "- Root Canal (USD 9000.00, 90 min)\n- Teeth Whitening (USD 6000.00, 45 min)\n"
        "- Dental Consultation (USD 500.00, 20 min)\n- Braces Checkup (USD 1200.00, 30 min)"
    )
    dashes = format_service_list(_REAL_LLM_DASHES, _SVC_NAMES)
    assert dashes.startswith("We offer:\n- Teeth Cleaning — USD 1500.00 (30 min)\n- Tooth Filling")
    assert dashes.count("\n- ") == 6 and ";" not in dashes
    nepali = format_service_list(_REAL_LLM_COMMAS_NEPALI, _SVC_NAMES)
    assert nepali.count("\n- ") == 6
    assert nepali.endswith("\n\nKun ko lagi appointment book garna mancha?"), "trailing sentence goes after a blank line"
    assert "- Braces Checkup (USD 1200.00, 30 min)\n" in nepali and "ani Braces" not in nepali
    two = format_service_list(
        "We offer Basic Cleaning (USD 75.00, 30 min) and Whitening (USD 150.00, 45 min).", ["Basic Cleaning", "Whitening"]
    )
    assert two == "We offer:\n- Basic Cleaning (USD 75.00, 30 min)\n- Whitening (USD 150.00, 45 min)"


def test_format_service_list_leaves_everything_that_is_not_a_list_alone():
    from app.services.conversation.formatting import format_service_list

    untouched = [
        "Teeth Cleaning is a routine 30-minute procedure, while Root Canal treats infected tooth pulp.",  # comparison
        "Teeth Cleaning (USD 1500) and Root Canal (USD 9000) are our most popular.",  # prose after an entry
        "Would you like Teeth Cleaning, Tooth Filling or Root Canal?",  # a question that names services
        "Root Canal costs USD 9000.00 and takes 90 min.",  # one service
        "You're all set! I've booked Teeth Cleaning for Monday at 9 AM.",
        "Yaha hamro services:\n- Teeth Cleaning — USD 1500.00, 30 min\n- Tooth Filling — USD 2500.00, 45 min",  # already lines
        "",
    ]
    for text in untouched:
        assert format_service_list(text, _SVC_NAMES) == text
    assert format_service_list(_REAL_LLM_SEMICOLONS, ["Teeth Cleaning"]) == _REAL_LLM_SEMICOLONS, "needs 2+ real services"


def test_real_orchestrator_breaks_an_llm_drafted_service_list_into_lines(two_businesses, monkeypatch):
    token_a, business_id_a = two_businesses["token_a"], two_businesses["business_id_a"]
    for name, price in (("Teeth Cleaning", "1500"), ("Tooth Filling", "2500"), ("Root Canal", "9000")):
        assert client.post("/api/v1/services", json={"name": name, "price": price, "duration_minutes": 30},
                           headers=_auth_header(token_a)).status_code == 201
    conversation_id = _create_conversation(business_id_a, _create_customer_with_contact(token_a))
    llm_line = "We offer: Teeth Cleaning (USD 1500, 30 min); Tooth Filling (USD 2500, 30 min); and Root Canal (USD 9000, 30 min)."
    _stub_providers(monkeypatch, json.dumps({"intent": "service_question", "response": llm_line, "needs_human_handoff": False}))
    body = _say(token_a, conversation_id, "what services do you offer?")
    assert body == ("We offer:\n- Teeth Cleaning (USD 1500, 30 min)\n- Tooth Filling (USD 2500, 30 min)\n"
                    "- Root Canal (USD 9000, 30 min)"), body

    # a non-list reply for the same intent is untouched, and so is a template-composed intent
    _stub_providers(monkeypatch, json.dumps({"intent": "pricing_question", "response": "Root Canal is USD 9000 and takes 30 min.", "needs_human_handoff": False}))
    assert _say(token_a, conversation_id, "how much is a root canal?") == "Root Canal is USD 9000 and takes 30 min."


def _fake_urlopen_capturing(captured: list):
    class _Resp:
        def __init__(self, payload):
            self._payload = payload

        def __enter__(self):
            return self

        def __exit__(self, *exc):
            return False

        def read(self):
            return json.dumps(self._payload).encode()

    def _fake(request, timeout=None):
        captured.append(json.loads(request.data.decode("utf-8")))
        return _Resp({"messages": [{"id": "wamid.T"}], "message_id": "mid.T"})

    return _fake


def test_outbound_channel_payloads_carry_a_service_list_newline_and_link_unchanged(monkeypatch):
    """WhatsApp, Messenger and Instagram all send the reply text verbatim inside their JSON body, so "\\n" is a real line
    break on each (they render it natively) — checked at the exact payload each real send would POST."""
    import app.services.channels.instagram as instagram_module
    import app.services.channels.messenger as messenger_module
    import app.services.channels.whatsapp as whatsapp_module

    text = "We offer:\n- Teeth Cleaning (USD 1500, 30 min)\n- Root Canal (USD 9000, 90 min)\n\nOpen: https://example.test/qr/abc.123.def"
    sent: list[dict] = []
    for module in (whatsapp_module, messenger_module, instagram_module):
        monkeypatch.setattr(module.urllib.request, "urlopen", _fake_urlopen_capturing(sent))
    whatsapp_module.WhatsAppChannelAdapter().send_message(to="977980", text=text, phone_number_id="1", access_token="t")
    messenger_module.MessengerChannelAdapter().send_message(psid="p1", text=text, page_access_token="t")
    instagram_module.InstagramChannelAdapter().send_message(igsid="i1", text=text, ig_account_id="9", access_token="t")
    assert sent[0]["text"]["body"] == text
    assert sent[1]["message"]["text"] == text
    assert sent[2]["message"]["text"] == text
    assert all("\n- Teeth Cleaning" in json.dumps(x, ensure_ascii=False).replace("\\n", "\n") for x in sent)


def test_widget_and_test_chat_render_newlines_and_only_linkify_http_urls():
    """Static guard for the two browser surfaces (the real rendering is also verified live in a browser, see
    PHASE_STATUS.md): both keep newlines via white-space:pre-wrap, and both insert message text as DOM text nodes."""
    from pathlib import Path

    static = Path(__file__).resolve().parents[2] / "app" / "static"
    for name in ("widget.js", "test-chat.html"):
        src = (static / name).read_text()
        assert "white-space:pre-wrap" in src.replace(" ", "") , f"{name} must preserve newlines"
        assert "fillWithLinks" in src and "createTextNode" in src, f"{name} must build message DOM without innerHTML"
        assert "https?:" in src, f"{name} must only linkify http(s) URLs"
        assert "bubble.innerHTML" not in src, f"{name} must not put message text into innerHTML"


# ---------------------------------------------------------------- resend: signed QR link ------------------------


def test_qr_token_is_signed_expiring_and_names_only_the_appointment():
    from app.services import qr_link_service as q

    appointment_id = uuid.uuid4()
    scheduled = datetime(2026, 9, 21, 14, 0, tzinfo=ZoneInfo("UTC"))
    token = q.make_token(appointment_id, scheduled, now=1_000.0)
    assert q.verify_token(token, now=1_000.0) == appointment_id
    assert q.verify_token(token, now=scheduled.timestamp() + 23 * 3600) == appointment_id
    assert q.verify_token(token, now=scheduled.timestamp() + 25 * 3600) is None, "expires 24h after the appointment"

    hex_id, exp, sig = token.split(".")
    assert q.verify_token(f"{uuid.uuid4().hex}.{exp}.{sig}", now=1_000.0) is None, "id swap must fail the HMAC"
    assert q.verify_token(f"{hex_id}.{int(exp) + 9999}.{sig}", now=1_000.0) is None, "expiry edit must fail the HMAC"
    assert q.verify_token(f"{hex_id}.{exp}.{sig[:-2]}AA", now=1_000.0) is None
    for garbage in ("", "x", "a.b.c", f"{hex_id}.{exp}", f"{hex_id}.abc.{sig}", "../../etc/passwd"):
        assert q.verify_token(garbage, now=1_000.0) is None
    # a link issued for a past appointment still lives >=1h so the customer can actually open it
    past = q.make_token(appointment_id, datetime(2020, 1, 1, tzinfo=ZoneInfo("UTC")), now=5_000.0)
    assert q.verify_token(past, now=5_000.0 + 3000) == appointment_id
    assert q.mask_email("jordan@example.com") == "j***@example.com"


def _qr_page(token: str):
    return client.get(f"/qr/{token}")


def test_qr_page_shows_the_same_qr_as_the_email_and_reveals_nothing_else(two_businesses):
    import base64

    from app.services import qr_link_service as q
    from app.services.notifications.qr import generate_qr_png

    token_a, business_id_a = two_businesses["token_a"], two_businesses["business_id_a"]
    service_id = _setup_booking_business(token_a)
    customer_id = _create_customer(token_a, email=_unique_email("qr-page"))
    appointment_id = _book_appointment(business_id_a, customer_id, service_id)
    with SessionLocal() as db:
        appointment = db.get(Appointment, appointment_id)
        checkin_token, scheduled_at = str(appointment.checkin_token), appointment.scheduled_at
        business = db.get(Business, business_id_a)
        business.name = "A&B <Dental>"
        db.commit()

    resp = _qr_page(q.make_token(appointment_id, scheduled_at))
    assert resp.status_code == 200 and resp.headers["content-type"].startswith("text/html")
    assert resp.headers["cache-control"] == "no-store" and "noindex" in resp.headers["x-robots-tag"]
    assert resp.headers["referrer-policy"] == "no-referrer" and "default-src 'none'" in resp.headers["content-security-policy"]
    # the embedded PNG IS the Phase 46 QR (same bytes the confirmation email embeds), i.e. it encodes the check-in token
    assert base64.b64encode(generate_qr_png(checkin_token)).decode() in resp.text
    assert "A&amp;B &lt;Dental&gt;" in resp.text and "<Dental>" not in resp.text, "tenant-controlled text must be escaped"
    # nothing that identifies the customer or grants more than the QR itself
    assert checkin_token not in resp.text and appointment_id.hex not in resp.text and str(appointment_id) not in resp.text
    assert "@" not in resp.text.split("<img")[0], "no email address on the page"


def test_qr_page_every_failure_is_the_same_generic_404(two_businesses):
    from app.services import qr_link_service as q

    token_a, business_id_a = two_businesses["token_a"], two_businesses["business_id_a"]
    service_id = _setup_booking_business(token_a)
    customer_id = _create_customer(token_a, email=_unique_email("qr-404"))
    appointment_id = _book_appointment(business_id_a, customer_id, service_id)
    other_id = _book_appointment(business_id_a, customer_id, service_id, hour=15)
    with SessionLocal() as db:
        scheduled_at = db.get(Appointment, appointment_id).scheduled_at
    good = q.make_token(appointment_id, scheduled_at)
    hex_id, exp, sig = good.split(".")
    other_hex = other_id.hex

    bodies = set()
    for bad in (
        "garbage", f"{other_hex}.{exp}.{sig}", f"{hex_id}.{exp}.{sig[:-1]}X",
        q.make_token(appointment_id, scheduled_at, now=0.0).replace(exp, "1"),  # expired
        f"{uuid.uuid4().hex}.{exp}.{q._sign(f'{uuid.uuid4().hex}.{exp}')}",  # validly signed but unknown appointment
    ):
        resp = _qr_page(bad)
        assert resp.status_code == 404, (bad, resp.status_code)
        bodies.add(resp.text)
    with SessionLocal() as db:
        booking_service.cancel_appointment(db, business_id=business_id_a, appointment_id=appointment_id)
    resp = _qr_page(good)  # authentic + unexpired, but the appointment is now CANCELLED
    assert resp.status_code == 404
    bodies.add(resp.text)
    assert len(bodies) == 1, "every failure must be byte-identical: the endpoint must not be an oracle"


def test_qr_page_is_rate_limited_per_ip(two_businesses):
    from app.core.rate_limit import qr_view_ip_rate_limiter

    qr_view_ip_rate_limiter._attempts.clear()
    try:
        statuses = [_qr_page("garbage").status_code for _ in range(qr_view_ip_rate_limiter.max_attempts + 3)]
    finally:
        qr_view_ip_rate_limiter._attempts.clear()
    assert statuses[: qr_view_ip_rate_limiter.max_attempts] == [404] * qr_view_ip_rate_limiter.max_attempts
    assert statuses[-1] == 429


# ---------------------------------------------------------------- resend: the shared atomic cap -------------------


def test_resend_cap_is_one_shared_atomic_counter_under_8_concurrent_requests(two_businesses, monkeypatch):
    """Same real threading.Barrier technique as Phase 45's reminder claim / Phase 46's check-in claim: 8 threads, each
    with its own DB session, released at the same instant against ONE appointment, mixing all three delivery types
    (email, chat link, both). Exactly 3 requests may win the atomic claim in TOTAL, whatever they asked for."""
    from app.services.conversation.appointment_tools import ResendConfirmationTool

    token_a, business_id_a = two_businesses["token_a"], two_businesses["business_id_a"]
    service_id = _setup_booking_business(token_a)
    on_file = _unique_email("cap-onfile")
    customer_id = _create_customer(token_a, email=on_file)
    appointment_id = _book_appointment(business_id_a, customer_id, service_id)
    fake = _capture_email(monkeypatch)

    wanted = ["email", "chat", "both", "chat", "email", "both", "chat", "email"]
    n = len(wanted)
    barrier = threading.Barrier(n)
    results: list = [None] * n

    def worker(i):
        with SessionLocal() as db:
            barrier.wait()
            try:
                results[i] = ResendConfirmationTool().run(
                    db, business_id=business_id_a, customer_id=customer_id, appointment_id=appointment_id,
                    channel=wanted[i], conversation_channel="widget",
                )
            except Exception as exc:  # a crash is a failed proof, surfaced below
                results[i] = exc

    threads = [threading.Thread(target=worker, args=(i,)) for i in range(n)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    assert not [r for r in results if isinstance(r, Exception)], results
    granted = [i for i, r in enumerate(results) if not r["rate_limited"]]
    refused = [i for i, r in enumerate(results) if r["rate_limited"]]
    assert len(granted) == 3 and len(refused) == 5, f"granted={granted} refused={refused}"
    with SessionLocal() as db:
        assert db.get(Appointment, appointment_id).confirmation_resend_count == 3
    # only granted requests delivered anything, and every email that went out went to the on-file address
    assert len(fake.recipients) == sum(1 for i in granted if wanted[i] in ("email", "both"))
    assert set(fake.recipients) <= {on_file}
    assert all(not results[i]["channels"] for i in refused), "a refused request must not have delivered anything"


# ---------------------------------------------------------------- resend: destination is never chat-supplied ------


@pytest.mark.parametrize("field,value", [("email", "attacker@evil.example"), ("phone", "9811111111")])
def test_resend_never_goes_to_a_destination_typed_into_the_chat(two_businesses, monkeypatch, field, value):
    """The customer's message carries a DIFFERENT email/phone in the same breath as the resend request, and the LLM
    duly extracts it as a contact_info_update. It must not be saved, must not become the destination, and the customer
    must be told why — the resend goes to the exact contact info already on file."""
    token_a, business_id_a = two_businesses["token_a"], two_businesses["business_id_a"]
    service_id = _setup_booking_business(token_a)
    on_file_email, on_file_phone = _unique_email("onfile"), "9800000001"
    customer_id = _create_customer(token_a, email=on_file_email, phone=on_file_phone)
    appointment_id = _book_appointment(business_id_a, customer_id, service_id)
    conversation_id = _create_conversation(business_id_a, customer_id)
    fake = _capture_email(monkeypatch)

    _stub_providers(monkeypatch, _resend_llm_reply(appointment_id, channel="email", contact_info_update={field: value}))
    body = _say(token_a, conversation_id, f"please resend my confirmation to {value}")

    assert fake.recipients == [on_file_email], "the ONLY send must be to the address already on file"
    assert value not in body
    assert f"{on_file_email[0]}***@example.com" in body, "reply must say which on-file address it went to (masked)"
    assert "already on file" in body and "separately" in body, "customer must be told it was not used and how to change it"
    with SessionLocal() as db:
        customer = db.get(Customer, customer_id)
        assert (customer.email, customer.phone) == (on_file_email, on_file_phone), "the redirect must not have been saved"
        assert db.get(Appointment, appointment_id).confirmation_resend_count == 1


def test_resend_chat_link_turn_also_ignores_a_typed_destination(two_businesses, monkeypatch):
    token_a, business_id_a = two_businesses["token_a"], two_businesses["business_id_a"]
    service_id = _setup_booking_business(token_a)
    on_file = _unique_email("onfile2")
    customer_id = _create_customer(token_a, email=on_file)
    appointment_id = _book_appointment(business_id_a, customer_id, service_id)
    conversation_id = _create_conversation(business_id_a, customer_id)
    fake = _capture_email(monkeypatch)

    _stub_providers(monkeypatch, _resend_llm_reply(appointment_id, channel="both", contact_info_update={"email": "attacker@evil.example"}))
    body = _say(token_a, conversation_id, "send my QR to attacker@evil.example and here too")
    assert fake.recipients == [on_file] and "attacker@evil.example" not in body
    assert "/qr/" in body and "already on file" in body
    with SessionLocal() as db:
        assert db.get(Customer, customer_id).email == on_file


def test_a_separate_contact_update_request_still_works_as_its_own_action(two_businesses, monkeypatch):
    """The boundary, stated honestly: a contact change is its own, separate request (existing behavior, unchanged). It
    applies on its own turn — and only THEN does a later, separate resend go to the new on-file address."""
    token_a, business_id_a = two_businesses["token_a"], two_businesses["business_id_a"]
    service_id = _setup_booking_business(token_a)
    old, new = _unique_email("old"), _unique_email("new")
    customer_id = _create_customer(token_a, email=old)
    appointment_id = _book_appointment(business_id_a, customer_id, service_id)
    conversation_id = _create_conversation(business_id_a, customer_id)
    fake = _capture_email(monkeypatch)

    _stub_providers(monkeypatch, json.dumps({"intent": "follow_up", "response": "ok", "contact_info_update": {"email": new}}))
    _say(token_a, conversation_id, f"please update my email to {new}")
    with SessionLocal() as db:
        assert db.get(Customer, customer_id).email == new

    _stub_providers(monkeypatch, _resend_llm_reply(appointment_id, channel="email"))
    _say(token_a, conversation_id, "resend my confirmation email")
    assert fake.recipients[-1] == new


def test_embedded_email_saved_even_when_the_llms_own_extraction_misses_it(two_businesses, monkeypatch):
    """Smoke check reproducing the real Samaj Dental Clinic transcript end to end against the real
    orchestrator: "mero email samratghimire01@gmail.com ho yes ma malai conformation ko mail send
    gardenu na" -- a real email embedded mid-sentence in a longer Romanized-Nepali/English message.
    Stubs the LLM call to reproduce the confirmed failure mode exactly (contact_info_update comes
    back null, as it genuinely did live) so this test exercises orchestrator._resolve_contact_
    update's deterministic fallback, not the LLM's own (unreliable) judgment."""
    token_a, business_id_a = two_businesses["token_a"], two_businesses["business_id_a"]
    _setup_booking_business(token_a)
    customer_id = _create_customer(token_a)  # no email on file yet
    conversation_id = _create_conversation(business_id_a, customer_id)
    email = _unique_email("samrat")

    _stub_providers(monkeypatch, json.dumps({"intent": "follow_up", "response": "Dhanyabad!", "contact_info_update": None}))
    _say(token_a, conversation_id, f"mero email {email} ho yes ma malai conformation ko mail send gardenu na")

    with SessionLocal() as db:
        assert db.get(Customer, customer_id).email == email, (
            "a real embedded email must be saved even when the LLM's own extraction misses it"
        )


def test_resend_tool_refuses_any_caller_supplied_destination(two_businesses):
    from app.services.conversation.appointment_tools import ResendConfirmationTool

    token_a, business_id_a = two_businesses["token_a"], two_businesses["business_id_a"]
    service_id = _setup_booking_business(token_a)
    customer_id = _create_customer(token_a, email=_unique_email("guard"))
    appointment_id = _book_appointment(business_id_a, customer_id, service_id)
    for kwarg in ("to", "email", "phone", "destination", "recipient", "address"):
        with SessionLocal() as db, pytest.raises(ValueError):
            ResendConfirmationTool().run(
                db, business_id=business_id_a, customer_id=customer_id, appointment_id=appointment_id,
                channel="email", conversation_channel="widget", **{kwarg: "attacker@evil.example"},
            )
    with SessionLocal() as db:
        assert db.get(Appointment, appointment_id).confirmation_resend_count == 0, "a refused call must not consume the cap"


# ---------------------------------------------------------------- resend: tenant / appointment isolation ---------


def test_resend_can_only_ever_act_on_the_requesting_conversations_own_appointment(two_businesses, monkeypatch):
    """The LLM is handed (or hallucinates / is talked into) appointment ids belonging to ANOTHER customer of the same
    business and to ANOTHER tenant. Neither may be resent, nothing may be delivered, and no cap may be consumed."""
    from app.services.conversation.appointment_tools import ResendConfirmationTool

    token_a, token_b = two_businesses["token_a"], two_businesses["token_b"]
    business_id_a, business_id_b = two_businesses["business_id_a"], two_businesses["business_id_b"]
    service_a, service_b = _setup_booking_business(token_a), _setup_booking_business(token_b)
    me = _create_customer(token_a, email=_unique_email("me"))
    stranger_same_tenant = _create_customer(token_a, email=_unique_email("stranger"))
    stranger_other_tenant = _create_customer(token_b, email=_unique_email("other-tenant"))
    my_appt = _book_appointment(business_id_a, me, service_a)
    foreign_same_tenant = _book_appointment(business_id_a, stranger_same_tenant, service_a, hour=15)
    foreign_other_tenant = _book_appointment(business_id_b, stranger_other_tenant, service_b, hour=16)
    conversation_id = _create_conversation(business_id_a, me)
    fake = _capture_email(monkeypatch)

    from app.db.models.notification import Notification

    def _notification_count() -> int:
        with SessionLocal() as db:
            return db.query(Notification).filter(
                Notification.appointment_id.in_([my_appt, foreign_same_tenant, foreign_other_tenant])
            ).count()

    notifications_before = _notification_count()  # booking itself created its own booking_confirmed rows
    clarify = "make sure I send the right one"
    for target in (foreign_same_tenant, foreign_other_tenant, uuid.uuid4()):
        for channel in ("email", "both", None):
            _stub_providers(monkeypatch, _resend_llm_reply(target, channel=channel))
            body = _say(token_a, conversation_id, f"resend appointment {target}")
            assert clarify in body, body
            assert "/qr/" not in body
    assert fake.recipients == []
    with SessionLocal() as db:
        for appointment_id in (my_appt, foreign_same_tenant, foreign_other_tenant):
            assert db.get(Appointment, appointment_id).confirmation_resend_count == 0
    assert _notification_count() == notifications_before, "the refused resend attempts must create no notification at all"

    # defense in depth: even a direct tool call with a mismatched business/customer pair is refused and consumes nothing
    for business_id, customer_id, appointment_id in (
        (business_id_a, me, foreign_same_tenant), (business_id_a, me, foreign_other_tenant),
        (business_id_b, stranger_other_tenant, my_appt), (business_id_b, me, foreign_other_tenant),
    ):
        with SessionLocal() as db:
            result = ResendConfirmationTool().run(
                db, business_id=business_id, customer_id=customer_id, appointment_id=appointment_id,
                channel="both", conversation_channel="widget",
            )
        assert result["success"] is False and result["channels"] == {} and "not found" in result["message"].lower()
    with SessionLocal() as db:
        assert all(db.get(Appointment, a).confirmation_resend_count == 0 for a in (my_appt, foreign_same_tenant, foreign_other_tenant))

    # and the legitimate request for MY appointment works, from the same conversation
    _stub_providers(monkeypatch, _resend_llm_reply(my_appt, channel="whatsapp"))  # the LLM contract: whatsapp/email/both/null
    assert "/qr/" in _say(token_a, conversation_id, "send me my QR")


# ---------------------------------------------------------------- resend: the honest 4th attempt -----------------


def test_fourth_resend_request_is_honest_and_creates_a_real_front_desk_handoff(two_businesses, monkeypatch):
    from app.db.models.handoff import HumanHandoff

    token_a, business_id_a = two_businesses["token_a"], two_businesses["business_id_a"]
    service_id = _setup_booking_business(token_a)
    on_file = _unique_email("fourth")
    customer_id = _create_customer(token_a, email=on_file)
    appointment_id = _book_appointment(business_id_a, customer_id, service_id)
    conversation_id = _create_conversation(business_id_a, customer_id)
    fake = _capture_email(monkeypatch)

    _stub_providers(monkeypatch, _resend_llm_reply(appointment_id, channel="email"))
    for attempt in (1, 2, 3):
        body = _say(token_a, conversation_id, "resend my confirmation email")
        assert "on their way" in body, (attempt, body)
    with SessionLocal() as db:
        assert db.query(HumanHandoff).filter(HumanHandoff.conversation_id == conversation_id).count() == 0

    body = _say(token_a, conversation_id, "resend it again please")
    assert "already received this several times" in body and "front desk" in body, body
    assert "a real person will follow up" in body, "the 'front desk' promise must be backed by a real handoff"
    assert len(fake.recipients) == 3, "the 4th request must not send anything"
    with SessionLocal() as db:
        assert db.get(Appointment, appointment_id).confirmation_resend_count == 3
        handoffs = db.query(HumanHandoff).filter(HumanHandoff.conversation_id == conversation_id).all()
        assert len(handoffs) == 1 and handoffs[0].resolved_at is None
        assert "resend limit" in handoffs[0].reason


# ---------------------------------------------------------------- resend: the QR link across channels ------------


@pytest.mark.parametrize("channel", ["whatsapp", "messenger", "instagram", "website"])
def test_resend_qr_link_is_the_same_plain_link_on_every_chat_channel(two_businesses, monkeypatch, channel):
    from app.core.config import settings
    from app.services import qr_link_service
    from app.services.conversation.response_templates import render

    token_a, business_id_a = two_businesses["token_a"], two_businesses["business_id_a"]
    service_id = _setup_booking_business(token_a)
    customer_id = _create_customer(token_a)  # NO email/phone: the chat link needs no contact info at all
    appointment_id = _book_appointment(business_id_a, customer_id, service_id)
    with SessionLocal() as db:
        conversation = Conversation(business_id=business_id_a, customer_id=customer_id, channel=channel, status="open")
        db.add(conversation)
        db.commit()
        conversation_id = conversation.id

    _stub_providers(monkeypatch, _resend_llm_reply(appointment_id, channel=None))  # customer named no channel
    body = _say(token_a, conversation_id, "can you send me my QR code?")

    url = re.search(r"https?://\S+", body).group(0)
    assert url.startswith(f"{settings.backend_base_url.rstrip('/')}/qr/")
    assert qr_link_service.verify_token(url.rsplit("/qr/", 1)[1]) == appointment_id
    assert body == render("resend_qr_link", "en", url=url), "identical text on every channel, link on its own line"
    assert body.endswith(url) and "\n" in body
    with SessionLocal() as db:
        assert db.get(Appointment, appointment_id).confirmation_resend_count == 1


def test_resend_in_a_website_channel_conversation_defaults_to_the_qr_link(two_businesses, monkeypatch):
    """The public widget creates its conversations with channel="website" (widget_service). A live run showed a channel
    list that named it "widget" silently routed website visitors to email; this pins the routing for that channel value
    (driven via the authenticated conversations API; the real widget endpoint is exercised in the live check)."""

    token_a, business_id_a = two_businesses["token_a"], two_businesses["business_id_a"]
    service_id = _setup_booking_business(token_a)
    customer_id = _create_customer(token_a, email=_unique_email("widget-resend"))
    appointment_id = _book_appointment(business_id_a, customer_id, service_id)
    with SessionLocal() as db:
        conversation = Conversation(business_id=business_id_a, customer_id=customer_id, channel="website", status="open")
        db.add(conversation)
        db.commit()
        conversation_id = conversation.id
    fake = _capture_email(monkeypatch)
    _stub_providers(monkeypatch, _resend_llm_reply(appointment_id, channel=None))
    assert _say(token_a, conversation_id, "send me my QR code") != ""
    with SessionLocal() as db:
        from app.db.models.conversation import Message

        reply = db.query(Message).filter(Message.conversation_id == conversation_id).order_by(Message.created_at.desc()).first().content
    assert "/qr/" in reply and fake.recipients == [], "a website visitor gets the link in the chat, not an email"


# --- 2026-09-20 live bug: the identical slot list repeated forever when the customer named no specific time --------


def test_slot_list_is_never_repeated_verbatim_when_the_customer_names_no_time(two_businesses, monkeypatch):
    """Real transcript: after the slot list, "I think I'll come on Monday morning instead, does that work?" and "Great,
    can you book that for me?" both extract (service/date, NO time, wants_availability=true), so the orchestrator
    re-rendered the identical list word for word, three times. Language-independent state bug, not an English
    extraction failure. The same list must never be sent twice in a row; the repeat asks for a time instead, and
    naming a time then still progresses the booking."""
    token_a, business_id_a = two_businesses["token_a"], two_businesses["business_id_a"]
    _setup_booking_business(token_a)
    conversation_id = _create_conversation(business_id_a, _create_customer(token_a))
    monday = _next_monday()

    def say(content: str) -> str:
        resp = client.post(
            f"/api/v1/conversations/{conversation_id}/messages", headers=_auth_header(token_a), json={"content": content}
        )
        assert resp.status_code == 201, resp.text
        return resp.json()["response"]

    _stub_providers(monkeypatch, _partial_booking_reply(service="Cleaning", date=monday.isoformat(), wants_availability=True))
    first = say("I'd like a cleaning on Monday")
    assert "9:00 AM" in first and "Which works for you?" in first

    second = say("I think I'll come on Monday morning instead, does that work?")
    third = say("Great, can you book that for me?")
    assert first not in (second, third), "the identical slot list was repeated"
    for reply in (second, third):
        assert "tell me which one" in reply and "9:00 AM" in reply, f"repeat must ask for a time, keeping the options: {reply}"

    # the customer finally names a time: the flow advances past the list (no more "which works for you" list)
    _stub_providers(monkeypatch, _partial_booking_reply(time="09:15", response="Great."))
    fourth = say("9:15 please")
    assert "Which works for you?" not in fourth and "tell me which one" not in fourth, fourth


def test_pick_one_template_exists_in_every_language():
    from app.services.conversation.response_templates import render

    for lang in ("en", "ne_deva", "ne_roman"):
        assert "9:00 AM" in render("availability_pick_one", lang, options="9:00 AM, 9:15 AM")


def test_describe_business_hours_reads_the_real_row_data_never_a_western_weekend_assumption():
    """Regression guard for the confirmed Samaj Dental Clinic bug (PHASE_STATUS.md /
    failure_log_batches/batch4_samaj.json): Sunday configured OPEN, only Saturday closed --
    this must never come back as "Saturday and Sunday closed"."""
    from datetime import time as _time

    from app.services.conversation.response_templates import describe_business_hours

    class _Hours:
        def __init__(self, day_of_week, closed, open_time=None, close_time=None):
            self.day_of_week = day_of_week
            self.closed = closed
            self.open_time = open_time
            self.close_time = close_time

    weekday = (_time(9, 0), _time(18, 0))
    hours = [_Hours(i, False, *weekday) for i in range(5)] + [
        _Hours(5, True),
        _Hours(6, False, _time(10, 0), _time(18, 0)),
    ]
    text = describe_business_hours(hours, "en")
    assert "Monday-Friday: 9:00 AM - 6:00 PM" in text
    assert "Saturday: Closed" in text
    assert "Sunday: 10:00 AM - 6:00 PM" in text
    assert "Sunday: Closed" not in text

    assert describe_business_hours([], "en") == (
        "I don't have our hours on file yet — let me connect you with our team for that."
    )

    # Confirmed regression (full 615-case live regression run): fact_validator.check_weekday_hours
    # splits on sentence-ending punctuation only, so a single comma-joined sentence naming several
    # days was ONE clause to it -- and a closed day anywhere in that clause got wrongly attributed
    # to every OTHER day also named there ("Monday is closed"). Each day-group must end its own
    # sentence so the shared checker scopes "closed" to the day it actually describes.
    from app.services.conversation.fact_validator import check_weekday_hours

    hours_by_day = {h.day_of_week: h.closed for h in hours}
    assert not check_weekday_hours(text, hours_by_day=hours_by_day)


# --- Phase 17: deterministic backfill of a service the customer literally named but the LLM left null -----------------


def _post_message(token: str, conversation_id: uuid.UUID, content: str) -> dict:
    resp = client.post(
        f"/api/v1/conversations/{conversation_id}/messages", headers=_auth_header(token), json={"content": content}
    )
    assert resp.status_code == 201, resp.text
    return resp.json()


def _conversation_state(conversation_id: uuid.UUID) -> Conversation:
    with SessionLocal() as db:
        return db.get(Conversation, conversation_id)



class _Svc:
    def __init__(self, name):
        self.name = name


def test_service_named_in_matches_only_one_real_service_by_whole_words():
    from app.services.conversation.orchestrator import _service_named_in

    services = [_Svc("Teeth Cleaning (Scaling & Polishing)"), _Svc("Teeth Whitening"), _Svc("Root Canal Treatment"), _Svc("Dental Consultation")]
    assert _service_named_in(services, "what times do you have for a teeth cleaning tomorrow?") is services[0]
    assert _service_named_in(services, "TEETH CLEANING (Scaling & Polishing) please") is services[0]  # full name, any case
    assert _service_named_in(services, "bholi 2 baje teeth whitening ko lagi milcha?") is services[1]
    assert _service_named_in(services, "not the teeth cleaning, the teeth whitening") is None  # two named: never a guess
    assert _service_named_in(services, "what times do you have tomorrow?") is None  # none named
    assert _service_named_in(services, "I need a cleaning") is None  # a bare fragment is the LLM's call, not ours
    assert _service_named_in(services, "unteeth cleanings") is None  # whole words only
    assert _service_named_in([], "teeth cleaning") is None


def test_booking_intent_naming_a_service_the_llm_dropped_still_shows_real_availability(two_businesses, monkeypatch):
    """Measured at low reasoning effort: the model sometimes returns booking_request.service=null for "what times do you have for a
    cleaning tomorrow?", so the customer got "which service?" for a service they had just named. The service is now filled in
    from the message itself, and the real slot list is shown."""
    token_a, business_id_a = two_businesses["token_a"], two_businesses["business_id_a"]
    _setup_booking_business(token_a)
    conversation_id = _create_conversation(business_id_a, _create_customer(token_a))
    monday = _next_monday()
    _stub_providers(monkeypatch, _partial_booking_reply(service=None, date=monday.isoformat(), wants_availability=True))
    body = _post_message(token_a, conversation_id, "what times do you have for a Cleaning on monday?")["response"]
    assert "9:00 AM" in body and "Which works for you?" in body, body
    assert _conversation_state(conversation_id).booking_draft_service_id is not None


def test_service_is_not_invented_when_the_message_names_none(two_businesses, monkeypatch):
    token_a, business_id_a = two_businesses["token_a"], two_businesses["business_id_a"]
    _setup_booking_business(token_a)
    conversation_id = _create_conversation(business_id_a, _create_customer(token_a))
    _stub_providers(monkeypatch, _partial_booking_reply(service=None, date=_next_monday().isoformat(), wants_availability=True))
    body = _post_message(token_a, conversation_id, "what times do you have on monday?")["response"]
    assert "Which works for you?" not in body and "9:00 AM" not in body, body
    assert _conversation_state(conversation_id).booking_draft_service_id is None


def test_backfill_only_applies_to_booking_intent(two_businesses, monkeypatch):
    """A pricing question that mentions a service (LLM left it null) is not silently turned into a booking draft."""
    token_a, business_id_a = two_businesses["token_a"], two_businesses["business_id_a"]
    _setup_booking_business(token_a)
    conversation_id = _create_conversation(business_id_a, _create_customer(token_a))
    reply = json.dumps({"intent": "pricing_question", "response": "It is $50.", "booking_request": {"service": None, "date": None, "time": None, "wants_availability": False}})
    _stub_providers(monkeypatch, reply)
    _post_message(token_a, conversation_id, "how much is a Cleaning?")
    assert _conversation_state(conversation_id).booking_draft_service_id is None


def test_backfill_also_covers_a_short_service_name_that_is_not_an_exact_real_one(two_businesses, monkeypatch):
    """Found live: the model wrote service="Teeth Cleaning" for the real "Teeth Cleaning (Scaling & Polishing)". The resolver is
    exact-match by design, so the draft stayed service-less and the customer was asked "which service?" for one they had named."""
    token_a, business_id_a = two_businesses["token_a"], two_businesses["business_id_a"]
    _setup_booking_business(token_a)
    resp = client.post(
        "/api/v1/services",
        json={"name": "Teeth Whitening (Laser Session)", "price": "80.00", "duration_minutes": 30},
        headers=_auth_header(token_a),
    )
    assert resp.status_code == 201, resp.text
    conversation_id = _create_conversation(business_id_a, _create_customer(token_a))
    _stub_providers(monkeypatch, _partial_booking_reply(service="Teeth Whitening", date=_next_monday().isoformat(), wants_availability=True))
    body = _post_message(token_a, conversation_id, "what times do you have for a teeth whitening on monday?")["response"]
    assert "9:00 AM" in body and "Which works for you?" in body, body


# --- Phase 16: per-business language mode ("automatic" vs "ask upfront") ---------------------------------------------


def _set_language_mode(token: str, mode: str):
    return client.patch("/api/v1/business/me", headers=_auth_header(token), json={"language_mode": mode})



def _lang_reply(message_language: str, switch: str | None = None, text: str = "Sure.") -> str:
    return json.dumps(
        {"intent": "greeting", "response": text, "message_language": message_language, "language_switch_request": switch}
    )



def test_language_mode_defaults_to_automatic_and_is_settable_via_the_business_api(two_businesses):
    token = two_businesses["token_a"]
    assert client.get("/api/v1/business/me", headers=_auth_header(token)).json()["language_mode"] == "automatic"
    resp = _set_language_mode(token, "ask")
    assert resp.status_code == 200, resp.text
    assert resp.json()["language_mode"] == "ask"
    assert client.get("/api/v1/business/me", headers=_auth_header(token)).json()["language_mode"] == "ask"
    assert _set_language_mode(token, "automatic").json()["language_mode"] == "automatic"
    # a value outside the enum, and an explicit null, are rejected -- never reach the DB
    assert _set_language_mode(token, "sometimes").status_code == 422
    assert client.patch("/api/v1/business/me", headers=_auth_header(token), json={"language_mode": None}).status_code == 422
    # other businesses are unaffected
    assert client.get("/api/v1/business/me", headers=_auth_header(two_businesses["token_b"])).json()["language_mode"] == "automatic"


def test_automatic_mode_never_asks_and_goes_straight_to_the_llm(two_businesses, monkeypatch):
    stub = _stub_providers(monkeypatch, _lang_reply("en", text="Hi! How can I help?"))
    token = two_businesses["token_a"]
    conversation_id = _create_conversation(two_businesses["business_id_a"], _create_customer(token))
    body = _post_message(token, conversation_id, "hello")
    assert body["response"] == "Hi! How can I help?"
    assert len(stub.calls) == 1
    assert _conversation_state(conversation_id).language_prompted is False


def test_ask_mode_first_reply_asks_then_locks_to_the_answer_then_only_an_explicit_request_switches(two_businesses, monkeypatch):
    """The full ask-mode conversation: question (no LLM call) -> answer locks (no LLM call) -> 4 plain-English messages do NOT
    move the lock (no passive-drift detection in this mode) -> an explicit "switch to English" request does."""
    # Genuine Romanized-Nepali reply text (not the usual generic "Sure.") -- the conversation
    # locks to ne_roman below, and the tone/language phase's post-generation check would
    # otherwise (correctly) flag a plain-English canned reply as a mismatch and regenerate,
    # which isn't what this test is about (it's checking the LOCK survives passive drift).
    stub = _stub_providers(monkeypatch, _lang_reply("en", text="Huncha, ma tapailai madat garna sakchu."))
    token = two_businesses["token_a"]
    assert _set_language_mode(token, "ask").status_code == 200
    conversation_id = _create_conversation(two_businesses["business_id_a"], _create_customer(token))

    first = _post_message(token, conversation_id, "hello")
    assert "Which language would you like to chat in" in first["response"] and "Conv A" in first["response"]
    assert "भाषा" in first["response"]  # the Devanagari half of the two-language question
    assert len(stub.calls) == 0, "the language question is deterministic -- no LLM call"
    state = _conversation_state(conversation_id)
    assert state.language_prompted is True and state.detected_language is None

    second = _post_message(token, conversation_id, "Nepali")
    assert second["response"].startswith("Huncha, Nepali ma kura garaun")
    assert len(stub.calls) == 0
    state = _conversation_state(conversation_id)
    assert state.detected_language == "ne_roman" and state.language_switch_streak == 0

    for text in ("What are your hours?", "Do you take walk-ins?", "How much is a cleaning?", "Is there parking nearby?"):
        _post_message(token, conversation_id, text)  # the stub reports message_language="en" every time (the L7 anchoring shape)
    state = _conversation_state(conversation_id)
    assert state.detected_language == "ne_roman", "ask mode must not follow passive drift"
    assert state.language_switch_streak == 0
    assert len(stub.calls) == 4
    assert "locked language: Nepali, written in Romanized" in stub.calls[-1][1]["content"], "the LLM is told the locked language"

    _stub_providers(monkeypatch, _lang_reply("en", switch="en", text="Of course! Switching to English."))
    _post_message(token, conversation_id, "Can we switch to English please?")
    assert _conversation_state(conversation_id).detected_language == "en"


@pytest.mark.parametrize(
    "answer,expected",
    [("English", "en"), ("english please", "en"), ("Nepali", "ne_roman"), ("नेपाली", "ne_deva"), ("Nepali in Devanagari", "ne_deva")],
)
def test_ask_mode_answer_variants_lock_the_right_language(two_businesses, monkeypatch, answer, expected):
    _stub_providers(monkeypatch, _lang_reply("en"))
    token = two_businesses["token_a"]
    _set_language_mode(token, "ask")
    conversation_id = _create_conversation(two_businesses["business_id_a"], _create_customer(token))
    _post_message(token, conversation_id, "hi")
    _post_message(token, conversation_id, answer)
    assert _conversation_state(conversation_id).detected_language == expected


def test_ask_mode_answer_that_is_really_a_question_falls_through_to_the_normal_flow(two_businesses, monkeypatch):
    """The customer ignores the question and asks something: no second question, the normal flow answers and locks from the
    message itself (same as automatic mode's first-clear-signal lock). The language question is asked exactly once."""
    stub = _stub_providers(monkeypatch, _lang_reply("en", text="We're open 9 to 5."))
    token = two_businesses["token_a"]
    _set_language_mode(token, "ask")
    conversation_id = _create_conversation(two_businesses["business_id_a"], _create_customer(token))
    _post_message(token, conversation_id, "hello")
    body = _post_message(token, conversation_id, "What time do you open on weekdays?")
    assert body["response"] == "We're open 9 to 5." and len(stub.calls) == 1
    assert _conversation_state(conversation_id).detected_language == "en"
    _post_message(token, conversation_id, "And on Saturday?")
    assert len(stub.calls) == 2  # still no further language question


def test_ask_mode_does_not_ask_a_conversation_that_started_before_the_switch(two_businesses, monkeypatch):
    stub = _stub_providers(monkeypatch, _lang_reply("en", text="Hi!"))
    token = two_businesses["token_a"]
    conversation_id = _create_conversation(two_businesses["business_id_a"], _create_customer(token))
    _post_message(token, conversation_id, "hello")  # automatic mode: an ordinary first turn
    _set_language_mode(token, "ask")
    body = _post_message(token, conversation_id, "what are your hours?")
    assert body["response"] == "Hi!" and len(stub.calls) == 2
    assert _conversation_state(conversation_id).language_prompted is False


def test_toggling_the_setting_changes_the_next_conversation_and_never_another_tenants(two_businesses, monkeypatch):
    stub = _stub_providers(monkeypatch, _lang_reply("en", text="Hi!"))
    token_a, token_b = two_businesses["token_a"], two_businesses["token_b"]

    def first_reply(token, business_id):
        conversation_id = _create_conversation(business_id, _create_customer(token))
        return _post_message(token, conversation_id, "hello")["response"]

    assert first_reply(token_a, two_businesses["business_id_a"]) == "Hi!"  # default: automatic
    _set_language_mode(token_a, "ask")
    asked = first_reply(token_a, two_businesses["business_id_a"])
    assert "Which language would you like to chat in" in asked
    assert first_reply(token_b, two_businesses["business_id_b"]) == "Hi!", "tenant B is still automatic"
    _set_language_mode(token_a, "automatic")
    assert first_reply(token_a, two_businesses["business_id_a"]) == "Hi!"
    assert len(stub.calls) == 3


def test_ask_mode_does_not_ask_a_voice_turn_whose_language_is_already_known(two_businesses, monkeypatch):
    from app.services.conversation.orchestrator import handle_incoming_message

    stub = _stub_providers(monkeypatch, _lang_reply("ne_roman", text="Namaste!"))
    token = two_businesses["token_a"]
    _set_language_mode(token, "ask")
    conversation_id = _create_conversation(two_businesses["business_id_a"], _create_customer(token))
    with SessionLocal() as db:
        result = handle_incoming_message(
            db,
            conversation_id=conversation_id,
            business_id=two_businesses["business_id_a"],
            content="नमस्ते",
            force_language="ne_roman",
        )
    assert result["response"] == "Namaste!" and len(stub.calls) == 1


def test_parse_language_choice_only_accepts_a_short_single_language_answer():
    from app.services.conversation.response_templates import parse_language_choice as parse

    assert parse("English") == "en" and parse("English ma") == "en" and parse("इङ्लिश") == "en"
    assert parse("Nepali") == "ne_roman" and parse("Romanized Nepali") == "ne_roman"
    assert parse("नेपालीमा") == "ne_deva" and parse("Devanagari nepali please") == "ne_deva"
    for not_an_answer in (
        "hello",
        "",
        "English or Nepali both fine",
        "what is the price of a cleaning in English?",
        "teeth cleaning kati ho?",
    ):
        assert parse(not_an_answer) is None, not_an_answer


# --- service-name resolution tolerates the list's own "(...)" suffix (Phase 19) ---------------------------------


def _svc(name):
    from app.db.models.service import Service

    return Service(name=name)


@pytest.mark.parametrize(
    "said, expected",
    [
        ("Teeth Cleaning (Scaling & Polishing)", "Teeth Cleaning (Scaling & Polishing)"),  # exact, unchanged
        ("teeth cleaning", "Teeth Cleaning (Scaling & Polishing)"),  # model dropped the parenthetical
        ("Teeth Cleaning (NPR 1500.00, 30 min)", "Teeth Cleaning (Scaling & Polishing)"),  # model copied the price suffix
        ("Teeth Whitening (NPR 6000.00, 45 min)", "Teeth Whitening"),
        ("Dental Implant", "Dental Implant (per tooth)"),
        ("Cleaning", None),  # a different name is never a match
        ("Teeth", None),
        ("", None),
        ("(NPR 1)", None),  # nothing left after stripping
    ],
)
def test_resolve_service_by_name_tolerates_parenthetical_suffixes_but_never_guesses(said, expected):
    from app.services.conversation.orchestrator import _resolve_service_by_name

    services = [_svc("Teeth Cleaning (Scaling & Polishing)"), _svc("Teeth Whitening"), _svc("Dental Implant (per tooth)")]
    resolved = _resolve_service_by_name(services, said)
    assert (resolved.name if resolved else None) == expected


def test_resolve_service_by_name_refuses_when_two_services_share_a_base_name():
    from app.services.conversation.orchestrator import _resolve_service_by_name

    services = [_svc("Cleaning (Kids)"), _svc("Cleaning (Adults)")]
    assert _resolve_service_by_name(services, "Cleaning") is None  # ambiguous -> never a guess
    assert _resolve_service_by_name(services, "Cleaning (Kids)").name == "Cleaning (Kids)"  # exact still wins


# ---------------------------------------------------------------- resend: failed send is refunded + retry guard ----


class _FailingEmailProvider:
    def __init__(self):
        self.calls = 0

    def send(self, **kwargs):
        from app.services.notifications.base import NotificationDeliveryError

        self.calls += 1
        raise NotificationDeliveryError("550 5.4.5 Daily user sending limit exceeded", transient=False)


def _resend_email(business_id, customer_id, appointment_id):
    from app.services.conversation.appointment_tools import ResendConfirmationTool

    with SessionLocal() as db:
        return ResendConfirmationTool().run(
            db, business_id=business_id, customer_id=customer_id, appointment_id=appointment_id,
            channel="email", conversation_channel="widget",
        )


def _resend_count(appointment_id) -> int:
    with SessionLocal() as db:
        return db.get(Appointment, appointment_id).confirmation_resend_count


def test_failed_resend_is_refunded_but_a_burst_of_failed_retries_is_throttled(two_businesses, monkeypatch):
    from app.services.notifications import dispatch_service

    token_a, business_id_a = two_businesses["token_a"], two_businesses["business_id_a"]
    service_id = _setup_booking_business(token_a)
    customer_id = _create_customer(token_a, email=_unique_email("refund"))
    appointment_id = _book_appointment(business_id_a, customer_id, service_id)
    failing = _FailingEmailProvider()
    monkeypatch.setitem(dispatch_service._PROVIDERS, "email", failing)

    for _ in range(5):  # more failures than the real cap of 3 — none may consume it
        result = _resend_email(business_id_a, customer_id, appointment_id)
        assert result["channels"]["email"]["status"] == "failed" and not result["success"]
        assert not result["rate_limited"] and not result.get("throttled")
        assert _resend_count(appointment_id) == 0, "a failed send must not consume the customer's real cap"

    burst = _resend_email(business_id_a, customer_id, appointment_id)  # 6th failed retry inside the window
    assert burst["throttled"] and burst["channels"] == {}
    assert failing.calls == 5, "a throttled retry must not even attempt a send"
    assert _resend_count(appointment_id) == 0

    # the orchestrator's reply + handoff for a throttled result
    from app.services.conversation.orchestrator import _format_resend_result, _resend_needs_front_desk

    assert "front desk" in _format_resend_result(burst, language="en")
    assert _resend_needs_front_desk(burst)


def test_successful_resend_still_consumes_the_cap_after_a_refunded_failure(two_businesses, monkeypatch):
    token_a, business_id_a = two_businesses["token_a"], two_businesses["business_id_a"]
    service_id = _setup_booking_business(token_a)
    customer_id = _create_customer(token_a, email=_unique_email("refund-ok"))
    appointment_id = _book_appointment(business_id_a, customer_id, service_id)
    from app.services.notifications import dispatch_service

    monkeypatch.setitem(dispatch_service._PROVIDERS, "email", _FailingEmailProvider())
    assert _resend_email(business_id_a, customer_id, appointment_id)["success"] is False
    assert _resend_count(appointment_id) == 0

    _capture_email(monkeypatch)
    assert _resend_email(business_id_a, customer_id, appointment_id)["success"] is True
    assert _resend_count(appointment_id) == 1


# --- Phase 54: per-business content scope (single_business vs aggregator) -----------------------------------------
# Real gap found dogfooding SikshyaNepal (PHASE_STATUS.md Phase 53/54): the off_topic rule 0 in intent.py's system
# prompt was written assuming every tenant is a single local business, where naming another company really is out
# of scope -- wrong for an aggregator/info-hub tenant whose real content is inherently ABOUT other named
# institutions. content_scope="aggregator" relaxes that ONE rule's wording (never disables off_topic entirely);
# every pre-existing business defaults to "single_business" and sees today's exact prompt, unchanged.


def _set_content_scope(token: str, scope: str):
    return client.patch("/api/v1/business/me", headers=_auth_header(token), json={"content_scope": scope})


def test_content_scope_defaults_to_single_business_and_is_settable_via_the_business_api(two_businesses):
    token = two_businesses["token_a"]
    assert client.get("/api/v1/business/me", headers=_auth_header(token)).json()["content_scope"] == "single_business"
    resp = _set_content_scope(token, "aggregator")
    assert resp.status_code == 200, resp.text
    assert resp.json()["content_scope"] == "aggregator"
    assert client.get("/api/v1/business/me", headers=_auth_header(token)).json()["content_scope"] == "aggregator"
    assert _set_content_scope(token, "single_business").json()["content_scope"] == "single_business"
    # a value outside the enum, and an explicit null, are rejected -- never reach the DB
    assert _set_content_scope(token, "nonsense").status_code == 422
    assert client.patch("/api/v1/business/me", headers=_auth_header(token), json={"content_scope": None}).status_code == 422
    # other businesses are unaffected
    assert (
        client.get("/api/v1/business/me", headers=_auth_header(two_businesses["token_b"])).json()["content_scope"]
        == "single_business"
    )


def test_system_prompt_carries_aggregator_exception_only_for_aggregator_businesses(two_businesses, monkeypatch):
    """Real regression: SINGLE_BUSINESS (every pre-existing tenant, and the default for every new one) must see
    EXACTLY today's rule 0 wording -- this is the literal text sent to the real LLM, not just a Python-side flag,
    so the two must never silently drift apart."""
    token_a, business_id_a = two_businesses["token_a"], two_businesses["business_id_a"]
    stub = _stub_providers(monkeypatch, json.dumps({"intent": "greeting", "response": "Hi!"}))
    conversation_id = _create_conversation(business_id_a, _create_customer(token_a))
    _post_message(token_a, conversation_id, "hi")
    system_prompt = stub.calls[0][0]["content"]
    assert "AGGREGATOR EXCEPTION" not in system_prompt

    assert _set_content_scope(token_a, "aggregator").status_code == 200
    stub.calls.clear()
    conversation_id2 = _create_conversation(business_id_a, _create_customer(token_a))
    _post_message(token_a, conversation_id2, "hi")
    system_prompt2 = stub.calls[0][0]["content"]
    assert "AGGREGATOR EXCEPTION" in system_prompt2
    assert "naming an external institution is normal and expected" in system_prompt2


def test_off_topic_still_declines_for_a_genuinely_unrelated_question_on_an_aggregator_business(two_businesses, monkeypatch):
    """The narrowing must never become "off_topic disabled" -- a real aggregator tenant (SikshyaNepal-style) still
    declines something truly unrelated, exactly like a single_business tenant does, and still creates no handoff."""
    token_a, business_id_a = two_businesses["token_a"], two_businesses["business_id_a"]
    assert _set_content_scope(token_a, "aggregator").status_code == 200
    _stub_providers(
        monkeypatch,
        json.dumps({"intent": "off_topic", "response": "whatever the llm drafted", "needs_human_handoff": False}),
    )
    conversation_id = _create_conversation(business_id_a, _create_customer(token_a))
    body = _post_message(token_a, conversation_id, "What's today's weather like in Kathmandu?")
    assert body["intent"] == "off_topic"
    assert "is there something about that i can help with" in body["response"].lower()

    with SessionLocal() as db:
        from app.db.models.handoff import HumanHandoff

        assert db.query(HumanHandoff).filter(HumanHandoff.business_id == business_id_a).count() == 0


def test_aggregator_business_answers_normally_when_llm_recognizes_real_content(two_businesses, monkeypatch):
    """When the LLM (per the relaxed prompt) classifies a question naming an external institution as a real,
    answerable business question -- not off_topic -- the orchestrator lets that answer through untouched, exactly
    as it would for any other general_question."""
    token_a, business_id_a = two_businesses["token_a"], two_businesses["business_id_a"]
    assert _set_content_scope(token_a, "aggregator").status_code == 200
    real_answer = "Kathmandu University's latest notice is about the Fall 2026 admission deadline, Oct 15."
    _stub_providers(
        monkeypatch,
        json.dumps({"intent": "general_question", "response": real_answer, "needs_human_handoff": False}),
    )
    conversation_id = _create_conversation(business_id_a, _create_customer(token_a))
    body = _post_message(token_a, conversation_id, "What's the latest notice from Kathmandu University?")
    assert body["intent"] == "general_question"
    assert body["response"] == real_answer
