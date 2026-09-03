"""The most important test in this project.

Proves that Business A's token can never read, modify, or even detect the
existence of Business B's data through the API — tenant isolation is enforced
by app.api.dependencies.get_current_user + business_id-scoped queries, not by
trusting anything the client sends.
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


@pytest.fixture
def two_businesses():
    """Registers Business A / User A and Business B / User B, yields their
    tokens and ids, then deletes both businesses (ON DELETE CASCADE cleans up
    everything hanging off them: users, customers, etc.)."""
    email_a = _unique_email("tenant-a-owner")
    email_b = _unique_email("tenant-b-owner")

    resp_a = client.post(
        "/api/v1/auth/register",
        json={
            "business_name": "Tenant A Dental",
            "timezone": "UTC",
            "email": email_a,
            "password": "correcthorse1",
        },
    )
    assert resp_a.status_code == 201, resp_a.text

    resp_b = client.post(
        "/api/v1/auth/register",
        json={
            "business_name": "Tenant B Dental",
            "timezone": "UTC",
            "email": email_b,
            "password": "correcthorse1",
        },
    )
    assert resp_b.status_code == 201, resp_b.text

    login_a = client.post("/api/v1/auth/login", json={"email": email_a, "password": "correcthorse1"})
    login_b = client.post("/api/v1/auth/login", json={"email": email_b, "password": "correcthorse1"})
    assert login_a.status_code == 200, login_a.text
    assert login_b.status_code == 200, login_b.text

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


def _auth_header(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


def test_business_a_cannot_read_business_bs_customer(two_businesses):
    token_a = two_businesses["token_a"]
    token_b = two_businesses["token_b"]

    # Business B creates a customer.
    create_resp = client.post(
        "/api/v1/customers",
        json={"name": "Bob (belongs to Business B)"},
        headers=_auth_header(token_b),
    )
    assert create_resp.status_code == 201, create_resp.text
    business_b_customer_id = create_resp.json()["id"]

    # Sanity check: Business B can read its own customer.
    own_read = client.get(f"/api/v1/customers/{business_b_customer_id}", headers=_auth_header(token_b))
    assert own_read.status_code == 200, own_read.text

    # THE ACTUAL TEST: Business A tries to read Business B's customer by ID
    # (enumeration/IDOR attack). Our API never accepts business_id from the
    # client at all, so there is no field to "correct" — the only lever an
    # attacker has is guessing another tenant's resource id, which is exactly
    # what this simulates.
    cross_tenant_resp = client.get(
        f"/api/v1/customers/{business_b_customer_id}", headers=_auth_header(token_a)
    )
    assert cross_tenant_resp.status_code == 404, (
        f"SECURITY FAILURE: Business A read Business B's customer! "
        f"status={cross_tenant_resp.status_code} body={cross_tenant_resp.text}"
    )

    # And it must not leak existence via a different-shaped success response.
    body = cross_tenant_resp.json()
    assert body["error"]["type"] == "not_found"


def test_business_a_cannot_delete_business_bs_customer(two_businesses):
    token_a = two_businesses["token_a"]
    token_b = two_businesses["token_b"]

    create_resp = client.post(
        "/api/v1/customers", json={"name": "Carol"}, headers=_auth_header(token_b)
    )
    assert create_resp.status_code == 201, create_resp.text
    business_b_customer_id = create_resp.json()["id"]

    delete_resp = client.delete(
        f"/api/v1/customers/{business_b_customer_id}", headers=_auth_header(token_a)
    )
    assert delete_resp.status_code == 404, delete_resp.text

    # Confirm it's still there (Business A's attempt did not delete it).
    still_there = client.get(
        f"/api/v1/customers/{business_b_customer_id}", headers=_auth_header(token_b)
    )
    assert still_there.status_code == 200


def test_unauthenticated_request_is_rejected():
    resp = client.get("/api/v1/customers/00000000-0000-0000-0000-000000000000")
    assert resp.status_code == 403  # HTTPBearer: no credentials supplied


def test_role_based_access_control_blocks_staff_from_delete(two_businesses):
    """Proves require_role(["owner", "admin"]) actually gates the route.

    No staff-creation endpoint exists yet, so a staff BusinessUser is inserted
    directly for this test, and a token is minted for it the same way login
    does internally.
    """
    business_id_a = uuid.UUID(two_businesses["business_id_a"])
    token_a_owner = two_businesses["token_a"]

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
        staff_token = create_access_token(
            user_id=staff_user.id, business_id=business_id_a, role=staff_user.role.value
        )

    create_resp = client.post(
        "/api/v1/customers", json={"name": "Dave"}, headers=_auth_header(token_a_owner)
    )
    assert create_resp.status_code == 201, create_resp.text
    customer_id = create_resp.json()["id"]

    staff_delete_resp = client.delete(
        f"/api/v1/customers/{customer_id}", headers=_auth_header(staff_token)
    )
    assert staff_delete_resp.status_code == 403, staff_delete_resp.text

    owner_delete_resp = client.delete(
        f"/api/v1/customers/{customer_id}", headers=_auth_header(token_a_owner)
    )
    assert owner_delete_resp.status_code == 204, owner_delete_resp.text
