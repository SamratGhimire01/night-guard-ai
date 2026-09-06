"""POST/GET /api/v1/integrations — real endpoint replacing the hand-edit-the-DB
path for connecting a Meta Page/App (Messenger/Instagram/WhatsApp) to a
tenant. Covers upsert semantics (create then replace, not accumulate),
RBAC (owner/admin write, any authenticated role read), per-type config
validation, and cross-tenant isolation.
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
    assert second.json()["config"]["page_access_token"] == "token-2"

    listed = client.get("/api/v1/integrations", headers=_auth_header(token_a))
    assert listed.status_code == 200, listed.text
    messenger_rows = [row for row in listed.json() if row["type"] == "messenger"]
    assert len(messenger_rows) == 1


def test_missing_required_config_key_rejected_422(two_businesses):
    resp = client.post(
        "/api/v1/integrations",
        json={"type": "messenger", "config": {"page_id": "111"}},
        headers=_auth_header(two_businesses["token_a"]),
    )
    assert resp.status_code == 422, resp.text


def test_staff_role_cannot_write_but_can_read(two_businesses, staff_token):
    write = client.post(
        "/api/v1/integrations",
        json={"type": "whatsapp", "config": {"phone_number_id": "555"}},
        headers=_auth_header(staff_token),
    )
    assert write.status_code == 403, write.text

    read = client.get("/api/v1/integrations", headers=_auth_header(staff_token))
    assert read.status_code == 200, read.text


def test_integration_is_tenant_scoped(two_businesses):
    client.post(
        "/api/v1/integrations",
        json={"type": "instagram", "config": {"ig_account_id": "abc", "access_token": "tok"}},
        headers=_auth_header(two_businesses["token_a"]),
    )
    listed_b = client.get("/api/v1/integrations", headers=_auth_header(two_businesses["token_b"]))
    assert listed_b.status_code == 200, listed_b.text
    assert listed_b.json() == []
