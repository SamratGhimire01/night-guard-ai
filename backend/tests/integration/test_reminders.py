"""Phase 45 — appointment reminders, the first real "runs on its own clock"
feature in this codebase.

Real DB throughout; the actual asyncio scheduler loop (app/services/
scheduler.py) is proven live against the real running server (see
PHASE_STATUS.md) — it never starts under FastAPI's TestClient used the way
every test in this codebase uses it (confirmed directly, see main.py's
lifespan docstring), so this file exercises the real, callable
`reminder_service.run_due_reminders` function directly instead, the exact
same "prove the callable, the timer is a separate live check" precedent
Phase 13 (dispatch_queued_notifications) and Phase 18 (run_followups) used.
Only the real network send is stubbed (dispatch_service._PROVIDERS["email"]),
same discipline as test_notifications.py.
"""

import threading
import uuid
from datetime import datetime, timedelta, timezone

import pytest
from fastapi.testclient import TestClient

from app.db.database import SessionLocal
from app.db.models.appointment import Appointment, AppointmentStatus
from app.db.models.business import Business
from app.db.models.notification import Notification, NotificationStatus
from app.main import app
from app.services import reminder_service
from app.services.notifications import dispatch_service

client = TestClient(app)


def _unique_email(label: str) -> str:
    return f"{label}-{uuid.uuid4().hex[:10]}@example.com"


def _auth_header(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


class _FakeProvider:
    def __init__(self):
        self.calls = 0
        self.recipients = []

    def send(self, *, to, subject, body, html_body=None, attachments=None, inline_images=None, credentials=None):
        self.calls += 1
        self.recipients.append(to)
        return "ok"


@pytest.fixture
def fake_email_provider(monkeypatch):
    fake = _FakeProvider()
    monkeypatch.setitem(dispatch_service._PROVIDERS, "email", fake)
    return fake


@pytest.fixture
def business_ready():
    """A real business (UTC, so Mon-Sat 9-5 hours are irrelevant — reminder
    eligibility never checks business hours, only the appointment's own real
    scheduled_at), reminders enabled with a 60-minute window, one service,
    one customer with a real email on file."""
    email = _unique_email("reminders-owner")
    resp = client.post(
        "/api/v1/auth/register",
        json={"business_name": "Reminders Test Dental", "timezone": "UTC", "email": email, "password": "correcthorse1"},
    )
    assert resp.status_code == 201, resp.text
    business_id = uuid.UUID(resp.json()["business_id"])
    login = client.post("/api/v1/auth/login", json={"email": email, "password": "correcthorse1"})
    token = login.json()["access_token"]

    updated = client.patch(
        "/api/v1/business/me",
        json={"reminder_enabled": True, "reminder_minutes_before": 60},
        headers=_auth_header(token),
    )
    assert updated.status_code == 200, updated.text

    service = client.post(
        "/api/v1/services",
        json={"name": "Cleaning", "price": "50.00", "duration_minutes": 30},
        headers=_auth_header(token),
    ).json()
    customer = client.post(
        "/api/v1/customers", json={"name": "Test Customer", "email": "customer@example.com"}, headers=_auth_header(token)
    ).json()

    yield {"business_id": business_id, "token": token, "service_id": uuid.UUID(service["id"]), "customer_id": uuid.UUID(customer["id"])}

    with SessionLocal() as db:
        business = db.get(Business, business_id)
        if business is not None:
            db.delete(business)
        db.commit()


def _make_appointment(
    db,
    *,
    business_id: uuid.UUID,
    customer_id: uuid.UUID,
    service_id: uuid.UUID,
    scheduled_at: datetime,
    created_at: datetime,
    status: AppointmentStatus = AppointmentStatus.CONFIRMED,
) -> Appointment:
    """Directly constructs an Appointment row with an explicit created_at/
    scheduled_at pair, bypassing the real booking flow's real-time
    availability checks — needed here because these tests must control the
    exact relationship between "when this was booked" and "when it's
    scheduled" relative to a fixed, controlled `now`, not real wall-clock
    time. Same direct-construction technique test_google_calendar.py's
    `_connect_integration` helper and Phase 18's timestamp-backdating use for
    analogous reasons."""
    appointment = Appointment(
        business_id=business_id,
        customer_id=customer_id,
        service_id=service_id,
        staff_id=None,
        scheduled_at=scheduled_at,
        duration_minutes=30,
        status=status,
        created_at=created_at,
    )
    db.add(appointment)
    db.commit()
    db.refresh(appointment)
    return appointment


def test_due_appointment_gets_a_real_reminder_notification(business_ready, fake_email_provider):
    now = datetime.now(timezone.utc)
    with SessionLocal() as db:
        appt = _make_appointment(
            db,
            business_id=business_ready["business_id"],
            customer_id=business_ready["customer_id"],
            service_id=business_ready["service_id"],
            scheduled_at=now + timedelta(minutes=30),  # inside the 60-min window
            created_at=now - timedelta(hours=2),  # booked well before the window started
        )
        sent = reminder_service.run_due_reminders(db, now=now, business_id=business_ready["business_id"])
        assert sent == 1

        db.refresh(appt)
        assert appt.reminder_sent_at is not None
        assert appt.status == AppointmentStatus.CONFIRMED  # untouched

        notification = db.query(Notification).filter(Notification.appointment_id == appt.id).one()
        assert notification.event_type == "appointment_reminder"
        assert notification.status == NotificationStatus.SENT
    assert fake_email_provider.calls == 1
    assert fake_email_provider.recipients == ["customer@example.com"]


def test_appointment_outside_window_is_not_yet_due(business_ready, fake_email_provider):
    now = datetime.now(timezone.utc)
    with SessionLocal() as db:
        _make_appointment(
            db,
            business_id=business_ready["business_id"],
            customer_id=business_ready["customer_id"],
            service_id=business_ready["service_id"],
            scheduled_at=now + timedelta(hours=5),  # far outside the 60-min window
            created_at=now - timedelta(hours=2),
        )
        sent = reminder_service.run_due_reminders(db, now=now, business_id=business_ready["business_id"])
        assert sent == 0
    assert fake_email_provider.calls == 0


def test_short_notice_booking_never_gets_a_reminder_even_much_later(business_ready, fake_email_provider):
    """The ticket's explicit requirement: booked with LESS lead time than the
    reminder window (booked when the appointment was only 20 minutes away,
    against a 60-minute reminder threshold — lead time at booking =
    scheduled_at - created_at = 20min < 60min window) must be skipped
    ENTIRELY, not merely delayed — re-checked here at a time well past when
    it would otherwise have become "due", to prove it's a permanent skip."""
    now = datetime.now(timezone.utc)
    with SessionLocal() as db:
        appt = _make_appointment(
            db,
            business_id=business_ready["business_id"],
            customer_id=business_ready["customer_id"],
            service_id=business_ready["service_id"],
            scheduled_at=now + timedelta(minutes=20),  # only 20 min out at the moment of booking
            created_at=now,  # booked right now — 20min of real lead time, window is 60
        )
        # Right now: never due (would naively look "in window" from a pure
        # time-remaining check, which is exactly the bug this guards against).
        sent = reminder_service.run_due_reminders(db, now=now, business_id=business_ready["business_id"])
        assert sent == 0

        # Later, once the appointment is imminent — still never due.
        later = now + timedelta(minutes=15)
        sent_later = reminder_service.run_due_reminders(db, now=later, business_id=business_ready["business_id"])
        assert sent_later == 0

        db.refresh(appt)
        assert appt.reminder_sent_at is None
    assert fake_email_provider.calls == 0


def test_cancelled_appointment_never_gets_a_reminder(business_ready, fake_email_provider):
    now = datetime.now(timezone.utc)
    with SessionLocal() as db:
        appt = _make_appointment(
            db,
            business_id=business_ready["business_id"],
            customer_id=business_ready["customer_id"],
            service_id=business_ready["service_id"],
            scheduled_at=now + timedelta(minutes=30),
            created_at=now - timedelta(hours=2),
            status=AppointmentStatus.CANCELLED,
        )
        sent = reminder_service.run_due_reminders(db, now=now, business_id=business_ready["business_id"])
        assert sent == 0
        db.refresh(appt)
        assert appt.reminder_sent_at is None
    assert fake_email_provider.calls == 0


def test_cancellation_racing_the_claim_is_resolved_correctly(business_ready, fake_email_provider):
    """A real race, not just a pre-cancelled row: the appointment IS due and
    IS selected as a candidate, but is cancelled for real (via the real
    cancel_appointment service call) before the atomic claim runs — proving
    the claim's own `status = CONFIRMED` re-check (not the earlier SELECT)
    is what actually decides this, per the ticket's explicit requirement."""
    now = datetime.now(timezone.utc)
    with SessionLocal() as db:
        appt = _make_appointment(
            db,
            business_id=business_ready["business_id"],
            customer_id=business_ready["customer_id"],
            service_id=business_ready["service_id"],
            scheduled_at=now + timedelta(minutes=30),
            created_at=now - timedelta(hours=2),
        )
        candidate_ids = reminder_service._find_due_appointment_ids(db, now=now, business_id=business_ready["business_id"])
        assert appt.id in candidate_ids

        from app.services import booking_service

        booking_service.cancel_appointment(db, business_id=business_ready["business_id"], appointment_id=appt.id)

        notification = reminder_service._claim_and_queue_reminder(db, appt.id, now=now)
        assert notification is None

        db.refresh(appt)
        assert appt.status == AppointmentStatus.CANCELLED
        assert appt.reminder_sent_at is None
        reminder_count = (
            db.query(Notification)
            .filter(Notification.appointment_id == appt.id, Notification.event_type == "appointment_reminder")
            .count()
        )
        assert reminder_count == 0
    # cancel_appointment's own real cancellation email is the only send —
    # never a reminder alongside it.
    assert fake_email_provider.calls == 1


def test_reminder_never_sent_twice_under_real_concurrent_claims(business_ready, fake_email_provider):
    """Real duplicate-prevention proof, same `threading.Barrier` technique
    Phase 30 used to prove the webhook idempotency unique constraint under
    genuine concurrent commit pressure — 8 real threads, independent DB
    sessions, forced to the identical instant, all racing the exact same
    atomic claim UPDATE for the exact same appointment."""
    now = datetime.now(timezone.utc)
    with SessionLocal() as setup_db:
        appt = _make_appointment(
            setup_db,
            business_id=business_ready["business_id"],
            customer_id=business_ready["customer_id"],
            service_id=business_ready["service_id"],
            scheduled_at=now + timedelta(minutes=30),
            created_at=now - timedelta(hours=2),
        )
        appointment_id = appt.id

    n_threads = 8
    barrier = threading.Barrier(n_threads)
    results = [None] * n_threads

    def worker(i):
        with SessionLocal() as db:
            barrier.wait()
            notification = reminder_service._claim_and_queue_reminder(db, appointment_id, now=now)
            results[i] = notification.id if notification is not None else None

    threads = [threading.Thread(target=worker, args=(i,)) for i in range(n_threads)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    winners = [r for r in results if r is not None]
    assert len(winners) == 1, f"expected exactly 1 winner, got {len(winners)}: {results}"

    with SessionLocal() as db:
        count = db.query(Notification).filter(
            Notification.appointment_id == appointment_id, Notification.event_type == "appointment_reminder"
        ).count()
        assert count == 1
        appt = db.get(Appointment, appointment_id)
        assert appt.reminder_sent_at is not None


def test_reminder_settings_persist_through_the_dashboard_route(business_ready):
    token = business_ready["token"]
    read = client.get("/api/v1/business/me", headers=_auth_header(token))
    assert read.json()["reminder_enabled"] is True
    assert read.json()["reminder_minutes_before"] == 60

    updated = client.patch(
        "/api/v1/business/me", json={"reminder_minutes_before": 30}, headers=_auth_header(token)
    )
    assert updated.status_code == 200, updated.text
    assert updated.json()["reminder_minutes_before"] == 30


def test_reminder_minutes_before_out_of_range_rejected(business_ready):
    token = business_ready["token"]
    resp = client.patch("/api/v1/business/me", json={"reminder_minutes_before": 2}, headers=_auth_header(token))
    assert resp.status_code == 422, resp.text
    resp = client.patch("/api/v1/business/me", json={"reminder_minutes_before": 2000}, headers=_auth_header(token))
    assert resp.status_code == 422, resp.text


def test_reminder_disabled_business_never_gets_a_reminder(business_ready, fake_email_provider):
    token = business_ready["token"]
    client.patch("/api/v1/business/me", json={"reminder_enabled": False}, headers=_auth_header(token))
    now = datetime.now(timezone.utc)
    with SessionLocal() as db:
        _make_appointment(
            db,
            business_id=business_ready["business_id"],
            customer_id=business_ready["customer_id"],
            service_id=business_ready["service_id"],
            scheduled_at=now + timedelta(minutes=30),
            created_at=now - timedelta(hours=2),
        )
        sent = reminder_service.run_due_reminders(db, now=now, business_id=business_ready["business_id"])
        assert sent == 0
    assert fake_email_provider.calls == 0
