"""Phase 13 — customer notifications (app/services/notifications/).

Real DB and real Appointment/Business/Service/Customer rows throughout — this
is what the acceptance criteria's real-conversation booking/cancel/reschedule
transcripts exercise too (see PHASE_STATUS.md). What's stubbed here is only
the actual network call: swapping the dispatch service's "email"/"sms"
provider instances for fakes with scripted outcomes, so the retry/bounded-
failure state machine can be proven deterministically without a real SMTP
server or a real Gmail inbox — the same "stub the LLM, not the business
logic" discipline test_conversation.py already applies to the chat provider.

The real, unstubbed Gmail SMTP send is proven separately (see
PHASE_STATUS.md's Phase 13 section) once GMAIL_ADDRESS/GMAIL_APP_PASSWORD
point at a real account.
"""

import uuid
from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

import pytest
from fastapi.testclient import TestClient

from app.db.database import SessionLocal
from app.db.models.business import Business
from app.db.models.notification import Notification, NotificationStatus
from app.main import app
from app.services import notifications as notifications_pkg
from app.services.notifications import dispatch_service
from app.services.notifications.base import NotificationDeliveryError
from app.services.notifications.email_provider import EmailNotificationProvider

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


class _FakeProvider:
    """Scripted provider: pops one outcome per call ("ok"/a string, or an
    Exception instance to raise); repeats the last outcome once exhausted."""

    def __init__(self, outcomes):
        self.outcomes = list(outcomes)
        self._last = self.outcomes[-1] if self.outcomes else "ok"
        self.calls = 0
        self.recipients = []

    def send(self, *, to, subject, body):
        self.calls += 1
        self.recipients.append(to)
        outcome = self.outcomes.pop(0) if self.outcomes else self._last
        if isinstance(outcome, Exception):
            raise outcome
        return outcome


@pytest.fixture
def business_ready():
    email = _unique_email("notif-owner")
    resp = client.post(
        "/api/v1/auth/register",
        json={"business_name": "Notif Test Co", "timezone": "UTC", "email": email, "password": "correcthorse1"},
    )
    assert resp.status_code == 201, resp.text
    business_id = uuid.UUID(resp.json()["business_id"])
    login = client.post("/api/v1/auth/login", json={"email": email, "password": "correcthorse1"})
    token = login.json()["access_token"]

    days = [{"day_of_week": d, "open_time": "09:00:00", "close_time": "17:00:00"} for d in range(6)]
    days.append({"day_of_week": 6, "closed": True})
    assert client.put("/api/v1/business/hours", json={"days": days}, headers=_auth_header(token)).status_code == 200

    service = client.post(
        "/api/v1/services",
        json={"name": "Cleaning", "price": "50.00", "duration_minutes": 30},
        headers=_auth_header(token),
    )
    assert service.status_code == 201, service.text

    customer = client.post(
        "/api/v1/customers",
        json={"name": "Jordan Lee", "email": "jordan@example.com"},
        headers=_auth_header(token),
    )
    assert customer.status_code == 201, customer.text

    data = {
        "business_id": business_id,
        "token": token,
        "service_id": uuid.UUID(service.json()["id"]),
        "customer_id": uuid.UUID(customer.json()["id"]),
    }
    yield data

    with SessionLocal() as db:
        business = db.get(Business, business_id)
        if business is not None:
            db.delete(business)
        db.commit()


def _book(token: str, service_id: uuid.UUID, customer_id: uuid.UUID, when: datetime) -> dict:
    resp = client.post(
        "/api/v1/appointments",
        json={"customer_id": str(customer_id), "service_id": str(service_id), "scheduled_at": when.isoformat()},
        headers=_auth_header(token),
    )
    assert resp.status_code == 201, resp.text
    return resp.json()


def test_booking_queues_and_sends_a_real_email_notification(business_ready, monkeypatch):
    """A real booking through POST /appointments (no LLM involved) queues a
    real Notification and dispatches it inline — with a real recipient email
    on file, a scripted provider success moves it straight to SENT."""
    fake = _FakeProvider(["250 message accepted for delivery"])
    monkeypatch.setitem(dispatch_service._PROVIDERS, "email", fake)

    when = datetime.combine(_next_weekday(0), datetime.min.time()).replace(hour=10, tzinfo=ZoneInfo("UTC"))
    appointment = _book(business_ready["token"], business_ready["service_id"], business_ready["customer_id"], when)

    with SessionLocal() as db:
        notifications = (
            db.query(Notification).filter(Notification.appointment_id == uuid.UUID(appointment["id"])).all()
        )
    assert len(notifications) == 1
    assert notifications[0].channel == "email"
    assert notifications[0].event_type == "booking_confirmed"
    assert notifications[0].status == NotificationStatus.SENT
    assert fake.calls == 1
    assert fake.recipients == ["jordan@example.com"]


def test_dispatch_retries_transient_failure_then_succeeds(business_ready, monkeypatch):
    fake = _FakeProvider(
        [
            NotificationDeliveryError("smtp hiccup", transient=True),
            NotificationDeliveryError("smtp hiccup again", transient=True),
            "250 ok",
        ]
    )
    monkeypatch.setitem(dispatch_service._PROVIDERS, "email", fake)
    monkeypatch.setattr(dispatch_service, "_RETRY_DELAY_SECONDS", 0)

    when = datetime.combine(_next_weekday(1), datetime.min.time()).replace(hour=10, tzinfo=ZoneInfo("UTC"))
    appointment = _book(business_ready["token"], business_ready["service_id"], business_ready["customer_id"], when)

    with SessionLocal() as db:
        notification = (
            db.query(Notification).filter(Notification.appointment_id == uuid.UUID(appointment["id"])).one()
        )
    assert notification.status == NotificationStatus.SENT
    assert fake.calls == 3, "must have retried exactly twice before succeeding on the 3rd attempt"


def test_dispatch_exhausts_bounded_retries_and_marks_failed(business_ready, monkeypatch):
    fake = _FakeProvider([NotificationDeliveryError("smtp down", transient=True)])
    monkeypatch.setitem(dispatch_service._PROVIDERS, "email", fake)
    monkeypatch.setattr(dispatch_service, "_RETRY_DELAY_SECONDS", 0)

    when = datetime.combine(_next_weekday(2), datetime.min.time()).replace(hour=10, tzinfo=ZoneInfo("UTC"))
    appointment = _book(business_ready["token"], business_ready["service_id"], business_ready["customer_id"], when)

    with SessionLocal() as db:
        notification = (
            db.query(Notification).filter(Notification.appointment_id == uuid.UUID(appointment["id"])).one()
        )
    assert notification.status == NotificationStatus.FAILED
    assert fake.calls == dispatch_service._MAX_SEND_ATTEMPTS, "must retry exactly the bounded number of times, no more"


def test_dispatch_permanent_failure_is_never_retried(business_ready, monkeypatch):
    fake = _FakeProvider([NotificationDeliveryError("bad credentials", transient=False)])
    monkeypatch.setitem(dispatch_service._PROVIDERS, "email", fake)
    monkeypatch.setattr(dispatch_service, "_RETRY_DELAY_SECONDS", 0)

    when = datetime.combine(_next_weekday(3), datetime.min.time()).replace(hour=10, tzinfo=ZoneInfo("UTC"))
    appointment = _book(business_ready["token"], business_ready["service_id"], business_ready["customer_id"], when)

    with SessionLocal() as db:
        notification = (
            db.query(Notification).filter(Notification.appointment_id == uuid.UUID(appointment["id"])).one()
        )
    assert notification.status == NotificationStatus.FAILED
    assert fake.calls == 1, "a permanent (non-transient) failure must not be retried at all"


def test_dispatch_never_raises_even_on_a_provider_bug(business_ready, monkeypatch):
    """dispatch_notification must never propagate — a bug in a provider (any
    exception, not just NotificationDeliveryError) must still leave the
    Notification in a real FAILED state, and must never break the caller
    (booking_service, which already committed a real appointment before
    calling this)."""

    class _BuggyProvider:
        def send(self, **kwargs):
            raise RuntimeError("boom — not a NotificationDeliveryError at all")

    monkeypatch.setitem(dispatch_service._PROVIDERS, "email", _BuggyProvider())

    when = datetime.combine(_next_weekday(4), datetime.min.time()).replace(hour=10, tzinfo=ZoneInfo("UTC"))
    appointment = _book(business_ready["token"], business_ready["service_id"], business_ready["customer_id"], when)
    # If dispatch had raised, the request above would have 500'd — it didn't
    # (asserted inside _book via status_code == 201).

    with SessionLocal() as db:
        notification = (
            db.query(Notification).filter(Notification.appointment_id == uuid.UUID(appointment["id"])).one()
        )
    assert notification.status == NotificationStatus.FAILED


def test_sms_channel_is_marked_simulated_never_sent_or_delivered(business_ready):
    """No real SMS gateway exists — dispatching an sms-channel Notification
    must land on SIMULATED, never SENT/DELIVERED, so it can never be mistaken
    for proof a real text message went out."""
    when = datetime.combine(_next_weekday(5), datetime.min.time()).replace(hour=10, tzinfo=ZoneInfo("UTC"))
    appointment = _book(business_ready["token"], business_ready["service_id"], business_ready["customer_id"], when)

    with SessionLocal() as db:
        appointment_row_id = uuid.UUID(appointment["id"])
        notification = Notification(
            business_id=business_ready["business_id"],
            appointment_id=appointment_row_id,
            channel="sms",
            event_type="booking_confirmed",
            status=NotificationStatus.QUEUED,
        )
        db.add(notification)
        db.commit()
        db.refresh(notification)

        notifications_pkg.dispatch_notification(db, notification)
        db.refresh(notification)
        assert notification.status == NotificationStatus.SIMULATED


def test_email_provider_rejects_missing_recipient_without_any_network_call():
    provider = EmailNotificationProvider()
    with pytest.raises(NotificationDeliveryError) as exc_info:
        provider.send(to="", subject="x", body="y")
    assert exc_info.value.transient is False


def test_email_provider_rejects_missing_credentials_without_any_network_call(monkeypatch):
    from app.core.config import settings

    monkeypatch.setattr(settings, "gmail_address", "")
    monkeypatch.setattr(settings, "gmail_app_password", "")
    provider = EmailNotificationProvider()
    with pytest.raises(NotificationDeliveryError) as exc_info:
        provider.send(to="someone@example.com", subject="x", body="y")
    assert exc_info.value.transient is False


def test_dispatch_queued_notifications_picks_up_a_notification_that_was_never_dispatched_inline(
    business_ready, monkeypatch
):
    fake = _FakeProvider(["250 ok"])
    when = datetime.combine(_next_weekday(0), datetime.min.time()).replace(hour=11, tzinfo=ZoneInfo("UTC"))
    # Book with the real provider disabled (simulate "process crashed before
    # inline dispatch ran") by pre-empting with a permanent failure, then
    # requeue it by hand and use the pickup path.
    monkeypatch.setitem(
        dispatch_service._PROVIDERS, "email", _FakeProvider([NotificationDeliveryError("down", transient=False)])
    )
    appointment = _book(business_ready["token"], business_ready["service_id"], business_ready["customer_id"], when)

    with SessionLocal() as db:
        notification = (
            db.query(Notification).filter(Notification.appointment_id == uuid.UUID(appointment["id"])).one()
        )
        assert notification.status == NotificationStatus.FAILED
        notification.status = NotificationStatus.QUEUED
        db.commit()

        monkeypatch.setitem(dispatch_service._PROVIDERS, "email", fake)
        picked_up = notifications_pkg.dispatch_queued_notifications(db, business_id=business_ready["business_id"])
        assert picked_up == 1

        db.refresh(notification)
        assert notification.status == NotificationStatus.SENT
