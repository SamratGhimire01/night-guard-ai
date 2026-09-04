"""Phase 12 — family/group bookings (app/services/booking_service.py's
create_group_appointments, app/services/conversation/booking_tool.py's
run_group).

Real DB throughout, no LLM involved (that's covered separately in
test_conversation.py's group-booking-tool wiring tests) — this file is about
the deterministic clustering/validation/atomicity logic: same-slot people
sharing one Appointment row with real AppointmentParticipant children,
different-service-per-person getting separate rows tied by group_booking_id,
honest partial-success reporting, real all-or-nothing atomicity (including the
race path), and cross-tenant isolation.
"""

import uuid
from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

import pytest
from fastapi.testclient import TestClient

from app.core.exceptions import ConflictError
from app.db.database import SessionLocal
from app.db.models.appointment import Appointment, AppointmentParticipant
from app.db.models.business import Business
from app.main import app
from app.services import booking_service

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
    email_a = _unique_email("grp-a-owner")
    email_b = _unique_email("grp-b-owner")

    resp_a = client.post(
        "/api/v1/auth/register",
        json={"business_name": "Group A", "timezone": "UTC", "email": email_a, "password": "correcthorse1"},
    )
    resp_b = client.post(
        "/api/v1/auth/register",
        json={"business_name": "Group B", "timezone": "UTC", "email": email_b, "password": "correcthorse1"},
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
    """Business A: Mon-Sat 9am-5pm (UTC), Sunday closed, two services (Cleaning
    30min, Consultation 20min), one customer (the account holder every group
    booking is attached to — Conversation.customer_id, same Phase 10 design)."""
    token_a = two_businesses["token_a"]

    days = [{"day_of_week": d, "open_time": "09:00:00", "close_time": "17:00:00"} for d in range(6)]
    days.append({"day_of_week": 6, "closed": True})
    resp = client.put("/api/v1/business/hours", json={"days": days}, headers=_auth_header(token_a))
    assert resp.status_code == 200, resp.text

    cleaning = client.post(
        "/api/v1/services",
        json={"name": "Cleaning", "price": "50.00", "duration_minutes": 30},
        headers=_auth_header(token_a),
    )
    assert cleaning.status_code == 201, cleaning.text

    consult = client.post(
        "/api/v1/services",
        json={"name": "Consultation", "price": "30.00", "duration_minutes": 20},
        headers=_auth_header(token_a),
    )
    assert consult.status_code == 201, consult.text

    customer = client.post("/api/v1/customers", json={"name": "Test Customer"}, headers=_auth_header(token_a))
    assert customer.status_code == 201, customer.text

    return {
        **two_businesses,
        "cleaning_id": uuid.UUID(cleaning.json()["id"]),
        "consult_id": uuid.UUID(consult.json()["id"]),
        "customer_id": uuid.UUID(customer.json()["id"]),
    }


def _person(label: str, service_id: uuid.UUID, scheduled_at: datetime) -> dict:
    return {"label": label, "service_id": service_id, "staff_id": None, "scheduled_at": scheduled_at}


# --- clustering: same slot shares one Appointment + participants -----------------


def test_same_service_same_time_creates_one_appointment_with_participants(business_a_ready):
    business_id = business_a_ready["business_id_a"]
    customer_id = business_a_ready["customer_id"]
    cleaning_id = business_a_ready["cleaning_id"]
    target = datetime.combine(_next_weekday(0), datetime.min.time()).replace(hour=10, tzinfo=ZoneInfo("UTC"))

    with SessionLocal() as db:
        result = booking_service.create_group_appointments(
            db,
            business_id=business_id,
            customer_id=customer_id,
            people=[
                _person("Jordan", cleaning_id, target),
                _person("Spouse", cleaning_id, target),
                _person("Daughter", cleaning_id, target),
            ],
            all_or_nothing=False,
        )

    assert result["success"] is True
    assert len(result["bookings"]) == 1, "three identical slots must cluster into one booking entry"
    booking = result["bookings"][0]
    assert booking["labels"] == ["Jordan", "Spouse", "Daughter"]
    appointment_id = uuid.UUID(booking["appointment"]["id"])

    with SessionLocal() as db:
        rows = db.query(Appointment).filter(Appointment.business_id == business_id).all()
        assert len(rows) == 1, "same slot for 3 people must be ONE Appointment row, not three"
        assert rows[0].group_booking_id is not None
        participants = (
            db.query(AppointmentParticipant).filter(AppointmentParticipant.appointment_id == appointment_id).all()
        )
    assert sorted(p.name for p in participants) == ["Daughter", "Jordan", "Spouse"]


def test_different_service_per_person_creates_separate_appointments_same_group_id(business_a_ready):
    business_id = business_a_ready["business_id_a"]
    customer_id = business_a_ready["customer_id"]
    cleaning_id = business_a_ready["cleaning_id"]
    consult_id = business_a_ready["consult_id"]
    day = _next_weekday(1)
    t1 = datetime.combine(day, datetime.min.time()).replace(hour=9, tzinfo=ZoneInfo("UTC"))
    t2 = datetime.combine(day, datetime.min.time()).replace(hour=11, tzinfo=ZoneInfo("UTC"))

    with SessionLocal() as db:
        result = booking_service.create_group_appointments(
            db,
            business_id=business_id,
            customer_id=customer_id,
            people=[_person("Jordan", consult_id, t1), _person("Spouse", cleaning_id, t2)],
            all_or_nothing=False,
        )

    assert result["success"] is True
    assert len(result["bookings"]) == 2

    with SessionLocal() as db:
        rows = db.query(Appointment).filter(Appointment.business_id == business_id).all()
    assert len(rows) == 2
    group_ids = {r.group_booking_id for r in rows}
    assert len(group_ids) == 1, "different service/time per person must still share one group_booking_id"
    assert {r.service_id for r in rows} == {cleaning_id, consult_id}


# --- honest partial success --------------------------------------------------------


def test_partial_success_reports_which_succeeded_and_which_failed(business_a_ready):
    business_id = business_a_ready["business_id_a"]
    customer_id = business_a_ready["customer_id"]
    cleaning_id = business_a_ready["cleaning_id"]
    consult_id = business_a_ready["consult_id"]
    day = _next_weekday(2)
    ok_time = datetime.combine(day, datetime.min.time()).replace(hour=9, tzinfo=ZoneInfo("UTC"))
    taken_time = datetime.combine(day, datetime.min.time()).replace(hour=13, tzinfo=ZoneInfo("UTC"))

    with SessionLocal() as db:
        # occupy the second person's requested slot ahead of time, under a
        # different customer, so it's genuinely unavailable when the group
        # booking runs.
        blocker = client.post(
            "/api/v1/customers", json={"name": "Blocker"}, headers=_auth_header(business_a_ready["token_a"])
        ).json()
        booking_service.create_appointment(
            db,
            business_id=business_id,
            customer_id=uuid.UUID(blocker["id"]),
            service_id=consult_id,
            staff_id=None,
            scheduled_at=taken_time,
        )

        result = booking_service.create_group_appointments(
            db,
            business_id=business_id,
            customer_id=customer_id,
            people=[_person("Jordan", cleaning_id, ok_time), _person("Spouse", consult_id, taken_time)],
            all_or_nothing=False,
        )

    assert result["success"] is False
    by_label = {tuple(b["labels"]): b for b in result["bookings"]}
    assert by_label[("Jordan",)]["success"] is True
    assert by_label[("Jordan",)]["appointment"] is not None
    assert by_label[("Spouse",)]["success"] is False
    assert by_label[("Spouse",)]["appointment"] is None
    assert "not available" in by_label[("Spouse",)]["message"].lower()

    with SessionLocal() as db:
        # exactly the successful one was written — the failed one left no trace.
        rows = (
            db.query(Appointment)
            .filter(Appointment.business_id == business_id, Appointment.customer_id == customer_id)
            .all()
        )
    assert len(rows) == 1
    assert rows[0].service_id == cleaning_id


# --- all-or-nothing atomicity -------------------------------------------------------


def test_all_or_nothing_writes_nothing_when_one_slot_is_unavailable(business_a_ready):
    business_id = business_a_ready["business_id_a"]
    customer_id = business_a_ready["customer_id"]
    cleaning_id = business_a_ready["cleaning_id"]
    consult_id = business_a_ready["consult_id"]
    day = _next_weekday(3)
    ok_time = datetime.combine(day, datetime.min.time()).replace(hour=9, tzinfo=ZoneInfo("UTC"))
    taken_time = datetime.combine(day, datetime.min.time()).replace(hour=13, tzinfo=ZoneInfo("UTC"))

    with SessionLocal() as db:
        blocker = client.post(
            "/api/v1/customers", json={"name": "Blocker"}, headers=_auth_header(business_a_ready["token_a"])
        ).json()
        booking_service.create_appointment(
            db,
            business_id=business_id,
            customer_id=uuid.UUID(blocker["id"]),
            service_id=consult_id,
            staff_id=None,
            scheduled_at=taken_time,
        )

        result = booking_service.create_group_appointments(
            db,
            business_id=business_id,
            customer_id=customer_id,
            people=[_person("Jordan", cleaning_id, ok_time), _person("Spouse", consult_id, taken_time)],
            all_or_nothing=True,
        )

    assert result["success"] is False
    assert result["all_or_nothing"] is True
    assert all(b["success"] is False for b in result["bookings"])

    with SessionLocal() as db:
        rows = (
            db.query(Appointment)
            .filter(Appointment.business_id == business_id, Appointment.customer_id == customer_id)
            .all()
        )
    assert rows == [], "all-or-nothing must write NOTHING when even one requested slot is unavailable"


def test_all_or_nothing_books_everyone_when_every_slot_is_free(business_a_ready):
    business_id = business_a_ready["business_id_a"]
    customer_id = business_a_ready["customer_id"]
    cleaning_id = business_a_ready["cleaning_id"]
    consult_id = business_a_ready["consult_id"]
    day = _next_weekday(4)
    t1 = datetime.combine(day, datetime.min.time()).replace(hour=9, tzinfo=ZoneInfo("UTC"))
    t2 = datetime.combine(day, datetime.min.time()).replace(hour=11, tzinfo=ZoneInfo("UTC"))

    with SessionLocal() as db:
        result = booking_service.create_group_appointments(
            db,
            business_id=business_id,
            customer_id=customer_id,
            people=[_person("Jordan", cleaning_id, t1), _person("Spouse", consult_id, t2)],
            all_or_nothing=True,
        )

    assert result["success"] is True
    assert all(b["success"] for b in result["bookings"])
    with SessionLocal() as db:
        rows = (
            db.query(Appointment)
            .filter(Appointment.business_id == business_id, Appointment.customer_id == customer_id)
            .all()
        )
    assert len(rows) == 2


def test_all_or_nothing_race_rolls_back_everything(business_a_ready, monkeypatch):
    """The pre-check (Pass 1) says every slot is free, but a genuine race steals
    one slot before the write pass (Pass 2) runs — the whole transaction must
    roll back, leaving zero rows, never a partial write."""
    business_id = business_a_ready["business_id_a"]
    customer_id = business_a_ready["customer_id"]
    cleaning_id = business_a_ready["cleaning_id"]
    consult_id = business_a_ready["consult_id"]
    day = _next_weekday(5)
    t1 = datetime.combine(day, datetime.min.time()).replace(hour=9, tzinfo=ZoneInfo("UTC"))
    t2 = datetime.combine(day, datetime.min.time()).replace(hour=11, tzinfo=ZoneInfo("UTC"))

    real_create_appointment = booking_service.create_appointment
    call_count = {"n": 0}

    def _flaky_create_appointment(db, **kwargs):
        call_count["n"] += 1
        if call_count["n"] == 2:
            db.rollback()
            raise ConflictError("This slot was just booked by someone else — please choose another time.")
        return real_create_appointment(db, **kwargs)

    monkeypatch.setattr(booking_service, "create_appointment", _flaky_create_appointment)

    with SessionLocal() as db:
        result = booking_service.create_group_appointments(
            db,
            business_id=business_id,
            customer_id=customer_id,
            people=[_person("Jordan", cleaning_id, t1), _person("Spouse", consult_id, t2)],
            all_or_nothing=True,
        )

    assert result["success"] is False
    assert all(b["success"] is False for b in result["bookings"])
    with SessionLocal() as db:
        rows = (
            db.query(Appointment)
            .filter(Appointment.business_id == business_id, Appointment.customer_id == customer_id)
            .all()
        )
    assert rows == [], "a race during the write pass must leave zero rows, not a partial group"


# --- GET /appointments?group_booking_id= filtering --------------------------------


def test_list_appointments_filters_by_group_booking_id(business_a_ready):
    token_a = business_a_ready["token_a"]
    business_id = business_a_ready["business_id_a"]
    customer_id = business_a_ready["customer_id"]
    cleaning_id = business_a_ready["cleaning_id"]
    consult_id = business_a_ready["consult_id"]
    day = _next_weekday(0)
    t1 = datetime.combine(day, datetime.min.time()).replace(hour=9, tzinfo=ZoneInfo("UTC"))
    t2 = datetime.combine(day, datetime.min.time()).replace(hour=11, tzinfo=ZoneInfo("UTC"))

    with SessionLocal() as db:
        result = booking_service.create_group_appointments(
            db,
            business_id=business_id,
            customer_id=customer_id,
            people=[_person("Jordan", cleaning_id, t1), _person("Spouse", consult_id, t2)],
            all_or_nothing=False,
        )
    group_id = result["group_booking_id"]

    resp = client.get(
        f"/api/v1/appointments?group_booking_id={group_id}", headers=_auth_header(token_a)
    )
    assert resp.status_code == 200, resp.text
    ids = {a["id"] for a in resp.json()}
    assert ids == {b["appointment"]["id"] for b in result["bookings"]}
    assert all(a["group_booking_id"] == group_id for a in resp.json())

    # An unrelated appointment (no group) must never show up under this filter.
    other = client.post(
        "/api/v1/appointments",
        json={
            "customer_id": str(customer_id),
            "service_id": str(cleaning_id),
            "scheduled_at": f"{_next_weekday(1).isoformat()}T09:00:00+00:00",
        },
        headers=_auth_header(token_a),
    )
    assert other.status_code == 201, other.text
    resp2 = client.get(f"/api/v1/appointments?group_booking_id={group_id}", headers=_auth_header(token_a))
    assert other.json()["id"] not in {a["id"] for a in resp2.json()}


# --- cross-tenant isolation ----------------------------------------------------------


def test_group_booking_rejects_other_businesss_customer(business_a_ready):
    business_id = business_a_ready["business_id_a"]
    cleaning_id = business_a_ready["cleaning_id"]

    email_c = _unique_email("grp-c-owner")
    resp_c = client.post(
        "/api/v1/auth/register",
        json={"business_name": "Group C", "timezone": "UTC", "email": email_c, "password": "correcthorse1"},
    )
    login_c = client.post("/api/v1/auth/login", json={"email": email_c, "password": "correcthorse1"})
    customer_c = client.post(
        "/api/v1/customers", json={"name": "Foreign Customer"}, headers=_auth_header(login_c.json()["access_token"])
    ).json()

    target = datetime.combine(_next_weekday(0), datetime.min.time()).replace(hour=9, tzinfo=ZoneInfo("UTC"))
    with pytest.raises(Exception) as exc_info:
        with SessionLocal() as db:
            booking_service.create_group_appointments(
                db,
                business_id=business_id,
                customer_id=uuid.UUID(customer_c["id"]),
                people=[_person("Someone", cleaning_id, target)],
                all_or_nothing=False,
            )
    assert "not found" in str(exc_info.value).lower()

    with SessionLocal() as db:
        business_c = db.get(Business, uuid.UUID(resp_c.json()["business_id"]))
        if business_c is not None:
            db.delete(business_c)
        db.commit()

    with SessionLocal() as db:
        count = db.query(Appointment).filter(Appointment.business_id == business_id).count()
    assert count == 0, "a rejected cross-tenant group booking must not have written anything"


def test_group_booking_rejects_other_businesss_service(business_a_ready):
    business_id = business_a_ready["business_id_a"]
    customer_id = business_a_ready["customer_id"]

    email_c = _unique_email("grp-c2-owner")
    resp_c = client.post(
        "/api/v1/auth/register",
        json={"business_name": "Group C2", "timezone": "UTC", "email": email_c, "password": "correcthorse1"},
    )
    login_c = client.post("/api/v1/auth/login", json={"email": email_c, "password": "correcthorse1"})
    foreign_service = client.post(
        "/api/v1/services",
        json={"name": "Other Biz Service", "price": "10.00", "duration_minutes": 15},
        headers=_auth_header(login_c.json()["access_token"]),
    ).json()

    target = datetime.combine(_next_weekday(0), datetime.min.time()).replace(hour=9, tzinfo=ZoneInfo("UTC"))
    with SessionLocal() as db:
        result = booking_service.create_group_appointments(
            db,
            business_id=business_id,
            customer_id=customer_id,
            people=[_person("Someone", uuid.UUID(foreign_service["id"]), target)],
            all_or_nothing=False,
        )
    assert result["success"] is False
    assert "not found" in result["bookings"][0]["message"].lower()

    with SessionLocal() as db:
        business_c = db.get(Business, uuid.UUID(resp_c.json()["business_id"]))
        if business_c is not None:
            db.delete(business_c)
        db.commit()
