"""The Overview's setup checklist (GET /business/setup-status) and website-chat install detection.

Real HTTP and Postgres; each step is completed through the same API the dashboard uses."""

import uuid

import pytest
from fastapi.testclient import TestClient

import app.services.knowledge_service as knowledge_service_module
from app.db.database import SessionLocal
from app.db.models.business import Business
from app.db.models.integration import Integration
from app.db.models.knowledge import EMBEDDING_DIMENSIONS
from app.main import app

client = TestClient(app)


class _Embed:
    def embed(self, texts):
        return [[0.01] * EMBEDDING_DIMENSIONS for _ in texts]


@pytest.fixture
def owner(monkeypatch):
    monkeypatch.setattr(knowledge_service_module, "get_embedding_provider", lambda: _Embed())
    email = f"setup-{uuid.uuid4().hex[:10]}@example.com"
    reg = client.post(
        "/api/v1/auth/register",
        json={"business_name": "Setup Clinic", "timezone": "UTC", "email": email, "password": "correcthorse1"},
    )
    token = client.post("/api/v1/auth/login", json={"email": email, "password": "correcthorse1"}).json()["access_token"]
    business_id = reg.json()["business_id"]
    yield business_id, {"Authorization": f"Bearer {token}"}
    with SessionLocal() as db:
        db.delete(db.get(Business, uuid.UUID(business_id)))
        db.commit()


def _status(headers):
    body = client.get("/api/v1/business/setup-status", headers=headers).json()
    return {s["key"]: s["done"] for s in body["steps"]}, body


def test_a_new_business_has_every_step_open(owner):
    _, headers = owner
    done, body = _status(headers)
    assert done == {"services": False, "hours": False, "knowledge": False, "website": False, "channel": False}
    assert body["completed"] == 0 and body["total"] == 5


def test_each_step_ticks_itself_off_from_real_data(owner):
    business_id, headers = owner
    client.post("/api/v1/services", headers=headers, json={"name": "Cleaning", "price": "1500", "duration_minutes": 45})
    week = [{"day_of_week": d, "closed": d == 5, "open_time": None if d == 5 else "09:00", "close_time": None if d == 5 else "17:00"} for d in range(7)]
    assert client.put("/api/v1/business/hours", headers=headers, json={"days": week}).status_code == 200
    client.post("/api/v1/knowledge", headers=headers, json={"title": "Parking", "content": "Free parking behind."})
    client.get(f"/api/v1/widget/{business_id}/config", headers={"Origin": "https://setupclinic.example"})
    with SessionLocal() as db:
        db.add(Integration(business_id=uuid.UUID(business_id), type="whatsapp", config={}, enabled=True))
        db.commit()

    done, body = _status(headers)
    assert all(done.values()), done
    assert body["completed"] == 5


def test_the_dashboard_preview_and_the_dashboard_itself_do_not_count_as_installed(owner):
    business_id, headers = owner
    for origin in (None, "null", "http://localhost:5173"):
        client.get(f"/api/v1/widget/{business_id}/config", headers={"Origin": origin} if origin else {})
    done, _ = _status(headers)
    assert done["website"] is False


def test_install_origin_is_remembered(owner):
    business_id, headers = owner
    client.get(f"/api/v1/widget/{business_id}/config", headers={"Origin": "https://setupclinic.example"})
    client.get(f"/api/v1/widget/{business_id}/config", headers={"Origin": "https://other.example"})
    with SessionLocal() as db:
        b = db.get(Business, uuid.UUID(business_id))
        assert b.widget_installed_origin == "https://setupclinic.example"


def test_businesses_that_do_not_take_bookings_skip_the_services_step(owner):
    _, headers = owner
    client.patch("/api/v1/business/me", headers=headers, json={"booking_enabled": False})
    done, body = _status(headers)
    assert "services" not in done and body["total"] == 4


def test_a_disabled_channel_does_not_count(owner):
    business_id, headers = owner
    with SessionLocal() as db:
        db.add(Integration(business_id=uuid.UUID(business_id), type="instagram", config={}, enabled=False))
        db.commit()
    done, _ = _status(headers)
    assert done["channel"] is False
