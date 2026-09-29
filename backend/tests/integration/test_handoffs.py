"""Phase 19 — human handoff (app/services/handoff_service.py,
GET/PATCH /api/v1/handoffs).

Direct handoff_service calls exercise the trigger logic and the anti-duplicate
DB constraint precisely and fast (no LLM needed to prove those). A smaller
number of real-endpoint tests go through the full orchestrator (stubbed
ChatProvider/EmbeddingProvider — no real API cost) to prove the actual wiring:
a real customer message produces a real Message with a real detected intent,
and the orchestrator turns that into a real HumanHandoff row plus an honest
appended sentence in the customer-facing response.
"""

import json as jsonlib
import uuid

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.exc import IntegrityError

from app.core.security import create_access_token
from app.db.database import SessionLocal
from app.db.models.business import Business, BusinessUser, BusinessUserRole
from app.db.models.conversation import Conversation
from app.db.models.handoff import HumanHandoff
from app.main import app
from app.services.conversation.response_templates import render
from app.schemas.conversation import ConversationIntent
from app.services import handoff_service

client = TestClient(app)


def _unique_email(label: str) -> str:
    return f"{label}-{uuid.uuid4().hex[:10]}@example.com"


def _auth_header(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


@pytest.fixture
def two_businesses():
    email_a = _unique_email("ho-a-owner")
    email_b = _unique_email("ho-b-owner")
    resp_a = client.post(
        "/api/v1/auth/register",
        json={"business_name": "Handoff Test A", "timezone": "UTC", "email": email_a, "password": "correcthorse1"},
    )
    resp_b = client.post(
        "/api/v1/auth/register",
        json={"business_name": "Handoff Test B", "timezone": "UTC", "email": email_b, "password": "correcthorse1"},
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
def staff_token(two_businesses):
    business_id_a = two_businesses["business_id_a"]
    with SessionLocal() as db:
        staff_user = BusinessUser(
            business_id=business_id_a,
            email=_unique_email("ho-staff"),
            hashed_password="unused",
            role=BusinessUserRole.STAFF,
        )
        db.add(staff_user)
        db.commit()
        db.refresh(staff_user)
        return create_access_token(user_id=staff_user.id, business_id=business_id_a, role=staff_user.role.value)


def _create_customer(token: str, **kwargs) -> dict:
    payload = {"name": "Handoff Customer", **kwargs}
    resp = client.post("/api/v1/customers", json=payload, headers=_auth_header(token))
    assert resp.status_code == 201, resp.text
    return resp.json()


def _create_conversation(business_id: uuid.UUID, customer_id: uuid.UUID) -> uuid.UUID:
    with SessionLocal() as db:
        conversation = Conversation(
            business_id=business_id, customer_id=customer_id, channel="sms", status="open"
        )
        db.add(conversation)
        db.commit()
        db.refresh(conversation)
        return conversation.id


def _open_handoffs(conversation_id: uuid.UUID) -> list[HumanHandoff]:
    with SessionLocal() as db:
        return list(
            db.query(HumanHandoff)
            .filter(HumanHandoff.conversation_id == conversation_id, HumanHandoff.resolved_at.is_(None))
            .all()
        )


# ---------------------------------------------------------------------------
# Trigger logic + anti-duplicate — direct handoff_service calls, real DB.
# ---------------------------------------------------------------------------


def test_no_knowledge_match_on_a_genuine_info_question_creates_a_real_handoff(two_businesses):
    business_id = two_businesses["business_id_a"]
    token = two_businesses["token_a"]
    customer = _create_customer(token, email="lead@example.com")
    conversation_id = _create_conversation(business_id, uuid.UUID(customer["id"]))

    with SessionLocal() as db:
        handoff = handoff_service.maybe_create_handoff(
            db,
            business_id=business_id,
            conversation_id=conversation_id,
            intent=ConversationIntent.PRICING_QUESTION,
            best_similarity=None,
        )
        assert handoff is not None
        assert handoff.status == "open"
        assert handoff.resolved_at is None
        assert "pricing_question" in handoff.reason
        assert "no knowledge base results" in handoff.reason

    assert len(_open_handoffs(conversation_id)) == 1


def test_low_similarity_below_threshold_creates_a_handoff_with_the_real_score(two_businesses):
    business_id = two_businesses["business_id_a"]
    token = two_businesses["token_a"]
    customer = _create_customer(token, email="lead2@example.com")
    conversation_id = _create_conversation(business_id, uuid.UUID(customer["id"]))

    with SessionLocal() as db:
        handoff = handoff_service.maybe_create_handoff(
            db,
            business_id=business_id,
            conversation_id=conversation_id,
            intent=ConversationIntent.SERVICE_QUESTION,
            best_similarity=0.289,
        )
        assert handoff is not None
        assert "0.29" in handoff.reason


def test_relevant_knowledge_match_does_not_create_a_handoff(two_businesses):
    business_id = two_businesses["business_id_a"]
    token = two_businesses["token_a"]
    customer = _create_customer(token, email="lead3@example.com")
    conversation_id = _create_conversation(business_id, uuid.UUID(customer["id"]))

    with SessionLocal() as db:
        handoff = handoff_service.maybe_create_handoff(
            db,
            business_id=business_id,
            conversation_id=conversation_id,
            intent=ConversationIntent.PRICING_QUESTION,
            best_similarity=0.91,
        )
        assert handoff is None
    assert len(_open_handoffs(conversation_id)) == 0


def test_complaint_intent_always_creates_a_handoff_regardless_of_knowledge(two_businesses):
    business_id = two_businesses["business_id_a"]
    token = two_businesses["token_a"]
    customer = _create_customer(token, email="lead4@example.com")
    conversation_id = _create_conversation(business_id, uuid.UUID(customer["id"]))

    with SessionLocal() as db:
        handoff = handoff_service.maybe_create_handoff(
            db,
            business_id=business_id,
            conversation_id=conversation_id,
            intent=ConversationIntent.COMPLAINT,
            best_similarity=0.99,  # irrelevant to this trigger
        )
        assert handoff is not None
        assert handoff.reason == "Customer message was classified as a complaint."


def test_human_handoff_intent_creates_a_handoff_with_the_explicit_request_reason(two_businesses):
    business_id = two_businesses["business_id_a"]
    token = two_businesses["token_a"]
    customer = _create_customer(token, email="lead5@example.com")
    conversation_id = _create_conversation(business_id, uuid.UUID(customer["id"]))

    with SessionLocal() as db:
        handoff = handoff_service.maybe_create_handoff(
            db,
            business_id=business_id,
            conversation_id=conversation_id,
            intent=ConversationIntent.HUMAN_HANDOFF,
            best_similarity=None,
        )
        assert handoff is not None
        assert handoff.reason == "Customer explicitly asked to speak with a human/staff member."


def test_booking_intent_never_triggers_a_handoff_even_with_no_knowledge_results(two_businesses):
    """BOOKING has its own dedicated tool path (Phase 10) — a knowledge-search
    miss means nothing for it, unlike a genuine info question."""
    business_id = two_businesses["business_id_a"]
    token = two_businesses["token_a"]
    customer = _create_customer(token, email="lead6@example.com")
    conversation_id = _create_conversation(business_id, uuid.UUID(customer["id"]))

    with SessionLocal() as db:
        handoff = handoff_service.maybe_create_handoff(
            db,
            business_id=business_id,
            conversation_id=conversation_id,
            intent=ConversationIntent.BOOKING,
            best_similarity=None,
        )
        assert handoff is None
    assert len(_open_handoffs(conversation_id)) == 0


def test_multiple_qualifying_calls_same_conversation_reuse_the_open_handoff_not_duplicate(two_businesses):
    business_id = two_businesses["business_id_a"]
    token = two_businesses["token_a"]
    customer = _create_customer(token, email="lead7@example.com")
    conversation_id = _create_conversation(business_id, uuid.UUID(customer["id"]))

    with SessionLocal() as db:
        first = handoff_service.maybe_create_handoff(
            db,
            business_id=business_id,
            conversation_id=conversation_id,
            intent=ConversationIntent.PRICING_QUESTION,
            best_similarity=None,
        )
    with SessionLocal() as db:
        second = handoff_service.maybe_create_handoff(
            db,
            business_id=business_id,
            conversation_id=conversation_id,
            intent=ConversationIntent.COMPLAINT,
            best_similarity=None,
        )
    with SessionLocal() as db:
        third = handoff_service.maybe_create_handoff(
            db,
            business_id=business_id,
            conversation_id=conversation_id,
            intent=ConversationIntent.HUMAN_HANDOFF,
            best_similarity=None,
        )

    assert first.id == second.id == third.id
    # The FIRST real reason is what's kept — a later qualifying message on an
    # already-escalated conversation doesn't overwrite why it was escalated.
    assert "pricing_question" in first.reason
    assert len(_open_handoffs(conversation_id)) == 1


def test_db_constraint_itself_rejects_a_second_open_handoff_row(two_businesses):
    """Bypasses handoff_service's application-level check entirely and inserts
    a second open row by hand — proves the real backstop is the partial
    unique index (see the model), not just application logic that a
    race/retry could get around."""
    business_id = two_businesses["business_id_a"]
    token = two_businesses["token_a"]
    customer = _create_customer(token, email="lead8@example.com")
    conversation_id = _create_conversation(business_id, uuid.UUID(customer["id"]))

    with SessionLocal() as db:
        db.add(HumanHandoff(business_id=business_id, conversation_id=conversation_id, reason="first", status="open"))
        db.commit()

    with SessionLocal() as db, pytest.raises(IntegrityError):
        db.add(HumanHandoff(business_id=business_id, conversation_id=conversation_id, reason="second", status="open"))
        db.commit()


def test_a_new_handoff_is_allowed_after_the_previous_one_is_resolved(two_businesses):
    """The real difference from Phase 18's FollowUp constraint: resolving a
    handoff must genuinely allow a fresh escalation later, not block it
    forever."""
    business_id = two_businesses["business_id_a"]
    token = two_businesses["token_a"]
    customer = _create_customer(token, email="lead9@example.com")
    conversation_id = _create_conversation(business_id, uuid.UUID(customer["id"]))

    with SessionLocal() as db:
        first = handoff_service.maybe_create_handoff(
            db,
            business_id=business_id,
            conversation_id=conversation_id,
            intent=ConversationIntent.COMPLAINT,
            best_similarity=None,
        )
        handoff_service.resolve_handoff(db, business_id=business_id, handoff_id=first.id)

    with SessionLocal() as db:
        second = handoff_service.maybe_create_handoff(
            db,
            business_id=business_id,
            conversation_id=conversation_id,
            intent=ConversationIntent.HUMAN_HANDOFF,
            best_similarity=None,
        )
        assert second is not None
        assert second.id != first.id

    with SessionLocal() as db:
        all_rows = db.query(HumanHandoff).filter(HumanHandoff.conversation_id == conversation_id).all()
        assert len(all_rows) == 2
    assert len(_open_handoffs(conversation_id)) == 1


# ---------------------------------------------------------------------------
# Real orchestrator wiring — stubbed ChatProvider/EmbeddingProvider (no real
# API cost), real DB, real endpoint.
# ---------------------------------------------------------------------------


def test_real_orchestrator_no_knowledge_match_creates_handoff_and_appends_honest_sentence(two_businesses, monkeypatch):
    from app.services.conversation import intent as intent_module
    from app.services.conversation import orchestrator as orchestrator_module

    honest_llm_text = "I don't have info on that in the materials I was given."

    class _StubChat:
        def chat(self, messages):
            return jsonlib.dumps({"intent": "service_question", "response": honest_llm_text})

    class _StubEmbed:
        def embed(self, texts):
            return [[0.01] * 1536 for _ in texts]

    monkeypatch.setattr(intent_module, "get_chat_provider", lambda: _StubChat())
    monkeypatch.setattr(orchestrator_module, "get_embedding_provider", lambda: _StubEmbed())

    token = two_businesses["token_a"]
    customer = _create_customer(token, email="realcust@example.com")
    conversation_id = _create_conversation(two_businesses["business_id_a"], uuid.UUID(customer["id"]))

    resp = client.post(
        f"/api/v1/conversations/{conversation_id}/messages",
        json={"content": "Do you use laser whitening equipment?"},
        headers=_auth_header(token),
    )
    assert resp.status_code == 201, resp.text
    body = resp.json()

    # Phase 5 grounding guard update: a low-similarity info-question answer is
    # now ALWAYS replaced by the fixed honest-fallback template, never left as
    # the LLM's own self-reported "I don't know" wording — code decides this
    # is ungrounded, not the model's own (unverifiable) honesty. The stub's
    # `honest_llm_text` deliberately does NOT appear in the real response
    # anymore; that's the guarantee this test now checks.
    assert honest_llm_text not in body["response"]
    assert "don't want to guess" in body["response"]
    # The fallback already promises "have them follow up with you": the addendum would say it twice (Phase 4 eval).
    assert render("handoff_addendum", "en") not in body["response"]

    handoffs = _open_handoffs(conversation_id)
    assert len(handoffs) == 1
    assert "service_question" in handoffs[0].reason


def test_real_orchestrator_second_qualifying_message_does_not_duplicate_the_handoff(two_businesses, monkeypatch):
    from app.services.conversation import intent as intent_module
    from app.services.conversation import orchestrator as orchestrator_module

    class _StubChat:
        def chat(self, messages):
            return jsonlib.dumps({"intent": "service_question", "response": "I don't have that information."})

    class _StubEmbed:
        def embed(self, texts):
            return [[0.01] * 1536 for _ in texts]

    monkeypatch.setattr(intent_module, "get_chat_provider", lambda: _StubChat())
    monkeypatch.setattr(orchestrator_module, "get_embedding_provider", lambda: _StubEmbed())

    token = two_businesses["token_a"]
    customer = _create_customer(token, email="realcust2@example.com")
    conversation_id = _create_conversation(two_businesses["business_id_a"], uuid.UUID(customer["id"]))

    for _ in range(3):
        resp = client.post(
            f"/api/v1/conversations/{conversation_id}/messages",
            json={"content": "Another question you won't know."},
            headers=_auth_header(token),
        )
        assert resp.status_code == 201, resp.text

    assert len(_open_handoffs(conversation_id)) == 1


# ---------------------------------------------------------------------------
# Business-facing endpoints — real HTTP.
# ---------------------------------------------------------------------------


def test_staff_can_list_open_handoffs_and_resolve_one(two_businesses, staff_token):
    business_id = two_businesses["business_id_a"]
    token = two_businesses["token_a"]
    customer = _create_customer(token, email="staffcust@example.com")
    conversation_id = _create_conversation(business_id, uuid.UUID(customer["id"]))
    with SessionLocal() as db:
        handoff = handoff_service.maybe_create_handoff(
            db,
            business_id=business_id,
            conversation_id=conversation_id,
            intent=ConversationIntent.COMPLAINT,
            best_similarity=None,
        )
        handoff_id = handoff.id

    resp = client.get("/api/v1/handoffs", headers=_auth_header(staff_token))
    assert resp.status_code == 200, resp.text
    ids = {h["id"] for h in resp.json()}
    assert str(handoff_id) in ids

    resp = client.patch(f"/api/v1/handoffs/{handoff_id}", json={"status": "resolved"}, headers=_auth_header(staff_token))
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["status"] == "resolved"
    assert body["resolved_at"] is not None

    resp = client.get("/api/v1/handoffs", headers=_auth_header(token))
    assert str(handoff_id) not in {h["id"] for h in resp.json()}

    resp = client.get("/api/v1/handoffs", params={"status": "resolved"}, headers=_auth_header(token))
    assert str(handoff_id) in {h["id"] for h in resp.json()}

    resp = client.get("/api/v1/handoffs", params={"status": "all"}, headers=_auth_header(token))
    assert str(handoff_id) in {h["id"] for h in resp.json()}


def test_cross_tenant_handoffs_are_isolated(two_businesses):
    business_id_a = two_businesses["business_id_a"]
    token_a = two_businesses["token_a"]
    token_b = two_businesses["token_b"]
    customer_a = _create_customer(token_a, email="crosscust@example.com")
    conversation_id = _create_conversation(business_id_a, uuid.UUID(customer_a["id"]))
    with SessionLocal() as db:
        handoff = handoff_service.maybe_create_handoff(
            db,
            business_id=business_id_a,
            conversation_id=conversation_id,
            intent=ConversationIntent.COMPLAINT,
            best_similarity=None,
        )
        handoff_id = handoff.id

    resp = client.get("/api/v1/handoffs", headers=_auth_header(token_b))
    assert resp.status_code == 200
    assert str(handoff_id) not in {h["id"] for h in resp.json()}

    resp = client.patch(f"/api/v1/handoffs/{handoff_id}", json={"status": "resolved"}, headers=_auth_header(token_b))
    assert resp.status_code == 404, resp.text
