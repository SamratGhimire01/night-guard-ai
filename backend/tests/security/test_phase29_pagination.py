"""Phase 29 — TIER 2 ITEM 7: real before/after proof that GET /appointments
and GET /training/history are now bounded, using a business with 50+ real
rows (Phase 28's F3 flagged both as the highest-risk unbounded endpoints).

Appointments are inserted directly via the ORM (not through the booking API)
purely for test speed — 60 real bookings through the full slot-availability
check would need 60 non-overlapping real slots; the pagination code path
under test is the SELECT in booking_service.list_appointments, which doesn't
care how the rows got there. TrainingQuestion rows are inserted directly too
(same pattern every other phase's tests use — no create-by-id API exists for
either resource type reachable outside their own normal flow)."""

import uuid
from datetime import datetime, timedelta, timezone

import pytest
from fastapi.testclient import TestClient

from app.db.database import SessionLocal
from app.db.models.appointment import Appointment, AppointmentStatus
from app.db.models.business import Business, BusinessUser
from app.db.models.training import TrainingQuestion
from app.main import app

client = TestClient(app)


def _auth_header(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


@pytest.fixture
def business_with_60_rows():
    email = f"pagination-{uuid.uuid4().hex[:10]}@example.com"
    resp = client.post(
        "/api/v1/auth/register",
        json={"business_name": "Pagination Test Co", "timezone": "UTC", "email": email, "password": "correcthorse1"},
    )
    assert resp.status_code == 201, resp.text
    business_id = uuid.UUID(resp.json()["business_id"])
    token = client.post("/api/v1/auth/login", json={"email": email, "password": "correcthorse1"}).json()["access_token"]

    customer = client.post("/api/v1/customers", json={"name": "Pagination Customer"}, headers=_auth_header(token)).json()
    service = client.post(
        "/api/v1/services", json={"name": "Pagination Service", "price": "10.00", "duration_minutes": 15},
        headers=_auth_header(token),
    ).json()

    with SessionLocal() as db:
        owner = db.query(BusinessUser).filter(BusinessUser.business_id == business_id).first()
        base_time = datetime.now(timezone.utc) + timedelta(days=10)
        for i in range(60):
            db.add(
                Appointment(
                    business_id=business_id,
                    customer_id=uuid.UUID(customer["id"]),
                    service_id=uuid.UUID(service["id"]),
                    staff_id=None,
                    scheduled_at=base_time + timedelta(hours=i),
                    duration_minutes=15,
                    status=AppointmentStatus.CONFIRMED,
                )
            )
            db.add(
                TrainingQuestion(
                    business_id=business_id,
                    question=f"Question number {i}",
                    answer=f"Answer number {i}",
                    intent="general_question",
                    asked_by=owner.id,
                )
            )
        db.commit()

    yield {"business_id": business_id, "token": token}

    with SessionLocal() as db:
        b = db.get(Business, business_id)
        if b is not None:
            db.delete(b)
        db.commit()


def test_appointments_pagination_before_after_with_60_real_rows(business_with_60_rows):
    token = business_with_60_rows["token"]

    default_page = client.get("/api/v1/appointments", headers=_auth_header(token))
    assert default_page.status_code == 200, default_page.text
    default_body = default_page.json()
    print(f"\n=== TIER 2 ITEM 7 — GET /appointments, 60 real rows, no limit/offset given ===")
    print(f"BEFORE the fix this would have returned all 60. AFTER: returned {len(default_body)} (default limit=50).")
    assert len(default_body) == 50, f"expected the default page size of 50, got {len(default_body)}"

    page_1 = client.get("/api/v1/appointments?limit=20&offset=0", headers=_auth_header(token)).json()
    page_2 = client.get("/api/v1/appointments?limit=20&offset=20", headers=_auth_header(token)).json()
    page_3 = client.get("/api/v1/appointments?limit=20&offset=40", headers=_auth_header(token)).json()
    assert [len(page_1), len(page_2), len(page_3)] == [20, 20, 20]
    ids_1, ids_2, ids_3 = {a["id"] for a in page_1}, {a["id"] for a in page_2}, {a["id"] for a in page_3}
    assert ids_1.isdisjoint(ids_2) and ids_2.isdisjoint(ids_3) and ids_1.isdisjoint(ids_3), (
        "pages overlapped — offset is not working"
    )
    print(f"3 pages of 20 (limit=20&offset=0/20/40): {len(ids_1)}+{len(ids_2)}+{len(ids_3)} = 60 rows, zero overlap.")

    oversized = client.get("/api/v1/appointments?limit=500", headers=_auth_header(token))
    assert oversized.status_code == 422, f"limit above the 200 cap should be rejected: {oversized.text}"
    print(f"limit=500 (above the 200 cap) -> 422, not silently clamped or a 500: {oversized.json()}")


def test_training_history_pagination_before_after_with_60_real_rows(business_with_60_rows):
    token = business_with_60_rows["token"]

    default_page = client.get("/api/v1/training/history", headers=_auth_header(token))
    assert default_page.status_code == 200, default_page.text
    default_body = default_page.json()
    print(f"\n=== TIER 2 ITEM 7 — GET /training/history, 60 real rows, no limit/offset given ===")
    print(f"BEFORE the fix this would have returned all 60. AFTER: returned {len(default_body)} (default limit=50).")
    assert len(default_body) == 50, f"expected the default page size of 50, got {len(default_body)}"

    page_1 = client.get("/api/v1/training/history?limit=25&offset=0", headers=_auth_header(token)).json()
    page_2 = client.get("/api/v1/training/history?limit=25&offset=25", headers=_auth_header(token)).json()
    page_3 = client.get("/api/v1/training/history?limit=25&offset=50", headers=_auth_header(token)).json()
    assert [len(page_1), len(page_2), len(page_3)] == [25, 25, 10]
    ids_1, ids_2, ids_3 = (
        {q["id"] for q in page_1},
        {q["id"] for q in page_2},
        {q["id"] for q in page_3},
    )
    assert ids_1.isdisjoint(ids_2) and ids_2.isdisjoint(ids_3) and ids_1.isdisjoint(ids_3)
    print(f"3 pages (limit=25, offsets 0/25/50): {len(ids_1)}+{len(ids_2)}+{len(ids_3)} = 60 rows, zero overlap.")
