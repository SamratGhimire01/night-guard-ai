"""Phase 5 — knowledge base ingestion endpoints.

Covers the manual-entry CRUD + status lifecycle (draft -> approved -> archived),
file upload (.txt and a real .pdf fixture), invalid-upload rejection, cross-tenant
isolation, and RBAC (owner/admin write including approve/archive, any role read).
"""

import uuid
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.core.security import create_access_token
from app.db.database import SessionLocal
from app.db.models.business import Business, BusinessUser, BusinessUserRole
from app.main import app

client = TestClient(app)

_FIXTURES = Path(__file__).parent.parent / "fixtures"


def _unique_email(label: str) -> str:
    return f"{label}-{uuid.uuid4().hex[:10]}@example.com"


def _auth_header(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


@pytest.fixture
def two_businesses():
    email_a = _unique_email("kb-a-owner")
    email_b = _unique_email("kb-b-owner")

    resp_a = client.post(
        "/api/v1/auth/register",
        json={"business_name": "KB A", "timezone": "UTC", "email": email_a, "password": "correcthorse1"},
    )
    resp_b = client.post(
        "/api/v1/auth/register",
        json={"business_name": "KB B", "timezone": "UTC", "email": email_b, "password": "correcthorse1"},
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
            email=_unique_email("kb-staff"),
            hashed_password="not-used-in-this-test",
            role=BusinessUserRole.STAFF,
        )
        db.add(staff_user)
        db.commit()
        db.refresh(staff_user)
        return create_access_token(user_id=staff_user.id, business_id=business_id_a, role=staff_user.role.value)


def test_manual_entry_full_lifecycle(two_businesses):
    token_a = two_businesses["token_a"]

    create = client.post(
        "/api/v1/knowledge",
        json={"title": "Cancellation Policy", "content": "Cancel 24h ahead, no fee."},
        headers=_auth_header(token_a),
    )
    assert create.status_code == 201, create.text
    doc = create.json()
    assert doc["status"] == "draft"
    assert doc["source"] == "manual"
    assert doc["version"] == 1
    doc_id = doc["id"]

    listing = client.get("/api/v1/knowledge", headers=_auth_header(token_a)).json()
    assert any(d["id"] == doc_id for d in listing)

    edit = client.patch(
        f"/api/v1/knowledge/{doc_id}",
        json={"content": "Cancel 48h ahead, no fee."},
        headers=_auth_header(token_a),
    )
    assert edit.status_code == 200, edit.text
    assert edit.json()["version"] == 2  # content edit bumps the version counter
    reread = client.get(f"/api/v1/knowledge/{doc_id}", headers=_auth_header(token_a)).json()
    assert reread["content"] == "Cancel 48h ahead, no fee."

    approve = client.patch(
        f"/api/v1/knowledge/{doc_id}", json={"status": "approved"}, headers=_auth_header(token_a)
    )
    assert approve.status_code == 200, approve.text
    approved = approve.json()
    assert approved["status"] == "approved"
    assert approved["approved_by"] is not None
    assert approved["approved_at"] is not None

    filtered = client.get("/api/v1/knowledge?status=approved", headers=_auth_header(token_a)).json()
    assert any(d["id"] == doc_id for d in filtered)
    filtered_draft = client.get("/api/v1/knowledge?status=draft", headers=_auth_header(token_a)).json()
    assert all(d["id"] != doc_id for d in filtered_draft)

    archive = client.patch(
        f"/api/v1/knowledge/{doc_id}", json={"status": "archived"}, headers=_auth_header(token_a)
    )
    assert archive.status_code == 200, archive.text
    assert archive.json()["status"] == "archived"
    assert archive.json()["approved_by"] is not None  # retained as history

    delete = client.delete(f"/api/v1/knowledge/{doc_id}", headers=_auth_header(token_a))
    assert delete.status_code == 204

    final = client.get(f"/api/v1/knowledge/{doc_id}", headers=_auth_header(token_a))
    assert final.status_code == 404


def test_upload_txt_extracts_content(two_businesses):
    token_a = two_businesses["token_a"]
    text = "Business hours: Mon-Fri 9-5.\n"

    resp = client.post(
        "/api/v1/knowledge/upload",
        files={"file": ("hours.txt", text.encode("utf-8"), "text/plain")},
        headers=_auth_header(token_a),
    )
    assert resp.status_code == 201, resp.text
    doc = resp.json()
    assert doc["source"] == "upload"
    assert doc["status"] == "draft"
    assert doc["content"] == text


def test_upload_pdf_extracts_content(two_businesses):
    token_a = two_businesses["token_a"]
    pdf_bytes = (_FIXTURES / "sample.pdf").read_bytes()

    resp = client.post(
        "/api/v1/knowledge/upload",
        files={"file": ("sample.pdf", pdf_bytes, "application/pdf")},
        headers=_auth_header(token_a),
    )
    assert resp.status_code == 201, resp.text
    doc = resp.json()
    assert doc["source"] == "upload"
    assert "Refund Policy" in doc["content"]
    assert "5 to 7 business days" in doc["content"]


def test_upload_rejects_invalid_type_and_oversized_file(two_businesses):
    token_a = two_businesses["token_a"]

    bad_type = client.post(
        "/api/v1/knowledge/upload",
        files={"file": ("malware.exe", b"not a real exe", "application/octet-stream")},
        headers=_auth_header(token_a),
    )
    assert bad_type.status_code == 415, bad_type.text

    oversized = client.post(
        "/api/v1/knowledge/upload",
        files={"file": ("huge.txt", b"A" * (11 * 1024 * 1024), "text/plain")},
        headers=_auth_header(token_a),
    )
    assert oversized.status_code == 413, oversized.text

    listing = client.get("/api/v1/knowledge", headers=_auth_header(token_a)).json()
    assert listing == []  # neither rejected upload created a document


def test_cross_tenant_knowledge_documents_are_isolated(two_businesses):
    token_a = two_businesses["token_a"]
    token_b = two_businesses["token_b"]

    doc = client.post(
        "/api/v1/knowledge",
        json={"title": "B's secret doc", "content": "confidential"},
        headers=_auth_header(token_b),
    ).json()

    assert client.get(f"/api/v1/knowledge/{doc['id']}", headers=_auth_header(token_a)).status_code == 404
    assert (
        client.patch(
            f"/api/v1/knowledge/{doc['id']}", json={"content": "hacked"}, headers=_auth_header(token_a)
        ).status_code
        == 404
    )
    assert (
        client.patch(
            f"/api/v1/knowledge/{doc['id']}", json={"status": "approved"}, headers=_auth_header(token_a)
        ).status_code
        == 404
    )
    assert (
        client.delete(f"/api/v1/knowledge/{doc['id']}", headers=_auth_header(token_a)).status_code == 404
    )

    still_there = client.get(f"/api/v1/knowledge/{doc['id']}", headers=_auth_header(token_b))
    assert still_there.status_code == 200
    assert still_there.json()["content"] == "confidential"
    assert still_there.json()["status"] == "draft"


def test_rbac_staff_can_read_but_not_approve_archive_or_delete(staff_token, two_businesses):
    token_a = two_businesses["token_a"]

    doc = client.post(
        "/api/v1/knowledge",
        json={"title": "Doc", "content": "content"},
        headers=_auth_header(token_a),
    ).json()

    assert client.get("/api/v1/knowledge", headers=_auth_header(staff_token)).status_code == 200
    assert client.get(f"/api/v1/knowledge/{doc['id']}", headers=_auth_header(staff_token)).status_code == 200

    assert (
        client.post(
            "/api/v1/knowledge", json={"title": "x", "content": "y"}, headers=_auth_header(staff_token)
        ).status_code
        == 403
    )
    assert (
        client.patch(
            f"/api/v1/knowledge/{doc['id']}", json={"status": "approved"}, headers=_auth_header(staff_token)
        ).status_code
        == 403
    )
    assert (
        client.patch(
            f"/api/v1/knowledge/{doc['id']}", json={"status": "archived"}, headers=_auth_header(staff_token)
        ).status_code
        == 403
    )
    assert (
        client.delete(f"/api/v1/knowledge/{doc['id']}", headers=_auth_header(staff_token)).status_code == 403
    )

    # owner (token_a) still can approve the same document, proving it's a role gate
    approve = client.patch(
        f"/api/v1/knowledge/{doc['id']}", json={"status": "approved"}, headers=_auth_header(token_a)
    )
    assert approve.status_code == 200, approve.text


@pytest.mark.parametrize(
    "body",
    [
        {"title": "", "content": "x"},
        {"title": "x", "content": ""},
    ],
)
def test_create_rejects_blank_fields_with_422(two_businesses, body):
    resp = client.post("/api/v1/knowledge", json=body, headers=_auth_header(two_businesses["token_a"]))
    assert resp.status_code == 422, resp.text
