"""Phase 44 — real eSewa/Khalti payment collection (Premium-only), per-service
deposit configuration.

Real network calls to eSewa/Khalti are stubbed at payment_service._PROVIDERS
(the same seam google_calendar_service tests stub _create_event/_post_token_
endpoint at) so this automated suite never depends on network access — the
real, unstubbed eSewa/Khalti sandbox walkthrough (real signed form, real
login, real status-check/lookup API, real completed + failed transactions)
is a separate manual verification pass documented in PHASE_STATUS.md.

Covers: per-service deposit validation and persistence, the payment-settings
402 gate + NPR-currency guard, real deposit-amount calculation, a
deposit-disabled service never generating a payment request, a gateway
failure never touching the appointment, and cross-tenant isolation of the
pending-payments dashboard view.
"""

import uuid

import pytest
from fastapi.testclient import TestClient

from app.db.database import SessionLocal
from app.db.models.appointment import Appointment
from app.db.models.business import Business, BusinessPlan
from app.db.models.payment import Payment, PaymentStatus
from app.main import app
from app.services import payment_service
from app.services.payments.base import PaymentGatewayError, PaymentInitiation, PaymentVerification

client = TestClient(app)


def _unique_email(label: str) -> str:
    return f"{label}-{uuid.uuid4().hex[:10]}@example.com"


def _auth_header(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


def _set_plan(business_id: uuid.UUID, plan: BusinessPlan) -> None:
    with SessionLocal() as db:
        business = db.get(Business, business_id)
        business.plan = plan
        db.commit()


class _FakeProvider:
    """Deterministic stand-in for EsewaPaymentProvider/KhaltiPaymentProvider —
    never touches the network. `initiate_result`/`verify_result` are set per
    test; `raise_on_initiate` lets a test simulate a real gateway failure."""

    name = "fake"

    def __init__(self):
        self.initiate_result = PaymentInitiation(payment_url="https://fake-gateway.example/pay/1", gateway_reference="ref-1")
        self.verify_result = PaymentVerification(completed=True, raw_status="Completed", gateway_reference="ref-1")
        self.raise_on_initiate = False

    def initiate_payment(self, *, payment_id, amount, product_name):
        if self.raise_on_initiate:
            raise PaymentGatewayError("simulated gateway outage")
        return self.initiate_result

    def verify_payment(self, *, payment_id, amount, gateway_reference):
        return self.verify_result


@pytest.fixture
def fake_provider(monkeypatch):
    provider = _FakeProvider()
    monkeypatch.setitem(payment_service._PROVIDERS, "esewa", provider)
    monkeypatch.setitem(payment_service._PROVIDERS, "khalti", provider)
    return provider


@pytest.fixture
def two_businesses():
    email_a = _unique_email("pay-a-owner")
    email_b = _unique_email("pay-b-owner")

    resp_a = client.post(
        "/api/v1/auth/register",
        json={"business_name": "Pay A Dental", "timezone": "UTC", "email": email_a, "password": "correcthorse1"},
    )
    resp_b = client.post(
        "/api/v1/auth/register",
        json={"business_name": "Pay B Dental", "timezone": "UTC", "email": email_b, "password": "correcthorse1"},
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
def premium_npr_ready(two_businesses):
    """Business A: Premium, NPR currency, Mon-Sat 9-5, payment collection
    enabled via eSewa, one 20%-deposit service, one no-deposit service, one
    customer."""
    business_id_a = two_businesses["business_id_a"]
    token_a = two_businesses["token_a"]
    _set_plan(business_id_a, BusinessPlan.PREMIUM)

    resp = client.patch("/api/v1/business/me", json={"currency": "NPR"}, headers=_auth_header(token_a))
    assert resp.status_code == 200, resp.text

    days = [{"day_of_week": d, "open_time": "09:00:00", "close_time": "17:00:00"} for d in range(6)]
    days.append({"day_of_week": 6, "closed": True})
    resp = client.put("/api/v1/business/hours", json={"days": days}, headers=_auth_header(token_a))
    assert resp.status_code == 200, resp.text

    resp = client.patch(
        "/api/v1/business/payment-settings",
        json={"payment_collection_enabled": True, "payment_provider": "esewa"},
        headers=_auth_header(token_a),
    )
    assert resp.status_code == 200, resp.text

    deposit_service = client.post(
        "/api/v1/services",
        json={"name": "Root Canal", "price": "45000.00", "duration_minutes": 60, "deposit_enabled": True, "deposit_percentage": 20},
        headers=_auth_header(token_a),
    )
    assert deposit_service.status_code == 201, deposit_service.text

    no_deposit_service = client.post(
        "/api/v1/services",
        json={"name": "Checkup", "price": "1500.00", "duration_minutes": 30},
        headers=_auth_header(token_a),
    )
    assert no_deposit_service.status_code == 201, no_deposit_service.text

    customer = client.post("/api/v1/customers", json={"name": "Test Customer"}, headers=_auth_header(token_a))
    assert customer.status_code == 201, customer.text

    return {
        **two_businesses,
        "deposit_service_id": uuid.UUID(deposit_service.json()["id"]),
        "no_deposit_service_id": uuid.UUID(no_deposit_service.json()["id"]),
        "customer_id": uuid.UUID(customer.json()["id"]),
    }


def _next_weekday_datetime(hour: int) -> str:
    from datetime import date, datetime, timedelta

    today = date.today()
    days_ahead = 1
    target = today + timedelta(days=days_ahead)
    while target.weekday() == 6:  # Sunday closed in the fixture above
        target += timedelta(days=1)
    return datetime(target.year, target.month, target.day, hour, 0, tzinfo=None).isoformat() + "Z"


# --- Service deposit field validation ---------------------------------------


def test_service_create_rejects_deposit_percentage_out_of_range(two_businesses):
    resp = client.post(
        "/api/v1/services",
        json={"name": "X", "price": "100.00", "duration_minutes": 30, "deposit_enabled": True, "deposit_percentage": 0},
        headers=_auth_header(two_businesses["token_a"]),
    )
    assert resp.status_code == 422, resp.text

    resp = client.post(
        "/api/v1/services",
        json={"name": "X", "price": "100.00", "duration_minutes": 30, "deposit_enabled": True, "deposit_percentage": 101},
        headers=_auth_header(two_businesses["token_a"]),
    )
    assert resp.status_code == 422, resp.text


def test_service_create_rejects_deposit_enabled_without_percentage(two_businesses):
    resp = client.post(
        "/api/v1/services",
        json={"name": "X", "price": "100.00", "duration_minutes": 30, "deposit_enabled": True},
        headers=_auth_header(two_businesses["token_a"]),
    )
    assert resp.status_code == 422, resp.text


def test_service_create_allows_100_percent_deposit_as_ordinary_value(two_businesses):
    resp = client.post(
        "/api/v1/services",
        json={"name": "Full Upfront", "price": "100.00", "duration_minutes": 30, "deposit_enabled": True, "deposit_percentage": 100},
        headers=_auth_header(two_businesses["token_a"]),
    )
    assert resp.status_code == 201, resp.text
    assert resp.json()["deposit_percentage"] == 100


def test_service_update_toggle_persists_and_clears_percentage_when_disabled(two_businesses):
    token_a = two_businesses["token_a"]
    created = client.post(
        "/api/v1/services",
        json={"name": "Root Canal", "price": "45000.00", "duration_minutes": 60, "deposit_enabled": True, "deposit_percentage": 20},
        headers=_auth_header(token_a),
    ).json()

    updated = client.patch(
        f"/api/v1/services/{created['id']}",
        json={"deposit_enabled": False},
        headers=_auth_header(token_a),
    )
    assert updated.status_code == 200, updated.text
    assert updated.json()["deposit_enabled"] is False
    assert updated.json()["deposit_percentage"] is None

    reread = client.get("/api/v1/services", headers=_auth_header(token_a)).json()
    row = next(s for s in reread if s["id"] == created["id"])
    assert row["deposit_enabled"] is False
    assert row["deposit_percentage"] is None


# --- Business payment-settings gating ---------------------------------------


def test_payment_settings_402_for_free_plan(two_businesses):
    resp = client.patch(
        "/api/v1/business/payment-settings",
        json={"payment_collection_enabled": True, "payment_provider": "esewa"},
        headers=_auth_header(two_businesses["token_a"]),
    )
    assert resp.status_code == 402, resp.text
    assert resp.json()["error"]["type"] == "plan_required"


def test_payment_settings_rejects_non_npr_currency(two_businesses):
    _set_plan(two_businesses["business_id_a"], BusinessPlan.PREMIUM)
    resp = client.patch(
        "/api/v1/business/payment-settings",
        json={"payment_collection_enabled": True, "payment_provider": "esewa"},
        headers=_auth_header(two_businesses["token_a"]),
    )
    assert resp.status_code == 422, resp.text


def test_payment_settings_requires_provider_when_enabling(two_businesses):
    _set_plan(two_businesses["business_id_a"], BusinessPlan.PREMIUM)
    resp = client.patch(
        "/api/v1/business/me", json={"currency": "NPR"}, headers=_auth_header(two_businesses["token_a"])
    )
    assert resp.status_code == 200

    resp = client.patch(
        "/api/v1/business/payment-settings",
        json={"payment_collection_enabled": True},
        headers=_auth_header(two_businesses["token_a"]),
    )
    assert resp.status_code == 422, resp.text


# --- Real deposit-amount calculation + payment creation ---------------------


def test_booking_deposit_service_creates_payment_with_exact_percentage_amount(premium_npr_ready, fake_provider):
    token_a = premium_npr_ready["token_a"]
    resp = client.post(
        "/api/v1/appointments",
        json={
            "customer_id": str(premium_npr_ready["customer_id"]),
            "service_id": str(premium_npr_ready["deposit_service_id"]),
            "scheduled_at": _next_weekday_datetime(10),
        },
        headers=_auth_header(token_a),
    )
    assert resp.status_code == 201, resp.text
    appointment_id = resp.json()["id"]

    payments = client.get("/api/v1/payments", headers=_auth_header(token_a)).json()
    match = [p for p in payments if p["appointment_id"] == appointment_id]
    assert len(match) == 1
    assert match[0]["amount"] == "9000.00"  # 20% of 45000.00
    assert match[0]["currency"] == "NPR"
    assert match[0]["status"] == "pending"
    assert match[0]["payment_url"] == fake_provider.initiate_result.payment_url

    with SessionLocal() as db:
        appt = db.get(Appointment, uuid.UUID(appointment_id))
        assert appt.status.value == "confirmed"


def test_booking_no_deposit_service_creates_no_payment(premium_npr_ready, fake_provider):
    token_a = premium_npr_ready["token_a"]
    resp = client.post(
        "/api/v1/appointments",
        json={
            "customer_id": str(premium_npr_ready["customer_id"]),
            "service_id": str(premium_npr_ready["no_deposit_service_id"]),
            "scheduled_at": _next_weekday_datetime(11),
        },
        headers=_auth_header(token_a),
    )
    assert resp.status_code == 201, resp.text
    appointment_id = resp.json()["id"]

    payments = client.get("/api/v1/payments", headers=_auth_header(token_a)).json()
    assert [p for p in payments if p["appointment_id"] == appointment_id] == []


def test_booking_free_plan_creates_no_payment_even_with_deposit_service(two_businesses, fake_provider):
    """A business that was Premium when its service was configured but is
    Free at booking time must never generate a real payment request."""
    token_a = two_businesses["token_a"]
    client.patch("/api/v1/business/me", json={"currency": "NPR"}, headers=_auth_header(token_a))
    days = [{"day_of_week": d, "open_time": "09:00:00", "close_time": "17:00:00"} for d in range(6)]
    days.append({"day_of_week": 6, "closed": True})
    client.put("/api/v1/business/hours", json={"days": days}, headers=_auth_header(token_a))
    service = client.post(
        "/api/v1/services",
        json={"name": "Root Canal", "price": "45000.00", "duration_minutes": 60, "deposit_enabled": True, "deposit_percentage": 20},
        headers=_auth_header(token_a),
    ).json()
    customer = client.post("/api/v1/customers", json={"name": "T"}, headers=_auth_header(token_a)).json()

    resp = client.post(
        "/api/v1/appointments",
        json={"customer_id": customer["id"], "service_id": service["id"], "scheduled_at": _next_weekday_datetime(10)},
        headers=_auth_header(token_a),
    )
    assert resp.status_code == 201, resp.text

    with SessionLocal() as db:
        count = db.query(Payment).filter(Payment.appointment_id == uuid.UUID(resp.json()["id"])).count()
        assert count == 0


def test_gateway_initiation_failure_never_blocks_or_corrupts_the_booking(premium_npr_ready, fake_provider):
    fake_provider.raise_on_initiate = True
    token_a = premium_npr_ready["token_a"]
    resp = client.post(
        "/api/v1/appointments",
        json={
            "customer_id": str(premium_npr_ready["customer_id"]),
            "service_id": str(premium_npr_ready["deposit_service_id"]),
            "scheduled_at": _next_weekday_datetime(12),
        },
        headers=_auth_header(token_a),
    )
    assert resp.status_code == 201, resp.text
    appointment_id = resp.json()["id"]

    with SessionLocal() as db:
        appt = db.get(Appointment, uuid.UUID(appointment_id))
        assert appt.status.value == "confirmed"
        payment = db.query(Payment).filter(Payment.appointment_id == appt.id).first()
        assert payment is not None
        assert payment.status == PaymentStatus.FAILED


def test_verify_and_update_never_touches_appointment_either_way(premium_npr_ready, fake_provider):
    token_a = premium_npr_ready["token_a"]
    resp = client.post(
        "/api/v1/appointments",
        json={
            "customer_id": str(premium_npr_ready["customer_id"]),
            "service_id": str(premium_npr_ready["deposit_service_id"]),
            "scheduled_at": _next_weekday_datetime(13),
        },
        headers=_auth_header(token_a),
    )
    appointment_id = uuid.UUID(resp.json()["id"])

    fake_provider.verify_result = PaymentVerification(completed=False, raw_status="User canceled")
    with SessionLocal() as db:
        payment = db.query(Payment).filter(Payment.appointment_id == appointment_id).first()
        payment_service.verify_and_update(db, payment)
        db.refresh(payment)
        assert payment.status == PaymentStatus.FAILED
        appt = db.get(Appointment, appointment_id)
        assert appt.status.value == "confirmed"


# --- Cross-tenant isolation --------------------------------------------------


def test_payments_are_tenant_scoped(premium_npr_ready, fake_provider):
    token_a = premium_npr_ready["token_a"]
    token_b = premium_npr_ready["token_b"]
    client.post(
        "/api/v1/appointments",
        json={
            "customer_id": str(premium_npr_ready["customer_id"]),
            "service_id": str(premium_npr_ready["deposit_service_id"]),
            "scheduled_at": _next_weekday_datetime(14),
        },
        headers=_auth_header(token_a),
    )
    payments_b = client.get("/api/v1/payments", headers=_auth_header(token_b))
    assert payments_b.status_code == 200
    assert payments_b.json() == []


def test_staff_role_can_read_payments_but_not_change_settings(premium_npr_ready):
    """Ticket's explicit ask: staff can SEE payment status (read GET /payments)
    even though only owner/admin can change the payment-settings toggle."""
    from app.core.security import create_access_token
    from app.db.models.business import BusinessUser, BusinessUserRole

    business_id_a = premium_npr_ready["business_id_a"]
    with SessionLocal() as db:
        staff_user = BusinessUser(
            business_id=business_id_a,
            email=_unique_email("staff"),
            hashed_password="not-used",
            role=BusinessUserRole.STAFF,
        )
        db.add(staff_user)
        db.commit()
        db.refresh(staff_user)
        token = create_access_token(user_id=staff_user.id, business_id=business_id_a, role=staff_user.role.value)

    assert client.get("/api/v1/payments", headers=_auth_header(token)).status_code == 200
    assert (
        client.patch(
            "/api/v1/business/payment-settings",
            json={"payment_collection_enabled": False},
            headers=_auth_header(token),
        ).status_code
        == 403
    )
