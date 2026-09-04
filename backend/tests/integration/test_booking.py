"""Phase 10 — booking engine (app/services/booking_service.py, app/api/routes/appointments.py).

Real DB throughout, no LLM involved (that's covered separately in
test_conversation.py's booking-tool tests) — this file is about the
deterministic availability/booking logic and its HTTP surface: slot exclusion
(booked/outside-hours/holiday), validation status codes, cross-tenant
isolation, and the real concurrent-request race condition.
"""

import uuid
from concurrent.futures import ThreadPoolExecutor
from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

import pytest
from fastapi.testclient import TestClient

from app.db.database import SessionLocal
from app.db.models.appointment import Appointment, AppointmentStatus
from app.db.models.business import Business
from app.main import app
from app.services import booking_service

client = TestClient(app)


def _unique_email(label: str) -> str:
    return f"{label}-{uuid.uuid4().hex[:10]}@example.com"


def _auth_header(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


def _next_weekday(target_weekday: int) -> date:
    """The next date (strictly after today) that falls on `target_weekday`
    (0=Monday..6=Sunday) — deterministic regardless of what day the test runs."""
    today = date.today()
    days_ahead = (target_weekday - today.weekday()) % 7
    days_ahead = days_ahead or 7
    return today + timedelta(days=days_ahead)


@pytest.fixture
def two_businesses():
    email_a = _unique_email("book-a-owner")
    email_b = _unique_email("book-b-owner")

    resp_a = client.post(
        "/api/v1/auth/register",
        json={"business_name": "Book A", "timezone": "UTC", "email": email_a, "password": "correcthorse1"},
    )
    resp_b = client.post(
        "/api/v1/auth/register",
        json={"business_name": "Book B", "timezone": "UTC", "email": email_b, "password": "correcthorse1"},
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


# --- get_available_slots exclusions ---------------------------------------------


def test_get_available_slots_excludes_already_booked_slot(business_a_ready):
    business_id = business_a_ready["business_id_a"]
    service_id = business_a_ready["service_id"]
    customer_id = business_a_ready["customer_id"]
    target_date = _next_weekday(0)  # a Monday, always open per the fixture

    with SessionLocal() as db:
        booked_at = datetime.combine(target_date, datetime.min.time()).replace(hour=10, tzinfo=ZoneInfo("UTC"))
        appointment = booking_service.create_appointment(
            db,
            business_id=business_id,
            customer_id=customer_id,
            service_id=service_id,
            staff_id=None,
            scheduled_at=booked_at,
        )
        assert appointment.id is not None

        slots = booking_service.get_available_slots(
            db, business_id=business_id, service_id=service_id, date_from=target_date, date_to=target_date
        )

    assert booked_at not in slots, "a real booked slot must never come back as available"
    # its neighbor (10:30, back-to-back, no overlap) must still be free
    assert (booked_at + timedelta(minutes=30)) in slots


def test_get_available_slots_excludes_outside_business_hours(business_a_ready):
    business_id = business_a_ready["business_id_a"]
    service_id = business_a_ready["service_id"]
    target_date = _next_weekday(0)

    with SessionLocal() as db:
        slots = booking_service.get_available_slots(
            db, business_id=business_id, service_id=service_id, date_from=target_date, date_to=target_date
        )

    assert slots, "expected real open slots on a normal open weekday"
    for slot in slots:
        assert slot.hour >= 9
        assert (slot + timedelta(minutes=30)).time() <= datetime.min.time().replace(hour=17)


def test_get_available_slots_excludes_holiday(business_a_ready):
    token_a = business_a_ready["token_a"]
    business_id = business_a_ready["business_id_a"]
    service_id = business_a_ready["service_id"]
    target_date = _next_weekday(1)  # a Tuesday, normally open per the fixture

    exc = client.post(
        "/api/v1/business/hours/exceptions",
        json={"date": target_date.isoformat(), "closed": True},
        headers=_auth_header(token_a),
    )
    assert exc.status_code == 201, exc.text

    with SessionLocal() as db:
        slots = booking_service.get_available_slots(
            db, business_id=business_id, service_id=service_id, date_from=target_date, date_to=target_date
        )

    assert slots == [], "a real holiday exception must exclude every slot on that date"


# --- validation ------------------------------------------------------------------


def test_create_appointment_rejects_nonexistent_service(business_a_ready):
    token_a = business_a_ready["token_a"]
    customer_id = business_a_ready["customer_id"]
    target_date = _next_weekday(0)

    resp = client.post(
        "/api/v1/appointments",
        json={
            "customer_id": str(customer_id),
            "service_id": str(uuid.uuid4()),
            "scheduled_at": f"{target_date.isoformat()}T10:00:00+00:00",
        },
        headers=_auth_header(token_a),
    )
    assert resp.status_code == 404, resp.text
    assert resp.status_code != 500


def test_create_appointment_rejects_slot_outside_business_hours(business_a_ready):
    token_a = business_a_ready["token_a"]
    service_id = business_a_ready["service_id"]
    customer_id = business_a_ready["customer_id"]
    target_date = _next_weekday(0)

    resp = client.post(
        "/api/v1/appointments",
        json={
            "customer_id": str(customer_id),
            "service_id": str(service_id),
            "scheduled_at": f"{target_date.isoformat()}T20:00:00+00:00",  # 8pm, hours end at 5pm
        },
        headers=_auth_header(token_a),
    )
    assert resp.status_code == 422, resp.text
    assert resp.status_code != 500


def test_create_appointment_rejects_holiday(business_a_ready):
    token_a = business_a_ready["token_a"]
    service_id = business_a_ready["service_id"]
    customer_id = business_a_ready["customer_id"]
    target_date = _next_weekday(2)  # a Wednesday, normally open

    exc = client.post(
        "/api/v1/business/hours/exceptions",
        json={"date": target_date.isoformat(), "closed": True},
        headers=_auth_header(token_a),
    )
    assert exc.status_code == 201, exc.text

    resp = client.post(
        "/api/v1/appointments",
        json={
            "customer_id": str(customer_id),
            "service_id": str(service_id),
            "scheduled_at": f"{target_date.isoformat()}T10:00:00+00:00",
        },
        headers=_auth_header(token_a),
    )
    assert resp.status_code == 422, resp.text
    assert resp.status_code != 500


def test_create_appointment_rejects_already_booked_slot(business_a_ready):
    token_a = business_a_ready["token_a"]
    service_id = business_a_ready["service_id"]
    customer_id = business_a_ready["customer_id"]
    target_date = _next_weekday(3)
    payload = {
        "customer_id": str(customer_id),
        "service_id": str(service_id),
        "scheduled_at": f"{target_date.isoformat()}T11:00:00+00:00",
    }

    first = client.post("/api/v1/appointments", json=payload, headers=_auth_header(token_a))
    assert first.status_code == 201, first.text

    second = client.post("/api/v1/appointments", json=payload, headers=_auth_header(token_a))
    assert second.status_code == 422, second.text
    assert second.status_code != 500


# --- cross-tenant isolation --------------------------------------------------------


def test_cross_tenant_cannot_book_against_other_businesss_service(business_a_ready):
    token_b = business_a_ready["token_b"]
    service_id = business_a_ready["service_id"]  # belongs to business A
    customer_id = business_a_ready["customer_id"]  # also business A's
    target_date = _next_weekday(0)

    resp = client.post(
        "/api/v1/appointments",
        json={
            "customer_id": str(customer_id),
            "service_id": str(service_id),
            "scheduled_at": f"{target_date.isoformat()}T10:00:00+00:00",
        },
        headers=_auth_header(token_b),
    )
    assert resp.status_code == 404, resp.text

    with SessionLocal() as db:
        count = db.query(Appointment).filter(Appointment.service_id == service_id).count()
    assert count == 0, "the rejected cross-tenant request must not have written anything"


def test_cross_tenant_cannot_read_appointment_by_guessed_id(business_a_ready):
    token_a = business_a_ready["token_a"]
    token_b = business_a_ready["token_b"]
    service_id = business_a_ready["service_id"]
    customer_id = business_a_ready["customer_id"]
    target_date = _next_weekday(0)

    created = client.post(
        "/api/v1/appointments",
        json={
            "customer_id": str(customer_id),
            "service_id": str(service_id),
            "scheduled_at": f"{target_date.isoformat()}T10:00:00+00:00",
        },
        headers=_auth_header(token_a),
    )
    assert created.status_code == 201, created.text
    appointment_id = created.json()["id"]

    resp = client.get(f"/api/v1/appointments/{appointment_id}", headers=_auth_header(token_b))
    assert resp.status_code == 404, resp.text

    resp_list = client.get("/api/v1/appointments", headers=_auth_header(token_b))
    assert resp_list.status_code == 200
    assert all(a["id"] != appointment_id for a in resp_list.json())


# --- race condition ----------------------------------------------------------------


def test_concurrent_booking_race_exactly_one_succeeds(business_a_ready):
    """Regression coverage for the invariant that actually matters: two requests
    for the same slot can never BOTH succeed, and the DB never ends up with two
    rows for it. Run through a thread pool so the two requests genuinely overlap
    in wall-clock time rather than running strictly sequentially.

    This in-process TestClient version is a best-effort regression test, not the
    authoritative proof of the DB-level race guarantee: FastAPI's TestClient can
    serialize two threads' calls closely enough that the second one loses at
    booking_service's own pre-check (422) rather than at the database's exclusion
    constraint (409) — both are honest "not available" outcomes, so both are
    accepted here. The actual DB-constraint race (both requests passing the
    pre-check, one losing at INSERT with a real 409) was separately verified with
    real concurrent HTTP requests against the live running server — see
    PHASE_STATUS.md, this never-both-succeed property is what's asserted here."""
    token_a = business_a_ready["token_a"]
    service_id = business_a_ready["service_id"]
    customer_id = business_a_ready["customer_id"]
    target_date = _next_weekday(4)
    payload = {
        "customer_id": str(customer_id),
        "service_id": str(service_id),
        "scheduled_at": f"{target_date.isoformat()}T13:00:00+00:00",
    }

    def _book():
        return client.post("/api/v1/appointments", json=payload, headers=_auth_header(token_a))

    with ThreadPoolExecutor(max_workers=2) as pool:
        futures = [pool.submit(_book), pool.submit(_book)]
        responses = [f.result() for f in futures]

    statuses = sorted(r.status_code for r in responses)
    assert statuses[0] == 201, [r.text for r in responses]
    assert statuses[1] in (409, 422), [r.text for r in responses]

    with SessionLocal() as db:
        count = (
            db.query(Appointment)
            .filter(Appointment.service_id == service_id, Appointment.status != AppointmentStatus.CANCELLED)
            .count()
        )
    assert count == 1, "exactly one Appointment row must exist after the race"
