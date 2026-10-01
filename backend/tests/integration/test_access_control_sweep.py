"""Access control, checked where the data is read — not by hidden buttons.

Every route is discovered from the app itself, so a route added later is covered automatically:
- logged out: every non-public route answers 401;
- another business: every route that takes a record id answers 403/404 for business A's records, and nothing of A's
  changes;
- staff: every owner/admin route answers 403;
- record ids smuggled in a body or query string, edited tokens, demotion and removal.
"""

import re
import time
import uuid
from datetime import UTC, datetime, timedelta
from decimal import Decimal

import jwt
import pytest
from fastapi.routing import APIRoute
from fastapi.testclient import TestClient

from app.core.config import settings
from app.core.security import hash_password
from app.db.database import SessionLocal
from app.db.models.appointment import Appointment, AppointmentStatus
from app.db.models.business import Business, BusinessPlan, BusinessUser, BusinessUserRole
from app.db.models.conversation import Conversation, Message, MessageSenderType
from app.db.models.handoff import HumanHandoff
from app.db.models.knowledge import KnowledgeDocument, KnowledgeDocumentStatus
from app.db.models.payment import Payment, PaymentStatus
from app.main import app

client = TestClient(app)
PW = "correcthorse1"

# Reachable without a login on purpose: sign-up/login, the website chat, Meta webhooks, payment returns, QR pages.
PUBLIC = re.compile(
    r"^/(widget\.js|test-chat|widget-demo|qr/|pay-qr/)"
    r"|^/api/v1/(health|auth/(register|login|forgot-password|reset-password)$|widget/|webhooks/"
    r"|payments/(esewa|khalti)/|integrations/google-calendar/callback$)"
)
# Path params that name the business itself rather than one of its records (superadmin-only routes).
_NOT_A_RECORD = {"type"}


def _routes():
    def flat(routes, prefix=""):
        for r in routes:
            if isinstance(r, APIRoute):
                yield prefix + r.path, r
            elif hasattr(r, "original_router"):
                yield from flat(r.original_router.routes, prefix + (r.include_context.prefix or ""))

    out = []
    for path, route in flat(app.routes):
        deps = []

        def walk(d):
            for sub in d.dependencies:
                deps.append(getattr(sub.call, "__qualname__", ""))
                walk(sub)

        walk(route.dependant)
        for method in sorted(route.methods - {"HEAD", "OPTIONS"}):
            out.append((method, path, any("require_role" in d for d in deps)))
    return out


ROUTES = _routes()


def _register(label):
    email = f"sweep-{label}-{uuid.uuid4().hex[:8]}@example.com"
    resp = client.post("/api/v1/auth/register", json={"business_name": f"Sweep {label}", "timezone": "UTC", "email": email, "password": PW})
    assert resp.status_code == 201, resp.text
    return uuid.UUID(resp.json()["business_id"]), email


def _login(email):
    resp = client.post("/api/v1/auth/login", json={"email": email, "password": PW})
    assert resp.status_code == 200, resp.text
    return {"Authorization": "Bearer " + resp.json()["access_token"]}


def _add_user(business_id, role):
    email = f"sweep-{role.value}-{uuid.uuid4().hex[:8]}@example.com"
    with SessionLocal() as db:
        user = BusinessUser(business_id=business_id, email=email, hashed_password=hash_password(PW), role=role)
        db.add(user)
        db.commit()
        return user.id, email


@pytest.fixture(scope="module")
def world():
    a, a_email = _register("a")
    b, b_email = _register("b")
    with SessionLocal() as db:
        for business_id in (a, b):
            db.get(Business, business_id).plan = BusinessPlan.PREMIUM
        db.commit()
    headers = {"owner": _login(a_email), "b": _login(b_email)}
    staff_user_id, staff_email = _add_user(a, BusinessUserRole.STAFF)
    headers["staff"] = _login(staff_email)
    owner = headers["owner"]
    ids = {"user_id": staff_user_id, "business_id": a}
    ids["service_id"] = client.post("/api/v1/services", json={"name": "Cleaning", "price": "1000", "duration_minutes": 30}, headers=owner).json()["id"]
    ids["staff_id"] = client.post("/api/v1/staff", json={"name": "Dr Rai", "role": "Dentist"}, headers=owner).json()["id"]
    ids["customer_id"] = client.post("/api/v1/customers", json={"name": "Secret Customer A", "phone": "9800000999"}, headers=owner).json()["id"]
    when = (datetime.now(UTC) + timedelta(days=30)).date().isoformat()
    ids["exception_id"] = client.post("/api/v1/business/hours/exceptions", json={"date": when, "is_closed": True}, headers=owner).json()["id"]
    with SessionLocal() as db:
        appt = Appointment(
            business_id=a, customer_id=uuid.UUID(ids["customer_id"]), service_id=uuid.UUID(ids["service_id"]),
            scheduled_at=datetime.now(UTC) + timedelta(days=2), duration_minutes=30, status=AppointmentStatus.CONFIRMED,
        )
        db.add(appt)
        db.flush()
        conv = Conversation(business_id=a, customer_id=appt.customer_id, channel="widget", status="active")
        db.add(conv)
        db.flush()
        db.add(Message(conversation_id=conv.id, sender_type=MessageSenderType.CUSTOMER, content="private question"))
        handoff = HumanHandoff(business_id=a, conversation_id=conv.id, reason="complaint", status="open")
        doc = KnowledgeDocument(business_id=a, title="Secret price list", source="manual", status=KnowledgeDocumentStatus.APPROVED)
        db.add_all([handoff, doc])
        db.flush()
        payment = Payment(
            business_id=a, appointment_id=appt.id, provider="esewa", amount=Decimal("500"), currency="NPR",
            status=PaymentStatus.PENDING, payment_url="https://example.invalid/pay",
        )
        db.add(payment)
        db.commit()
        ids.update(
            appointment_id=appt.id, conversation_id=conv.id, handoff_id=handoff.id, document_id=doc.id,
            knowledge_document_id=doc.id, payment_id=payment.id, checkin_token=appt.checkin_token,
        )
    resp = client.post(f"/api/v1/services/{ids['service_id']}/knowledge-documents", json={"knowledge_document_id": str(doc.id)}, headers=owner)
    assert resp.status_code == 201, resp.text
    yield {"a": a, "b": b, "h": headers, "ids": {k: str(v) for k, v in ids.items()}}
    with SessionLocal() as db:
        for business_id in (a, b):
            business = db.get(Business, business_id)
            if business is not None:
                db.delete(business)
        db.commit()


def _url(path, ids):
    url = path.replace("{type}", "whatsapp")
    for key, value in ids.items():
        url = url.replace("{" + key + "}", value)
    return url


def test_every_route_is_either_public_or_needs_a_login(world):
    checked = 0
    for method, path, _ in ROUTES:
        if PUBLIC.search(path):
            continue
        resp = client.request(method, _url(path, world["ids"]), json={} if method != "GET" else None)
        assert resp.status_code == 401, f"{method} {path} answered {resp.status_code} without a login"
        checked += 1
    assert checked > 80  # the sweep really ran over the dashboard API


def test_another_business_cannot_reach_any_record_by_id(world):
    bodies = {
        "PATCH /api/v1/customers/{customer_id}": {"name": "HACKED"},
        "PATCH /api/v1/services/{service_id}": {"name": "HACKED"},
        "PATCH /api/v1/staff/{staff_id}": {"name": "HACKED"},
        "PATCH /api/v1/team/{user_id}": {"role": "admin"},
        "PATCH /api/v1/knowledge/{document_id}": {"title": "HACKED"},
        "PATCH /api/v1/handoffs/{handoff_id}": {"status": "resolved"},
        "PATCH /api/v1/appointments/{appointment_id}/reschedule": {
            "scheduled_at": (datetime.now(UTC) + timedelta(days=3)).replace(hour=10, minute=0, second=0, microsecond=0).isoformat()
        },
        "POST /api/v1/inbox/conversations/{conversation_id}/reply": {"content": "HACKED"},
        "POST /api/v1/conversations/{conversation_id}/messages": {"content": "hi"},
        "POST /api/v1/services/{service_id}/knowledge-documents": {"knowledge_document_id": world["ids"]["document_id"]},
        "POST /api/v1/payments/{payment_id}/collect-in-person": {"amount": "500"},
        "PATCH /api/v1/admin/businesses/{business_id}/plan": {"plan": "free"},
    }
    checked = 0
    for method, path, _ in ROUTES:
        params = set(re.findall(r"{(\w+)}", path)) - _NOT_A_RECORD
        if PUBLIC.search(path) or not params:
            continue
        body = bodies.get(f"{method} {path}", {})
        resp = client.request(method, _url(path, world["ids"]), headers=world["h"]["b"], json=body if method != "GET" else None)
        assert resp.status_code in (403, 404), f"{method} {path}: another business got {resp.status_code}"
        checked += 1
    assert checked > 30

    owner, ids = world["h"]["owner"], world["ids"]
    assert client.get(f"/api/v1/customers/{ids['customer_id']}", headers=owner).json()["name"] == "Secret Customer A"
    assert [s["name"] for s in client.get("/api/v1/services", headers=owner).json()] == ["Cleaning"]
    assert [s["name"] for s in client.get("/api/v1/staff", headers=owner).json()] == ["Dr Rai"]
    assert client.get(f"/api/v1/knowledge/{ids['document_id']}", headers=owner).json()["title"] == "Secret price list"


def test_staff_cannot_use_any_owner_or_admin_route(world):
    staff_allowed = re.compile(r"^/api/v1/(inbox/|handoffs)")  # front-desk staff answer customers by design
    checked = 0
    for method, path, role_gated in ROUTES:
        if not role_gated or PUBLIC.search(path) or staff_allowed.search(path):
            continue
        resp = client.request(method, _url(path, world["ids"]), headers=world["h"]["staff"], json={} if method != "GET" else None)
        assert resp.status_code == 403, f"{method} {path}: staff got {resp.status_code}"
        checked += 1
    assert checked > 40


def test_record_ids_hidden_in_a_body_or_query_are_scoped_too(world):
    b, ids = world["h"]["b"], world["ids"]
    own_service = client.post("/api/v1/services", json={"name": "B svc", "price": "10", "duration_minutes": 30}, headers=b).json()["id"]
    own_customer = client.post("/api/v1/customers", json={"name": "B cust", "phone": "9811111111"}, headers=b).json()["id"]
    slot = (datetime.now(UTC) + timedelta(days=5)).replace(hour=10, minute=0, second=0, microsecond=0).isoformat()

    assert client.get(f"/api/v1/appointments/available-slots?service_id={ids['service_id']}&on={slot[:10]}", headers=b).status_code == 404
    for body in (
        {"customer_id": own_customer, "service_id": ids["service_id"], "scheduled_at": slot},
        {"customer_id": ids["customer_id"], "service_id": own_service, "scheduled_at": slot},
        {"customer_id": own_customer, "service_id": own_service, "staff_id": ids["staff_id"], "scheduled_at": slot},
    ):
        assert client.post("/api/v1/appointments", json=body, headers=b).status_code == 404
    resp = client.post(f"/api/v1/services/{own_service}/knowledge-documents", json={"knowledge_document_id": ids["document_id"]}, headers=b)
    assert resp.status_code == 404
    assert client.post("/api/v1/appointments/checkin", json={"token": ids["checkin_token"]}, headers=b).status_code == 404

    for path in ("/api/v1/customers?q=Secret", "/api/v1/appointments", "/api/v1/inbox/conversations?tab=all", "/api/v1/payments",
                 "/api/v1/knowledge", "/api/v1/handoffs", "/api/v1/staff", "/api/v1/services", "/api/v1/team",
                 "/api/v1/customers/export.csv"):
        text = client.get(path, headers=b).text
        assert not any(str(v) in text for v in ids.values()) and "Secret" not in text, path


def test_edited_expired_and_unsigned_tokens(world):
    ids = world["ids"]

    def token(key=settings.secret_key, exp=3600, role="owner", business_id=None, alg="HS256"):
        claims = {"sub": ids["user_id"], "business_id": business_id or str(world["a"]), "role": role,
                  "iat": int(time.time()), "exp": int(time.time()) + exp}
        return {"Authorization": "Bearer " + jwt.encode(claims, key if alg != "none" else None, algorithm=alg)}

    assert client.get("/api/v1/customers", headers=token(key="not-the-real-key-" + "x" * 32)).status_code == 401
    assert client.get("/api/v1/customers", headers=token(exp=-10)).status_code == 401
    assert client.get("/api/v1/customers", headers=token(alg="none")).status_code == 401
    # a staff login whose token claims "owner" and another business is still that staff member, in their own business
    assert client.get("/api/v1/customers/export.csv", headers=token(role="owner")).status_code == 403
    listed = client.get("/api/v1/customers", headers=token(role="staff", business_id=str(world["b"]))).text
    assert "B cust" not in listed


def test_demotion_and_removal_take_effect_on_existing_logins(world):
    owner = world["h"]["owner"]
    admin_id, admin_email = _add_user(world["a"], BusinessUserRole.ADMIN)
    admin = _login(admin_email)
    assert client.get("/api/v1/team", headers=admin).status_code == 200
    assert client.patch(f"/api/v1/team/{admin_id}", json={"role": "staff"}, headers=owner).status_code == 200
    assert client.get("/api/v1/team", headers=admin).status_code == 403
    assert client.delete(f"/api/v1/team/{admin_id}", headers=owner).status_code in (200, 204)
    assert client.get("/api/v1/customers", headers=admin).status_code == 401
