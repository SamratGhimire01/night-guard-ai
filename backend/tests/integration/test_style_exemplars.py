"""Phase 2 -- style exemplar retrieval, injection, and isolation.

Covers:
  (a) style_exemplar_service.retrieve's tenant/business_type/language scoping
      (mirrors knowledge_service.search_chunks's own tenant-isolation pattern).
  (b) the exemplar prompt section actually reaches intent.py's user prompt for a
      free-text intent, and is structurally never able to reach a
      template-dispatch branch's response_text (booking/cancellation/hours/
      resend/off_topic/...) regardless of what the LLM drafts.
  (c) fact_validator.check_unfilled_slots' regenerate-once-then-fallback wiring
      for a leaked {PLACEHOLDER} token, same pattern as every other fact
      violation.
  (d) the persona card's additive, default-preserving system-prompt notes.

Stubbed ChatProvider/EmbeddingProvider throughout -- real semantic-similarity
ranking (like knowledge_service's) is a live-API concern, not re-verified here;
a small deterministic "directional" embedding stub is used only where ranking
itself is the thing under test (the scoping tests below).
"""

import json
import uuid

import pytest
from fastapi.testclient import TestClient

from app.db.database import SessionLocal
from app.db.models.business import Business
from app.db.models.customer import Customer
from app.db.models.conversation import Conversation
from app.db.models.knowledge import EMBEDDING_DIMENSIONS
from app.db.models.style_exemplar import StyleExemplar
from app.main import app
from app.services import style_exemplar_service
from app.services.conversation.fact_validator import check_response_facts, check_unfilled_slots
from app.services.conversation.intent import _build_system_prompt
from app.services.conversation.response_templates import describe_business_hours, render

client = TestClient(app)


# --- shared helpers -------------------------------------------------------


def _make_business(db, **overrides) -> Business:
    business = Business(name=overrides.pop("name", "Test Biz"), timezone="UTC", **overrides)
    db.add(business)
    db.commit()
    db.refresh(business)
    return business


class _DirectionalEmbeddingProvider:
    """Deterministic stub: each distinct text gets its own orthonormal basis
    vector on first use, so cosine distance between any two DIFFERENT
    registered texts is always 1.0 and a vector against itself is 0.0 -- lets
    a scoping test assert exact set membership without a real embedding
    model. Shared across creation and query calls within one test via a
    single instance."""

    def __init__(self):
        self._index: dict[str, int] = {}

    def _vector(self, text: str) -> list[float]:
        if text not in self._index:
            self._index[text] = len(self._index)
        v = [0.0] * EMBEDDING_DIMENSIONS
        v[self._index[text]] = 1.0
        return v

    def embed(self, texts: list[str]) -> list[list[float]]:
        return [self._vector(t) for t in texts]


@pytest.fixture
def directional_provider(monkeypatch):
    provider = _DirectionalEmbeddingProvider()
    monkeypatch.setattr(style_exemplar_service, "get_embedding_provider", lambda: provider)
    return provider


@pytest.fixture
def scoping_businesses():
    db = SessionLocal()
    dental = _make_business(db, name="Scoping Dental", business_type="dental")
    generic = _make_business(db, name="Scoping Generic", business_type=None)
    yield db, dental, generic
    db.query(StyleExemplar).filter(
        StyleExemplar.business_id.in_([dental.id, generic.id])
    ).delete(synchronize_session=False)
    db.delete(dental)
    db.delete(generic)
    db.commit()
    db.close()


# --- (a) retrieval scoping --------------------------------------------------


# Real seed data (scripts/seed_style_exemplars.py) already lives in this DB and is eligible
# for these same scopes (shared/dental/en), so scoping correctness below is checked by
# membership/exclusion against a comfortably-large top_k, never by exact set equality --
# ranking against that real, unrelated data isn't what's under test here.
_ALL_ROWS_TOP_K = 5000


def test_retrieve_scopes_shared_exemplars_by_business_type(scoping_businesses, directional_provider):
    db, dental, generic = scoping_businesses
    style_exemplar_service.create_exemplar(
        db, business_id=None, business_type="dental", intent="pricing_question",
        language="en", register="neutral", text="dental-flavored example",
    )
    style_exemplar_service.create_exemplar(
        db, business_id=None, business_type="trekking", intent="pricing_question",
        language="en", register="neutral", text="trekking-flavored example",
    )
    style_exemplar_service.create_exemplar(
        db, business_id=None, business_type=None, intent="greeting",
        language="en", register="warm", text="universal example",
    )
    query_vector = directional_provider.embed(["some customer message"])[0]

    dental_texts = {
        e.text for e in style_exemplar_service.retrieve(
            db, business_id=dental.id, business_type=dental.business_type, language="en",
            query_vector=query_vector, top_k=_ALL_ROWS_TOP_K,
        )
    }
    assert "dental-flavored example" in dental_texts
    assert "universal example" in dental_texts
    assert "trekking-flavored example" not in dental_texts

    generic_texts = {
        e.text for e in style_exemplar_service.retrieve(
            db, business_id=generic.id, business_type=generic.business_type, language="en",
            query_vector=query_vector, top_k=_ALL_ROWS_TOP_K,
        )
    }
    assert "universal example" in generic_texts
    assert "dental-flavored example" not in generic_texts
    assert "trekking-flavored example" not in generic_texts


def test_retrieve_tenant_specific_override_is_isolated(scoping_businesses, directional_provider):
    db, dental, generic = scoping_businesses
    style_exemplar_service.create_exemplar(
        db, business_id=dental.id, business_type=None, intent="greeting",
        language="en", register="warm", text="dental-tenant-specific override",
    )
    query_vector = directional_provider.embed(["some customer message"])[0]

    dental_texts = {
        e.text for e in style_exemplar_service.retrieve(
            db, business_id=dental.id, business_type=dental.business_type, language="en",
            query_vector=query_vector, top_k=_ALL_ROWS_TOP_K,
        )
    }
    assert "dental-tenant-specific override" in dental_texts

    generic_texts = {
        e.text for e in style_exemplar_service.retrieve(
            db, business_id=generic.id, business_type=generic.business_type, language="en",
            query_vector=query_vector, top_k=_ALL_ROWS_TOP_K,
        )
    }
    assert "dental-tenant-specific override" not in generic_texts


def test_retrieve_language_is_a_hard_filter(scoping_businesses, directional_provider):
    db, dental, _generic = scoping_businesses
    style_exemplar_service.create_exemplar(
        db, business_id=dental.id, business_type=None, intent="greeting",
        language="en", register="warm", text="english greeting only this test creates",
    )
    style_exemplar_service.create_exemplar(
        db, business_id=dental.id, business_type=None, intent="greeting",
        language="ne_deva", register="warm", text="nepali greeting only this test creates",
    )
    query_vector = directional_provider.embed(["some customer message"])[0]

    en_texts = {
        e.text for e in style_exemplar_service.retrieve(
            db, business_id=dental.id, business_type=dental.business_type, language="en",
            query_vector=query_vector, top_k=_ALL_ROWS_TOP_K,
        )
    }
    assert "english greeting only this test creates" in en_texts
    assert "nepali greeting only this test creates" not in en_texts

    ne_texts = {
        e.text for e in style_exemplar_service.retrieve(
            db, business_id=dental.id, business_type=dental.business_type, language="ne_deva",
            query_vector=query_vector, top_k=_ALL_ROWS_TOP_K,
        )
    }
    assert "nepali greeting only this test creates" in ne_texts
    assert "english greeting only this test creates" not in ne_texts


def test_retrieve_respects_top_k(scoping_businesses, directional_provider):
    db, dental, _generic = scoping_businesses
    for i in range(8):
        style_exemplar_service.create_exemplar(
            db, business_id=None, business_type=None, intent="greeting",
            language="en", register="warm", text=f"universal example {i}",
        )
    query_vector = directional_provider.embed(["some customer message"])[0]

    results = style_exemplar_service.retrieve(
        db, business_id=dental.id, business_type=dental.business_type, language="en",
        query_vector=query_vector, top_k=3,
    )
    assert len(results) == 3


# --- (b) orchestrator injection + isolation --------------------------------


def _unique_email(label: str) -> str:
    return f"{label}-{uuid.uuid4().hex[:10]}@example.com"


def _auth_header(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


@pytest.fixture
def business():
    email = _unique_email("style-exemplar-owner")
    resp = client.post(
        "/api/v1/auth/register",
        json={"business_name": "Style Exemplar Biz", "timezone": "UTC", "email": email, "password": "correcthorse1"},
    )
    assert resp.status_code == 201, resp.text
    business_id = uuid.UUID(resp.json()["business_id"])
    login = client.post("/api/v1/auth/login", json={"email": email, "password": "correcthorse1"})
    data = {"business_id": business_id, "token": login.json()["access_token"]}
    yield data
    with SessionLocal() as db:
        b = db.get(Business, business_id)
        if b is not None:
            db.delete(b)
        db.commit()


def _create_customer(token: str) -> uuid.UUID:
    resp = client.post("/api/v1/customers", headers=_auth_header(token), json={"name": "Test Customer"})
    assert resp.status_code == 201, resp.text
    return uuid.UUID(resp.json()["id"])


def _create_conversation(business_id: uuid.UUID, customer_id: uuid.UUID) -> uuid.UUID:
    with SessionLocal() as db:
        conversation = Conversation(business_id=business_id, customer_id=customer_id, channel="sms", status="open")
        db.add(conversation)
        db.commit()
        db.refresh(conversation)
        return conversation.id


class _StubChatProvider:
    """Returns each entry of `replies` in order, repeating the last one once
    exhausted -- lets a regenerate-once test simulate a bad first draft
    followed by a clean retry."""

    def __init__(self, replies: list[str]):
        self.replies = replies
        self.calls: list[list[dict[str, str]]] = []

    def chat(self, messages: list[dict[str, str]]) -> str:
        self.calls.append(messages)
        idx = min(len(self.calls) - 1, len(self.replies) - 1)
        return self.replies[idx]


class _StubEmbeddingProvider:
    def embed(self, texts: list[str]) -> list[list[float]]:
        return [[0.01] * EMBEDDING_DIMENSIONS for _ in texts]


def _stub_providers(monkeypatch, replies: list[str]) -> _StubChatProvider:
    import app.services.conversation.intent as intent_module
    import app.services.conversation.orchestrator as orchestrator_module

    chat_stub = _StubChatProvider(replies)
    monkeypatch.setattr(intent_module, "get_chat_provider", lambda: chat_stub)
    monkeypatch.setattr(orchestrator_module, "get_embedding_provider", lambda: _StubEmbeddingProvider())
    return chat_stub


# A phrase that would only ever appear if a style_exemplar's tone leaked into
# a supposedly-deterministic dispatch branch -- distinctive enough to never
# collide with any real response_templates.py string.
_EXEMPLAR_TELL = "yo-exemplar-tone-marker-should-never-reach-the-customer"


def test_exemplar_section_reaches_free_text_intent_prompt(business, monkeypatch):
    """A free-text intent (general_question) is exactly where exemplar tone is
    SUPPOSED to reach the customer -- this proves retrieval + injection are
    actually wired, not just designed."""
    stub = _stub_providers(
        monkeypatch, [json.dumps({"intent": "general_question", "response": "We're open every day!"})]
    )
    customer_id = _create_customer(business["token"])
    conversation_id = _create_conversation(business["business_id"], customer_id)

    resp = client.post(
        f"/api/v1/conversations/{conversation_id}/messages",
        headers=_auth_header(business["token"]),
        json={"content": "Do you take walk-ins?"},
    )
    assert resp.status_code == 201, resp.text

    user_prompt = stub.calls[0][1]["content"]
    assert "Example replies illustrating this business's tone" in user_prompt


def test_off_topic_dispatch_never_leaks_llm_drafted_text(business, monkeypatch):
    stub = _stub_providers(
        monkeypatch, [json.dumps({
            "intent": "off_topic",
            "response": f"Sure, here's how America was discovered: {_EXEMPLAR_TELL}",
            "needs_human_handoff": False,
        })]
    )
    customer_id = _create_customer(business["token"])
    conversation_id = _create_conversation(business["business_id"], customer_id)

    resp = client.post(
        f"/api/v1/conversations/{conversation_id}/messages",
        headers=_auth_header(business["token"]),
        json={"content": "how was America discovered?"},
    )
    assert resp.status_code == 201, resp.text
    body = resp.json()
    assert _EXEMPLAR_TELL not in body["response"]
    # Deterministic template, not the LLM's own text, regardless of what it drafted.
    assert body["response"] == render("off_topic", None, name="Style Exemplar Biz")


def test_business_hours_dispatch_never_leaks_llm_drafted_text(business, monkeypatch):
    stub = _stub_providers(
        monkeypatch, [json.dumps({
            "intent": "business_hours",
            "response": f"We're open 24/7, always! {_EXEMPLAR_TELL}",
            "needs_human_handoff": False,
        })]
    )
    customer_id = _create_customer(business["token"])
    conversation_id = _create_conversation(business["business_id"], customer_id)

    resp = client.post(
        f"/api/v1/conversations/{conversation_id}/messages",
        headers=_auth_header(business["token"]),
        json={"content": "what are your hours?"},
    )
    assert resp.status_code == 201, resp.text
    body = resp.json()
    assert _EXEMPLAR_TELL not in body["response"]
    assert body["response"] == describe_business_hours([], "en")


# --- (c) slot-leak guard: regenerate once, then honest fallback -----------


def test_unfilled_slot_leak_is_caught_and_regenerated(business, monkeypatch):
    # Intent deliberately kept OUTSIDE {general_question, service_question, pricing_question,
    # location} -- those trigger a SEPARATE free-text grounding guard (best_similarity is None
    # for a business with no knowledge base) that would override a clean regen too, muddying
    # this test's one thing under test: the slot-leak check's own regenerate-once behavior.
    stub = _stub_providers(
        monkeypatch, [
            json.dumps({
                "intent": "greeting", "response": "Hi! Today's special is {PRICE} for {SERVICE}.",
                "needs_human_handoff": False,
            }),
            json.dumps({
                "intent": "greeting", "response": "Hi there! How can I help you today?",
                "needs_human_handoff": False,
            }),
        ]
    )
    customer_id = _create_customer(business["token"])
    conversation_id = _create_conversation(business["business_id"], customer_id)

    resp = client.post(
        f"/api/v1/conversations/{conversation_id}/messages",
        headers=_auth_header(business["token"]),
        json={"content": "hello there"},
    )
    assert resp.status_code == 201, resp.text
    body = resp.json()
    assert "{" not in body["response"] and "}" not in body["response"]
    assert len(stub.calls) == 2, "must have regenerated exactly once"
    assert body["response"] == "Hi there! How can I help you today?"


def test_unfilled_slot_leak_persisting_falls_back_honestly(business, monkeypatch):
    stub = _stub_providers(
        monkeypatch, [
            json.dumps({
                "intent": "greeting", "response": "Hi! It's {PRICE} today.", "needs_human_handoff": False,
            }),
            json.dumps({
                "intent": "greeting", "response": "Still {PRICE}, sorry.", "needs_human_handoff": False,
            }),
        ]
    )
    customer_id = _create_customer(business["token"])
    conversation_id = _create_conversation(business["business_id"], customer_id)

    resp = client.post(
        f"/api/v1/conversations/{conversation_id}/messages",
        headers=_auth_header(business["token"]),
        json={"content": "hello there"},
    )
    assert resp.status_code == 201, resp.text
    body = resp.json()
    assert "{" not in body["response"]
    # A real handoff is created (needs_human_handoff=True) on the persisting-violation path; the
    # fallback already promises a follow-up, so no handoff_addendum is appended -- see orchestrator.py.
    assert body["response"] == render("unconfirmed_fact_fallback", "en")


def test_check_unfilled_slots_unit():
    assert check_unfilled_slots("That's {PRICE} for {SERVICE}.") == [
        "reply contains an unfilled placeholder token: {PRICE}",
        "reply contains an unfilled placeholder token: {SERVICE}",
    ]
    assert check_unfilled_slots("That's NPR 1200 for Teeth Cleaning.") == []


def test_check_response_facts_includes_slot_leak_check():
    violations = check_response_facts(
        "That's {PRICE} for the service.", currency="USD", services=[], hours_by_day=None, known_text="",
    )
    assert any("placeholder" in v for v in violations)


# --- (d) persona card -------------------------------------------------------


def test_persona_card_defaults_add_nothing_to_system_prompt():
    db = SessionLocal()
    business = _make_business(db, name="Default Persona Biz")
    try:
        prompt = _build_system_prompt(business)
        assert "Your name is" not in prompt
        assert "Emoji override" not in prompt
        assert "may close with" not in prompt
        assert "Lean casual" not in prompt and "Lean more formal" not in prompt
    finally:
        db.delete(business)
        db.commit()
        db.close()


def test_persona_card_fields_appear_when_set():
    from app.db.models.business import BusinessFormality, EmojiPolicy

    db = SessionLocal()
    business = _make_business(
        db, name="Custom Persona Biz", persona_name="Maya",
        formality=BusinessFormality.CASUAL, emoji_policy=EmojiPolicy.NONE, sign_off="- The Front Desk",
    )
    try:
        prompt = _build_system_prompt(business)
        assert "Your name is Maya" in prompt
        assert "Emoji override" in prompt
        assert "The Front Desk" in prompt
        assert "Lean casual" in prompt
    finally:
        db.delete(business)
        db.commit()
        db.close()
