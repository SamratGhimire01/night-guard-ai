"""Phase 34 — subscription plan entitlement system.

Covers: default plan on a freshly-registered business, the require_plan gate
blocking/allowing at the HTTP layer, the same gate (ensure_plan) working
inside the conversation orchestrator's own tool logic (never via FastAPI
Depends), real AuditLog rows on every plan change, superadmin-only admin
endpoints (cross-tenant + non-superadmin rejections), and the self-serve
GET /business/plan endpoint any authenticated role can read.
"""

import uuid

import pytest
from fastapi.testclient import TestClient

from app.core.security import create_access_token, hash_password
from app.db.database import SessionLocal
from app.db.models.audit_log import AuditLog
from app.db.models.business import Business, BusinessPlan, BusinessUser, BusinessUserRole
from app.main import app

client = TestClient(app)


def _unique_email(label: str) -> str:
    return f"{label}-{uuid.uuid4().hex[:10]}@example.com"


def _auth_header(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


@pytest.fixture
def two_businesses():
    email_a = _unique_email("plan-a-owner")
    email_b = _unique_email("plan-b-owner")

    resp_a = client.post(
        "/api/v1/auth/register",
        json={"business_name": "Plan A Dental", "timezone": "UTC", "email": email_a, "password": "correcthorse1"},
    )
    resp_b = client.post(
        "/api/v1/auth/register",
        json={"business_name": "Plan B Dental", "timezone": "UTC", "email": email_b, "password": "correcthorse1"},
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
def superadmin_token():
    """No API exists to grant is_superadmin (deliberate — see BusinessUser.
    is_superadmin's docstring), so this test mints one the only way it can
    happen: a direct ORM insert, same technique test_business_configuration.
    py's `staff_token` fixture already uses for a staff-role user."""
    with SessionLocal() as db:
        biz = Business(name="Test Ops (internal)", timezone="UTC")
        db.add(biz)
        db.flush()
        admin_user = BusinessUser(
            business_id=biz.id,
            email=_unique_email("platform-admin"),
            hashed_password=hash_password("not-used-in-this-test"),
            role=BusinessUserRole.OWNER,
            is_superadmin=True,
        )
        db.add(admin_user)
        db.commit()
        db.refresh(admin_user)
        token = create_access_token(
            user_id=admin_user.id, business_id=admin_user.business_id, role=admin_user.role.value
        )
        business_id = biz.id

    yield token

    with SessionLocal() as db:
        business = db.get(Business, business_id)
        if business is not None:
            db.delete(business)
        db.commit()


def test_new_business_defaults_to_free_plan(two_businesses):
    resp = client.get("/api/v1/business/plan", headers=_auth_header(two_businesses["token_a"]))
    assert resp.status_code == 200, resp.text
    assert resp.json()["plan"] == "free"
    assert len(resp.json()["features"]) > 0


def test_business_plan_readable_by_any_authenticated_role(two_businesses):
    """Requirement #5 — not owner/admin-gated, unlike the admin endpoints."""
    business_id_a = uuid.UUID(two_businesses["business_id_a"])
    with SessionLocal() as db:
        staff = BusinessUser(
            business_id=business_id_a,
            email=_unique_email("staff-member"),
            hashed_password="not-used-in-this-test",
            role=BusinessUserRole.STAFF,
        )
        db.add(staff)
        db.commit()
        db.refresh(staff)
        staff_token = create_access_token(user_id=staff.id, business_id=business_id_a, role=staff.role.value)

    resp = client.get("/api/v1/business/plan", headers=_auth_header(staff_token))
    assert resp.status_code == 200, resp.text
    assert resp.json()["plan"] == "free"


def test_plan_cannot_be_set_via_own_business_patch(two_businesses):
    """Defense in depth: BusinessUpdate has no `plan` field at all, so a
    business attempting to self-upgrade via its own PATCH /business/me is
    silently ignored (Pydantic drops the unknown field) rather than erroring
    — the plan stays whatever it really is."""
    resp = client.patch(
        "/api/v1/business/me", json={"plan": "premium"}, headers=_auth_header(two_businesses["token_a"])
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["plan"] == "free"


def test_premium_gated_route_blocks_free_then_allows_after_admin_upgrade(two_businesses, superadmin_token):
    business_id_a = two_businesses["business_id_a"]
    token_a = two_businesses["token_a"]

    blocked = client.get("/api/v1/premium-test/ping", headers=_auth_header(token_a))
    assert blocked.status_code == 402, blocked.text
    assert blocked.json()["error"]["type"] == "plan_required"

    upgrade = client.patch(
        f"/api/v1/admin/businesses/{business_id_a}/plan",
        json={"plan": "premium"},
        headers=_auth_header(superadmin_token),
    )
    assert upgrade.status_code == 200, upgrade.text
    assert upgrade.json()["plan"] == "premium"

    allowed = client.get("/api/v1/premium-test/ping", headers=_auth_header(token_a))
    assert allowed.status_code == 200, allowed.text
    assert allowed.json() == {"message": "Premium feature executed."}


def test_downgrade_reengages_gate_immediately_same_token(two_businesses, superadmin_token):
    """No caching anywhere in the check — the same already-issued token must
    see the new, lower plan on its very next request."""
    business_id_a = two_businesses["business_id_a"]
    token_a = two_businesses["token_a"]

    client.patch(
        f"/api/v1/admin/businesses/{business_id_a}/plan",
        json={"plan": "premium"},
        headers=_auth_header(superadmin_token),
    )
    assert client.get("/api/v1/premium-test/ping", headers=_auth_header(token_a)).status_code == 200

    downgrade = client.patch(
        f"/api/v1/admin/businesses/{business_id_a}/plan",
        json={"plan": "free"},
        headers=_auth_header(superadmin_token),
    )
    assert downgrade.status_code == 200, downgrade.text
    assert downgrade.json()["plan"] == "free"

    reblocked = client.get("/api/v1/premium-test/ping", headers=_auth_header(token_a))
    assert reblocked.status_code == 402, reblocked.text


def test_plan_change_writes_real_audit_log_row(two_businesses, superadmin_token):
    business_id_a = two_businesses["business_id_a"]

    resp = client.patch(
        f"/api/v1/admin/businesses/{business_id_a}/plan",
        json={"plan": "premium"},
        headers=_auth_header(superadmin_token),
    )
    assert resp.status_code == 200, resp.text

    with SessionLocal() as db:
        rows = (
            db.query(AuditLog)
            .filter(AuditLog.business_id == uuid.UUID(business_id_a), AuditLog.action == "plan_changed")
            .all()
        )
    assert len(rows) == 1
    row = rows[0]
    assert row.result == "from=free to=premium"
    assert row.resource_type == "business"
    assert row.resource_id == business_id_a
    assert "@" in row.actor  # the real superadmin's email, never "system"


def test_non_superadmin_cannot_view_or_change_any_business_plan(two_businesses):
    """Business B's own OWNER role — real, valid credentials, just not a
    platform superadmin — must be rejected the same as a stranger."""
    business_id_a = two_businesses["business_id_a"]
    token_b = two_businesses["token_b"]

    view = client.get(f"/api/v1/admin/businesses/{business_id_a}/plan", headers=_auth_header(token_b))
    assert view.status_code == 403, view.text

    change = client.patch(
        f"/api/v1/admin/businesses/{business_id_a}/plan",
        json={"plan": "premium"},
        headers=_auth_header(token_b),
    )
    assert change.status_code == 403, change.text

    # confirm nothing actually changed
    with SessionLocal() as db:
        business = db.get(Business, uuid.UUID(business_id_a))
        assert business.plan == BusinessPlan.FREE


def test_admin_list_businesses_rejects_non_superadmin(two_businesses):
    resp = client.get("/api/v1/admin/businesses", headers=_auth_header(two_businesses["token_a"]))
    assert resp.status_code == 403, resp.text


def test_admin_endpoints_reject_unauthenticated():
    resp = client.get("/api/v1/admin/businesses")
    assert resp.status_code == 401, resp.text


def test_admin_plan_change_404s_for_nonexistent_business(superadmin_token):
    resp = client.patch(
        f"/api/v1/admin/businesses/{uuid.uuid4()}/plan",
        json={"plan": "premium"},
        headers=_auth_header(superadmin_token),
    )
    assert resp.status_code == 404, resp.text


# --- orchestrator-level gate (not via FastAPI Depends at all) -----------------


class _StubEmbeddingProvider:
    def embed(self, texts: list[str]) -> list[list[float]]:
        return [[0.01] * 1536 for _ in texts]


def test_orchestrator_blocks_premium_test_message_for_free_plan_business(two_businesses, monkeypatch):
    """Proves ensure_plan works from PLAIN Python inside the orchestrator,
    completely bypassing FastAPI's dependency-injection system — the
    "usable ... inside the conversation orchestrator's tool logic" half of
    Phase 34's requirement #2. No LLM stub needed: the literal trigger
    phrase is matched BEFORE any classify_and_respond call."""
    import app.services.conversation.orchestrator as orchestrator_module

    monkeypatch.setattr(orchestrator_module, "get_embedding_provider", lambda: _StubEmbeddingProvider())

    business_id_a = two_businesses["business_id_a"]
    token_a = two_businesses["token_a"]

    with SessionLocal() as db:
        from app.db.models.conversation import Conversation

        customer_resp = client.post(
            "/api/v1/customers", json={"name": "Orchestrator Test"}, headers=_auth_header(token_a)
        )
        customer_id = uuid.UUID(customer_resp.json()["id"])
        conversation = Conversation(
            business_id=uuid.UUID(business_id_a), customer_id=customer_id, channel="sms", status="open"
        )
        db.add(conversation)
        db.commit()
        db.refresh(conversation)
        conversation_id = conversation.id

    blocked = client.post(
        f"/api/v1/conversations/{conversation_id}/messages",
        headers=_auth_header(token_a),
        json={"content": "test premium feature"},
    )
    assert blocked.status_code == 201, blocked.text
    assert "isn't available on your current plan" in blocked.json()["response"]

    with SessionLocal() as db:
        business = db.get(Business, uuid.UUID(business_id_a))
        business.plan = BusinessPlan.PREMIUM
        db.commit()

    allowed = client.post(
        f"/api/v1/conversations/{conversation_id}/messages",
        headers=_auth_header(token_a),
        json={"content": "test premium feature"},
    )
    assert allowed.status_code == 201, allowed.text
    assert allowed.json()["response"] == "Premium feature executed."
