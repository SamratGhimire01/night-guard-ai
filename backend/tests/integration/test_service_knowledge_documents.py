"""Phase 36 — service <-> knowledge-document attachment (dashboard-only convenience,
does not affect Phase 6's RAG search scope). Covers attach/detach/list persistence,
cross-tenant isolation, RBAC, conflict-on-duplicate-attach, and 404s for a
nonexistent service or document.
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
    email_a = _unique_email("skd-a-owner")
    email_b = _unique_email("skd-b-owner")

    resp_a = client.post(
        "/api/v1/auth/register",
        json={"business_name": "SKD A", "timezone": "UTC", "email": email_a, "password": "correcthorse1"},
    )
    resp_b = client.post(
        "/api/v1/auth/register",
        json={"business_name": "SKD B", "timezone": "UTC", "email": email_b, "password": "correcthorse1"},
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
            email=_unique_email("skd-staff"),
            hashed_password="not-used-in-this-test",
            role=BusinessUserRole.STAFF,
        )
        db.add(staff_user)
        db.commit()
        db.refresh(staff_user)
        return create_access_token(user_id=staff_user.id, business_id=business_id_a, role=staff_user.role.value)


def _create_service(token: str, name: str = "Root Canal Treatment") -> str:
    resp = client.post(
        "/api/v1/services",
        json={"name": name, "price": "500.00", "duration_minutes": 60},
        headers=_auth_header(token),
    )
    assert resp.status_code == 201, resp.text
    return resp.json()["id"]


def _create_document(token: str, title: str = "Root Canal — What to Expect") -> str:
    resp = client.post(
        "/api/v1/knowledge",
        json={"title": title, "content": "Root canal aftercare instructions..."},
        headers=_auth_header(token),
    )
    assert resp.status_code == 201, resp.text
    return resp.json()["id"]


def test_attach_list_detach_full_cycle(two_businesses):
    token_a = two_businesses["token_a"]
    service_id = _create_service(token_a)
    doc_id = _create_document(token_a)

    # not attached yet
    resp = client.get(f"/api/v1/services/{service_id}/knowledge-documents", headers=_auth_header(token_a))
    assert resp.status_code == 200
    assert resp.json() == []

    resp = client.post(
        f"/api/v1/services/{service_id}/knowledge-documents",
        json={"knowledge_document_id": doc_id},
        headers=_auth_header(token_a),
    )
    assert resp.status_code == 201, resp.text
    assert resp.json()["id"] == doc_id

    # re-fetch confirms persistence
    resp = client.get(f"/api/v1/services/{service_id}/knowledge-documents", headers=_auth_header(token_a))
    assert resp.status_code == 200
    ids = [d["id"] for d in resp.json()]
    assert ids == [doc_id]

    # duplicate attach -> 409, not a silent no-op or a crash
    resp = client.post(
        f"/api/v1/services/{service_id}/knowledge-documents",
        json={"knowledge_document_id": doc_id},
        headers=_auth_header(token_a),
    )
    assert resp.status_code == 409, resp.text

    resp = client.delete(
        f"/api/v1/services/{service_id}/knowledge-documents/{doc_id}", headers=_auth_header(token_a)
    )
    assert resp.status_code == 204

    # re-fetch confirms the detach persisted
    resp = client.get(f"/api/v1/services/{service_id}/knowledge-documents", headers=_auth_header(token_a))
    assert resp.json() == []

    # detaching again -> 404, not a silent 204
    resp = client.delete(
        f"/api/v1/services/{service_id}/knowledge-documents/{doc_id}", headers=_auth_header(token_a)
    )
    assert resp.status_code == 404


def test_attach_404s_for_nonexistent_service_or_document(two_businesses):
    token_a = two_businesses["token_a"]
    service_id = _create_service(token_a)
    doc_id = _create_document(token_a)

    resp = client.post(
        f"/api/v1/services/{uuid.uuid4()}/knowledge-documents",
        json={"knowledge_document_id": doc_id},
        headers=_auth_header(token_a),
    )
    assert resp.status_code == 404

    resp = client.post(
        f"/api/v1/services/{service_id}/knowledge-documents",
        json={"knowledge_document_id": str(uuid.uuid4())},
        headers=_auth_header(token_a),
    )
    assert resp.status_code == 404


def test_cross_tenant_cannot_attach_or_see_another_businesss_service_or_document(two_businesses):
    token_a = two_businesses["token_a"]
    token_b = two_businesses["token_b"]
    service_id_a = _create_service(token_a)
    doc_id_a = _create_document(token_a)

    # Business B cannot list/attach against Business A's service id
    resp = client.get(f"/api/v1/services/{service_id_a}/knowledge-documents", headers=_auth_header(token_b))
    assert resp.status_code == 404

    resp = client.post(
        f"/api/v1/services/{service_id_a}/knowledge-documents",
        json={"knowledge_document_id": doc_id_a},
        headers=_auth_header(token_b),
    )
    assert resp.status_code == 404

    # Business B has its own service; cannot attach Business A's document to it
    service_id_b = _create_service(token_b, name="Cleaning")
    resp = client.post(
        f"/api/v1/services/{service_id_b}/knowledge-documents",
        json={"knowledge_document_id": doc_id_a},
        headers=_auth_header(token_b),
    )
    assert resp.status_code == 404

    # confirm A's attachment surface is untouched
    resp = client.get(f"/api/v1/services/{service_id_a}/knowledge-documents", headers=_auth_header(token_a))
    assert resp.status_code == 200
    assert resp.json() == []


def test_rbac_staff_can_list_but_not_attach_or_detach(two_businesses, staff_token):
    token_a = two_businesses["token_a"]
    service_id = _create_service(token_a)
    doc_id = _create_document(token_a)

    # staff can read
    resp = client.get(f"/api/v1/services/{service_id}/knowledge-documents", headers=_auth_header(staff_token))
    assert resp.status_code == 200

    # staff cannot attach
    resp = client.post(
        f"/api/v1/services/{service_id}/knowledge-documents",
        json={"knowledge_document_id": doc_id},
        headers=_auth_header(staff_token),
    )
    assert resp.status_code == 403

    # owner attaches for real
    resp = client.post(
        f"/api/v1/services/{service_id}/knowledge-documents",
        json={"knowledge_document_id": doc_id},
        headers=_auth_header(token_a),
    )
    assert resp.status_code == 201

    # staff still cannot detach
    resp = client.delete(
        f"/api/v1/services/{service_id}/knowledge-documents/{doc_id}", headers=_auth_header(staff_token)
    )
    assert resp.status_code == 403

    # confirm still attached (staff's blocked attempt did nothing)
    resp = client.get(f"/api/v1/services/{service_id}/knowledge-documents", headers=_auth_header(token_a))
    assert [d["id"] for d in resp.json()] == [doc_id]
