"""Customers page: list with channel / conversations / appointments, search, CSV export, tenant isolation."""

import uuid
from datetime import UTC, datetime, timedelta

import pytest
from fastapi.testclient import TestClient

from app.db.database import SessionLocal
from app.db.models.appointment import Appointment, AppointmentStatus
from app.db.models.business import Business
from app.db.models.conversation import Conversation, Message, MessageSenderType
from app.db.models.customer import Customer
from app.db.models.service import Service
from app.main import app

client = TestClient(app)


def _business(label):
    email = f"{label.replace(' ', '-').lower()}-{uuid.uuid4().hex[:10]}@example.com"
    reg = client.post(
        "/api/v1/auth/register", json={"business_name": label, "timezone": "UTC", "email": email, "password": "correcthorse1"}
    )
    token = client.post("/api/v1/auth/login", json={"email": email, "password": "correcthorse1"}).json()["access_token"]
    return uuid.UUID(reg.json()["business_id"]), {"Authorization": f"Bearer {token}"}


@pytest.fixture
def shop():
    business_id, headers = _business("Customer Shop")
    with SessionLocal() as db:
        sita = Customer(business_id=business_id, name="Sita Gurung", phone="9800000011", email="sita@example.com")
        visitor = Customer(business_id=business_id, name="Website Visitor")
        tricky = Customer(business_id=business_id, name="=HYPERLINK(\"http://evil\")", phone="+977 1")
        db.add_all([sita, visitor, tricky])
        db.flush()
        convo = Conversation(business_id=business_id, customer_id=sita.id, channel="whatsapp", status="active")
        db.add(convo)
        db.flush()
        db.add(Message(conversation_id=convo.id, sender_type=MessageSenderType.CUSTOMER, content="hi"))
        service = Service(business_id=business_id, name="Cleaning", price=1500, duration_minutes=45)
        db.add(service)
        db.flush()
        db.add(Appointment(
            business_id=business_id, customer_id=sita.id, service_id=service.id,
            scheduled_at=datetime.now(UTC) + timedelta(days=1), duration_minutes=45, status=AppointmentStatus.CONFIRMED,
        ))
        db.commit()
    yield business_id, headers
    with SessionLocal() as db:
        db.delete(db.get(Business, business_id))
        db.commit()


def test_list_shows_channel_counts_and_hides_placeholder_names(shop):
    _, headers = shop
    rows = client.get("/api/v1/customers", headers=headers).json()
    by_phone = {r["phone"]: r for r in rows}
    sita = by_phone["9800000011"]
    assert sita["name"] == "Sita Gurung"
    assert sita["channel"] == "whatsapp"
    assert sita["conversations"] == 1 and sita["appointments"] == 1
    assert rows[0]["phone"] == "9800000011", "most recent contact first"
    assert any(r["name"] is None for r in rows), "channel placeholder names are not shown as names"


def test_search_matches_name_phone_or_email(shop):
    _, headers = shop
    for q in ("sita", "SITA@EXAMPLE", "98000000"):
        rows = client.get("/api/v1/customers", headers=headers, params={"q": q}).json()
        assert [r["phone"] for r in rows] == ["9800000011"], q


def test_csv_export_is_excel_friendly_and_defuses_formulas(shop):
    _, headers = shop
    resp = client.get("/api/v1/customers/export.csv", headers=headers)
    assert resp.status_code == 200
    assert resp.headers["content-type"].startswith("text/csv")
    text = resp.content.decode("utf-8")
    assert text.startswith("﻿")
    assert "Sita Gurung" in text
    assert "'=HYPERLINK" in text and ",=HYPERLINK" not in text
    assert "'+977 1" in text


def test_customers_never_cross_businesses(shop):
    _, _ = shop
    other_id, other_headers = _business("Other Shop")
    try:
        assert client.get("/api/v1/customers", headers=other_headers).json() == []
        assert "Sita" not in client.get("/api/v1/customers/export.csv", headers=other_headers).content.decode()
    finally:
        with SessionLocal() as db:
            db.delete(db.get(Business, other_id))
            db.commit()
