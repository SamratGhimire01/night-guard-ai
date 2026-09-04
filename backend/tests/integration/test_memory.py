"""Phase 7 — conversation memory layer (app/memory/).

Covers short-term recall, customer/appointment context bounds, cross-tenant
isolation, and conversation summarization (stubbed ChatProvider for cheap/fast
coverage; one real-API test, skipped by default — see test_summarization_real_api).
"""

import os
import uuid
from datetime import UTC, datetime, timedelta

import pytest
from fastapi.testclient import TestClient

from app.db.database import SessionLocal
from app.db.models.appointment import Appointment, AppointmentStatus
from app.db.models.business import Business
from app.db.models.conversation import Conversation, Message, MessageSenderType
from app.db.models.service import Service
from app.main import app
from app.memory import assemble_context, get_appointment_context, get_customer_context, get_recent_messages
from app.memory.summarization import DEFAULT_KEEP_RECENT, DEFAULT_THRESHOLD, maybe_summarize_conversation

client = TestClient(app)


def _unique_email(label: str) -> str:
    return f"{label}-{uuid.uuid4().hex[:10]}@example.com"


def _auth_header(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


@pytest.fixture
def two_businesses():
    email_a = _unique_email("mem-a-owner")
    email_b = _unique_email("mem-b-owner")

    resp_a = client.post(
        "/api/v1/auth/register",
        json={"business_name": "Memory A", "timezone": "UTC", "email": email_a, "password": "correcthorse1"},
    )
    resp_b = client.post(
        "/api/v1/auth/register",
        json={"business_name": "Memory B", "timezone": "UTC", "email": email_b, "password": "correcthorse1"},
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


def _create_customer(token: str, name: str = "Jordan Customer") -> uuid.UUID:
    resp = client.post(
        "/api/v1/customers",
        headers=_auth_header(token),
        json={"name": name, "phone": "555-0100", "email": "jordan@example.com", "preferred_language": "en"},
    )
    assert resp.status_code == 201, resp.text
    return uuid.UUID(resp.json()["id"])


def _create_conversation(business_id: uuid.UUID, customer_id: uuid.UUID) -> uuid.UUID:
    with SessionLocal() as db:
        conversation = Conversation(
            business_id=business_id, customer_id=customer_id, channel="sms", status="open"
        )
        db.add(conversation)
        db.commit()
        db.refresh(conversation)
        return conversation.id


def _add_message(conversation_id: uuid.UUID, sender_type: MessageSenderType, content: str) -> None:
    # Postgres now() is transaction-time, not statement-time — commit each message
    # separately so created_at actually advances and ordering is meaningfully tested.
    with SessionLocal() as db:
        db.add(Message(conversation_id=conversation_id, sender_type=sender_type, content=content))
        db.commit()


def _create_service(business_id: uuid.UUID) -> uuid.UUID:
    with SessionLocal() as db:
        service = Service(business_id=business_id, name="Checkup", price="50.00", duration_minutes=30)
        db.add(service)
        db.commit()
        db.refresh(service)
        return service.id


def _add_appointment(
    business_id: uuid.UUID,
    customer_id: uuid.UUID,
    service_id: uuid.UUID,
    *,
    status: AppointmentStatus,
    scheduled_at: datetime,
) -> uuid.UUID:
    with SessionLocal() as db:
        appointment = Appointment(
            business_id=business_id,
            customer_id=customer_id,
            service_id=service_id,
            scheduled_at=scheduled_at,
            duration_minutes=30,
            status=status,
        )
        db.add(appointment)
        db.commit()
        db.refresh(appointment)
        return appointment.id


# --- short-term memory -------------------------------------------------------


def test_get_recent_messages_ordered_and_bounded(two_businesses):
    business_id_a = two_businesses["business_id_a"]
    customer_id = _create_customer(two_businesses["token_a"])
    conversation_id = _create_conversation(business_id_a, customer_id)

    for i in range(5):
        _add_message(conversation_id, MessageSenderType.CUSTOMER, f"message {i}")

    with SessionLocal() as db:
        recent = get_recent_messages(db, conversation_id=conversation_id, business_id=business_id_a, limit=3)

    assert [m.content for m in recent] == ["message 2", "message 3", "message 4"]
    # chronological, not reverse-chronological
    assert recent[0].created_at <= recent[1].created_at <= recent[2].created_at


def test_get_recent_messages_cross_tenant_returns_empty(two_businesses):
    business_id_a = two_businesses["business_id_a"]
    business_id_b = two_businesses["business_id_b"]
    customer_id = _create_customer(two_businesses["token_a"])
    conversation_id = _create_conversation(business_id_a, customer_id)
    _add_message(conversation_id, MessageSenderType.CUSTOMER, "secret business A message")

    with SessionLocal() as db:
        # Business B calling with Business A's real (guessed) conversation_id.
        leaked = get_recent_messages(db, conversation_id=conversation_id, business_id=business_id_b, limit=10)
        # And a fully random conversation_id under B's own business_id.
        random_result = get_recent_messages(
            db, conversation_id=uuid.uuid4(), business_id=business_id_b, limit=10
        )

    assert leaked == []
    assert random_result == []


# --- customer profile memory --------------------------------------------------


def test_get_customer_context_returns_compact_profile_and_is_tenant_scoped(two_businesses):
    business_id_a = two_businesses["business_id_a"]
    business_id_b = two_businesses["business_id_b"]
    customer_id = _create_customer(two_businesses["token_a"], name="Priya Patel")

    with SessionLocal() as db:
        own = get_customer_context(db, customer_id=customer_id, business_id=business_id_a)
        cross_tenant = get_customer_context(db, customer_id=customer_id, business_id=business_id_b)

    assert own == {
        "id": str(customer_id),
        "name": "Priya Patel",
        "phone": "555-0100",
        "email": "jordan@example.com",
        "preferred_language": "en",
    }
    assert cross_tenant is None


# --- appointment memory --------------------------------------------------------


def test_get_appointment_context_bounds_past_but_not_active(two_businesses):
    business_id_a = two_businesses["business_id_a"]
    customer_id = _create_customer(two_businesses["token_a"])
    service_id = _create_service(business_id_a)
    now = datetime.now(UTC)

    # 5 past appointments (more than the 3-item bound), oldest to newest.
    past_ids = []
    for i in range(5):
        past_ids.append(
            _add_appointment(
                business_id_a,
                customer_id,
                service_id,
                status=AppointmentStatus.COMPLETED,
                scheduled_at=now - timedelta(days=30 - i),
            )
        )
    # 2 active/upcoming appointments — must ALWAYS be included regardless of bound.
    active_ids = {
        _add_appointment(
            business_id_a, customer_id, service_id, status=AppointmentStatus.CONFIRMED, scheduled_at=now + timedelta(days=1)
        ),
        _add_appointment(
            business_id_a, customer_id, service_id, status=AppointmentStatus.PENDING, scheduled_at=now + timedelta(days=5)
        ),
    }

    with SessionLocal() as db:
        context = get_appointment_context(db, customer_id=customer_id, business_id=business_id_a)

    assert {a["id"] for a in context["active"]} == {str(i) for i in active_ids}
    assert len(context["recent_past"]) == 3, "must be bounded to 3, not all 5 past appointments"
    # the 3 MOST RECENT past ones (the last 3 inserted, i.e. closest to `now`).
    assert {a["id"] for a in context["recent_past"]} == {str(i) for i in past_ids[-3:]}
    assert all(a["service"] == "Checkup" for a in context["active"] + context["recent_past"])


# --- summarization (stubbed ChatProvider — no real API cost) ------------------


class _StubChatProvider:
    def __init__(self, reply: str = "STUB SUMMARY"):
        self.reply = reply
        self.calls: list[list[dict[str, str]]] = []

    def chat(self, messages: list[dict[str, str]]) -> str:
        self.calls.append(messages)
        return self.reply


def test_maybe_summarize_conversation_below_threshold_is_noop(two_businesses, monkeypatch):
    import app.memory.summarization as summarization_module

    stub = _StubChatProvider()
    monkeypatch.setattr(summarization_module, "get_chat_provider", lambda: stub)

    business_id_a = two_businesses["business_id_a"]
    customer_id = _create_customer(two_businesses["token_a"])
    conversation_id = _create_conversation(business_id_a, customer_id)
    for i in range(5):
        _add_message(conversation_id, MessageSenderType.CUSTOMER, f"msg {i}")

    with SessionLocal() as db:
        result = maybe_summarize_conversation(db, conversation_id=conversation_id, business_id=business_id_a)

    assert result.summary is None
    assert stub.calls == []


def test_maybe_summarize_conversation_folds_older_messages_and_advances_incrementally(two_businesses, monkeypatch):
    import app.memory.summarization as summarization_module

    stub = _StubChatProvider(reply="Customer asked about hours; confirmed open Mon-Fri.")
    monkeypatch.setattr(summarization_module, "get_chat_provider", lambda: stub)

    business_id_a = two_businesses["business_id_a"]
    customer_id = _create_customer(two_businesses["token_a"])
    conversation_id = _create_conversation(business_id_a, customer_id)

    total_initial = DEFAULT_THRESHOLD + 5  # comfortably past the threshold
    for i in range(total_initial):
        _add_message(conversation_id, MessageSenderType.CUSTOMER, f"msg {i}")

    with SessionLocal() as db:
        result = maybe_summarize_conversation(db, conversation_id=conversation_id, business_id=business_id_a)

    expected_boundary = total_initial - DEFAULT_KEEP_RECENT
    assert result.summary == stub.reply
    assert result.summarized_message_count == expected_boundary
    assert len(stub.calls) == 1
    assert "Existing summary" not in stub.calls[0][1]["content"]  # first summarization, nothing to fold in

    # Calling again with no new messages must be a no-op (no wasted LLM call).
    with SessionLocal() as db:
        result2 = maybe_summarize_conversation(db, conversation_id=conversation_id, business_id=business_id_a)
    assert result2.summarized_message_count == expected_boundary
    assert len(stub.calls) == 1  # still 1 — not called again

    # 3 more messages arrive; only the NEWLY aged-out ones should be summarized,
    # combined with the existing summary (not the whole history re-sent).
    for i in range(3):
        _add_message(conversation_id, MessageSenderType.CUSTOMER, f"followup {i}")

    with SessionLocal() as db:
        result3 = maybe_summarize_conversation(db, conversation_id=conversation_id, business_id=business_id_a)

    assert result3.summarized_message_count == expected_boundary + 3
    assert len(stub.calls) == 2
    second_call_content = stub.calls[1][1]["content"]
    assert "Existing summary" in second_call_content
    # The 3 newly aged-out messages are the ones that just fell out of the
    # keep_recent window (msg 15/16/17) — NOT the 3 brand-new "followup"
    # messages, which are still within the fresh keep_recent(10) window. This
    # is the incremental-boundary behavior working correctly, not the whole
    # 28-message history being re-sent.
    for i in range(expected_boundary, expected_boundary + 3):
        assert f"msg {i}" in second_call_content
    assert "followup" not in second_call_content
    assert second_call_content.count("customer: msg") == 3  # exactly 3 newly-old messages, nothing more


def test_maybe_summarize_conversation_cross_tenant_returns_none(two_businesses, monkeypatch):
    import app.memory.summarization as summarization_module

    stub = _StubChatProvider()
    monkeypatch.setattr(summarization_module, "get_chat_provider", lambda: stub)

    business_id_a = two_businesses["business_id_a"]
    business_id_b = two_businesses["business_id_b"]
    customer_id = _create_customer(two_businesses["token_a"])
    conversation_id = _create_conversation(business_id_a, customer_id)

    with SessionLocal() as db:
        result = maybe_summarize_conversation(db, conversation_id=conversation_id, business_id=business_id_b)

    assert result is None
    assert stub.calls == []


# --- assembled context ---------------------------------------------------------


def test_assemble_context_is_bounded_and_reports_size(two_businesses, monkeypatch):
    import app.memory.summarization as summarization_module

    stub = _StubChatProvider(reply="Earlier: customer discussed rescheduling repeatedly.")
    monkeypatch.setattr(summarization_module, "get_chat_provider", lambda: stub)

    business_id_a = two_businesses["business_id_a"]
    customer_id = _create_customer(two_businesses["token_a"])
    conversation_id = _create_conversation(business_id_a, customer_id)
    service_id = _create_service(business_id_a)
    _add_appointment(
        business_id_a,
        customer_id,
        service_id,
        status=AppointmentStatus.CONFIRMED,
        scheduled_at=datetime.now(UTC) + timedelta(days=2),
    )

    total = DEFAULT_THRESHOLD + 5
    for i in range(total):
        _add_message(conversation_id, MessageSenderType.CUSTOMER, f"message number {i}")

    with SessionLocal() as db:
        maybe_summarize_conversation(db, conversation_id=conversation_id, business_id=business_id_a)
        context = assemble_context(db, conversation_id=conversation_id, business_id=business_id_a)

    assert context["summary"] == stub.reply
    # bounded: only the recent window of raw messages, never all `total` messages.
    assert len(context["recent_messages"]) == 10
    assert context["customer"]["id"] == str(customer_id)
    assert len(context["appointments"]["active"]) == 1
    assert context["_approx_size"]["words"] > 0
    assert context["_approx_size"]["tokens_estimate"] > 0


def test_assemble_context_cross_tenant_returns_none(two_businesses):
    business_id_a = two_businesses["business_id_a"]
    business_id_b = two_businesses["business_id_b"]
    customer_id = _create_customer(two_businesses["token_a"])
    conversation_id = _create_conversation(business_id_a, customer_id)

    with SessionLocal() as db:
        result = assemble_context(db, conversation_id=conversation_id, business_id=business_id_b)

    assert result is None


# --- real API (skipped by default — set RUN_REAL_LLM_TESTS=1 to exercise it) --


@pytest.mark.skipif(
    not os.environ.get("RUN_REAL_LLM_TESTS"),
    reason="hits the real chat LLM; run explicitly with RUN_REAL_LLM_TESTS=1",
)
def test_summarization_real_api(two_businesses):
    business_id_a = two_businesses["business_id_a"]
    customer_id = _create_customer(two_businesses["token_a"])
    conversation_id = _create_conversation(business_id_a, customer_id)

    script = [
        "Hi, I'd like to book a dental cleaning.",
        "Sure! What day works for you?",
        "How about next Tuesday afternoon?",
        "We have a 2pm slot open with Dr. Lee, does that work?",
        "Yes that works, please book it.",
        "Booked! Anything else?",
        "Actually, can we make it 3pm instead?",
        "Sure, moved to 3pm with Dr. Lee.",
        "Perfect, thank you.",
        "You're welcome! See you Tuesday.",
    ]
    for i, text in enumerate(script * 3):  # well past DEFAULT_THRESHOLD
        sender = MessageSenderType.CUSTOMER if i % 2 == 0 else MessageSenderType.AGENT
        _add_message(conversation_id, sender, text)

    with SessionLocal() as db:
        result = maybe_summarize_conversation(db, conversation_id=conversation_id, business_id=business_id_a)

    assert result.summary
    assert len(result.summary.strip()) > 0
    print(f"\nREAL SUMMARY OUTPUT:\n{result.summary}\n")
