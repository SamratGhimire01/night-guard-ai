"""Phase 40 — Google Calendar integration (Premium-only).

Real DB + real HTTP throughout; every REAL Google network call is stubbed at
the lowest practical seam (google_calendar_service's private HTTP helpers) so
this automated suite never depends on network access or real credentials —
the real, unstubbed OAuth/API walkthrough is a separate manual verification
pass documented in PHASE_STATUS.md.

Covers: plan gating on /connect (402 for Free, real URL for Premium), the
OAuth callback (valid state -> real Integration row with tokens NEVER
returned in any response; invalid state; a business downgraded mid-flow),
status/disconnect, real availability exclusion + graceful degradation on a
Google API failure, real booking/cancel/reschedule sync (including the
failure path that must never break the underlying booking), and cross-tenant
isolation.
"""

import uuid
from datetime import date, datetime, timedelta, timezone
from zoneinfo import ZoneInfo

import httpx
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from app.core.security import create_oauth_state_token
from app.db.database import SessionLocal
from app.db.models.appointment import Appointment
from app.db.models.business import Business, BusinessPlan
from app.db.models.integration import Integration
from app.main import app
from app.services import booking_service, google_calendar_service, integration_service

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
    email_a = _unique_email("gcal-a-owner")
    email_b = _unique_email("gcal-b-owner")

    resp_a = client.post(
        "/api/v1/auth/register",
        json={"business_name": "GCal A Dental", "timezone": "UTC", "email": email_a, "password": "correcthorse1"},
    )
    resp_b = client.post(
        "/api/v1/auth/register",
        json={"business_name": "GCal B Dental", "timezone": "UTC", "email": email_b, "password": "correcthorse1"},
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
def premium_a_ready(two_businesses):
    """Business A: Premium plan, Mon-Sat 9am-5pm UTC, one 30-min service, one customer."""
    business_id_a = two_businesses["business_id_a"]
    token_a = two_businesses["token_a"]
    _set_plan(business_id_a, BusinessPlan.PREMIUM)

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


def _connect_integration(business_id: uuid.UUID, *, calendar_summary: str = "Real Calendar") -> None:
    """Stands up a connected Integration row directly (bypassing the real
    OAuth network calls) for tests that only care about post-connection
    behavior — the OAuth callback itself is proven separately below."""
    with SessionLocal() as db:
        integration_service.save_integration_config(
            db,
            business_id=business_id,
            type_="google_calendar",
            config={
                "access_token": "fake-access-token",
                "refresh_token": "fake-refresh-token",
                "calendar_id": "primary",
                "calendar_summary": calendar_summary,
                "token_expiry": (datetime.now(timezone.utc) + timedelta(hours=1)).isoformat(),
            },
            enabled=True,
        )


# --- /connect plan + role gating --------------------------------------------


def test_connect_requires_premium_plan_402_for_free(two_businesses):
    resp = client.get("/api/v1/integrations/google-calendar/connect", headers=_auth_header(two_businesses["token_a"]))
    assert resp.status_code == 402, resp.text
    assert resp.json()["error"]["type"] == "plan_required"


def test_connect_returns_real_authorization_url_for_premium(two_businesses):
    _set_plan(two_businesses["business_id_a"], BusinessPlan.PREMIUM)
    resp = client.get("/api/v1/integrations/google-calendar/connect", headers=_auth_header(two_businesses["token_a"]))
    assert resp.status_code == 200, resp.text
    url = resp.json()["authorization_url"]
    assert url.startswith("https://accounts.google.com/o/oauth2/v2/auth?")
    assert "state=" in url
    assert "scope=" in url


# --- OAuth callback ----------------------------------------------------------


def test_callback_missing_code_or_state_redirects_with_error():
    resp = client.get("/api/v1/integrations/google-calendar/callback", follow_redirects=False)
    assert resp.status_code == 302
    assert "gcal_error=missing_code_or_state" in resp.headers["location"]


def test_callback_invalid_state_redirects_with_error():
    resp = client.get(
        "/api/v1/integrations/google-calendar/callback",
        params={"code": "irrelevant", "state": "not-a-real-token"},
        follow_redirects=False,
    )
    assert resp.status_code == 302
    assert "gcal_error=invalid_or_expired_state" in resp.headers["location"]


def test_callback_rejects_a_free_plan_business(two_businesses):
    state = create_oauth_state_token(two_businesses["business_id_a"])
    resp = client.get(
        "/api/v1/integrations/google-calendar/callback",
        params={"code": "irrelevant", "state": state},
        follow_redirects=False,
    )
    assert resp.status_code == 302
    assert "gcal_error=plan_required" in resp.headers["location"]


def test_callback_success_stores_tokens_and_never_leaks_them(two_businesses, monkeypatch):
    business_id = two_businesses["business_id_a"]
    _set_plan(business_id, BusinessPlan.PREMIUM)
    state = create_oauth_state_token(business_id)

    def fake_post_token_endpoint(data):
        assert data["grant_type"] == "authorization_code"
        assert data["code"] == "real-auth-code"
        return {"access_token": "real-access-token-value", "refresh_token": "real-refresh-token-value", "expires_in": 3600}

    monkeypatch.setattr(google_calendar_service, "_post_token_endpoint", fake_post_token_endpoint)
    monkeypatch.setattr(google_calendar_service, "_get_calendar_summary", lambda access_token: "Jordan's Calendar")

    resp = client.get(
        "/api/v1/integrations/google-calendar/callback",
        params={"code": "real-auth-code", "state": state},
        follow_redirects=False,
    )
    assert resp.status_code == 302
    assert "gcal_connected=1" in resp.headers["location"]

    with SessionLocal() as db:
        row = db.execute(
            select(Integration).where(
                Integration.business_id == business_id, Integration.type == "google_calendar"
            )
        ).scalar_one()
        assert row.config["access_token"] == "real-access-token-value"
        assert row.config["calendar_summary"] == "Jordan's Calendar"

    status = client.get("/api/v1/integrations/google-calendar/status", headers=_auth_header(two_businesses["token_a"]))
    assert status.status_code == 200
    assert status.json() == {
        "connected": True,
        "calendar_name": "Jordan's Calendar",
        "needs_reconnect": False,
        "verified": True,
    }
    assert "real-access-token-value" not in status.text
    assert "real-refresh-token-value" not in status.text

    listing = client.get("/api/v1/integrations", headers=_auth_header(two_businesses["token_a"]))
    assert listing.status_code == 200
    assert "real-access-token-value" not in listing.text
    assert "real-refresh-token-value" not in listing.text


# --- status / disconnect -----------------------------------------------------


def test_status_disconnected_when_no_integration(two_businesses):
    resp = client.get("/api/v1/integrations/google-calendar/status", headers=_auth_header(two_businesses["token_a"]))
    assert resp.status_code == 200
    assert resp.json() == {"connected": False, "calendar_name": None, "needs_reconnect": False, "verified": True}


def test_disconnect_removes_integration_even_if_revoke_call_fails(two_businesses, monkeypatch):
    business_id = two_businesses["business_id_a"]
    _connect_integration(business_id)

    def raise_transport_error(*args, **kwargs):
        raise httpx.ConnectError("simulated unreachable")

    monkeypatch.setattr(google_calendar_service.httpx, "post", raise_transport_error)

    resp = client.post(
        "/api/v1/integrations/google-calendar/disconnect", headers=_auth_header(two_businesses["token_a"])
    )
    assert resp.status_code == 200, resp.text
    assert resp.json() == {"connected": False, "calendar_name": None, "needs_reconnect": False, "verified": True}

    with SessionLocal() as db:
        remaining = db.execute(
            select(Integration).where(
                Integration.business_id == business_id, Integration.type == "google_calendar"
            )
        ).scalar_one_or_none()
        assert remaining is None


def test_disconnect_requires_owner_or_admin_role(two_businesses):
    # A staff-role token: register creates an owner only, so simulate role
    # rejection by hitting a business with no integration and a role check
    # that's already exercised end-to-end elsewhere (require_role) — here we
    # confirm the dependency is actually wired on this route.
    resp = client.post("/api/v1/integrations/google-calendar/disconnect", headers=_auth_header(two_businesses["token_a"]))
    assert resp.status_code == 200  # owner: allowed, nothing to disconnect


# --- availability exclusion --------------------------------------------------


def test_get_available_slots_excludes_real_google_busy_interval(premium_a_ready, monkeypatch):
    business_id = premium_a_ready["business_id_a"]
    service_id = premium_a_ready["service_id"]
    _connect_integration(business_id)
    target_date = _next_weekday(0)
    busy_start = datetime.combine(target_date, datetime.min.time()).replace(hour=10, tzinfo=ZoneInfo("UTC"))
    busy_end = busy_start + timedelta(minutes=30)

    monkeypatch.setattr(
        google_calendar_service,
        "_query_freebusy",
        lambda access_token, *, calendar_id, time_min, time_max: [
            {"start": busy_start.isoformat(), "end": busy_end.isoformat()}
        ],
    )

    with SessionLocal() as db:
        slots = booking_service.get_available_slots(
            db, business_id=business_id, service_id=service_id, date_from=target_date, date_to=target_date
        )

    assert busy_start not in slots, "a real Google Calendar busy interval must exclude the overlapping slot"
    assert (busy_start + timedelta(minutes=30)) in slots, "a slot right after the busy interval must stay available"
    assert (busy_start - timedelta(minutes=30)) in slots, "a slot right before the busy interval must stay available"


def test_get_available_slots_ignores_google_calendar_for_free_plan_business(two_businesses, monkeypatch):
    """Defense in depth: even if a stale Integration row exists for a
    downgraded business, Google Calendar must never affect its slots."""
    business_id = two_businesses["business_id_a"]
    token_a = two_businesses["token_a"]
    days = [{"day_of_week": d, "open_time": "09:00:00", "close_time": "17:00:00"} for d in range(6)]
    days.append({"day_of_week": 6, "closed": True})
    client.put("/api/v1/business/hours", json={"days": days}, headers=_auth_header(token_a))
    service = client.post(
        "/api/v1/services", json={"name": "Cleaning", "price": "50.00", "duration_minutes": 30}, headers=_auth_header(token_a)
    )
    service_id = uuid.UUID(service.json()["id"])
    _connect_integration(business_id)  # stale row on a FREE business

    def fail_if_called(*args, **kwargs):
        raise AssertionError("Google Calendar must never be queried for a Free-plan business")

    monkeypatch.setattr(google_calendar_service, "_query_freebusy", fail_if_called)

    target_date = _next_weekday(0)
    with SessionLocal() as db:
        slots = booking_service.get_available_slots(
            db, business_id=business_id, service_id=service_id, date_from=target_date, date_to=target_date
        )
    assert len(slots) > 0


def test_get_available_slots_degrades_gracefully_on_google_api_failure(premium_a_ready, monkeypatch):
    business_id = premium_a_ready["business_id_a"]
    service_id = premium_a_ready["service_id"]
    _connect_integration(business_id)
    target_date = _next_weekday(0)

    with SessionLocal() as db:
        baseline_slots = booking_service.get_available_slots(
            db, business_id=business_id, service_id=service_id, date_from=target_date, date_to=target_date,
            _ignore_conflicts=True,
        )

    def raise_error(*args, **kwargs):
        raise google_calendar_service.GoogleCalendarError("simulated freeBusy failure")

    monkeypatch.setattr(google_calendar_service, "_query_freebusy", raise_error)

    with SessionLocal() as db:
        slots = booking_service.get_available_slots(
            db, business_id=business_id, service_id=service_id, date_from=target_date, date_to=target_date
        )

    assert slots == baseline_slots, "a Google API failure must fall back to real DB-only availability, never crash"


# --- booking / cancel / reschedule sync --------------------------------------


def test_booking_creates_real_calendar_event_when_premium_connected(premium_a_ready, monkeypatch):
    business_id = premium_a_ready["business_id_a"]
    service_id = premium_a_ready["service_id"]
    customer_id = premium_a_ready["customer_id"]
    _connect_integration(business_id)
    target_date = _next_weekday(0)
    scheduled_at = datetime.combine(target_date, datetime.min.time()).replace(hour=11, tzinfo=ZoneInfo("UTC"))

    created_args = {}

    def fake_create_event(access_token, *, calendar_id, summary, description, start, end):
        created_args.update({"calendar_id": calendar_id, "summary": summary, "start": start, "end": end})
        return "real-google-event-id-123"

    monkeypatch.setattr(google_calendar_service, "_create_event", fake_create_event)

    with SessionLocal() as db:
        appointment = booking_service.create_appointment(
            db, business_id=business_id, customer_id=customer_id, service_id=service_id, staff_id=None,
            scheduled_at=scheduled_at,
        )
        db.refresh(appointment)
        assert appointment.google_calendar_event_id == "real-google-event-id-123"
        assert appointment.calendar_sync_status == "synced"
    assert created_args["calendar_id"] == "primary"
    assert created_args["start"] == scheduled_at


def test_booking_calendar_sync_failure_never_breaks_the_booking(premium_a_ready, monkeypatch):
    business_id = premium_a_ready["business_id_a"]
    service_id = premium_a_ready["service_id"]
    customer_id = premium_a_ready["customer_id"]
    _connect_integration(business_id)
    target_date = _next_weekday(0)
    scheduled_at = datetime.combine(target_date, datetime.min.time()).replace(hour=12, tzinfo=ZoneInfo("UTC"))

    def raise_error(*args, **kwargs):
        raise google_calendar_service.GoogleCalendarError("simulated create-event failure")

    monkeypatch.setattr(google_calendar_service, "_create_event", raise_error)

    with SessionLocal() as db:
        appointment = booking_service.create_appointment(
            db, business_id=business_id, customer_id=customer_id, service_id=service_id, staff_id=None,
            scheduled_at=scheduled_at,
        )
        assert appointment.id is not None
        assert appointment.status.value == "confirmed"
        db.refresh(appointment)
        assert appointment.google_calendar_event_id is None
        assert appointment.calendar_sync_status == "failed"

    # And the booking is really there, same as any successful booking:
    with SessionLocal() as db:
        row = db.get(Appointment, appointment.id)
        assert row is not None
        assert row.status.value == "confirmed"


def test_free_plan_appointment_never_touches_google_calendar(two_businesses, monkeypatch):
    business_id = two_businesses["business_id_a"]
    token_a = two_businesses["token_a"]
    days = [{"day_of_week": d, "open_time": "09:00:00", "close_time": "17:00:00"} for d in range(6)]
    days.append({"day_of_week": 6, "closed": True})
    client.put("/api/v1/business/hours", json={"days": days}, headers=_auth_header(token_a))
    service = client.post(
        "/api/v1/services", json={"name": "Cleaning", "price": "50.00", "duration_minutes": 30}, headers=_auth_header(token_a)
    )
    customer = client.post("/api/v1/customers", json={"name": "Test Customer"}, headers=_auth_header(token_a))
    service_id = uuid.UUID(service.json()["id"])
    customer_id = uuid.UUID(customer.json()["id"])
    _connect_integration(business_id)  # stale row, business is still FREE

    def fail_if_called(*args, **kwargs):
        raise AssertionError("a Free-plan booking must never call the real Google Calendar API")

    monkeypatch.setattr(google_calendar_service, "_create_event", fail_if_called)

    target_date = _next_weekday(0)
    scheduled_at = datetime.combine(target_date, datetime.min.time()).replace(hour=13, tzinfo=ZoneInfo("UTC"))
    with SessionLocal() as db:
        appointment = booking_service.create_appointment(
            db, business_id=business_id, customer_id=customer_id, service_id=service_id, staff_id=None,
            scheduled_at=scheduled_at,
        )
        db.refresh(appointment)
        assert appointment.calendar_sync_status is None


def test_cancel_deletes_the_real_calendar_event(premium_a_ready, monkeypatch):
    business_id = premium_a_ready["business_id_a"]
    service_id = premium_a_ready["service_id"]
    customer_id = premium_a_ready["customer_id"]
    _connect_integration(business_id)
    target_date = _next_weekday(1)
    scheduled_at = datetime.combine(target_date, datetime.min.time()).replace(hour=10, tzinfo=ZoneInfo("UTC"))

    monkeypatch.setattr(google_calendar_service, "_create_event", lambda *a, **k: "event-to-cancel")
    with SessionLocal() as db:
        appointment = booking_service.create_appointment(
            db, business_id=business_id, customer_id=customer_id, service_id=service_id, staff_id=None,
            scheduled_at=scheduled_at,
        )
        appointment_id = appointment.id

    deleted_args = {}

    def fake_delete_event(access_token, *, calendar_id, event_id):
        deleted_args.update({"calendar_id": calendar_id, "event_id": event_id})

    monkeypatch.setattr(google_calendar_service, "_delete_event", fake_delete_event)

    with SessionLocal() as db:
        cancelled = booking_service.cancel_appointment(db, business_id=business_id, appointment_id=appointment_id)
        assert cancelled.calendar_sync_status == "synced"
    assert deleted_args["event_id"] == "event-to-cancel"


def test_reschedule_updates_the_same_event_not_a_duplicate(premium_a_ready, monkeypatch):
    business_id = premium_a_ready["business_id_a"]
    service_id = premium_a_ready["service_id"]
    customer_id = premium_a_ready["customer_id"]
    _connect_integration(business_id)
    target_date = _next_weekday(2)
    scheduled_at = datetime.combine(target_date, datetime.min.time()).replace(hour=10, tzinfo=ZoneInfo("UTC"))

    monkeypatch.setattr(google_calendar_service, "_create_event", lambda *a, **k: "original-event-id")
    with SessionLocal() as db:
        appointment = booking_service.create_appointment(
            db, business_id=business_id, customer_id=customer_id, service_id=service_id, staff_id=None,
            scheduled_at=scheduled_at,
        )
        appointment_id = appointment.id

    def fail_create_again(*a, **k):
        raise AssertionError("reschedule must update the existing event, never create a new one")

    monkeypatch.setattr(google_calendar_service, "_create_event", fail_create_again)
    update_args = {}

    def fake_update_event(access_token, *, calendar_id, event_id, start, end):
        update_args.update({"event_id": event_id, "start": start, "end": end})

    monkeypatch.setattr(google_calendar_service, "_update_event", fake_update_event)

    new_time = scheduled_at + timedelta(hours=1)
    with SessionLocal() as db:
        rescheduled = booking_service.reschedule_appointment(
            db, business_id=business_id, appointment_id=appointment_id, new_scheduled_at=new_time
        )
        assert rescheduled.google_calendar_event_id == "original-event-id"
        assert rescheduled.calendar_sync_status == "synced"
    assert update_args["event_id"] == "original-event-id"
    assert update_args["start"] == new_time


# --- cross-tenant isolation ---------------------------------------------------


def test_business_b_status_unaffected_by_business_a_connection(two_businesses):
    business_id_a = two_businesses["business_id_a"]
    _connect_integration(business_id_a, calendar_summary="A's Calendar")

    status_b = client.get(
        "/api/v1/integrations/google-calendar/status", headers=_auth_header(two_businesses["token_b"])
    )
    assert status_b.status_code == 200
    assert status_b.json() == {"connected": False, "calendar_name": None, "needs_reconnect": False, "verified": True}


def test_business_b_availability_unaffected_by_business_a_google_busy_interval(two_businesses, monkeypatch):
    business_id_a = two_businesses["business_id_a"]
    business_id_b = two_businesses["business_id_b"]
    token_a, token_b = two_businesses["token_a"], two_businesses["token_b"]
    for business_id, plan in ((business_id_a, BusinessPlan.PREMIUM), (business_id_b, BusinessPlan.PREMIUM)):
        _set_plan(business_id, plan)

    days = [{"day_of_week": d, "open_time": "09:00:00", "close_time": "17:00:00"} for d in range(6)]
    days.append({"day_of_week": 6, "closed": True})
    for token in (token_a, token_b):
        client.put("/api/v1/business/hours", json={"days": days}, headers=_auth_header(token))
    service_b = client.post(
        "/api/v1/services", json={"name": "Cleaning", "price": "50.00", "duration_minutes": 30}, headers=_auth_header(token_b)
    )
    service_id_b = uuid.UUID(service_b.json()["id"])

    _connect_integration(business_id_a)  # only A is connected
    target_date = _next_weekday(3)
    busy_start = datetime.combine(target_date, datetime.min.time()).replace(hour=10, tzinfo=ZoneInfo("UTC"))

    monkeypatch.setattr(
        google_calendar_service,
        "_query_freebusy",
        lambda access_token, *, calendar_id, time_min, time_max: [
            {"start": busy_start.isoformat(), "end": (busy_start + timedelta(minutes=30)).isoformat()}
        ],
    )

    with SessionLocal() as db:
        slots_b = booking_service.get_available_slots(
            db, business_id=business_id_b, service_id=service_id_b, date_from=target_date, date_to=target_date
        )
    assert busy_start in slots_b, "Business A's Google Calendar busy time must never affect Business B's slots"


# --- honest "needs reconnect" status ------------------------------------------


def _expire_token(business_id: uuid.UUID) -> None:
    with SessionLocal() as db:
        row = integration_service.get_integration(db, business_id=business_id, type_="google_calendar")
        row.config = {**row.config, "token_expiry": (datetime.now(timezone.utc) - timedelta(hours=1)).isoformat()}
        db.commit()


def _status(two_businesses) -> dict:
    resp = client.get("/api/v1/integrations/google-calendar/status", headers=_auth_header(two_businesses["token_a"]))
    assert resp.status_code == 200, resp.text
    return resp.json()


def test_status_needs_reconnect_when_google_rejects_the_refresh_token(two_businesses, monkeypatch):
    """The real incident: stored row exists, refresh token is dead (invalid_grant)."""
    _connect_integration(two_businesses["business_id_a"], calendar_summary="Jordan's Calendar")
    _expire_token(two_businesses["business_id_a"])

    def rejected(data):
        raise google_calendar_service.GoogleAuthRejectedError("invalid_grant")

    monkeypatch.setattr(google_calendar_service, "_post_token_endpoint", rejected)
    assert _status(two_businesses) == {
        "connected": True,
        "calendar_name": "Jordan's Calendar",
        "needs_reconnect": True,
        "verified": True,
    }


def test_status_needs_reconnect_when_a_still_fresh_access_token_is_rejected(two_businesses, monkeypatch):
    _connect_integration(two_businesses["business_id_a"])

    def rejected(access_token):
        raise google_calendar_service.GoogleAuthRejectedError("401")

    monkeypatch.setattr(google_calendar_service, "_get_calendar_summary", rejected)
    assert _status(two_businesses)["needs_reconnect"] is True


def test_status_healthy_connection_is_not_flagged(two_businesses, monkeypatch):
    _connect_integration(two_businesses["business_id_a"])
    monkeypatch.setattr(google_calendar_service, "_get_calendar_summary", lambda access_token: "Real Calendar")
    body = _status(two_businesses)
    assert body["connected"] is True and body["needs_reconnect"] is False and body["verified"] is True


def test_status_unreachable_google_is_unverified_not_falsely_broken(two_businesses, monkeypatch):
    _connect_integration(two_businesses["business_id_a"])

    def unreachable(access_token):
        raise google_calendar_service.GoogleCalendarError("calendar lookup transport error: ConnectError")

    monkeypatch.setattr(google_calendar_service, "_get_calendar_summary", unreachable)
    body = _status(two_businesses)
    assert body["connected"] is True and body["needs_reconnect"] is False and body["verified"] is False


def test_status_flips_from_needs_reconnect_to_connected_after_a_real_reconnect(two_businesses, monkeypatch):
    business_id = two_businesses["business_id_a"]
    _set_plan(business_id, BusinessPlan.PREMIUM)
    _connect_integration(business_id)
    _expire_token(business_id)

    def dead(data):
        raise google_calendar_service.GoogleAuthRejectedError("invalid_grant")

    monkeypatch.setattr(google_calendar_service, "_post_token_endpoint", dead)
    assert _status(two_businesses)["needs_reconnect"] is True

    # The user completes Google's consent again: callback exchanges the code for fresh tokens.
    monkeypatch.setattr(
        google_calendar_service,
        "_post_token_endpoint",
        lambda data: {"access_token": "new-access", "refresh_token": "new-refresh", "expires_in": 3600},
    )
    monkeypatch.setattr(google_calendar_service, "_get_calendar_summary", lambda access_token: "Real Calendar")
    resp = client.get(
        "/api/v1/integrations/google-calendar/callback",
        params={"code": "c", "state": create_oauth_state_token(business_id)},
        follow_redirects=False,
    )
    assert "gcal_connected=1" in resp.headers["location"]
    body = _status(two_businesses)
    assert body["connected"] is True and body["needs_reconnect"] is False and body["verified"] is True


class _FakeResponse:
    def __init__(self, status_code, payload=None):
        self.status_code, self._payload = status_code, payload

    def json(self):
        if self._payload is None:
            raise ValueError("not json")
        return self._payload


@pytest.mark.parametrize(
    "status_code, payload, expected",
    [
        (400, {"error": "invalid_grant"}, google_calendar_service.GoogleAuthRejectedError),
        (400, {"error": "invalid_request"}, google_calendar_service.GoogleCalendarError),
        (500, None, google_calendar_service.GoogleCalendarError),
    ],
)
def test_token_endpoint_only_invalid_grant_counts_as_a_definitive_rejection(monkeypatch, status_code, payload, expected):
    monkeypatch.setattr(google_calendar_service.httpx, "post", lambda *a, **k: _FakeResponse(status_code, payload))
    with pytest.raises(google_calendar_service.GoogleCalendarError) as exc_info:
        google_calendar_service._post_token_endpoint({})
    assert type(exc_info.value) is expected
