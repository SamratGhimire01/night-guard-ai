"""Phase 18 — automatic follow-up (app/services/followups/,
POST /api/v1/followups/run).

Real DB throughout. Conversations/messages are inserted directly via the ORM
with explicit (backdated) created_at timestamps — the same "manipulate
timestamps" technique test_memory.py already established, and exactly what
this phase's own ticket explicitly permits ("manipulate timestamps or
genuinely wait, your call") — rather than waiting hours in real time. Only
the SMTP network call is ever stubbed; the detection query, the anti-spam DB
constraint, and the consent-safety logic are all real.
"""

import uuid
from datetime import date, datetime, timedelta, timezone
from zoneinfo import ZoneInfo

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.exc import IntegrityError

from app.core.security import create_access_token
from app.db.database import SessionLocal
from app.db.models.business import Business, BusinessUser, BusinessUserRole
from app.db.models.conversation import Conversation, Message, MessageSenderType
from app.db.models.customer import Customer
from app.db.models.follow_up import FollowUp
from app.main import app
from app.services.followups import followup_service
from app.services.followups.content import compose_followup_email
from app.services.notifications.base import NotificationDeliveryError

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


@pytest.fixture
def two_businesses():
    email_a = _unique_email("fu-a-owner")
    email_b = _unique_email("fu-b-owner")
    resp_a = client.post(
        "/api/v1/auth/register",
        json={"business_name": "Follow-up Test A", "timezone": "UTC", "email": email_a, "password": "correcthorse1"},
    )
    resp_b = client.post(
        "/api/v1/auth/register",
        json={"business_name": "Follow-up Test B", "timezone": "UTC", "email": email_b, "password": "correcthorse1"},
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


@pytest.fixture
def staff_token(two_businesses):
    business_id_a = two_businesses["business_id_a"]
    with SessionLocal() as db:
        staff_user = BusinessUser(
            business_id=business_id_a,
            email=_unique_email("fu-staff"),
            hashed_password="unused",
            role=BusinessUserRole.STAFF,
        )
        db.add(staff_user)
        db.commit()
        db.refresh(staff_user)
        return create_access_token(user_id=staff_user.id, business_id=business_id_a, role=staff_user.role.value)


def _enable_followups(token: str):
    resp = client.patch("/api/v1/business/me", json={"follow_ups_enabled": True}, headers=_auth_header(token))
    assert resp.status_code == 200, resp.text


def _create_customer(token: str, **kwargs) -> dict:
    payload = {"name": "Follow-up Customer", **kwargs}
    resp = client.post("/api/v1/customers", json=payload, headers=_auth_header(token))
    assert resp.status_code == 201, resp.text
    return resp.json()


def _create_conversation(business_id: uuid.UUID, customer_id: uuid.UUID, created_at: datetime) -> uuid.UUID:
    with SessionLocal() as db:
        conversation = Conversation(
            business_id=business_id, customer_id=customer_id, channel="sms", status="open", created_at=created_at
        )
        db.add(conversation)
        db.commit()
        db.refresh(conversation)
        return conversation.id


def _add_message(conversation_id, sender_type, content, created_at, detected_intent=None) -> uuid.UUID:
    with SessionLocal() as db:
        msg = Message(
            conversation_id=conversation_id,
            sender_type=sender_type,
            content=content,
            created_at=created_at,
            detected_intent=detected_intent,
        )
        db.add(msg)
        db.commit()
        db.refresh(msg)
        return msg.id


_OLD = datetime.now(timezone.utc) - timedelta(hours=48)
_RECENT = datetime.now(timezone.utc) - timedelta(minutes=5)


class _FakeEmailProvider:
    """Scripted: succeeds unless constructed with should_fail=True."""

    def __init__(self, should_fail: bool = False):
        self.should_fail = should_fail
        self.calls = []

    def send(self, *, to, subject, body, html_body=None, attachments=None, inline_images=None, credentials=None):
        self.calls.append({"to": to, "subject": subject, "body": body, "html_body": html_body})
        if self.should_fail:
            raise NotificationDeliveryError("smtp down", transient=True)
        return "250 ok"


@pytest.fixture
def cold_pricing_conversation(two_businesses):
    """A real, cold, pricing-interest conversation for Business A with no
    booking — the base "would qualify" scenario every test below tweaks one
    variable of."""
    token = two_businesses["token_a"]
    _enable_followups(token)
    customer = _create_customer(token, email="lead@example.com")
    conversation_id = _create_conversation(two_businesses["business_id_a"], uuid.UUID(customer["id"]), _OLD)
    _add_message(
        conversation_id,
        MessageSenderType.CUSTOMER,
        "How much does a teeth cleaning cost?",
        _OLD,
        detected_intent="pricing_question",
    )
    _add_message(
        conversation_id,
        MessageSenderType.AGENT,
        "A standard cleaning is $95.",
        _OLD + timedelta(minutes=1),
    )
    return {
        "business_id": two_businesses["business_id_a"],
        "token": token,
        "customer": customer,
        "conversation_id": conversation_id,
    }


# --- the real, positive scenario -----------------------------------------------------


def test_real_followup_sent_for_cold_pricing_conversation(cold_pricing_conversation, monkeypatch):
    fake = _FakeEmailProvider()
    monkeypatch.setattr(followup_service, "EmailNotificationProvider", lambda: fake)

    results = followup_service.run_followups(
        SessionLocal(), business_id=cold_pricing_conversation["business_id"]
    )

    assert len(results) == 1
    assert results[0]["status"] == "sent"
    assert results[0]["channel"] == "email"
    assert fake.calls[0]["to"] == "lead@example.com"
    assert "How much does a teeth cleaning cost?" in fake.calls[0]["body"]
    assert "How much does a teeth cleaning cost?" in fake.calls[0]["html_body"]

    with SessionLocal() as db:
        row = db.query(FollowUp).filter(FollowUp.conversation_id == cold_pricing_conversation["conversation_id"]).one()
        assert row.status == "sent"
        assert row.channel == "email"
        assert row.trigger_message_id is not None
        assert row.sent_at is not None


def test_compose_followup_email_quotes_real_message_and_autoescapes():
    business = Business(name="A & B <Dental>", timezone="UTC")
    customer = Customer(name="<script>x</script>")
    message = Message(content="Do you offer teeth whitening, and how much?", created_at=datetime.now(timezone.utc))
    subject, body, html = compose_followup_email(business=business, customer=customer, interest_message=message)
    assert "Do you offer teeth whitening, and how much?" in body
    assert "Do you offer teeth whitening, and how much?" in html
    assert "<script>" not in html
    assert "&lt;script&gt;" in html


# --- toggle: disabling blocks a candidate that would otherwise qualify ---------------


def test_disabling_followups_blocks_an_otherwise_qualifying_candidate(cold_pricing_conversation):
    client.patch(
        "/api/v1/business/me", json={"follow_ups_enabled": False}, headers=_auth_header(cold_pricing_conversation["token"])
    )
    with SessionLocal() as db:
        candidates = followup_service.identify_followup_candidates(db, business_id=cold_pricing_conversation["business_id"])
    assert candidates == []

    with SessionLocal() as db:
        results = followup_service.run_followups(db, business_id=cold_pricing_conversation["business_id"])
    assert results == []
    with SessionLocal() as db:
        count = db.query(FollowUp).filter(FollowUp.conversation_id == cold_pricing_conversation["conversation_id"]).count()
        assert count == 0


# --- anti-spam: second run never duplicates, DB constraint is the real backstop -----


def test_second_run_does_not_send_a_duplicate_followup(cold_pricing_conversation, monkeypatch):
    fake = _FakeEmailProvider()
    monkeypatch.setattr(followup_service, "EmailNotificationProvider", lambda: fake)

    first = followup_service.run_followups(SessionLocal(), business_id=cold_pricing_conversation["business_id"])
    assert len(first) == 1
    assert fake.calls  # real send happened once

    second = followup_service.run_followups(SessionLocal(), business_id=cold_pricing_conversation["business_id"])
    assert second == [], "detection must not re-propose an already-handled conversation"
    assert len(fake.calls) == 1, "no second real send attempt was ever made"

    with SessionLocal() as db:
        rows = db.query(FollowUp).filter(FollowUp.conversation_id == cold_pricing_conversation["conversation_id"]).all()
        assert len(rows) == 1, "exactly one FollowUp row exists, never two"


def test_db_constraint_itself_rejects_a_second_followup_row(cold_pricing_conversation, monkeypatch):
    """The real, load-bearing proof: bypass detection entirely and try to
    insert a second FollowUp row for the same conversation directly — the
    unique constraint, not application logic, must be what refuses it."""
    fake = _FakeEmailProvider()
    monkeypatch.setattr(followup_service, "EmailNotificationProvider", lambda: fake)
    followup_service.run_followups(SessionLocal(), business_id=cold_pricing_conversation["business_id"])

    with SessionLocal() as db:
        row = db.query(FollowUp).filter(FollowUp.conversation_id == cold_pricing_conversation["conversation_id"]).one()
        duplicate = FollowUp(
            business_id=cold_pricing_conversation["business_id"],
            customer_id=row.customer_id,
            conversation_id=row.conversation_id,
            status="sent",
            scheduled_at=datetime.now(timezone.utc),
            sent_at=datetime.now(timezone.utc),
            channel="email",
        )
        db.add(duplicate)
        with pytest.raises(IntegrityError):
            db.commit()
        db.rollback()


# --- consent safety: no email on file, no SMS workaround -----------------------------


def test_no_email_on_file_skips_without_any_sms_workaround(two_businesses, monkeypatch):
    token = two_businesses["token_a"]
    _enable_followups(token)
    # Real SMS "consent" exists for booking purposes (business.sms_enabled +
    # customer.sms_opt_in), but must NEVER be reused for a follow-up — that's
    # the whole point of this test.
    client.patch("/api/v1/business/me", json={"sms_enabled": True}, headers=_auth_header(token))
    customer = _create_customer(token, phone="+15551234567", sms_opt_in=True)  # no email
    conversation_id = _create_conversation(two_businesses["business_id_a"], uuid.UUID(customer["id"]), _OLD)
    _add_message(
        conversation_id, MessageSenderType.CUSTOMER, "What's the price for a checkup?", _OLD, detected_intent="pricing_question"
    )

    from app.services.notifications import sms_provider as sms_provider_module

    class _ExplodingSMSProvider:
        def send(self, **kwargs):
            raise AssertionError("follow-up must NEVER attempt SMS, even when SMS consent exists for booking purposes")

    monkeypatch.setattr(sms_provider_module, "SMSNotificationProvider", _ExplodingSMSProvider)
    monkeypatch.setattr(sms_provider_module, "TwilioSMSProvider", _ExplodingSMSProvider)

    with SessionLocal() as db:
        results = followup_service.run_followups(db, business_id=two_businesses["business_id_a"])

    assert len(results) == 1
    assert results[0]["status"] == "skipped_no_consent"
    assert results[0]["channel"] is None

    with SessionLocal() as db:
        row = db.query(FollowUp).filter(FollowUp.conversation_id == conversation_id).one()
        assert row.status == "skipped_no_consent"
        assert row.channel is None


# --- a real booking excludes the conversation from ever getting a follow-up ----------


def test_conversation_that_resulted_in_a_booking_never_gets_a_followup(cold_pricing_conversation):
    token = cold_pricing_conversation["token"]
    days = [{"day_of_week": d, "open_time": "00:00:00", "close_time": "23:45:00"} for d in range(7)]
    client.put("/api/v1/business/hours", json={"days": days}, headers=_auth_header(token))
    service = client.post(
        "/api/v1/services", json={"name": "Cleaning", "price": "50.00", "duration_minutes": 30}, headers=_auth_header(token)
    )
    when = datetime.combine(_next_weekday(0), datetime.min.time()).replace(hour=10, tzinfo=ZoneInfo("UTC"))
    book = client.post(
        "/api/v1/appointments",
        json={
            "customer_id": cold_pricing_conversation["customer"]["id"],
            "service_id": service.json()["id"],
            "scheduled_at": when.isoformat(),
        },
        headers=_auth_header(token),
    )
    assert book.status_code == 201, book.text

    with SessionLocal() as db:
        candidates = followup_service.identify_followup_candidates(db, business_id=cold_pricing_conversation["business_id"])
    assert candidates == [], "a customer who already booked must never be nagged with a follow-up"


# --- still-active conversation (not yet cold) is excluded ----------------------------


def test_recently_active_conversation_is_not_yet_a_candidate(two_businesses):
    token = two_businesses["token_a"]
    _enable_followups(token)
    customer = _create_customer(token, email="active@example.com")
    conversation_id = _create_conversation(two_businesses["business_id_a"], uuid.UUID(customer["id"]), _RECENT)
    _add_message(
        conversation_id, MessageSenderType.CUSTOMER, "How much for a cleaning?", _RECENT, detected_intent="pricing_question"
    )

    with SessionLocal() as db:
        candidates = followup_service.identify_followup_candidates(db, business_id=two_businesses["business_id_a"])
    assert candidates == []


# --- no real interest shown (e.g. only a greeting) is excluded -----------------------


def test_conversation_without_real_interest_intent_is_excluded(two_businesses):
    token = two_businesses["token_a"]
    _enable_followups(token)
    customer = _create_customer(token, email="justsaidhi@example.com")
    conversation_id = _create_conversation(two_businesses["business_id_a"], uuid.UUID(customer["id"]), _OLD)
    _add_message(conversation_id, MessageSenderType.CUSTOMER, "Hi there", _OLD, detected_intent="greeting")

    with SessionLocal() as db:
        candidates = followup_service.identify_followup_candidates(db, business_id=two_businesses["business_id_a"])
    assert candidates == []


# --- cross-tenant isolation -----------------------------------------------------------


def test_followups_are_cross_tenant_isolated(two_businesses, monkeypatch):
    token_a, token_b = two_businesses["token_a"], two_businesses["token_b"]
    _enable_followups(token_a)
    _enable_followups(token_b)

    cust_a = _create_customer(token_a, email="a-lead@example.com")
    cust_b = _create_customer(token_b, email="b-lead@example.com")
    conv_a = _create_conversation(two_businesses["business_id_a"], uuid.UUID(cust_a["id"]), _OLD)
    conv_b = _create_conversation(two_businesses["business_id_b"], uuid.UUID(cust_b["id"]), _OLD)
    _add_message(conv_a, MessageSenderType.CUSTOMER, "Pricing for A?", _OLD, detected_intent="pricing_question")
    _add_message(conv_b, MessageSenderType.CUSTOMER, "Pricing for B?", _OLD, detected_intent="pricing_question")

    fake = _FakeEmailProvider()
    monkeypatch.setattr(followup_service, "EmailNotificationProvider", lambda: fake)

    results = followup_service.run_followups(SessionLocal(), business_id=two_businesses["business_id_a"])
    assert len(results) == 1
    assert results[0]["conversation_id"] == str(conv_a)

    with SessionLocal() as db:
        assert db.query(FollowUp).filter(FollowUp.conversation_id == conv_a).count() == 1
        assert db.query(FollowUp).filter(FollowUp.conversation_id == conv_b).count() == 0
    assert fake.calls[0]["to"] == "a-lead@example.com"


# --- provider failure never crashes, still claims the conversation -------------------


def test_provider_failure_marks_failed_and_still_claims_the_conversation(cold_pricing_conversation, monkeypatch):
    fake = _FakeEmailProvider(should_fail=True)
    monkeypatch.setattr(followup_service, "EmailNotificationProvider", lambda: fake)

    results = followup_service.run_followups(SessionLocal(), business_id=cold_pricing_conversation["business_id"])
    assert results[0]["status"] == "failed"

    with SessionLocal() as db:
        row = db.query(FollowUp).filter(FollowUp.conversation_id == cold_pricing_conversation["conversation_id"]).one()
        assert row.status == "failed"

    # A second run must NOT retry it — "at most one, ever" applies to failures too.
    second = followup_service.run_followups(SessionLocal(), business_id=cold_pricing_conversation["business_id"])
    assert second == []


# --- RBAC + real HTTP endpoint --------------------------------------------------------


def test_staff_forbidden_from_followups_run(staff_token):
    resp = client.post("/api/v1/followups/run", headers=_auth_header(staff_token))
    assert resp.status_code == 403, resp.text


def test_owner_can_trigger_real_followups_endpoint(cold_pricing_conversation, monkeypatch):
    fake = _FakeEmailProvider()
    monkeypatch.setattr(followup_service, "EmailNotificationProvider", lambda: fake)

    resp = client.post("/api/v1/followups/run", headers=_auth_header(cold_pricing_conversation["token"]))
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["processed"] == 1
    assert body["results"][0]["status"] == "sent"


# --- intent persistence actually wired from the real orchestrator --------------------


def test_orchestrator_persists_real_detected_intent(two_businesses, monkeypatch):
    import json as jsonlib

    from app.services.conversation import intent as intent_module
    from app.services.conversation import orchestrator as orchestrator_module

    class _StubChat:
        def chat(self, messages):
            return jsonlib.dumps({"intent": "pricing_question", "response": "A cleaning is $95."})

    class _StubEmbed:
        def embed(self, texts):
            return [[0.01] * 1536 for _ in texts]

    monkeypatch.setattr(intent_module, "get_chat_provider", lambda: _StubChat())
    monkeypatch.setattr(orchestrator_module, "get_embedding_provider", lambda: _StubEmbed())

    token = two_businesses["token_a"]
    customer = _create_customer(token)
    conversation_id = _create_conversation(two_businesses["business_id_a"], uuid.UUID(customer["id"]), datetime.now(timezone.utc))

    resp = client.post(
        f"/api/v1/conversations/{conversation_id}/messages",
        json={"content": "How much is a cleaning?"},
        headers=_auth_header(token),
    )
    assert resp.status_code == 201, resp.text

    with SessionLocal() as db:
        customer_msg = (
            db.query(Message)
            .filter(Message.conversation_id == conversation_id, Message.sender_type == MessageSenderType.CUSTOMER)
            .one()
        )
        assert customer_msg.detected_intent == "pricing_question"


# ---------------------------------------------------------------- automatic runs (background scheduler) -------------


def test_scheduler_runs_followups_only_for_businesses_that_turned_them_on(monkeypatch):
    from app.services.followups import followup_service

    ids = []
    with SessionLocal() as db:
        for enabled in (True, False):
            b = Business(name=f"auto-followup-{enabled}", timezone="UTC", follow_ups_enabled=enabled)
            db.add(b)
            db.commit()
            ids.append((b.id, enabled))
    called = []
    monkeypatch.setattr(
        followup_service,
        "run_followups",
        lambda db, *, business_id, **kw: called.append(business_id) or [{"status": "sent"}, {"status": "skipped"}],
    )
    try:
        with SessionLocal() as db:
            sent = followup_service.run_due_followups(db)
        enabled_id, disabled_id = ids[0][0], ids[1][0]
        assert enabled_id in called
        assert disabled_id not in called
        assert sent >= 1
    finally:
        with SessionLocal() as db:
            for business_id, _ in ids:
                db.delete(db.get(Business, business_id))
            db.commit()


def test_one_business_failing_does_not_stop_the_others(monkeypatch):
    from app.services.followups import followup_service

    ids = []
    with SessionLocal() as db:
        for i in range(2):
            b = Business(name=f"auto-followup-fail-{i}", timezone="UTC", follow_ups_enabled=True)
            db.add(b)
            db.commit()
            ids.append(b.id)
    reached = []

    def fake(db, *, business_id, **kw):
        if business_id == ids[0]:
            raise RuntimeError("smtp down")
        reached.append(business_id)
        return []

    monkeypatch.setattr(followup_service, "run_followups", fake)
    try:
        with SessionLocal() as db:
            followup_service.run_due_followups(db)
        assert ids[1] in reached
    finally:
        with SessionLocal() as db:
            for business_id in ids:
                db.delete(db.get(Business, business_id))
            db.commit()


def test_scheduler_runs_followups_at_most_once_per_interval(monkeypatch):
    import asyncio

    from app.services import scheduler

    runs = []
    monkeypatch.setattr(scheduler, "_followups_sync", lambda: runs.append(1) or 0)
    monkeypatch.setattr(scheduler, "_last_followup_run", 0.0)
    interval = scheduler.settings.followup_run_interval_seconds
    asyncio.run(scheduler._followups_if_due(now=1000.0))
    asyncio.run(scheduler._followups_if_due(now=1000.0 + interval - 1))
    asyncio.run(scheduler._followups_if_due(now=1000.0 + interval + 1))
    assert len(runs) == 2
