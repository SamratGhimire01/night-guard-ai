"""Data entering the system is validated on the server (not only in the dashboard form), and what goes out in
downloads is inert: no spreadsheet formulas, no executable links."""

import io
import uuid
import zipfile

import pytest
from fastapi.testclient import TestClient
from openpyxl import Workbook

from app.db.database import SessionLocal
from app.db.models.business import Business
from app.main import app
from app.services.reporting.excel_export import _write_sheet

client = TestClient(app)


@pytest.fixture
def owner():
    email = f"validate-{uuid.uuid4().hex[:8]}@example.com"
    resp = client.post("/api/v1/auth/register", json={"business_name": "Validate", "timezone": "UTC", "email": email, "password": "correcthorse1"})
    business_id = uuid.UUID(resp.json()["business_id"])
    token = client.post("/api/v1/auth/login", json={"email": email, "password": "correcthorse1"}).json()["access_token"]
    yield {"Authorization": f"Bearer {token}"}
    with SessionLocal() as db:
        db.delete(db.get(Business, business_id))
        db.commit()


@pytest.mark.parametrize(
    ("body", "why"),
    [
        ({"name": "S", "price": "10", "duration_minutes": 100000}, "a service can't last 69 days"),
        ({"name": "S", "price": "1e30", "duration_minutes": 30}, "a price too big for the column used to crash with a 500"),
        ({"name": "S", "price": "NaN", "duration_minutes": 30}, "not a number"),
        ({"name": "   ", "price": "10", "duration_minutes": 30}, "blank name"),
    ],
)
def test_service_values_are_checked(owner, body, why):
    assert client.post("/api/v1/services", json=body, headers=owner).status_code == 422, why


@pytest.mark.parametrize(
    "body",
    [{"name": "X", "phone": "call me maybe"}, {"name": "X", "phone": "12"}, {"name": "X", "email": "not-an-email"}, {"name": "  "}],
)
def test_customer_contact_details_are_checked(owner, body):
    assert client.post("/api/v1/customers", json=body, headers=owner).status_code == 422


def test_usual_phone_formats_are_accepted(owner):
    for phone in ("+977 980-000 0000", "(555) 010-0100", "9800000000"):
        assert client.post("/api/v1/customers", json={"name": "X", "phone": phone}, headers=owner).status_code == 201


@pytest.mark.parametrize("url", ["javascript:alert(1)", "data:text/html,<script>alert(1)</script>", "yourbusiness.com"])
def test_business_website_must_be_a_web_address(owner, url):
    assert client.patch("/api/v1/business/me", json={"website": url}, headers=owner).status_code == 422


def test_business_website_accepts_https_and_clearing(owner):
    assert client.patch("/api/v1/business/me", json={"website": "https://clinic.example"}, headers=owner).json()["website"] == "https://clinic.example"
    assert client.patch("/api/v1/business/me", json={"website": None}, headers=owner).status_code == 200


def test_spreadsheet_downloads_never_contain_live_formulas():
    wb = Workbook()
    _write_sheet(wb.active, ["Customer"], [['=HYPERLINK("http://evil.example","Refund")'], ["Sita"], [5]])
    buf = io.BytesIO()
    wb.save(buf)
    sheet = zipfile.ZipFile(io.BytesIO(buf.getvalue())).read("xl/worksheets/sheet1.xml").decode()
    assert "<f>" not in sheet  # no formula element anywhere
    assert "HYPERLINK" in sheet  # the text itself is kept, as text


def test_the_same_customer_added_twice_is_one_customer(owner):
    first = client.post("/api/v1/customers", json={"name": "Hari", "phone": "+977 980-111 2222"}, headers=owner).json()
    again = client.post("/api/v1/customers", json={"name": "Hari Bahadur", "phone": "9779801112222", "email": "hari@example.com"}, headers=owner).json()
    assert again["id"] == first["id"]
    assert again["email"] == "hari@example.com"  # the new detail is kept
    assert len(client.get("/api/v1/customers?q=Hari", headers=owner).json()) == 1


@pytest.mark.parametrize(("paid", "completed"), [(50000, True), (1000, False), (None, True)])
def test_khalti_deposit_counts_only_when_the_full_amount_was_paid(monkeypatch, paid, completed):
    from decimal import Decimal

    from app.services.payments import khalti

    reply = {"status": "Completed", "pidx": "p1"} | ({"total_amount": paid} if paid is not None else {})
    monkeypatch.setattr(khalti, "_post_json", lambda *a, **k: reply)
    result = khalti.KhaltiPaymentProvider().verify_payment(payment_id=uuid.uuid4(), amount=Decimal("500.00"), gateway_reference="p1")
    assert result.completed is completed
