"""Owner alerts (app/services/owner_alert_service.py) and the dashboard upgrade request.

Real Postgres and the real handoff/booking code paths; only the email sender is replaced by a recorder, and the
background thread is run inline so the test can see what would have been sent."""

import uuid
from datetime import UTC, datetime, timedelta

import pytest
from fastapi.testclient import TestClient

import app.services.owner_alert_service as alerts
from app.db.database import SessionLocal
from app.db.models.appointment import Appointment, AppointmentStatus
from app.db.models.business import Business, BusinessPlan
from app.db.models.conversation import Conversation
from app.db.models.customer import Customer
from app.db.models.service import Service
from app.main import app
from app.schemas.conversation import ConversationIntent
from app.services import handoff_service

client = TestClient(app)


@pytest.fixture
def sent(monkeypatch):
    outbox = []

    def record(*, to, subject, body, credentials=None):
        outbox.append({"to": to, "subject": subject, "body": body})
        return True

    monkeypatch.setattr(alerts, "_send", record)
    monkeypatch.setattr(alerts, "_in_background", lambda **kw: record(**kw))
    return outbox


@pytest.fixture
def biz():
    email = f"alerts-{uuid.uuid4().hex[:10]}@example.com"
    reg = client.post(
        "/api/v1/auth/register",
        json={"business_name": "Alert Clinic", "timezone": "Asia/Kathmandu", "email": email, "password": "correcthorse1"},
    )
    token = client.post("/api/v1/auth/login", json={"email": email, "password": "correcthorse1"}).json()["access_token"]
    business_id = uuid.UUID(reg.json()["business_id"])
    with SessionLocal() as db:
        customer = Customer(business_id=business_id, name="Sita Gurung", phone="9800000001", email="sita@example.com")
        db.add(customer)
        db.flush()
        conversation = Conversation(business_id=business_id, customer_id=customer.id, channel="whatsapp", status="active")
        db.add(conversation)
        db.commit()
        ids = {"business": business_id, "customer": customer.id, "conversation": conversation.id}
    yield ids, email, {"Authorization": f"Bearer {token}"}
    with SessionLocal() as db:
        db.delete(db.get(Business, business_id))
        db.commit()


def _complaint(ids):
    with SessionLocal() as db:
        return handoff_service.maybe_create_handoff(
            db, business_id=ids["business"], conversation_id=ids["conversation"],
            intent=ConversationIntent.COMPLAINT, best_similarity=None,
        )


def test_new_handoff_emails_the_owner_once_with_a_link_to_the_conversation(biz, sent):
    ids, owner_email, _ = biz
    _complaint(ids)
    _complaint(ids)  # same conversation, still open: no second email
    assert len(sent) == 1
    assert sent[0]["to"] == [owner_email]
    assert "Sita Gurung needs a person" in sent[0]["subject"]
    assert f"/dashboard/inbox/{ids['conversation']}" in sent[0]["body"]


def test_no_alert_when_the_owner_turned_alerts_off(biz, sent):
    ids, _, headers = biz
    resp = client.patch("/api/v1/business/me", headers=headers, json={"owner_alerts_enabled": False})
    assert resp.status_code == 200 and resp.json()["owner_alerts_enabled"] is False
    _complaint(ids)
    assert sent == []


def test_new_chat_booking_emails_the_owner_with_the_details(biz, sent):
    ids, owner_email, _ = biz
    with SessionLocal() as db:
        service = Service(business_id=ids["business"], name="Teeth Cleaning", price=1500, duration_minutes=45)
        db.add(service)
        db.flush()
        appointment = Appointment(
            business_id=ids["business"], customer_id=ids["customer"], service_id=service.id,
            scheduled_at=datetime.now(UTC) + timedelta(days=2), duration_minutes=45, status=AppointmentStatus.CONFIRMED,
        )
        db.add(appointment)
        db.commit()
        alerts.notify_new_booking(db, appointment=appointment)
    assert len(sent) == 1
    assert sent[0]["to"] == [owner_email]
    assert "New booking: Sita Gurung, Teeth Cleaning" in sent[0]["subject"]
    assert "9800000001" in sent[0]["body"]


def test_alert_failure_never_reaches_the_caller(biz, monkeypatch):
    ids, _, _ = biz

    def explode(*a, **k):
        raise RuntimeError("smtp down")

    monkeypatch.setattr(alerts, "_in_background", explode)
    handoff = _complaint(ids)  # must not raise
    assert handoff is not None


def test_upgrade_request_is_recorded_and_sent_to_the_platform_team(biz, sent, monkeypatch):
    _, _, headers = biz
    monkeypatch.setattr(alerts.settings, "platform_support_email", "support@nightguard.example")
    resp = client.post("/api/v1/business/plan/upgrade-request", headers=headers)
    assert resp.status_code == 200, resp.text
    assert resp.json()["team_notified"] is True
    assert sent[0]["to"] == ["support@nightguard.example"]
    assert "Alert Clinic" in sent[0]["subject"]
    me = client.get("/api/v1/business/me", headers=headers).json()
    assert me["upgrade_requested_at"] is not None


def test_upgrade_request_is_kept_even_when_no_support_email_is_configured(biz, monkeypatch):
    _, _, headers = biz
    monkeypatch.setattr(alerts.settings, "platform_support_email", "")
    monkeypatch.setattr(alerts.settings, "gmail_address", "")
    resp = client.post("/api/v1/business/plan/upgrade-request", headers=headers)
    assert resp.status_code == 200
    assert resp.json()["team_notified"] is False
    assert client.get("/api/v1/business/me", headers=headers).json()["upgrade_requested_at"] is not None


def test_premium_business_cannot_request_an_upgrade(biz):
    ids, _, headers = biz
    with SessionLocal() as db:
        db.get(Business, ids["business"]).plan = BusinessPlan.PREMIUM
        db.commit()
    assert client.post("/api/v1/business/plan/upgrade-request", headers=headers).status_code == 409


def test_plan_features_describe_what_premium_really_unlocks(biz):
    _, _, headers = biz
    features = client.get("/api/v1/business/plan", headers=headers).json()["features"]
    assert any("Everything" not in f and "AI assistant" in f for f in features)
    assert not any("upcoming" in f.lower() for f in features)
