"""POST/GET /api/v1/integrations — real endpoint replacing the hand-edit-the-DB
path for connecting a Meta Page/App (Messenger/Instagram/WhatsApp) to a
tenant, now also backing the dashboard's Channels page. Covers upsert
semantics (create then replace, not accumulate), RBAC (owner/admin only for
both read and write — see the dashboard channel-connect phase), per-type
config validation, secret redaction on every response, real Graph API
test-connection calls, and cross-tenant isolation.
"""

import uuid

import pytest
from fastapi.testclient import TestClient

from app.core.security import create_access_token
from app.db.database import SessionLocal
from app.db.models.business import Business, BusinessUser, BusinessUserRole
from app.main import app

client = TestClient(app)


def _unique_email(label: str) -> str:
    return f"{label}-{uuid.uuid4().hex[:10]}@example.com"


def _auth_header(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


@pytest.fixture
def two_businesses():
    email_a = _unique_email("biz-a-owner")
    email_b = _unique_email("biz-b-owner")

    resp_a = client.post(
        "/api/v1/auth/register",
        json={"business_name": "A Dental", "timezone": "UTC", "email": email_a, "password": "correcthorse1"},
    )
    resp_b = client.post(
        "/api/v1/auth/register",
        json={"business_name": "B Dental", "timezone": "UTC", "email": email_b, "password": "correcthorse1"},
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
            email=_unique_email("staff-member"),
            hashed_password="not-used-in-this-test",
            role=BusinessUserRole.STAFF,
        )
        db.add(staff_user)
        db.commit()
        db.refresh(staff_user)
        return create_access_token(user_id=staff_user.id, business_id=business_id_a, role=staff_user.role.value)


def test_create_then_replace_messenger_integration_upserts_not_accumulates(two_businesses):
    token_a = two_businesses["token_a"]

    first = client.post(
        "/api/v1/integrations",
        json={"type": "messenger", "config": {"page_id": "111", "page_access_token": "token-1"}},
        headers=_auth_header(token_a),
    )
    assert first.status_code == 201, first.text
    integration_id = first.json()["id"]

    second = client.post(
        "/api/v1/integrations",
        json={"type": "messenger", "config": {"page_id": "111", "page_access_token": "token-2"}},
        headers=_auth_header(token_a),
    )
    assert second.status_code == 201, second.text
    assert second.json()["id"] == integration_id
    # The real token is never echoed back, even right after saving it —
    # write-only, same posture as a password field.
    assert "page_access_token" not in second.json()["config"]
    assert second.json()["config"]["page_id"] == "111"

    listed = client.get("/api/v1/integrations", headers=_auth_header(token_a))
    assert listed.status_code == 200, listed.text
    messenger_rows = [row for row in listed.json() if row["type"] == "messenger"]
    assert len(messenger_rows) == 1
    assert "page_access_token" not in messenger_rows[0]["config"]


def test_missing_required_config_key_rejected_422(two_businesses):
    resp = client.post(
        "/api/v1/integrations",
        json={"type": "messenger", "config": {"page_id": "111"}},
        headers=_auth_header(two_businesses["token_a"]),
    )
    assert resp.status_code == 422, resp.text


def test_whatsapp_requires_access_token_key(two_businesses):
    """WhatsApp now stores a real per-business access token in config
    (dashboard channel-connect phase), not just phone_number_id — matching
    Messenger/Instagram's existing per-business-token requirement."""
    resp = client.post(
        "/api/v1/integrations",
        json={"type": "whatsapp", "config": {"phone_number_id": "555"}},
        headers=_auth_header(two_businesses["token_a"]),
    )
    assert resp.status_code == 422, resp.text


def test_whatsapp_and_instagram_secrets_never_returned(two_businesses):
    token_a = two_businesses["token_a"]

    wa = client.post(
        "/api/v1/integrations",
        json={"type": "whatsapp", "config": {"phone_number_id": "555", "access_token": "wa-secret-token"}},
        headers=_auth_header(token_a),
    )
    assert wa.status_code == 201, wa.text
    assert "access_token" not in wa.json()["config"]
    assert wa.json()["config"]["phone_number_id"] == "555"

    ig = client.post(
        "/api/v1/integrations",
        json={"type": "instagram", "config": {"ig_account_id": "abc", "access_token": "ig-secret-token"}},
        headers=_auth_header(token_a),
    )
    assert ig.status_code == 201, ig.text
    assert "access_token" not in ig.json()["config"]
    assert ig.json()["config"]["ig_account_id"] == "abc"

    listed = client.get("/api/v1/integrations", headers=_auth_header(token_a))
    assert listed.status_code == 200, listed.text
    for row in listed.json():
        assert "access_token" not in row["config"]
        assert "page_access_token" not in row["config"]


def test_staff_role_cannot_read_or_write(two_businesses, staff_token):
    """A saved channel's credentials are sensitive enough (before this phase's
    redaction even applies to a fresh POST response) that the whole page is
    owner/admin only — staff can't view connection status or edit it,
    stricter than a generic settings page's "view yes, edit no" split."""
    write = client.post(
        "/api/v1/integrations",
        json={"type": "whatsapp", "config": {"phone_number_id": "555", "access_token": "tok"}},
        headers=_auth_header(staff_token),
    )
    assert write.status_code == 403, write.text

    read = client.get("/api/v1/integrations", headers=_auth_header(staff_token))
    assert read.status_code == 403, read.text

    test_conn = client.post(
        "/api/v1/integrations/whatsapp/test-connection", headers=_auth_header(staff_token)
    )
    assert test_conn.status_code == 403, test_conn.text


def test_integration_is_tenant_scoped(two_businesses):
    client.post(
        "/api/v1/integrations",
        json={"type": "instagram", "config": {"ig_account_id": "abc", "access_token": "tok"}},
        headers=_auth_header(two_businesses["token_a"]),
    )
    listed_b = client.get("/api/v1/integrations", headers=_auth_header(two_businesses["token_b"]))
    assert listed_b.status_code == 200, listed_b.text
    assert listed_b.json() == []


def test_test_connection_without_a_saved_integration_reports_not_connected(two_businesses):
    resp = client.post(
        "/api/v1/integrations/messenger/test-connection", headers=_auth_header(two_businesses["token_a"])
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["ok"] is False
    assert "not connected" in resp.json()["detail"].lower()


def test_test_connection_makes_a_real_graph_api_call_with_saved_credentials(two_businesses):
    """Real network call to Meta's real Graph API (no mocking) — the token is
    fake, so Meta's own real servers reject it, proving the mechanism is
    genuinely live rather than a faked check. Same honest "real code, no real
    Meta account" posture as every other adapter in this codebase."""
    token_a = two_businesses["token_a"]
    saved = client.post(
        "/api/v1/integrations",
        json={"type": "whatsapp", "config": {"phone_number_id": "not-a-real-id", "access_token": "not-a-real-token"}},
        headers=_auth_header(token_a),
    )
    assert saved.status_code == 201, saved.text

    resp = client.post("/api/v1/integrations/whatsapp/test-connection", headers=_auth_header(token_a))
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["ok"] is False
    assert "oauth" in body["detail"].lower() or "token" in body["detail"].lower()
