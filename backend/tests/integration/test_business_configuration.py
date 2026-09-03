"""Phase 4 — business configuration endpoints.

Covers full CRUD persistence for services/staff, cross-tenant isolation
(same IDOR pattern as test_tenant_isolation.py), RBAC (owner/admin write,
any authenticated role read), and 422 validation for bad payloads.
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
    """Mints a staff-role token for Business A (no staff-user invite endpoint exists yet)."""
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


def test_business_profile_crud(two_businesses):
    token_a = two_businesses["token_a"]

    read = client.get("/api/v1/business/me", headers=_auth_header(token_a))
    assert read.status_code == 200, read.text
    assert read.json()["name"] == "A Dental"

    update = client.patch(
        "/api/v1/business/me",
        json={"description": "desc", "tone": "friendly", "languages": ["en"]},
        headers=_auth_header(token_a),
    )
    assert update.status_code == 200, update.text

    reread = client.get("/api/v1/business/me", headers=_auth_header(token_a))
    assert reread.json()["description"] == "desc"
    assert reread.json()["tone"] == "friendly"
    assert reread.json()["languages"] == ["en"]


def test_service_full_crud_cycle(two_businesses):
    token_a = two_businesses["token_a"]

    create = client.post(
        "/api/v1/services",
        json={"name": "Cleaning", "price": "75.00", "duration_minutes": 30},
        headers=_auth_header(token_a),
    )
    assert create.status_code == 201, create.text
    service_id = create.json()["id"]

    listing = client.get("/api/v1/services", headers=_auth_header(token_a))
    assert listing.status_code == 200
    assert any(s["id"] == service_id for s in listing.json())

    update = client.patch(
        f"/api/v1/services/{service_id}", json={"price": "80.00"}, headers=_auth_header(token_a)
    )
    assert update.status_code == 200, update.text
    assert update.json()["price"] == "80.00"

    reread = client.get("/api/v1/services", headers=_auth_header(token_a))
    assert next(s for s in reread.json() if s["id"] == service_id)["price"] == "80.00"

    delete = client.delete(f"/api/v1/services/{service_id}", headers=_auth_header(token_a))
    assert delete.status_code == 204

    final = client.get("/api/v1/services", headers=_auth_header(token_a))
    assert all(s["id"] != service_id for s in final.json())


def test_staff_full_crud_cycle(two_businesses):
    token_a = two_businesses["token_a"]

    create = client.post(
        "/api/v1/staff", json={"name": "Dr. A", "role": "dentist"}, headers=_auth_header(token_a)
    )
    assert create.status_code == 201, create.text
    staff_id = create.json()["id"]

    update = client.patch(
        f"/api/v1/staff/{staff_id}", json={"role": "lead dentist"}, headers=_auth_header(token_a)
    )
    assert update.status_code == 200, update.text
    assert update.json()["role"] == "lead dentist"

    delete = client.delete(f"/api/v1/staff/{staff_id}", headers=_auth_header(token_a))
    assert delete.status_code == 204

    final = client.get("/api/v1/staff", headers=_auth_header(token_a))
    assert all(s["id"] != staff_id for s in final.json())


def test_business_hours_put_replaces_full_week(two_businesses):
    token_a = two_businesses["token_a"]

    put = client.put(
        "/api/v1/business/hours",
        json={"days": [{"day_of_week": 0, "open_time": "09:00:00", "close_time": "17:00:00"}]},
        headers=_auth_header(token_a),
    )
    assert put.status_code == 200, put.text

    reput = client.put(
        "/api/v1/business/hours",
        json={"days": [{"day_of_week": 1, "closed": True}]},
        headers=_auth_header(token_a),
    )
    assert reput.status_code == 200, reput.text

    hours = client.get("/api/v1/business/hours", headers=_auth_header(token_a)).json()
    assert len(hours["weekly"]) == 1
    assert hours["weekly"][0]["day_of_week"] == 1
    assert hours["weekly"][0]["closed"] is True


def test_cross_tenant_service_and_staff_are_isolated(two_businesses):
    token_a = two_businesses["token_a"]
    token_b = two_businesses["token_b"]

    service = client.post(
        "/api/v1/services",
        json={"name": "B's service", "price": "1.00", "duration_minutes": 1},
        headers=_auth_header(token_b),
    ).json()
    staff = client.post(
        "/api/v1/staff", json={"name": "B's staff", "role": "x"}, headers=_auth_header(token_b)
    ).json()

    patch_resp = client.patch(
        f"/api/v1/services/{service['id']}", json={"price": "9999.00"}, headers=_auth_header(token_a)
    )
    assert patch_resp.status_code == 404, patch_resp.text

    delete_resp = client.delete(f"/api/v1/services/{service['id']}", headers=_auth_header(token_a))
    assert delete_resp.status_code == 404, delete_resp.text

    staff_delete_resp = client.delete(f"/api/v1/staff/{staff['id']}", headers=_auth_header(token_a))
    assert staff_delete_resp.status_code == 404, staff_delete_resp.text

    # confirm nothing was mutated by the failed cross-tenant attempts
    still_there = client.get("/api/v1/services", headers=_auth_header(token_b)).json()
    assert next(s for s in still_there if s["id"] == service["id"])["price"] == "1.00"


def test_rbac_staff_role_can_read_but_not_write(staff_token, two_businesses):
    token_a = two_businesses["token_a"]

    assert client.get("/api/v1/business/me", headers=_auth_header(staff_token)).status_code == 200
    assert client.get("/api/v1/services", headers=_auth_header(staff_token)).status_code == 200
    assert client.get("/api/v1/staff", headers=_auth_header(staff_token)).status_code == 200
    assert client.get("/api/v1/business/hours", headers=_auth_header(staff_token)).status_code == 200

    assert (
        client.patch("/api/v1/business/me", json={"name": "x"}, headers=_auth_header(staff_token)).status_code
        == 403
    )
    assert (
        client.post(
            "/api/v1/services",
            json={"name": "x", "price": "1.00", "duration_minutes": 1},
            headers=_auth_header(staff_token),
        ).status_code
        == 403
    )
    assert (
        client.post(
            "/api/v1/staff", json={"name": "x", "role": "x"}, headers=_auth_header(staff_token)
        ).status_code
        == 403
    )
    assert (
        client.put(
            "/api/v1/business/hours", json={"days": []}, headers=_auth_header(staff_token)
        ).status_code
        == 403
    )

    # owner (token_a) still can, proving it's a role gate, not a blanket lock
    assert (
        client.post(
            "/api/v1/services",
            json={"name": "x", "price": "1.00", "duration_minutes": 1},
            headers=_auth_header(token_a),
        ).status_code
        == 201
    )


def test_patch_omitted_fields_are_left_unchanged(two_businesses):
    """The Phase 4 no-op-null bug: a field never sent in the PATCH body must not
    be wiped, even though the schema types it as Optional to allow omission."""
    token_a = two_businesses["token_a"]

    staff = client.post(
        "/api/v1/staff", json={"name": "Dr. Assigned", "role": "dentist"}, headers=_auth_header(token_a)
    ).json()
    service = client.post(
        "/api/v1/services",
        json={
            "name": "Root Canal",
            "description": "Full endodontic treatment",
            "price": "500.00",
            "duration_minutes": 60,
            "staff_id": staff["id"],
        },
        headers=_auth_header(token_a),
    ).json()

    patch = client.patch(
        f"/api/v1/services/{service['id']}", json={"price": 100}, headers=_auth_header(token_a)
    )
    assert patch.status_code == 200, patch.text
    after = patch.json()
    assert after["price"] == "100.00"
    assert after["name"] == "Root Canal"
    assert after["description"] == "Full endodontic treatment"
    assert after["duration_minutes"] == 60
    assert after["staff_id"] == staff["id"]

    staff_patch = client.patch(
        f"/api/v1/staff/{staff['id']}", json={"role": "lead dentist"}, headers=_auth_header(token_a)
    )
    assert staff_patch.status_code == 200, staff_patch.text
    assert staff_patch.json()["name"] == "Dr. Assigned"
    assert staff_patch.json()["role"] == "lead dentist"


def test_patch_explicit_null_clears_nullable_field_but_rejects_on_required_field(two_businesses):
    token_a = two_businesses["token_a"]

    service = client.post(
        "/api/v1/services",
        json={"name": "Cleaning", "description": "desc", "price": "75.00", "duration_minutes": 30},
        headers=_auth_header(token_a),
    ).json()

    # explicit null on a nullable field clears it
    cleared = client.patch(
        f"/api/v1/services/{service['id']}", json={"description": None}, headers=_auth_header(token_a)
    )
    assert cleared.status_code == 200, cleared.text
    assert cleared.json()["description"] is None
    assert cleared.json()["name"] == "Cleaning"  # untouched

    # explicit null on a NOT NULL field is rejected with 422, never reaches the DB
    rejected = client.patch(
        f"/api/v1/services/{service['id']}", json={"price": None}, headers=_auth_header(token_a)
    )
    assert rejected.status_code == 422, rejected.text

    # confirm the rejected request did not mutate anything
    still_there = client.get("/api/v1/services", headers=_auth_header(token_a)).json()
    assert next(s for s in still_there if s["id"] == service["id"])["price"] == "75.00"

    # same rule on business profile: nullable clears, required rejects
    business_patch = client.patch(
        "/api/v1/business/me", json={"description": None}, headers=_auth_header(token_a)
    )
    assert business_patch.status_code == 200, business_patch.text
    business_reject = client.patch(
        "/api/v1/business/me", json={"name": None}, headers=_auth_header(token_a)
    )
    assert business_reject.status_code == 422, business_reject.text


@pytest.mark.parametrize(
    "path,method,body",
    [
        ("/api/v1/services", "post", {"name": "bad", "price": "-1.00", "duration_minutes": 30}),
        ("/api/v1/services", "post", {"name": "bad", "price": "1.00", "duration_minutes": -5}),
        ("/api/v1/staff", "post", {"name": "   ", "role": "dentist"}),
        (
            "/api/v1/business/hours",
            "put",
            {"days": [{"day_of_week": 0, "open_time": "17:00:00", "close_time": "09:00:00"}]},
        ),
    ],
)
def test_invalid_payloads_return_422_not_500(two_businesses, path, method, body):
    token_a = two_businesses["token_a"]
    resp = getattr(client, method)(path, json=body, headers=_auth_header(token_a))
    assert resp.status_code == 422, resp.text
