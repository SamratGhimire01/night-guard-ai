"""Phase 11 — cancellation + rescheduling (app/services/booking_service.py,
app/api/routes/appointments.py's /cancel and /reschedule endpoints).

Real DB throughout, no LLM involved (that's covered separately in
test_conversation.py's cancellation/reschedule-tool tests) — this file is
about the deterministic cancel/reschedule logic and its HTTP surface: slot
release, validation status codes, cross-tenant isolation, the audit
trail/Notification side effects, and the real concurrent-request race
condition on reschedule.
"""

import uuid
from concurrent.futures import ThreadPoolExecutor
from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

import pytest
from fastapi.testclient import TestClient

from app.db.database import SessionLocal
from app.db.models.appointment import Appointment, AppointmentStatus
from app.db.models.audit_log import AuditLog
from app.db.models.business import Business
from app.db.models.notification import Notification, NotificationStatus
from app.main import app

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
    email_a = _unique_email("cr-a-owner")
    email_b = _unique_email("cr-b-owner")

    resp_a = client.post(
        "/api/v1/auth/register",
        json={"business_name": "CR A", "timezone": "UTC", "email": email_a, "password": "correcthorse1"},
    )
    resp_b = client.post(
        "/api/v1/auth/register",
        json={"business_name": "CR B", "timezone": "UTC", "email": email_b, "password": "correcthorse1"},
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
def business_a_ready(two_businesses):
    """Business A: Mon-Sat 9am-5pm (UTC), Sunday closed, one 30-min service, one customer."""
    token_a = two_businesses["token_a"]

    days = [{"day_of_week": d, "open_time": "09:00:00", "close_time": "17:00:00"} for d in range(6)]
    days.append({"day_of_week": 6, "closed": True})
    resp = client.put("/api/v1/business/hours", json={"days": days}, headers=_auth_header(token_a))
    assert resp.status_code == 200, resp.text

    service = client.post(
        "/api/v1/services",
        json={"name": "Cleaning", "price": "50.00", "duration_minutes": 30},
        headers=_auth_header(token_a),
    )
    assert service.status_code == 201, service.text

    customer = client.post("/api/v1/customers", json={"name": "Test Customer"}, headers=_auth_header(token_a))
    assert customer.status_code == 201, customer.text

    return {
        **two_businesses,
        "service_id": uuid.UUID(service.json()["id"]),
        "customer_id": uuid.UUID(customer.json()["id"]),
    }


def _book(token: str, service_id: uuid.UUID, customer_id: uuid.UUID, when: datetime) -> dict:
    resp = client.post(
        "/api/v1/appointments",
        json={"customer_id": str(customer_id), "service_id": str(service_id), "scheduled_at": when.isoformat()},
        headers=_auth_header(token),
    )
    assert resp.status_code == 201, resp.text
    return resp.json()


# --- cancellation ------------------------------------------------------------------


def test_cancel_appointment_frees_the_slot_for_a_new_booking(business_a_ready):
    token_a = business_a_ready["token_a"]
    service_id = business_a_ready["service_id"]
    customer_id = business_a_ready["customer_id"]
    target_date = _next_weekday(0)
    when = datetime.combine(target_date, datetime.min.time()).replace(hour=10, tzinfo=ZoneInfo("UTC"))

    appointment = _book(token_a, service_id, customer_id, when)

    cancel = client.patch(f"/api/v1/appointments/{appointment['id']}/cancel", headers=_auth_header(token_a))
    assert cancel.status_code == 200, cancel.text
    assert cancel.json()["status"] == "cancelled"

    # a different customer can now book the freed slot
    other_customer = client.post("/api/v1/customers", json={"name": "Other Customer"}, headers=_auth_header(token_a))
    assert other_customer.status_code == 201, other_customer.text
    rebooked = _book(token_a, service_id, uuid.UUID(other_customer.json()["id"]), when)
    assert rebooked["scheduled_at"] == appointment["scheduled_at"]

    with SessionLocal() as db:
        notifications = db.query(Notification).filter(Notification.appointment_id == uuid.UUID(appointment["id"])).all()
    # Phase 13: booking now also queues its own booking_confirmed Notification
    # (previously only cancel/reschedule did) — so this appointment has two:
    # one from the original booking, one from this cancellation.
    cancel_notifications = [n for n in notifications if n.event_type == "appointment_cancelled"]
    assert len(cancel_notifications) == 1, "cancellation must queue a Notification"
    # cancel_appointment dispatches it for real, inline. This test's customer
    # has no email on file, so the real, honest outcome is FAILED (not a real
    # send failure) — never left sitting in QUEUED forever.
    assert cancel_notifications[0].status == NotificationStatus.FAILED


def test_cancel_appointment_rejects_already_cancelled(business_a_ready):
    token_a = business_a_ready["token_a"]
    service_id = business_a_ready["service_id"]
    customer_id = business_a_ready["customer_id"]
    when = datetime.combine(_next_weekday(1), datetime.min.time()).replace(hour=10, tzinfo=ZoneInfo("UTC"))
    appointment = _book(token_a, service_id, customer_id, when)

    first = client.patch(f"/api/v1/appointments/{appointment['id']}/cancel", headers=_auth_header(token_a))
    assert first.status_code == 200, first.text

    second = client.patch(f"/api/v1/appointments/{appointment['id']}/cancel", headers=_auth_header(token_a))
    assert second.status_code == 422, second.text
    assert second.status_code != 500


def test_cancel_appointment_rejects_nonexistent_appointment(business_a_ready):
    token_a = business_a_ready["token_a"]
    resp = client.patch(f"/api/v1/appointments/{uuid.uuid4()}/cancel", headers=_auth_header(token_a))
    assert resp.status_code == 404, resp.text


def test_cross_tenant_cannot_cancel_other_businesss_appointment(business_a_ready):
    token_a = business_a_ready["token_a"]
    token_b = business_a_ready["token_b"]
    service_id = business_a_ready["service_id"]
    customer_id = business_a_ready["customer_id"]
    when = datetime.combine(_next_weekday(2), datetime.min.time()).replace(hour=10, tzinfo=ZoneInfo("UTC"))
    appointment = _book(token_a, service_id, customer_id, when)

    resp = client.patch(f"/api/v1/appointments/{appointment['id']}/cancel", headers=_auth_header(token_b))
    assert resp.status_code == 404, resp.text

    with SessionLocal() as db:
        row = db.get(Appointment, uuid.UUID(appointment["id"]))
    assert row.status == AppointmentStatus.CONFIRMED, "the rejected cross-tenant request must not have cancelled it"


# --- rescheduling --------------------------------------------------------------------


def test_reschedule_appointment_moves_same_id_to_new_time(business_a_ready):
    token_a = business_a_ready["token_a"]
    service_id = business_a_ready["service_id"]
    customer_id = business_a_ready["customer_id"]
    target_date = _next_weekday(0)
    original = datetime.combine(target_date, datetime.min.time()).replace(hour=10, tzinfo=ZoneInfo("UTC"))
    new_time = datetime.combine(target_date, datetime.min.time()).replace(hour=14, tzinfo=ZoneInfo("UTC"))
    appointment = _book(token_a, service_id, customer_id, original)

    resp = client.patch(
        f"/api/v1/appointments/{appointment['id']}/reschedule",
        json={"scheduled_at": new_time.isoformat()},
        headers=_auth_header(token_a),
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["id"] == appointment["id"], "booking ID must not change on reschedule"
    assert datetime.fromisoformat(body["scheduled_at"].replace("Z", "+00:00")) == new_time
    assert body["status"] == "confirmed"

    # the old slot is now free again
    slots = client.get(
        "/api/v1/appointments",
        params={"customer_id": str(customer_id)},
        headers=_auth_header(token_a),
    )
    assert slots.status_code == 200
    assert len(slots.json()) == 1, "reschedule must update in place, not create a second appointment"

    with SessionLocal() as db:
        audit_rows = (
            db.query(AuditLog)
            .filter(AuditLog.resource_type == "appointment", AuditLog.resource_id == appointment["id"])
            .all()
        )
        notifications = db.query(Notification).filter(Notification.appointment_id == uuid.UUID(appointment["id"])).all()
    assert any(a.action == "appointment_rescheduled" for a in audit_rows), "reschedule must leave an audit trail"
    # Phase 13: booking now also queues its own booking_confirmed Notification,
    # alongside this reschedule's appointment_rescheduled one.
    reschedule_notifications = [n for n in notifications if n.event_type == "appointment_rescheduled"]
    assert len(reschedule_notifications) == 1
    # Same real-dispatch reasoning as the cancellation test above: no email on
    # file for this test customer, so FAILED is the honest, deterministic
    # real outcome, not QUEUED forever.
    assert reschedule_notifications[0].status == NotificationStatus.FAILED


def test_reschedule_appointment_rejects_already_taken_slot_with_409(business_a_ready):
    """An already-booked target slot is a CONFLICT with existing state (409), not
    a validation error (422) — even with no concurrency involved, this is a
    request that conflicts with another real appointment, not malformed input.
    Keeping this on the same code path (the DB exclusion constraint) as the
    concurrent-race case is what makes the race test's outcome consistent."""
    token_a = business_a_ready["token_a"]
    service_id = business_a_ready["service_id"]
    customer_id = business_a_ready["customer_id"]
    target_date = _next_weekday(3)
    taken_time = datetime.combine(target_date, datetime.min.time()).replace(hour=11, tzinfo=ZoneInfo("UTC"))
    other_customer = client.post("/api/v1/customers", json={"name": "Blocker"}, headers=_auth_header(token_a))
    assert other_customer.status_code == 201
    _book(token_a, service_id, uuid.UUID(other_customer.json()["id"]), taken_time)

    movable_time = datetime.combine(target_date, datetime.min.time()).replace(hour=9, tzinfo=ZoneInfo("UTC"))
    appointment = _book(token_a, service_id, customer_id, movable_time)

    resp = client.patch(
        f"/api/v1/appointments/{appointment['id']}/reschedule",
        json={"scheduled_at": taken_time.isoformat()},
        headers=_auth_header(token_a),
    )
    assert resp.status_code == 409, resp.text
    assert resp.status_code != 500

    with SessionLocal() as db:
        row = db.get(Appointment, uuid.UUID(appointment["id"]))
    assert row.scheduled_at == movable_time, "a rejected reschedule must not move the appointment"


def test_reschedule_appointment_rejects_outside_business_hours_with_422(business_a_ready):
    """A structurally invalid target slot (outside hours) is a client input
    error (422), not a conflict — distinguishing this from the "already taken"
    case above is the whole point of the fix: only a genuine resource conflict
    goes through the DB exclusion constraint / 409 path."""
    token_a = business_a_ready["token_a"]
    service_id = business_a_ready["service_id"]
    customer_id = business_a_ready["customer_id"]
    target_date = _next_weekday(3)
    movable_time = datetime.combine(target_date, datetime.min.time()).replace(hour=9, tzinfo=ZoneInfo("UTC"))
    appointment = _book(token_a, service_id, customer_id, movable_time)

    resp = client.patch(
        f"/api/v1/appointments/{appointment['id']}/reschedule",
        json={"scheduled_at": f"{target_date.isoformat()}T20:00:00+00:00"},  # 8pm, hours end at 5pm
        headers=_auth_header(token_a),
    )
    assert resp.status_code == 422, resp.text
    assert resp.status_code != 500


def test_reschedule_appointment_rejects_already_cancelled(business_a_ready):
    token_a = business_a_ready["token_a"]
    service_id = business_a_ready["service_id"]
    customer_id = business_a_ready["customer_id"]
    when = datetime.combine(_next_weekday(4), datetime.min.time()).replace(hour=10, tzinfo=ZoneInfo("UTC"))
    appointment = _book(token_a, service_id, customer_id, when)

    cancel = client.patch(f"/api/v1/appointments/{appointment['id']}/cancel", headers=_auth_header(token_a))
    assert cancel.status_code == 200, cancel.text

    resp = client.patch(
        f"/api/v1/appointments/{appointment['id']}/reschedule",
        json={"scheduled_at": (when + timedelta(hours=1)).isoformat()},
        headers=_auth_header(token_a),
    )
    assert resp.status_code == 422, resp.text
    assert resp.status_code != 500


def test_cross_tenant_cannot_reschedule_other_businesss_appointment(business_a_ready):
    token_a = business_a_ready["token_a"]
    token_b = business_a_ready["token_b"]
    service_id = business_a_ready["service_id"]
    customer_id = business_a_ready["customer_id"]
    when = datetime.combine(_next_weekday(5), datetime.min.time()).replace(hour=10, tzinfo=ZoneInfo("UTC"))
    appointment = _book(token_a, service_id, customer_id, when)

    resp = client.patch(
        f"/api/v1/appointments/{appointment['id']}/reschedule",
        json={"scheduled_at": (when + timedelta(hours=1)).isoformat()},
        headers=_auth_header(token_b),
    )
    assert resp.status_code == 404, resp.text

    with SessionLocal() as db:
        row = db.get(Appointment, uuid.UUID(appointment["id"]))
    assert row.scheduled_at == when


# --- race condition ------------------------------------------------------------------


def test_concurrent_reschedule_race_exactly_one_succeeds(business_a_ready):
    """Two DIFFERENT appointments, both rescheduled to the SAME target slot at the
    same instant: the Phase 10 exclusion constraint is enforced by Postgres on
    UPDATE exactly like it is on INSERT, so exactly one of these must win. Same
    ThreadPoolExecutor best-effort pattern as test_booking.py's booking race
    test — see PHASE_STATUS.md for the authoritative real-concurrent-HTTP proof.

    Unlike the booking race (which still accepts a 422-or-409 loser — see
    test_booking.py), the loser here MUST be 409: reschedule_appointment's
    pre-check deliberately ignores existing-appointment conflicts (only the DB
    exclusion constraint decides that), so there is no code path left that can
    produce a 422 for "someone else already holds this slot," racy or not."""
    token_a = business_a_ready["token_a"]
    service_id = business_a_ready["service_id"]
    customer_id = business_a_ready["customer_id"]
    target_date = _next_weekday(0)  # a Monday, always open per the fixture
    # two originally-distinct times, both movable into the same target slot
    original_1 = datetime.combine(target_date, datetime.min.time()).replace(hour=9, tzinfo=ZoneInfo("UTC"))
    original_2 = datetime.combine(target_date, datetime.min.time()).replace(hour=9, minute=30, tzinfo=ZoneInfo("UTC"))
    target_slot = datetime.combine(target_date, datetime.min.time()).replace(hour=15, tzinfo=ZoneInfo("UTC"))

    other_customer = client.post("/api/v1/customers", json={"name": "Second"}, headers=_auth_header(token_a))
    assert other_customer.status_code == 201
    appointment_1 = _book(token_a, service_id, customer_id, original_1)
    appointment_2 = _book(token_a, service_id, uuid.UUID(other_customer.json()["id"]), original_2)

    def _reschedule(appointment_id: str):
        return client.patch(
            f"/api/v1/appointments/{appointment_id}/reschedule",
            json={"scheduled_at": target_slot.isoformat()},
            headers=_auth_header(token_a),
        )

    with ThreadPoolExecutor(max_workers=2) as pool:
        futures = [pool.submit(_reschedule, appointment_1["id"]), pool.submit(_reschedule, appointment_2["id"])]
        responses = [f.result() for f in futures]

    statuses = sorted(r.status_code for r in responses)
    assert statuses[0] == 200, [r.text for r in responses]
    assert statuses[1] == 409, [r.text for r in responses]

    with SessionLocal() as db:
        at_target = (
            db.query(Appointment)
            .filter(
                Appointment.service_id == service_id,
                Appointment.scheduled_at == target_slot,
                Appointment.status != AppointmentStatus.CANCELLED,
            )
            .count()
        )
    assert at_target == 1, "exactly one appointment may end up occupying the contested slot"
