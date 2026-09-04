"""Phase 15 — SMS as a premium feature.

Covers: the business-level sms_enabled toggle (reusing PATCH /business/me,
tenant-scoped + owner/admin RBAC exactly like every other business-config
field since Phase 4 — no new route needed), the customer-level sms_opt_in
consent gate, the channel-selection fallback rule in booking_service, the
safe stub fallback when Twilio credentials aren't configured, and the real
TwilioSMSProvider class's request-shape/error-classification behavior with
the actual network call mocked out (same "stub the network, not the business
logic" discipline as test_notifications.py's Gmail tests).
"""

import uuid
from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

import pytest
from fastapi.testclient import TestClient

from app.core.security import create_access_token
from app.db.database import SessionLocal
from app.db.models.business import Business, BusinessUser, BusinessUserRole
from app.db.models.notification import Notification, NotificationStatus
from app.main import app
from app.services.notifications import dispatch_service
from app.services.notifications.base import NotificationDeliveryError
from app.services.notifications.sms_provider import TwilioSMSProvider

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
    email_a = _unique_email("sms-a-owner")
    email_b = _unique_email("sms-b-owner")
    resp_a = client.post(
        "/api/v1/auth/register",
        json={"business_name": "SMS A Dental", "timezone": "UTC", "email": email_a, "password": "correcthorse1"},
    )
    resp_b = client.post(
        "/api/v1/auth/register",
        json={"business_name": "SMS B Dental", "timezone": "UTC", "email": email_b, "password": "correcthorse1"},
    )
    assert resp_a.status_code == 201, resp_a.text
    assert resp_b.status_code == 201, resp_b.text
    login_a = client.post("/api/v1/auth/login", json={"email": email_a, "password": "correcthorse1"})
    login_b = client.post("/api/v1/auth/login", json={"email": email_b, "password": "correcthorse1"})

    data = {
        "business_id_a": resp_a.json()["business_id"],
        "business_id_b": resp_b.json()["business_id"],
        "token_a": login_a.json()["access_token"],
        "token_b": login_b.json()["access_token"],
    }
    yield data

    with SessionLocal() as db:
        for business_id in (data["business_id_a"], data["business_id_b"]):
            business = db.get(Business, uuid.UUID(business_id))
            if business is not None:
                db.delete(business)
        db.commit()


@pytest.fixture
def staff_token(two_businesses):
    business_id_a = uuid.UUID(two_businesses["business_id_a"])
    with SessionLocal() as db:
        staff_user = BusinessUser(
            business_id=business_id_a,
            email=_unique_email("sms-staff"),
            hashed_password="not-used-in-this-test",
            role=BusinessUserRole.STAFF,
        )
        db.add(staff_user)
        db.commit()
        db.refresh(staff_user)
        return create_access_token(user_id=staff_user.id, business_id=business_id_a, role=staff_user.role.value)


# --- business SMS toggle: tenant-scoped, owner/admin only -----------------------


def test_owner_can_enable_and_disable_sms(two_businesses):
    token_a = two_businesses["token_a"]

    read = client.get("/api/v1/business/me", headers=_auth_header(token_a))
    assert read.json()["sms_enabled"] is False

    enable = client.patch("/api/v1/business/me", json={"sms_enabled": True}, headers=_auth_header(token_a))
    assert enable.status_code == 200, enable.text
    assert enable.json()["sms_enabled"] is True
    assert client.get("/api/v1/business/me", headers=_auth_header(token_a)).json()["sms_enabled"] is True

    disable = client.patch("/api/v1/business/me", json={"sms_enabled": False}, headers=_auth_header(token_a))
    assert disable.status_code == 200, disable.text
    assert client.get("/api/v1/business/me", headers=_auth_header(token_a)).json()["sms_enabled"] is False


def test_staff_cannot_toggle_sms(staff_token):
    resp = client.patch("/api/v1/business/me", json={"sms_enabled": True}, headers=_auth_header(staff_token))
    assert resp.status_code == 403, resp.text


def test_sms_toggle_is_tenant_scoped(two_businesses):
    """Business A's token can only ever affect Business A's own row — there is
    no business_id in the payload, so the same IDOR-proof mechanism proven in
    test_tenant_isolation.py applies here with zero new surface. Enabling SMS
    for A must leave B's own row (fetched with B's own token) untouched."""
    token_a, token_b = two_businesses["token_a"], two_businesses["token_b"]

    enable_a = client.patch("/api/v1/business/me", json={"sms_enabled": True}, headers=_auth_header(token_a))
    assert enable_a.status_code == 200, enable_a.text
    assert enable_a.json()["sms_enabled"] is True

    read_b = client.get("/api/v1/business/me", headers=_auth_header(token_b))
    assert read_b.json()["sms_enabled"] is False, "Business A's toggle must not leak into Business B's row"


def test_sms_enabled_cannot_be_cleared_to_null(two_businesses):
    resp = client.patch("/api/v1/business/me", json={"sms_enabled": None}, headers=_auth_header(two_businesses["token_a"]))
    assert resp.status_code == 422, resp.text


# --- channel selection + stub fallback (no real Twilio credentials) -------------


@pytest.fixture
def business_with_sms(two_businesses):
    token = two_businesses["token_a"]
    days = [{"day_of_week": d, "open_time": "09:00:00", "close_time": "17:00:00"} for d in range(6)]
    days.append({"day_of_week": 6, "closed": True})
    assert client.put("/api/v1/business/hours", json={"days": days}, headers=_auth_header(token)).status_code == 200
    assert client.patch("/api/v1/business/me", json={"sms_enabled": True}, headers=_auth_header(token)).status_code == 200

    service = client.post(
        "/api/v1/services", json={"name": "Cleaning", "price": "50.00", "duration_minutes": 30}, headers=_auth_header(token)
    )
    assert service.status_code == 201, service.text
    return {"token": token, "service_id": uuid.UUID(service.json()["id"])}


def _create_customer(token: str, **kwargs) -> uuid.UUID:
    payload = {"name": "Test Customer", **kwargs}
    resp = client.post("/api/v1/customers", json=payload, headers=_auth_header(token))
    assert resp.status_code == 201, resp.text
    return uuid.UUID(resp.json()["id"])


def _book(token: str, service_id: uuid.UUID, customer_id: uuid.UUID, when: datetime) -> dict:
    resp = client.post(
        "/api/v1/appointments",
        json={"customer_id": str(customer_id), "service_id": str(service_id), "scheduled_at": when.isoformat()},
        headers=_auth_header(token),
    )
    assert resp.status_code == 201, resp.text
    return resp.json()


def _notification_for(appointment_id: str) -> Notification:
    with SessionLocal() as db:
        return db.query(Notification).filter(Notification.appointment_id == uuid.UUID(appointment_id)).one()


def test_sms_enabled_and_opted_in_no_email_customer_falls_back_to_stub_and_never_crashes(business_with_sms):
    """The real acceptance scenario when no Twilio credentials are configured
    (this test env has none — TWILIO_ACCOUNT_SID/TOKEN/FROM_NUMBER are all
    empty by default): a customer with a phone, no email, who HAS opted in,
    at a business with SMS enabled -> the notification is queued as
    channel="sms", dispatched inline through the safe stub, and lands on
    SIMULATED — never SENT (that would be a lie) and never a crash that could
    break the booking response."""
    customer_id = _create_customer(business_with_sms["token"], phone="+15551234567", sms_opt_in=True)
    when = datetime.combine(_next_weekday(0), datetime.min.time()).replace(hour=10, tzinfo=ZoneInfo("UTC"))

    appointment = _book(business_with_sms["token"], business_with_sms["service_id"], customer_id, when)
    assert appointment  # 201 already asserted inside _book — proves booking never broke

    notification = _notification_for(appointment["id"])
    assert notification.channel == "sms"
    assert notification.status == NotificationStatus.SIMULATED


def test_sms_enabled_but_customer_not_opted_in_stays_on_email_channel(business_with_sms):
    """Consent gate: business.sms_enabled alone is not enough. A customer with
    a phone and no email who has NOT opted in must still be queued on the
    email channel (which then honestly fails for lack of a recipient) rather
    than silently getting texted without consent."""
    customer_id = _create_customer(business_with_sms["token"], phone="+15551234567")  # sms_opt_in defaults False
    when = datetime.combine(_next_weekday(1), datetime.min.time()).replace(hour=10, tzinfo=ZoneInfo("UTC"))

    appointment = _book(business_with_sms["token"], business_with_sms["service_id"], customer_id, when)

    notification = _notification_for(appointment["id"])
    assert notification.channel == "email"
    assert notification.status == NotificationStatus.FAILED  # honest: no email on file, never retried


def test_customer_with_email_stays_on_email_even_when_sms_enabled_and_opted_in(business_with_sms):
    """SMS is a fallback for customers with no email on file, not a preferred
    channel — documented design choice (see booking_service._notification_channel).
    A customer who has both an email and SMS consent still gets email."""
    customer_id = _create_customer(
        business_with_sms["token"], email="jordan@example.com", phone="+15551234567", sms_opt_in=True
    )
    when = datetime.combine(_next_weekday(2), datetime.min.time()).replace(hour=10, tzinfo=ZoneInfo("UTC"))

    appointment = _book(business_with_sms["token"], business_with_sms["service_id"], customer_id, when)

    notification = _notification_for(appointment["id"])
    assert notification.channel == "email"


def test_sms_disabled_never_selects_sms_channel_even_with_opt_in(two_businesses):
    """Business never enabled SMS (default False) — opt-in alone must not be
    enough to select the sms channel."""
    token = two_businesses["token_a"]
    days = [{"day_of_week": d, "open_time": "09:00:00", "close_time": "17:00:00"} for d in range(6)]
    days.append({"day_of_week": 6, "closed": True})
    assert client.put("/api/v1/business/hours", json={"days": days}, headers=_auth_header(token)).status_code == 200
    service = client.post(
        "/api/v1/services", json={"name": "Cleaning", "price": "50.00", "duration_minutes": 30}, headers=_auth_header(token)
    )
    assert service.status_code == 201, service.text
    customer_id = _create_customer(token, phone="+15551234567", sms_opt_in=True)
    when = datetime.combine(_next_weekday(3), datetime.min.time()).replace(hour=10, tzinfo=ZoneInfo("UTC"))

    appointment = _book(token, uuid.UUID(service.json()["id"]), customer_id, when)

    notification = _notification_for(appointment["id"])
    assert notification.channel == "email"


# --- real-provider path, exercised with credentials + network both faked --------


def test_when_twilio_credentials_are_configured_dispatch_uses_the_real_provider_and_retries(
    business_with_sms, monkeypatch
):
    """Proves the gating logic actually branches to a real (retry-capable,
    SENT-terminal) provider once credentials are present, instead of always
    taking the stub path — without making a real network call. Mirrors the
    email provider's transient-retry test in test_notifications.py."""

    class _FakeTwilio:
        SIMULATED = False

        def __init__(self):
            self.calls = 0

        def send(self, *, to, subject, body):
            self.calls += 1
            if self.calls < 2:
                raise NotificationDeliveryError("Twilio 5xx", transient=True)
            return "twilio accepted sid=SMfake status=queued"

    fake = _FakeTwilio()
    monkeypatch.setattr(dispatch_service, "TwilioSMSProvider", lambda: fake)
    monkeypatch.setattr(dispatch_service.settings, "twilio_account_sid", "ACfake")
    monkeypatch.setattr(dispatch_service.settings, "twilio_auth_token", "tokenfake")
    monkeypatch.setattr(dispatch_service.settings, "twilio_from_number", "+15550000000")
    monkeypatch.setattr(dispatch_service, "_RETRY_DELAY_SECONDS", 0)

    customer_id = _create_customer(business_with_sms["token"], phone="+15551234567", sms_opt_in=True)
    when = datetime.combine(_next_weekday(4), datetime.min.time()).replace(hour=10, tzinfo=ZoneInfo("UTC"))
    appointment = _book(business_with_sms["token"], business_with_sms["service_id"], customer_id, when)

    notification = _notification_for(appointment["id"])
    assert notification.channel == "sms"
    assert notification.status == NotificationStatus.SENT, "real provider's terminal success state is SENT, not SIMULATED"
    assert fake.calls == 2, "must have retried the transient failure once before succeeding"


def test_missing_any_one_credential_still_falls_back_to_stub(business_with_sms, monkeypatch):
    """All three TWILIO_* vars are required — partial config is treated the
    same as no config, never a crash, never a half-real send attempt."""
    monkeypatch.setattr(dispatch_service.settings, "twilio_account_sid", "ACfake")
    monkeypatch.setattr(dispatch_service.settings, "twilio_auth_token", "")
    monkeypatch.setattr(dispatch_service.settings, "twilio_from_number", "+15550000000")

    customer_id = _create_customer(business_with_sms["token"], phone="+15551234567", sms_opt_in=True)
    when = datetime.combine(_next_weekday(5), datetime.min.time()).replace(hour=10, tzinfo=ZoneInfo("UTC"))
    appointment = _book(business_with_sms["token"], business_with_sms["service_id"], customer_id, when)

    notification = _notification_for(appointment["id"])
    assert notification.status == NotificationStatus.SIMULATED


# --- TwilioSMSProvider itself: real request shape, network call mocked ----------


class _FakeHTTPResponse:
    def __init__(self, body: bytes):
        self._body = body

    def read(self):
        return self._body

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


def test_twilio_provider_rejects_missing_phone_without_any_network_call():
    provider = TwilioSMSProvider()
    with pytest.raises(NotificationDeliveryError) as exc_info:
        provider.send(to="", subject="", body="hi")
    assert exc_info.value.transient is False


def test_twilio_provider_builds_a_real_request_with_basic_auth_and_normalized_phone(monkeypatch):
    import json

    from app.core.config import settings

    monkeypatch.setattr(settings, "twilio_account_sid", "ACtest123")
    monkeypatch.setattr(settings, "twilio_auth_token", "secrettoken")
    monkeypatch.setattr(settings, "twilio_from_number", "+15559999999")

    captured = {}

    def _fake_urlopen(request, timeout):
        captured["url"] = request.full_url
        captured["headers"] = dict(request.header_items())
        captured["body"] = request.data.decode()
        return _FakeHTTPResponse(json.dumps({"sid": "SM123", "status": "queued"}).encode())

    monkeypatch.setattr("urllib.request.urlopen", _fake_urlopen)

    provider = TwilioSMSProvider()
    detail = provider.send(to="5551234567", subject="", body="Your appointment is confirmed.")

    assert "SM123" in detail and "queued" in detail
    assert "ACtest123" in captured["url"]
    assert "To=%2B15551234567" in captured["body"], "10-digit US number must be normalized to +1E.164"
    # Basic auth header present and correctly encoded; the raw token itself is
    # never present as plaintext anywhere in the request (it's base64'd).
    assert captured["headers"]["Authorization"].startswith("Basic ")
    assert "secrettoken" not in captured["headers"]["Authorization"]


def test_twilio_provider_classifies_auth_failure_as_permanent_and_5xx_as_transient(monkeypatch):
    import io
    import urllib.error

    from app.core.config import settings

    monkeypatch.setattr(settings, "twilio_account_sid", "ACtest123")
    monkeypatch.setattr(settings, "twilio_auth_token", "secrettoken")
    monkeypatch.setattr(settings, "twilio_from_number", "+15559999999")

    def _raise(code):
        def _fake_urlopen(request, timeout):
            raise urllib.error.HTTPError("url", code, "err", {}, io.BytesIO(b"{}"))

        return _fake_urlopen

    monkeypatch.setattr("urllib.request.urlopen", _raise(401))
    provider = TwilioSMSProvider()
    with pytest.raises(NotificationDeliveryError) as exc_info:
        provider.send(to="+15551234567", subject="", body="hi")
    assert exc_info.value.transient is False

    monkeypatch.setattr("urllib.request.urlopen", _raise(500))
    with pytest.raises(NotificationDeliveryError) as exc_info:
        provider.send(to="+15551234567", subject="", body="hi")
    assert exc_info.value.transient is True
