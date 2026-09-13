"""Phase 46 — QR check-in, split into ARRIVED (the scan) + COMPLETED (a real,
separate "mark service complete" staff action) — real industry precedent:
Open Dental tracks "Time Arrived" separately from visit completion.

Real DB + real HTTP throughout. Google Calendar's real network call is
stubbed at google_calendar_service's private HTTP helpers, same seam
test_google_calendar.py itself stubs at. Payment-gateway network calls
(for the in-person-payment test) are stubbed at payment_service._PROVIDERS,
same seam test_payments.py uses.

Covers: real check-in marks ARRIVED (never COMPLETED directly), the real
separate "mark complete" action moves ARRIVED -> COMPLETED, one-time-use
enforced atomically for BOTH claims (sequential re-attempt + a real
concurrent-thread race each), cross-tenant isolation (a valid token from
another business is checked exactly like a token that doesn't exist), a
cancelled appointment can't be checked in, a not-yet-arrived appointment
can't be completed, staff (not just owner/admin) can do both actions, the
explicit/separate in-person-payment action, Google Calendar reflecting
ARRIVED and COMPLETED honestly differently, the monthly report's completed
count reflecting only genuine completions (not mere arrivals), and a
pre-split legacy COMPLETED row (as if written before ARRIVED ever existed)
remaining valid and correctly counted.
"""

import threading
import uuid
from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

import pytest
from fastapi.testclient import TestClient

from app.db.database import SessionLocal
from app.db.models.appointment import Appointment, AppointmentStatus
from app.db.models.business import Business, BusinessPlan, BusinessUser, BusinessUserRole
from app.db.models.payment import Payment
from app.main import app
from app.services import google_calendar_service, integration_service
from app.services.payments.base import PaymentInitiation, PaymentVerification

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


def _set_plan(business_id: uuid.UUID, plan: BusinessPlan) -> None:
    with SessionLocal() as db:
        business = db.get(Business, business_id)
        business.plan = plan
        db.commit()


@pytest.fixture
def two_businesses():
    email_a = _unique_email("checkin-a-owner")
    email_b = _unique_email("checkin-b-owner")

    resp_a = client.post(
        "/api/v1/auth/register",
        json={"business_name": "Checkin A Dental", "timezone": "UTC", "email": email_a, "password": "correcthorse1"},
    )
    resp_b = client.post(
        "/api/v1/auth/register",
        json={"business_name": "Checkin B Dental", "timezone": "UTC", "email": email_b, "password": "correcthorse1"},
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
def booked_ready(two_businesses):
    """Business A: a real Mon-Sat 9-5 UTC week, one service, one customer,
    one real CONFIRMED appointment booked via the real HTTP route."""
    token_a = two_businesses["token_a"]

    days = [{"day_of_week": d, "open_time": "09:00:00", "close_time": "17:00:00"} for d in range(6)]
    days.append({"day_of_week": 6, "closed": True})
    resp = client.put("/api/v1/business/hours", json={"days": days}, headers=_auth_header(token_a))
    assert resp.status_code == 200, resp.text

    service = client.post(
        "/api/v1/services", json={"name": "Cleaning", "price": "50.00", "duration_minutes": 30}, headers=_auth_header(token_a)
    ).json()
    customer = client.post(
        "/api/v1/customers", json={"name": "Test Customer", "email": "customer@example.com"}, headers=_auth_header(token_a)
    ).json()

    target_date = _next_weekday(0)
    scheduled_at = datetime.combine(target_date, datetime.min.time()).replace(hour=11, tzinfo=ZoneInfo("UTC"))
    appt_resp = client.post(
        "/api/v1/appointments",
        json={"customer_id": customer["id"], "service_id": service["id"], "scheduled_at": scheduled_at.isoformat()},
        headers=_auth_header(token_a),
    )
    assert appt_resp.status_code == 201, appt_resp.text
    appointment_id = uuid.UUID(appt_resp.json()["id"])

    with SessionLocal() as db:
        appointment = db.get(Appointment, appointment_id)
        token = appointment.checkin_token

    return {**two_businesses, "appointment_id": appointment_id, "checkin_token": token, "service_id": service["id"], "customer_id": customer["id"]}


def test_checkin_marks_appointment_arrived_real_http(booked_ready):
    token_a = booked_ready["token_a"]
    resp = client.post(
        "/api/v1/appointments/checkin", json={"token": str(booked_ready["checkin_token"])}, headers=_auth_header(token_a)
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["status"] == "arrived"
    assert body["checked_in_at"] is not None
    assert body["customer_name"] == "Test Customer"

    with SessionLocal() as db:
        appointment = db.get(Appointment, booked_ready["appointment_id"])
        assert appointment.status == AppointmentStatus.ARRIVED
        assert appointment.checked_in_at is not None
        assert appointment.completed_at is None


def test_duplicate_scan_returns_honest_already_checked_in(booked_ready):
    token_a = booked_ready["token_a"]
    first = client.post(
        "/api/v1/appointments/checkin", json={"token": str(booked_ready["checkin_token"])}, headers=_auth_header(token_a)
    )
    assert first.status_code == 200, first.text
    real_checked_in_at = first.json()["checked_in_at"]

    second = client.post(
        "/api/v1/appointments/checkin", json={"token": str(booked_ready["checkin_token"])}, headers=_auth_header(token_a)
    )
    assert second.status_code == 409, second.text
    message = second.json()["error"]["message"]
    assert "already checked in" in message
    assert real_checked_in_at[:19] in message  # the real timestamp is actually in the message


def test_cancelled_appointment_cannot_be_checked_in(booked_ready):
    token_a = booked_ready["token_a"]
    cancel = client.patch(f"/api/v1/appointments/{booked_ready['appointment_id']}/cancel", headers=_auth_header(token_a))
    assert cancel.status_code == 200, cancel.text

    resp = client.post(
        "/api/v1/appointments/checkin", json={"token": str(booked_ready["checkin_token"])}, headers=_auth_header(token_a)
    )
    assert resp.status_code == 422, resp.text
    assert "cancelled" in resp.json()["error"]["message"]


def test_cross_tenant_token_is_indistinguishable_from_nonexistent(booked_ready):
    """Business B's own real staff, real bearer token, attempting to check in
    using Business A's real, valid checkin_token — must fail exactly like an
    unknown token, not with any hint the token itself is real."""
    token_b = booked_ready["token_b"]
    resp = client.post(
        "/api/v1/appointments/checkin", json={"token": str(booked_ready["checkin_token"])}, headers=_auth_header(token_b)
    )
    assert resp.status_code == 404, resp.text

    # And confirm the SAME token still works for the real owning business —
    # Business B's failed attempt didn't consume or corrupt it.
    token_a = booked_ready["token_a"]
    resp2 = client.post(
        "/api/v1/appointments/checkin", json={"token": str(booked_ready["checkin_token"])}, headers=_auth_header(token_a)
    )
    assert resp2.status_code == 200, resp2.text


def test_random_unrelated_token_returns_404(booked_ready):
    token_a = booked_ready["token_a"]
    resp = client.post("/api/v1/appointments/checkin", json={"token": str(uuid.uuid4())}, headers=_auth_header(token_a))
    assert resp.status_code == 404, resp.text


def test_staff_role_can_check_in(booked_ready):
    business_id_a = booked_ready["business_id_a"]
    with SessionLocal() as db:
        staff_user = BusinessUser(
            business_id=business_id_a, email=_unique_email("staff"), hashed_password="not-used", role=BusinessUserRole.STAFF
        )
        db.add(staff_user)
        db.commit()
        db.refresh(staff_user)
        from app.core.security import create_access_token

        staff_token = create_access_token(user_id=staff_user.id, business_id=business_id_a, role=staff_user.role.value)

    resp = client.post(
        "/api/v1/appointments/checkin", json={"token": str(booked_ready["checkin_token"])}, headers=_auth_header(staff_token)
    )
    assert resp.status_code == 200, resp.text


def test_checkin_never_sent_twice_under_real_concurrent_claims(booked_ready):
    """Same real threading.Barrier proof technique as Phase 45's reminder
    claim / Phase 30's webhook idempotency constraint — 8 real threads,
    independent DB sessions, forced to the identical instant, all racing the
    exact same atomic claim for the exact same real appointment."""
    from app.services import checkin_service

    appointment_id = booked_ready["appointment_id"]
    business_id = booked_ready["business_id_a"]
    token = booked_ready["checkin_token"]

    n_threads = 8
    barrier = threading.Barrier(n_threads)
    results = [None] * n_threads

    def worker(i):
        with SessionLocal() as db:
            barrier.wait()
            try:
                appointment = checkin_service.check_in_appointment(db, business_id=business_id, token=token)
                results[i] = ("won", appointment.id)
            except Exception as exc:
                results[i] = ("lost", type(exc).__name__)

    threads = [threading.Thread(target=worker, args=(i,)) for i in range(n_threads)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    winners = [r for r in results if r[0] == "won"]
    assert len(winners) == 1, f"expected exactly 1 winner, got {len(winners)}: {results}"

    with SessionLocal() as db:
        appointment = db.get(Appointment, appointment_id)
        assert appointment.status == AppointmentStatus.ARRIVED
        assert appointment.checked_in_at is not None


def test_calendar_arrived_sync_is_best_effort_and_never_blocks_checkin(booked_ready, monkeypatch):
    business_id = booked_ready["business_id_a"]
    _set_plan(business_id, BusinessPlan.PREMIUM)
    with SessionLocal() as db:
        integration_service.save_integration_config(
            db,
            business_id=business_id,
            type_="google_calendar",
            config={
                "access_token": "fake-access-token",
                "refresh_token": "fake-refresh-token",
                "calendar_id": "primary",
                "calendar_summary": "Real Calendar",
                "token_expiry": (datetime.now(ZoneInfo("UTC")) + timedelta(hours=1)).isoformat(),
            },
            enabled=True,
        )
        appt = db.get(Appointment, booked_ready["appointment_id"])
        appt.google_calendar_event_id = "real-google-event-id-999"
        db.commit()

    captured = {}

    def fake_update_event(access_token, *, calendar_id, event_id, start=None, end=None, summary=None, description=None):
        captured.update({"event_id": event_id, "summary": summary, "description": description})

    monkeypatch.setattr(google_calendar_service, "_update_event", fake_update_event)

    token_a = booked_ready["token_a"]
    resp = client.post(
        "/api/v1/appointments/checkin", json={"token": str(booked_ready["checkin_token"])}, headers=_auth_header(token_a)
    )
    assert resp.status_code == 200, resp.text
    assert captured["event_id"] == "real-google-event-id-999"
    # A mere arrival never claims completion: sync_appointment_arrived never
    # passes a summary kwarg at all (falls through to _update_event's own
    # summary=None default), so the real PATCH body sent to Google never
    # includes a "summary" field — see _update_event, which only includes
    # fields actually given.
    assert captured["summary"] is None
    assert "Arrived:" in captured["description"]
    assert "completed" not in captured["description"].lower()

    with SessionLocal() as db:
        appt = db.get(Appointment, booked_ready["appointment_id"])
        assert appt.calendar_sync_status == "synced"


def test_calendar_completed_sync_fires_on_real_completion_not_on_arrival(booked_ready, monkeypatch):
    """The honest, real distinction the ticket asked for: ARRIVED gets the
    lighter note (previous test); only the separate, later COMPLETED
    transition gets the "✓ ... (completed)" summary treatment."""
    business_id = booked_ready["business_id_a"]
    _set_plan(business_id, BusinessPlan.PREMIUM)
    with SessionLocal() as db:
        integration_service.save_integration_config(
            db,
            business_id=business_id,
            type_="google_calendar",
            config={
                "access_token": "fake-access-token",
                "refresh_token": "fake-refresh-token",
                "calendar_id": "primary",
                "calendar_summary": "Real Calendar",
                "token_expiry": (datetime.now(ZoneInfo("UTC")) + timedelta(hours=1)).isoformat(),
            },
            enabled=True,
        )
        appt = db.get(Appointment, booked_ready["appointment_id"])
        appt.google_calendar_event_id = "real-google-event-id-completed"
        db.commit()

    captured = {}

    def fake_update_event(access_token, *, calendar_id, event_id, start=None, end=None, summary=None, description=None):
        captured.update({"event_id": event_id, "summary": summary, "description": description})

    monkeypatch.setattr(google_calendar_service, "_update_event", fake_update_event)

    token_a = booked_ready["token_a"]
    checkin_resp = client.post(
        "/api/v1/appointments/checkin", json={"token": str(booked_ready["checkin_token"])}, headers=_auth_header(token_a)
    )
    assert checkin_resp.status_code == 200, checkin_resp.text
    assert captured["summary"] is None  # confirmed by the previous test too: arrival never touches summary

    complete_resp = client.post(
        f"/api/v1/appointments/{booked_ready['appointment_id']}/complete", headers=_auth_header(token_a)
    )
    assert complete_resp.status_code == 200, complete_resp.text
    assert captured["event_id"] == "real-google-event-id-completed"
    assert "completed" in captured["summary"].lower()
    assert "Completed:" in captured["description"]

    with SessionLocal() as db:
        appt = db.get(Appointment, booked_ready["appointment_id"])
        assert appt.status == AppointmentStatus.COMPLETED
        assert appt.calendar_sync_status == "synced"


def test_calendar_sync_failure_never_blocks_checkin(booked_ready, monkeypatch):
    business_id = booked_ready["business_id_a"]
    _set_plan(business_id, BusinessPlan.PREMIUM)
    with SessionLocal() as db:
        integration_service.save_integration_config(
            db,
            business_id=business_id,
            type_="google_calendar",
            config={
                "access_token": "fake-access-token",
                "refresh_token": "fake-refresh-token",
                "calendar_id": "primary",
                "calendar_summary": "Real Calendar",
                "token_expiry": (datetime.now(ZoneInfo("UTC")) + timedelta(hours=1)).isoformat(),
            },
            enabled=True,
        )
        appt = db.get(Appointment, booked_ready["appointment_id"])
        appt.google_calendar_event_id = "real-google-event-id-broken"
        db.commit()

    def raise_error(*args, **kwargs):
        raise RuntimeError("simulated Calendar outage")

    monkeypatch.setattr(google_calendar_service, "_update_event", raise_error)

    token_a = booked_ready["token_a"]
    resp = client.post(
        "/api/v1/appointments/checkin", json={"token": str(booked_ready["checkin_token"])}, headers=_auth_header(token_a)
    )
    assert resp.status_code == 200, resp.text  # check-in itself still succeeds
    assert resp.json()["status"] == "arrived"

    with SessionLocal() as db:
        appt = db.get(Appointment, booked_ready["appointment_id"])
        assert appt.status == AppointmentStatus.ARRIVED
        assert appt.calendar_sync_status == "failed"


def test_in_person_payment_is_never_inferred_and_is_its_own_explicit_action(two_businesses, monkeypatch):
    from app.services.payment_service import _PROVIDERS

    class _FakeProvider:
        name = "fake"

        def initiate_payment(self, *, payment_id, amount, product_name):
            return PaymentInitiation(payment_url="https://fake-gateway.example/pay/1", gateway_reference="ref-1")

        def verify_payment(self, *, payment_id, amount, gateway_reference):
            return PaymentVerification(completed=True, raw_status="Completed")

    fake = _FakeProvider()
    monkeypatch.setitem(_PROVIDERS, "esewa", fake)

    business_id_a = two_businesses["business_id_a"]
    token_a = two_businesses["token_a"]
    _set_plan(business_id_a, BusinessPlan.PREMIUM)
    client.patch("/api/v1/business/me", json={"currency": "NPR"}, headers=_auth_header(token_a))
    days = [{"day_of_week": d, "open_time": "09:00:00", "close_time": "17:00:00"} for d in range(6)]
    days.append({"day_of_week": 6, "closed": True})
    client.put("/api/v1/business/hours", json={"days": days}, headers=_auth_header(token_a))
    client.patch(
        "/api/v1/business/payment-settings",
        json={"payment_collection_enabled": True, "payment_provider": "esewa"},
        headers=_auth_header(token_a),
    )
    service = client.post(
        "/api/v1/services",
        json={"name": "Root Canal", "price": "45000.00", "duration_minutes": 60, "deposit_enabled": True, "deposit_percentage": 20},
        headers=_auth_header(token_a),
    ).json()
    customer = client.post("/api/v1/customers", json={"name": "T", "email": "t@example.com"}, headers=_auth_header(token_a)).json()

    target_date = _next_weekday(0)
    scheduled_at = datetime.combine(target_date, datetime.min.time()).replace(hour=13, tzinfo=ZoneInfo("UTC"))
    appt = client.post(
        "/api/v1/appointments",
        json={"customer_id": customer["id"], "service_id": service["id"], "scheduled_at": scheduled_at.isoformat()},
        headers=_auth_header(token_a),
    ).json()

    with SessionLocal() as db:
        appointment = db.get(Appointment, uuid.UUID(appt["id"]))
        token = appointment.checkin_token
        payment = db.query(Payment).filter(Payment.appointment_id == appointment.id).one()
        payment_id = payment.id

    # Real check-in — must NOT silently mark the payment collected.
    checkin_resp = client.post("/api/v1/appointments/checkin", json={"token": str(token)}, headers=_auth_header(token_a))
    assert checkin_resp.status_code == 200, checkin_resp.text
    pending = checkin_resp.json()["pending_payment"]
    assert pending is not None
    assert pending["remaining"] == "36000.00"
    assert pending["collected_in_person_amount"] is None
    assert pending["collected_in_person_at"] is None

    with SessionLocal() as db:
        payment = db.get(Payment, payment_id)
        assert payment.collected_in_person_amount is None
        assert payment.collected_in_person_at is None

    # Now the real, separate, explicit action.
    record_resp = client.post(
        f"/api/v1/payments/{payment_id}/collect-in-person", json={"amount": "36000.00"}, headers=_auth_header(token_a)
    )
    assert record_resp.status_code == 200, record_resp.text
    assert record_resp.json()["collected_in_person_amount"] == "36000.00"

    with SessionLocal() as db:
        payment = db.get(Payment, payment_id)
        assert str(payment.collected_in_person_amount) == "36000.00"
        assert payment.collected_in_person_at is not None
        # status (the ONLINE deposit's own gateway-verified field) untouched
        assert payment.status.value == "pending"


def test_monthly_report_completed_count_reflects_genuine_completion_not_mere_arrival(booked_ready):
    """The exact real gap the ticket named: confirm the report's completed
    count only moves on a real COMPLETED transition, never on ARRIVED alone."""
    from app.services.reporting.monthly_report_service import generate_monthly_report

    token_a = booked_ready["token_a"]
    business_id_a = booked_ready["business_id_a"]
    appointment_id = booked_ready["appointment_id"]
    target_date = _next_weekday(0)

    with SessionLocal() as db:
        before = generate_monthly_report(db, business_id=business_id_a, year=target_date.year, month=target_date.month)
    assert before["appointments"]["completed"]["implemented"] is True

    resp = client.post(
        "/api/v1/appointments/checkin", json={"token": str(booked_ready["checkin_token"])}, headers=_auth_header(token_a)
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["status"] == "arrived"

    with SessionLocal() as db:
        after_arrival = generate_monthly_report(
            db, business_id=business_id_a, year=target_date.year, month=target_date.month
        )
    # Arrival alone must NOT move the completed count — that's exactly the
    # real bug this split closes.
    assert after_arrival["appointments"]["completed"]["count"] == before["appointments"]["completed"]["count"]

    complete_resp = client.post(f"/api/v1/appointments/{appointment_id}/complete", headers=_auth_header(token_a))
    assert complete_resp.status_code == 200, complete_resp.text

    with SessionLocal() as db:
        after_complete = generate_monthly_report(
            db, business_id=business_id_a, year=target_date.year, month=target_date.month
        )
    assert after_complete["appointments"]["completed"]["count"] == before["appointments"]["completed"]["count"] + 1
    assert after_complete["appointments"]["completed"]["implemented"] is True


def test_monthly_report_counts_pre_split_legacy_completed_row(booked_ready):
    """A row written directly to COMPLETED — exactly what every pre-Phase-46-
    continued row in a real production DB looks like, since ARRIVED did not
    exist yet when they were completed — must remain valid and still count.
    This never goes through checkin_service at all, by design: it simulates
    data that predates this split entirely."""
    from app.services.reporting.monthly_report_service import generate_monthly_report

    business_id_a = booked_ready["business_id_a"]
    appointment_id = booked_ready["appointment_id"]
    target_date = _next_weekday(0)

    with SessionLocal() as db:
        before = generate_monthly_report(db, business_id=business_id_a, year=target_date.year, month=target_date.month)

    with SessionLocal() as db:
        appointment = db.get(Appointment, appointment_id)
        appointment.status = AppointmentStatus.COMPLETED
        appointment.completed_at = None  # honest: legacy rows never had this column at all
        db.commit()

    with SessionLocal() as db:
        after = generate_monthly_report(db, business_id=business_id_a, year=target_date.year, month=target_date.month)
    assert after["appointments"]["completed"]["count"] == before["appointments"]["completed"]["count"] + 1

    with SessionLocal() as db:
        appointment = db.get(Appointment, appointment_id)
        assert appointment.status == AppointmentStatus.COMPLETED  # still a valid, real status value


def test_mark_complete_requires_arrived_status(booked_ready):
    """A CONFIRMED appointment (never checked in) cannot be marked complete —
    the real lifecycle order (arrive, then complete) is enforced, not just
    suggested by the UI."""
    token_a = booked_ready["token_a"]
    resp = client.post(f"/api/v1/appointments/{booked_ready['appointment_id']}/complete", headers=_auth_header(token_a))
    assert resp.status_code == 422, resp.text
    assert "confirmed" in resp.json()["error"]["message"]


def test_mark_complete_marks_appointment_completed_real_http(booked_ready):
    token_a = booked_ready["token_a"]
    checkin_resp = client.post(
        "/api/v1/appointments/checkin", json={"token": str(booked_ready["checkin_token"])}, headers=_auth_header(token_a)
    )
    assert checkin_resp.status_code == 200, checkin_resp.text

    resp = client.post(f"/api/v1/appointments/{booked_ready['appointment_id']}/complete", headers=_auth_header(token_a))
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["status"] == "completed"
    assert body["completed_at"] is not None
    assert body["checked_in_at"] is not None  # never cleared by completion

    with SessionLocal() as db:
        appointment = db.get(Appointment, booked_ready["appointment_id"])
        assert appointment.status == AppointmentStatus.COMPLETED
        assert appointment.completed_at is not None


def test_duplicate_complete_returns_honest_already_completed(booked_ready):
    token_a = booked_ready["token_a"]
    client.post(
        "/api/v1/appointments/checkin", json={"token": str(booked_ready["checkin_token"])}, headers=_auth_header(token_a)
    )
    first = client.post(f"/api/v1/appointments/{booked_ready['appointment_id']}/complete", headers=_auth_header(token_a))
    assert first.status_code == 200, first.text
    real_completed_at = first.json()["completed_at"]

    second = client.post(f"/api/v1/appointments/{booked_ready['appointment_id']}/complete", headers=_auth_header(token_a))
    assert second.status_code == 409, second.text
    message = second.json()["error"]["message"]
    assert "already marked complete" in message
    assert real_completed_at[:19] in message


def test_staff_role_can_mark_complete(booked_ready):
    business_id_a = booked_ready["business_id_a"]
    token_a = booked_ready["token_a"]
    client.post(
        "/api/v1/appointments/checkin", json={"token": str(booked_ready["checkin_token"])}, headers=_auth_header(token_a)
    )

    with SessionLocal() as db:
        staff_user = BusinessUser(
            business_id=business_id_a, email=_unique_email("staff-complete"), hashed_password="not-used", role=BusinessUserRole.STAFF
        )
        db.add(staff_user)
        db.commit()
        db.refresh(staff_user)
        from app.core.security import create_access_token

        staff_token = create_access_token(user_id=staff_user.id, business_id=business_id_a, role=staff_user.role.value)

    resp = client.post(f"/api/v1/appointments/{booked_ready['appointment_id']}/complete", headers=_auth_header(staff_token))
    assert resp.status_code == 200, resp.text


def test_complete_never_claimed_twice_under_real_concurrent_claims(booked_ready):
    """Same real threading.Barrier proof technique as the check-in claim
    above — 8 real threads, independent DB sessions, forced to the identical
    instant, all racing the exact same atomic "mark complete" claim for the
    exact same real, already-ARRIVED appointment."""
    from app.services import checkin_service

    token_a = booked_ready["token_a"]
    business_id = booked_ready["business_id_a"]
    appointment_id = booked_ready["appointment_id"]

    checkin_resp = client.post(
        "/api/v1/appointments/checkin", json={"token": str(booked_ready["checkin_token"])}, headers=_auth_header(token_a)
    )
    assert checkin_resp.status_code == 200, checkin_resp.text

    n_threads = 8
    barrier = threading.Barrier(n_threads)
    results = [None] * n_threads

    def worker(i):
        with SessionLocal() as db:
            barrier.wait()
            try:
                appointment = checkin_service.mark_appointment_completed(
                    db, business_id=business_id, appointment_id=appointment_id
                )
                results[i] = ("won", appointment.id)
            except Exception as exc:
                results[i] = ("lost", type(exc).__name__)

    threads = [threading.Thread(target=worker, args=(i,)) for i in range(n_threads)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    winners = [r for r in results if r[0] == "won"]
    assert len(winners) == 1, f"expected exactly 1 winner, got {len(winners)}: {results}"

    with SessionLocal() as db:
        appointment = db.get(Appointment, appointment_id)
        assert appointment.status == AppointmentStatus.COMPLETED
        assert appointment.completed_at is not None
