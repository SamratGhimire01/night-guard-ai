"""Phase 23 (urgent fix) — customer contact update (PATCH /api/v1/customers/{id},
app/services/conversation/contact_tool.py) and the handoff false-positive fix
(app/services/handoff_service.py's `llm_confirmed_answered`).

Real DB and real Appointment/Business/Service/Customer/Notification rows
throughout. What's stubbed is only the actual email network call
(`dispatch_service._PROVIDERS["email"]`), same "stub the network, not the
business logic" discipline as test_notifications.py — this proves the REAL
customer-update write path and the REAL dispatch_notification re-dispatch
actually run, without needing a real SMTP server in CI. The real, unstubbed
Gmail SMTP resend is proven separately (see PHASE_STATUS.md's Phase 23
section) against this environment's real Gmail credentials.
"""

import json as jsonlib
import uuid
from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from app.core.security import create_access_token
from app.db.database import SessionLocal
from app.db.models.business import Business, BusinessUser, BusinessUserRole
from app.db.models.conversation import Conversation
from app.db.models.customer import Customer
from app.db.models.notification import Notification, NotificationStatus
from app.main import app
from app.schemas.conversation import ConversationIntent
from app.services import handoff_service
from app.services.conversation.contact_tool import UpdateContactInfoTool
from app.services.notifications import dispatch_service

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


class _FakeProvider:
    def __init__(self, outcomes):
        self.outcomes = list(outcomes)
        self.calls = 0
        self.recipients = []

    def send(self, *, to, subject, body, html_body=None, attachments=None, inline_images=None, credentials=None):
        self.calls += 1
        self.recipients.append(to)
        outcome = self.outcomes.pop(0) if self.outcomes else self.outcomes[-1]
        if isinstance(outcome, Exception):
            raise outcome
        return outcome


@pytest.fixture
def business_ready():
    email = _unique_email("contact-owner")
    resp = client.post(
        "/api/v1/auth/register",
        json={"business_name": "Contact Update Test Co", "timezone": "UTC", "email": email, "password": "correcthorse1"},
    )
    assert resp.status_code == 201, resp.text
    business_id = uuid.UUID(resp.json()["business_id"])
    login = client.post("/api/v1/auth/login", json={"email": email, "password": "correcthorse1"})
    token = login.json()["access_token"]

    days = [{"day_of_week": d, "open_time": "09:00:00", "close_time": "17:00:00"} for d in range(6)]
    days.append({"day_of_week": 6, "closed": True})
    assert client.put("/api/v1/business/hours", json={"days": days}, headers=_auth_header(token)).status_code == 200

    service = client.post(
        "/api/v1/services",
        json={"name": "Cleaning", "price": "50.00", "duration_minutes": 30},
        headers=_auth_header(token),
    )
    assert service.status_code == 201, service.text

    data = {"business_id": business_id, "token": token, "service_id": uuid.UUID(service.json()["id"])}
    yield data

    with SessionLocal() as db:
        business = db.get(Business, business_id)
        if business is not None:
            db.delete(business)
        db.commit()


@pytest.fixture
def staff_token(business_ready):
    with SessionLocal() as db:
        staff_user = BusinessUser(
            business_id=business_ready["business_id"],
            email=_unique_email("contact-staff"),
            hashed_password="unused",
            role=BusinessUserRole.STAFF,
        )
        db.add(staff_user)
        db.commit()
        db.refresh(staff_user)
        return create_access_token(user_id=staff_user.id, business_id=business_ready["business_id"], role=staff_user.role.value)


def _create_customer(token: str, **kwargs) -> dict:
    payload = {"name": "Website Visitor", **kwargs}
    resp = client.post("/api/v1/customers", json=payload, headers=_auth_header(token))
    assert resp.status_code == 201, resp.text
    return resp.json()


def _book_confirmed_with_failed_email_notification(business: dict, customer_id: uuid.UUID) -> tuple[uuid.UUID, uuid.UUID]:
    """Real booking through POST /appointments, real inline dispatch — the
    customer has no email, so EmailNotificationProvider genuinely fails
    ("No recipient email address on file") before any network call. Returns
    (appointment_id, notification_id)."""
    when = datetime.combine(_next_weekday(1), datetime.min.time(), tzinfo=ZoneInfo("UTC")).replace(hour=10)
    resp = client.post(
        "/api/v1/appointments",
        json={"customer_id": str(customer_id), "service_id": str(business["service_id"]), "scheduled_at": when.isoformat()},
        headers=_auth_header(business["token"]),
    )
    assert resp.status_code == 201, resp.text
    appointment_id = uuid.UUID(resp.json()["id"])
    with SessionLocal() as db:
        notification = db.execute(
            select(Notification).where(Notification.appointment_id == appointment_id)
        ).scalar_one()
        assert notification.status == NotificationStatus.FAILED, notification.status
        return appointment_id, notification.id


# ---------------------------------------------------------------------------
# PATCH /api/v1/customers/{id}
# ---------------------------------------------------------------------------


def test_owner_can_update_customer_contact_fields(business_ready):
    token = business_ready["token"]
    customer = _create_customer(token)
    resp = client.patch(
        f"/api/v1/customers/{customer['id']}",
        json={"name": "Alex Rivera", "email": "alex.rivera@example.com", "phone": "+15551234567"},
        headers=_auth_header(token),
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["name"] == "Alex Rivera"
    assert body["email"] == "alex.rivera@example.com"
    assert body["phone"] == "+15551234567"


def test_staff_can_also_update_customer_contact_fields(business_ready, staff_token):
    """Same RBAC tier as POST/GET — not owner/admin-only like DELETE."""
    token = business_ready["token"]
    customer = _create_customer(token)
    resp = client.patch(
        f"/api/v1/customers/{customer['id']}",
        json={"name": "Staff Updated Name"},
        headers=_auth_header(staff_token),
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["name"] == "Staff Updated Name"


def test_invalid_email_format_is_rejected_with_422(business_ready):
    token = business_ready["token"]
    customer = _create_customer(token)
    resp = client.patch(
        f"/api/v1/customers/{customer['id']}", json={"email": "not-an-email"}, headers=_auth_header(token)
    )
    assert resp.status_code == 422, resp.text
    with SessionLocal() as db:
        row = db.get(Customer, uuid.UUID(customer["id"]))
        assert row.email is None


def test_name_cannot_be_cleared_to_null(business_ready):
    token = business_ready["token"]
    customer = _create_customer(token)
    resp = client.patch(f"/api/v1/customers/{customer['id']}", json={"name": None}, headers=_auth_header(token))
    assert resp.status_code == 422, resp.text


def test_email_can_be_cleared_to_null(business_ready):
    token = business_ready["token"]
    customer = _create_customer(token, email="had-one@example.com")
    resp = client.patch(f"/api/v1/customers/{customer['id']}", json={"email": None}, headers=_auth_header(token))
    assert resp.status_code == 200, resp.text
    assert resp.json()["email"] is None


def test_business_id_cannot_be_changed_through_this_endpoint(business_ready):
    """business_id isn't a declared field on CustomerUpdate at all — sending
    one in the body is silently ignored, never trusted from the client."""
    token = business_ready["token"]
    customer = _create_customer(token)
    other_business_id = str(uuid.uuid4())
    resp = client.patch(
        f"/api/v1/customers/{customer['id']}",
        json={"name": "Still Same Tenant", "business_id": other_business_id},
        headers=_auth_header(token),
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["business_id"] == str(business_ready["business_id"])


def test_cross_tenant_patch_returns_404_and_does_not_modify(business_ready):
    email_b = _unique_email("contact-owner-b")
    resp_b = client.post(
        "/api/v1/auth/register",
        json={"business_name": "Contact Update Test Co B", "timezone": "UTC", "email": email_b, "password": "correcthorse1"},
    )
    assert resp_b.status_code == 201, resp_b.text
    business_id_b = uuid.UUID(resp_b.json()["business_id"])
    login_b = client.post("/api/v1/auth/login", json={"email": email_b, "password": "correcthorse1"})
    token_b = login_b.json()["access_token"]

    token_a = business_ready["token"]
    customer_a = _create_customer(token_a)

    resp = client.patch(
        f"/api/v1/customers/{customer_a['id']}", json={"name": "Hijacked"}, headers=_auth_header(token_b)
    )
    assert resp.status_code == 404, resp.text

    resp = client.get(f"/api/v1/customers/{customer_a['id']}", headers=_auth_header(token_a))
    assert resp.json()["name"] == "Website Visitor"

    with SessionLocal() as db:
        business = db.get(Business, business_id_b)
        if business is not None:
            db.delete(business)
        db.commit()


# ---------------------------------------------------------------------------
# UpdateContactInfoTool — real update, real re-dispatch (stubbed network).
# ---------------------------------------------------------------------------


def test_tool_updates_customer_and_resends_a_real_failed_notification(business_ready, monkeypatch):
    token = business_ready["token"]
    customer = _create_customer(token)  # no email — "Website Visitor"
    # The REAL EmailNotificationProvider (unstubbed) genuinely fails here —
    # no recipient on file, no network call needed to know that. Only the
    # RESEND below is stubbed, so this FAILED status is real, not scripted.
    appointment_id, notification_id = _book_confirmed_with_failed_email_notification(
        business_ready, uuid.UUID(customer["id"])
    )

    fake = _FakeProvider(["250 message accepted for delivery"])
    monkeypatch.setitem(dispatch_service._PROVIDERS, "email", fake)

    with SessionLocal() as db:
        result = UpdateContactInfoTool().run(
            db,
            business_id=business_ready["business_id"],
            customer_id=uuid.UUID(customer["id"]),
            fields={"name": "Alex Rivera", "email": "alex.rivera@example.com"},
        )

    assert result["success"] is True
    assert set(result["updated_fields"]) == {"name", "email"}
    assert result["customer"]["email"] == "alex.rivera@example.com"
    assert len(result["resends"]) == 1
    assert result["resends"][0]["notification_id"] == str(notification_id)
    assert result["resends"][0]["status"] == NotificationStatus.SENT.value
    assert fake.calls == 1
    assert fake.recipients == ["alex.rivera@example.com"]  # the REAL new address, not the empty old one

    with SessionLocal() as db:
        row = db.get(Customer, uuid.UUID(customer["id"]))
        assert row.name == "Alex Rivera"
        assert row.email == "alex.rivera@example.com"
        notification = db.get(Notification, notification_id)
        assert notification.status == NotificationStatus.SENT


def test_tool_never_resends_when_only_name_changes(business_ready, monkeypatch):
    """Resend is only attempted when email/phone actually changed — a bare
    name correction shouldn't re-trigger a notification that has nothing to
    do with it."""
    fake = _FakeProvider(["250 ok"])
    monkeypatch.setitem(dispatch_service._PROVIDERS, "email", fake)

    token = business_ready["token"]
    customer = _create_customer(token, email="already-had-one@example.com")

    with SessionLocal() as db:
        result = UpdateContactInfoTool().run(
            db,
            business_id=business_ready["business_id"],
            customer_id=uuid.UUID(customer["id"]),
            fields={"name": "Corrected Name"},
        )

    assert result["success"] is True
    assert result["updated_fields"] == ["name"]
    assert result["resends"] == []
    assert fake.calls == 0


def test_tool_does_not_resend_notifications_that_already_succeeded(business_ready, monkeypatch):
    """Only genuinely FAILED notifications are ever re-dispatched — a
    SENT/SIMULATED one is left alone, never re-sent twice."""
    fake = _FakeProvider(["250 ok"])
    monkeypatch.setitem(dispatch_service._PROVIDERS, "email", fake)

    token = business_ready["token"]
    customer = _create_customer(token, email="already-worked@example.com")
    when = datetime.combine(_next_weekday(2), datetime.min.time(), tzinfo=ZoneInfo("UTC")).replace(hour=11)
    resp = client.post(
        "/api/v1/appointments",
        json={
            "customer_id": customer["id"],
            "service_id": str(business_ready["service_id"]),
            "scheduled_at": when.isoformat(),
        },
        headers=_auth_header(token),
    )
    assert resp.status_code == 201, resp.text
    assert fake.calls == 1  # the original booking-confirmation send already succeeded

    with SessionLocal() as db:
        result = UpdateContactInfoTool().run(
            db,
            business_id=business_ready["business_id"],
            customer_id=uuid.UUID(customer["id"]),
            fields={"phone": "+15559998888"},
        )
    assert result["resends"] == []
    assert fake.calls == 1  # still just the one real send — no needless re-send


def test_tool_rejects_a_malformed_email_without_writing_anything(business_ready):
    """Defense in depth: even if a garbled value ever slipped past the LLM
    extraction, CustomerUpdate's own EmailStr validation still guards the
    real write path."""
    token = business_ready["token"]
    customer = _create_customer(token)

    with SessionLocal() as db:
        result = UpdateContactInfoTool().run(
            db,
            business_id=business_ready["business_id"],
            customer_id=uuid.UUID(customer["id"]),
            fields={"email": "not-an-email"},
        )
    assert result["success"] is False

    with SessionLocal() as db:
        row = db.get(Customer, uuid.UUID(customer["id"]))
        assert row.email is None


def test_tool_returns_failure_for_a_nonexistent_customer(business_ready):
    with SessionLocal() as db:
        result = UpdateContactInfoTool().run(
            db,
            business_id=business_ready["business_id"],
            customer_id=uuid.uuid4(),
            fields={"name": "Ghost"},
        )
    assert result["success"] is False


# ---------------------------------------------------------------------------
# handoff_service — false-positive suppression (Phase 23 fix).
# ---------------------------------------------------------------------------


def test_llm_confirmed_answered_suppresses_a_low_similarity_info_handoff(business_ready):
    """The real bug this fixes: a pricing question fully answered from the
    Available services list (not the knowledge base) was getting a false
    handoff purely because knowledge-chunk similarity happened to be low."""
    from app.db.models.conversation import Conversation

    with SessionLocal() as db:
        customer = Customer(business_id=business_ready["business_id"], name="Suppress Test")
        db.add(customer)
        db.flush()
        conversation = Conversation(
            business_id=business_ready["business_id"], customer_id=customer.id, channel="website", status="open"
        )
        db.add(conversation)
        db.commit()
        db.refresh(conversation)
        conversation_id = conversation.id

    with SessionLocal() as db:
        handoff = handoff_service.maybe_create_handoff(
            db,
            business_id=business_ready["business_id"],
            conversation_id=conversation_id,
            intent=ConversationIntent.PRICING_QUESTION,
            best_similarity=0.26,
            llm_confirmed_answered=True,
        )
    assert handoff is None


def test_llm_confirmed_answered_true_never_suppresses_a_complaint():
    """Suppression only ever applies to the knowledge-similarity path for
    genuine info-question intents — never to complaint/human_handoff, which
    have nothing to do with knowledge relevance."""
    reason = handoff_service._handoff_reason(
        intent=ConversationIntent.COMPLAINT, best_similarity=0.99, llm_confirmed_answered=True
    )
    assert reason == "Customer message was classified as a complaint."


def test_missing_needs_human_handoff_field_falls_back_to_old_similarity_only_behavior():
    """Backward compatibility: llm_confirmed_answered=None (the field wasn't
    in the LLM's response at all) must behave EXACTLY like before this fix —
    zero regression risk for every pre-existing handoff test."""
    reason = handoff_service._handoff_reason(
        intent=ConversationIntent.SERVICE_QUESTION, best_similarity=0.26, llm_confirmed_answered=None
    )
    assert reason is not None
    assert "0.26" in reason


# ---------------------------------------------------------------------------
# Real orchestrator wiring — stubbed ChatProvider/EmbeddingProvider (no real
# API cost), real DB, real endpoint. This is the proof the acceptance
# criteria actually asks for: a real tool call fires from a real
# conversation turn, a real DB row changes, and a real notification actually
# re-dispatches — never just narrated text.
# ---------------------------------------------------------------------------


def _create_conversation(business_id: uuid.UUID, customer_id: uuid.UUID) -> uuid.UUID:
    with SessionLocal() as db:
        conversation = Conversation(
            business_id=business_id, customer_id=customer_id, channel="website", status="open"
        )
        db.add(conversation)
        db.commit()
        db.refresh(conversation)
        return conversation.id


def test_real_orchestrator_contact_info_update_triggers_real_tool_and_real_resend(business_ready, monkeypatch):
    from app.services.conversation import intent as intent_module
    from app.services.conversation import orchestrator as orchestrator_module

    token = business_ready["token"]
    customer = _create_customer(token)  # "Website Visitor", no email
    appointment_id, notification_id = _book_confirmed_with_failed_email_notification(
        business_ready, uuid.UUID(customer["id"])
    )
    conversation_id = _create_conversation(business_ready["business_id"], uuid.UUID(customer["id"]))

    fake = _FakeProvider(["250 message accepted for delivery"])
    monkeypatch.setitem(dispatch_service._PROVIDERS, "email", fake)

    stub_llm_text = "Thanks, Alex! Got your email down."

    class _StubChat:
        def chat(self, messages):
            return jsonlib.dumps(
                {
                    "intent": "follow_up",
                    "response": stub_llm_text,
                    "contact_info_update": {"name": "Alex Rivera", "email": "alex.rivera@example.com", "phone": None},
                    "needs_human_handoff": False,
                }
            )

    class _StubEmbed:
        def embed(self, texts):
            return [[0.01] * 1536 for _ in texts]

    monkeypatch.setattr(intent_module, "get_chat_provider", lambda: _StubChat())
    monkeypatch.setattr(orchestrator_module, "get_embedding_provider", lambda: _StubEmbed())

    resp = client.post(
        f"/api/v1/conversations/{conversation_id}/messages",
        json={"content": "Oh sorry, it's Alex Rivera, my email is alex.rivera@example.com"},
        headers=_auth_header(token),
    )
    assert resp.status_code == 201, resp.text
    body = resp.json()

    # The LLM's own honest text is preserved verbatim...
    assert stub_llm_text in body["response"]
    # ...and the REAL deterministic confirmation is appended — never the
    # LLM's own claim (the stub above never wrote anything about
    # resending/updating — proves this sentence comes from Python, not text
    # generation).
    assert "I've updated your contact info on file." in body["response"]
    assert "I also resent your appointment confirmation" in body["response"]
    # No false handoff sentence: needs_human_handoff was explicitly False and
    # this isn't a complaint/human_handoff/low-relevance-info-question turn.
    assert "real person will follow up" not in body["response"]

    with SessionLocal() as db:
        customer_row = db.get(Customer, uuid.UUID(customer["id"]))
        assert customer_row.name == "Alex Rivera"
        assert customer_row.email == "alex.rivera@example.com"
        notification = db.get(Notification, notification_id)
        assert notification.status == NotificationStatus.SENT
    assert fake.calls == 1
    assert fake.recipients == ["alex.rivera@example.com"]


def test_real_orchestrator_never_updates_contact_info_that_did_not_actually_change(business_ready, monkeypatch):
    """The LLM re-sending an already-correct value (e.g. repeating the same
    email back) must not trigger a spurious tool call or resend — the
    orchestrator re-diffs against the real Customer row first."""
    from app.services.conversation import intent as intent_module
    from app.services.conversation import orchestrator as orchestrator_module

    token = business_ready["token"]
    customer = _create_customer(token, name="Alex Rivera", email="alex.rivera@example.com")
    conversation_id = _create_conversation(business_ready["business_id"], uuid.UUID(customer["id"]))

    fake = _FakeProvider(["250 ok"])
    monkeypatch.setitem(dispatch_service._PROVIDERS, "email", fake)

    class _StubChat:
        def chat(self, messages):
            return jsonlib.dumps(
                {
                    "intent": "follow_up",
                    "response": "Sure thing!",
                    "contact_info_update": {"name": "Alex Rivera", "email": "alex.rivera@example.com", "phone": None},
                    "needs_human_handoff": False,
                }
            )

    class _StubEmbed:
        def embed(self, texts):
            return [[0.01] * 1536 for _ in texts]

    monkeypatch.setattr(intent_module, "get_chat_provider", lambda: _StubChat())
    monkeypatch.setattr(orchestrator_module, "get_embedding_provider", lambda: _StubEmbed())

    resp = client.post(
        f"/api/v1/conversations/{conversation_id}/messages",
        json={"content": "just confirming, still alex.rivera@example.com"},
        headers=_auth_header(token),
    )
    assert resp.status_code == 201, resp.text
    assert "I've updated your contact info" not in resp.json()["response"]
    assert fake.calls == 0
