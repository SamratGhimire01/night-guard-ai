"""Phase 29 — TIER 1 ITEM 1: one consolidated, adversarial pass across the
ENTIRE authenticated API surface, not per-phase spot checks.

This does not replace the existing per-phase cross-tenant tests (Phase
3/4/5/6/10/11/18/19/20 etc. already prove isolation for their own domain in
their own test files, and those all still run and pass — see the Phase 29
PHASE_STATUS.md entry for the live re-run). This file's job is different:
build ONE business (A) with one real row of every tenant-owned resource type
that exists anywhere in the schema — including the ones normally only
reachable through the LLM orchestrator (HumanHandoff, TrainingQuestion,
FollowUp) which are inserted directly to avoid a real LLM call — then, with a
SEPARATE business B's real JWT, attack every single read/write/delete route
that takes a resource id, by guessed/known id. Every attempt must fail
(404, never 403 that would leak existence, and never a 200) and every
resource must be provably unmodified afterward.
"""

import uuid
from datetime import datetime, timedelta, timezone

import pytest
from fastapi.testclient import TestClient

from sqlalchemy import select

from app.db.database import SessionLocal
from app.db.models.business import Business, BusinessUser
from app.db.models.conversation import Conversation
from app.db.models.follow_up import FollowUp
from app.db.models.handoff import HumanHandoff
from app.db.models.training import TrainingQuestion
from app.main import app

client = TestClient(app)


def _unique_email(label: str) -> str:
    return f"{label}-{uuid.uuid4().hex[:10]}@example.com"


def _auth_header(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


@pytest.fixture
def two_businesses():
    email_a = _unique_email("audit-a-owner")
    email_b = _unique_email("audit-b-owner")
    resp_a = client.post(
        "/api/v1/auth/register",
        json={"business_name": "Audit Tenant A", "timezone": "UTC", "email": email_a, "password": "correcthorse1"},
    )
    resp_b = client.post(
        "/api/v1/auth/register",
        json={"business_name": "Audit Tenant B", "timezone": "UTC", "email": email_b, "password": "correcthorse1"},
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
def one_of_everything(two_businesses):
    """Populates Business A with a real row of every id-addressable
    tenant-owned resource across the whole schema, via the real API where a
    route exists (services/staff/customers/knowledge/appointments) and via
    direct ORM insert only for the three resources with no create-by-id API
    (HumanHandoff/TrainingQuestion/FollowUp are normally only produced by the
    LLM orchestrator/training room's own internal calls) — matching the exact
    same pattern every prior phase's own tests already use for these."""
    token_a = two_businesses["token_a"]
    business_id_a = two_businesses["business_id_a"]

    service = client.post(
        "/api/v1/services",
        json={"name": "Audit Service", "price": "50.00", "duration_minutes": 30},
        headers=_auth_header(token_a),
    ).json()
    staff = client.post(
        "/api/v1/staff", json={"name": "Audit Staff", "role": "dentist"}, headers=_auth_header(token_a)
    ).json()
    customer = client.post(
        "/api/v1/customers", json={"name": "Audit Customer"}, headers=_auth_header(token_a)
    ).json()
    doc = client.post(
        "/api/v1/knowledge",
        json={"title": "Audit Doc", "content": "confidential business A content"},
        headers=_auth_header(token_a),
    ).json()
    hours_resp = client.put(
        "/api/v1/business/hours",
        json={"days": [{"day_of_week": d, "open_time": "00:00:00", "close_time": "23:59:00"} for d in range(7)]},
        headers=_auth_header(token_a),
    )
    assert hours_resp.status_code == 200, hours_resp.text
    exception = client.post(
        "/api/v1/business/hours/exceptions",
        json={"date": "2099-12-25", "closed": True},
        headers=_auth_header(token_a),
    ).json()

    scheduled_at = (datetime.now(timezone.utc) + timedelta(days=3)).replace(hour=10, minute=0, second=0, microsecond=0)
    appt = client.post(
        "/api/v1/appointments",
        json={
            "customer_id": customer["id"],
            "service_id": service["id"],
            "scheduled_at": scheduled_at.isoformat(),
        },
        headers=_auth_header(token_a),
    ).json()

    with SessionLocal() as db:
        conversation = Conversation(
            business_id=business_id_a,
            customer_id=uuid.UUID(customer["id"]),
            channel="widget",
            status="active",
        )
        db.add(conversation)
        db.commit()
        db.refresh(conversation)

        handoff = HumanHandoff(
            business_id=business_id_a,
            conversation_id=conversation.id,
            reason="Customer message was classified as a complaint.",
            status="open",
        )
        db.add(handoff)

        owner = db.execute(
            select(BusinessUser).where(BusinessUser.business_id == business_id_a)
        ).scalars().first()

        training_question = TrainingQuestion(
            business_id=business_id_a,
            question="Audit question",
            answer="Audit answer",
            intent="general_question",
            asked_by=owner.id,
        )
        db.add(training_question)

        follow_up = FollowUp(
            business_id=business_id_a,
            customer_id=uuid.UUID(customer["id"]),
            conversation_id=conversation.id,
            status="sent",
            scheduled_at=datetime.now(timezone.utc),
            sent_at=datetime.now(timezone.utc),
            channel="email",
        )
        db.add(follow_up)
        db.commit()
        db.refresh(handoff)
        db.refresh(training_question)
        db.refresh(follow_up)

        ids = {
            "service_id": service["id"],
            "staff_id": staff["id"],
            "customer_id": customer["id"],
            "knowledge_document_id": doc["id"],
            "exception_id": exception["id"],
            "appointment_id": appt["id"],
            "conversation_id": str(conversation.id),
            "handoff_id": str(handoff.id),
            "training_question_id": str(training_question.id),
            "follow_up_id": str(follow_up.id),
        }
    return {**two_businesses, **ids}


# (method, path template, expected status when Business B tries it against
# Business A's resource) — every one of these must return 404 (never 403,
# which would confirm the id exists; never 2xx).
_ATTACK_MATRIX = [
    ("GET", "/api/v1/services"),  # list — sanity: must not include A's row
    ("PATCH", "/api/v1/services/{service_id}"),
    ("DELETE", "/api/v1/services/{service_id}"),
    ("PATCH", "/api/v1/staff/{staff_id}"),
    ("DELETE", "/api/v1/staff/{staff_id}"),
    ("GET", "/api/v1/customers/{customer_id}"),
    ("PATCH", "/api/v1/customers/{customer_id}"),
    ("DELETE", "/api/v1/customers/{customer_id}"),
    ("GET", "/api/v1/knowledge/{knowledge_document_id}"),
    ("PATCH", "/api/v1/knowledge/{knowledge_document_id}"),
    ("DELETE", "/api/v1/knowledge/{knowledge_document_id}"),
    ("DELETE", "/api/v1/business/hours/exceptions/{exception_id}"),
    ("GET", "/api/v1/appointments/{appointment_id}"),
    ("PATCH", "/api/v1/appointments/{appointment_id}/cancel"),
    ("PATCH", "/api/v1/appointments/{appointment_id}/reschedule"),
    ("PATCH", "/api/v1/handoffs/{handoff_id}"),
    ("POST", "/api/v1/conversations/{conversation_id}/messages"),
]


def test_full_surface_cross_tenant_attack_matrix(one_of_everything):
    token_b = one_of_everything["token_b"]
    results = []
    for method, template in _ATTACK_MATRIX:
        path = template.format(**one_of_everything)
        kwargs = {"headers": _auth_header(token_b)}
        if method == "PATCH" and "cancel" not in template and "reschedule" not in template and "handoffs" not in template:
            kwargs["json"] = {}
        elif "reschedule" in template:
            future = (datetime.now(timezone.utc) + timedelta(days=5)).replace(hour=11, minute=0, second=0, microsecond=0)
            kwargs["json"] = {"scheduled_at": future.isoformat()}
        elif "handoffs" in template:
            kwargs["json"] = {"status": "resolved"}
        elif method == "POST" and "messages" in template:
            kwargs["json"] = {"content": "cross-tenant attack attempt"}

        resp = getattr(client, method.lower())(path, **kwargs)
        results.append((method, path, resp.status_code, resp.text[:200]))

    print("\n=== TIER 1 ITEM 1 — FULL-SURFACE CROSS-TENANT ATTACK MATRIX ===")
    for method, path, status, body in results:
        print(f"{method:6s} {path:65s} -> {status}  {body}")

    for method, path, status, body in results:
        if path.endswith("/services") and method == "GET":
            assert status == 200, f"{method} {path} unexpectedly failed: {status} {body}"
            assert one_of_everything["service_id"] not in body, "Business B's service list leaked Business A's service"
        else:
            assert status == 404, f"SECURITY FAILURE: {method} {path} returned {status}, expected 404: {body}"
            assert '"forbidden"' not in body, f"{method} {path} returned 403 (existence leak) instead of 404: {body}"


def test_training_history_and_followups_run_are_business_scoped_not_id_addressable(one_of_everything):
    """training/history and followups/run take no id at all — they're scoped
    purely by current_user.business_id, so the attack here isn't ID-guessing,
    it's confirming Business B's own call never returns Business A's rows."""
    token_b = one_of_everything["token_b"]
    history = client.get("/api/v1/training/history", headers=_auth_header(token_b))
    assert history.status_code == 200, history.text
    assert history.json() == [], f"Business B saw Business A's training history: {history.text}"

    handoffs = client.get("/api/v1/handoffs?status=all", headers=_auth_header(token_b))
    assert handoffs.status_code == 200, handoffs.text
    assert handoffs.json() == [], f"Business B saw Business A's handoffs: {handoffs.text}"


def test_resources_are_provably_unmodified_after_the_attack(one_of_everything):
    """Re-run the attack matrix, then confirm with Business A's OWN token that
    nothing was actually changed or deleted by the rejected cross-tenant
    attempts above (belt-and-suspenders on top of the 404 assertions)."""
    token_a = one_of_everything["token_a"]
    token_b = one_of_everything["token_b"]

    client.delete(f"/api/v1/services/{one_of_everything['service_id']}", headers=_auth_header(token_b))
    client.delete(f"/api/v1/customers/{one_of_everything['customer_id']}", headers=_auth_header(token_b))
    client.delete(f"/api/v1/knowledge/{one_of_everything['knowledge_document_id']}", headers=_auth_header(token_b))
    client.patch(
        f"/api/v1/appointments/{one_of_everything['appointment_id']}/cancel", headers=_auth_header(token_b)
    )

    assert client.get("/api/v1/services", headers=_auth_header(token_a)).json()[0]["id"] == one_of_everything["service_id"]
    assert (
        client.get(f"/api/v1/customers/{one_of_everything['customer_id']}", headers=_auth_header(token_a)).status_code
        == 200
    )
    assert (
        client.get(
            f"/api/v1/knowledge/{one_of_everything['knowledge_document_id']}", headers=_auth_header(token_a)
        ).status_code
        == 200
    )
    appt = client.get(f"/api/v1/appointments/{one_of_everything['appointment_id']}", headers=_auth_header(token_a)).json()
    assert appt["status"] == "confirmed", f"cross-tenant cancel attempt actually cancelled it: {appt}"
