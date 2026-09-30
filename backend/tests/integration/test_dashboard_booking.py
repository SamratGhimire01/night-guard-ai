"""Adding an appointment from the dashboard (phone and walk-in bookings): open times, the booking itself, no double
booking, and no "new booking" alert to the owner for a booking they made themselves."""

import uuid
from datetime import date, timedelta

import pytest
from fastapi.testclient import TestClient

import app.services.owner_alert_service as alerts
from app.db.database import SessionLocal
from app.db.models.business import Business
from app.main import app

client = TestClient(app)


def _next(weekday: int) -> date:
    today = date.today()
    return today + timedelta(days=(weekday - today.weekday()) % 7 or 7)


@pytest.fixture
def clinic(monkeypatch):
    sent = []
    monkeypatch.setattr(alerts, "_in_background", lambda **kw: sent.append(kw))
    email = f"desk-{uuid.uuid4().hex[:10]}@example.com"
    reg = client.post(
        "/api/v1/auth/register",
        json={"business_name": "Desk Clinic", "timezone": "UTC", "email": email, "password": "correcthorse1"},
    )
    token = client.post("/api/v1/auth/login", json={"email": email, "password": "correcthorse1"}).json()["access_token"]
    headers = {"Authorization": f"Bearer {token}"}
    week = [{"day_of_week": d, "closed": False, "open_time": "09:00", "close_time": "12:00"} for d in range(7)]
    assert client.put("/api/v1/business/hours", headers=headers, json={"days": week}).status_code == 200
    service = client.post("/api/v1/services", headers=headers, json={"name": "Check-up", "price": "800", "duration_minutes": 30}).json()
    business_id = reg.json()["business_id"]
    yield headers, service["id"], sent
    with SessionLocal() as db:
        db.delete(db.get(Business, uuid.UUID(business_id)))
        db.commit()


def _slots(headers, service_id, on):
    resp = client.get("/api/v1/appointments/available-slots", headers=headers, params={"service_id": service_id, "on": on.isoformat()})
    assert resp.status_code == 200, resp.text
    return resp.json()["slots"]


def test_open_times_follow_business_hours(clinic):
    headers, service_id, _ = clinic
    slots = _slots(headers, service_id, _next(2))
    assert slots, "a weekday inside opening hours has open times"
    assert all("T09:" in s or "T10:" in s or "T11:" in s for s in slots)


def test_booking_from_the_dashboard_takes_the_slot_and_does_not_alert_the_owner(clinic):
    headers, service_id, sent = clinic
    day = _next(3)
    slot = _slots(headers, service_id, day)[0]
    customer = client.post("/api/v1/customers", headers=headers, json={"name": "Walk-in Ram", "phone": "9800000002"})
    assert customer.status_code == 201, customer.text
    booking = client.post(
        "/api/v1/appointments", headers=headers,
        json={"customer_id": customer.json()["id"], "service_id": service_id, "scheduled_at": slot},
    )
    assert booking.status_code == 201, booking.text
    assert slot not in _slots(headers, service_id, day)
    listed = client.get("/api/v1/appointments", headers=headers, params={"date_from": day.isoformat(), "date_to": day.isoformat()}).json()
    assert [a["customer_name"] for a in listed] == ["Walk-in Ram"]
    assert sent == []

    again = client.post(
        "/api/v1/appointments", headers=headers,
        json={"customer_id": customer.json()["id"], "service_id": service_id, "scheduled_at": slot},
    )
    assert again.status_code == 422  # the slot is no longer open: refused, nothing double-booked


def test_open_times_for_another_business_service_are_not_visible(clinic):
    headers, _, _ = clinic
    resp = client.get(
        "/api/v1/appointments/available-slots", headers=headers, params={"service_id": str(uuid.uuid4()), "on": _next(2).isoformat()}
    )
    assert resp.status_code == 404
