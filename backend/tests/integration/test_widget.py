"""Phase 21 — website chat widget + channel abstraction
(app/services/channels/, app/api/routes/widget.py).

Stubbed ChatProvider/EmbeddingProvider (same discipline as test_conversation.py
/ test_followups.py / test_handoffs.py / test_training.py) for fast, free
coverage of the real wiring: session issuance, session continuity, session
isolation (a guessed/foreign token never reaches someone else's conversation),
cross-business replay, rate limiting (real per-IP and per-session limiter
state, reset per test via a fresh RateLimiter instance so tests don't share
budget), business-not-found handling, CORS scoping, and the static widget.js
file actually serving. Real, unstubbed Azure LLM end-to-end proof is pasted
into PHASE_STATUS.md.
"""

import json as jsonlib
import uuid

import pytest
from fastapi.testclient import TestClient

import app.api.routes.widget as widget_module
from app.core.rate_limit import WIDGET_IP_MAX_ATTEMPTS, WIDGET_SESSION_MAX_ATTEMPTS, WIDGET_WINDOW_SECONDS, RateLimiter
from app.db.database import SessionLocal
from app.db.models.business import Business
from app.db.models.channel_identity import ChannelIdentity
from app.db.models.conversation import Conversation, Message
from app.main import app

client = TestClient(app)


class _StubChat:
    def chat(self, messages):
        return jsonlib.dumps({"intent": "general_question", "response": "Thanks for reaching out!"})


class _StubEmbed:
    def embed(self, texts):
        return [[0.01] * 1536 for _ in texts]


@pytest.fixture(autouse=True)
def _stub_providers(monkeypatch):
    import app.services.conversation.intent as intent_module
    import app.services.conversation.orchestrator as orchestrator_module

    monkeypatch.setattr(intent_module, "get_chat_provider", lambda: _StubChat())
    monkeypatch.setattr(orchestrator_module, "get_embedding_provider", lambda: _StubEmbed())


@pytest.fixture(autouse=True)
def _fresh_rate_limiters(monkeypatch):
    """Rate limiters are process-wide singletons — reset to a fresh instance
    per test so one test's requests never consume another test's budget."""
    monkeypatch.setattr(
        widget_module, "widget_ip_rate_limiter", RateLimiter(max_attempts=WIDGET_IP_MAX_ATTEMPTS, window_seconds=WIDGET_WINDOW_SECONDS)
    )
    monkeypatch.setattr(
        widget_module,
        "widget_session_rate_limiter",
        RateLimiter(max_attempts=WIDGET_SESSION_MAX_ATTEMPTS, window_seconds=WIDGET_WINDOW_SECONDS),
    )


def _unique_email(label: str) -> str:
    return f"{label}-{uuid.uuid4().hex[:10]}@example.com"


@pytest.fixture
def business():
    email = _unique_email("widget-owner")
    resp = client.post(
        "/api/v1/auth/register",
        json={"business_name": "Widget Test Biz", "timezone": "UTC", "email": email, "password": "correcthorse1"},
    )
    assert resp.status_code == 201, resp.text
    business_id = resp.json()["business_id"]
    yield business_id
    with SessionLocal() as db:
        b = db.get(Business, uuid.UUID(business_id))
        if b is not None:
            db.delete(b)
        db.commit()


def test_first_contact_creates_real_session_customer_and_conversation(business):
    resp = client.post(f"/api/v1/widget/{business}/messages", json={"content": "Hi, do you take walk-ins?"})
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["session_token"]
    assert len(body["session_token"]) >= 32  # real high-entropy token, not a short/sequential id
    # The stubbed LLM's own text is preserved verbatim, plus Phase 19's real
    # honest handoff sentence — this business has no knowledge base at all,
    # so a general_question here correctly triggers a real HumanHandoff too
    # (proof the widget path reuses the FULL real orchestrator, not a
    # simplified copy of it).
    assert body["response"] == "Thanks for reaching out! I've also let our team know, so a real person will follow up with you."
    assert body["intent"] == "general_question"

    with SessionLocal() as db:
        identities = db.query(ChannelIdentity).filter(ChannelIdentity.business_id == uuid.UUID(business)).all()
        assert len(identities) == 1
        assert identities[0].channel == "website"
        # the raw token is never stored — only its hash
        assert identities[0].external_ref != body["session_token"]

        conversations = db.query(Conversation).filter(Conversation.business_id == uuid.UUID(business)).all()
        assert len(conversations) == 1
        assert conversations[0].channel == "website"
        assert conversations[0].customer_id == identities[0].customer_id

        messages = db.query(Message).filter(Message.conversation_id == conversations[0].id).all()
        assert len(messages) == 2  # customer + agent


def test_continuing_with_the_real_session_token_reuses_the_same_conversation(business):
    first = client.post(f"/api/v1/widget/{business}/messages", json={"content": "Hello"})
    token = first.json()["session_token"]

    second = client.post(f"/api/v1/widget/{business}/messages", json={"session_token": token, "content": "Are you open Sundays?"})
    assert second.status_code == 200, second.text
    assert second.json()["session_token"] == token  # same token echoed back

    with SessionLocal() as db:
        conversations = db.query(Conversation).filter(Conversation.business_id == uuid.UUID(business)).all()
        assert len(conversations) == 1  # NOT a second conversation
        messages = db.query(Message).filter(Message.conversation_id == conversations[0].id).all()
        assert len(messages) == 4  # 2 customer + 2 agent, same conversation


def test_guessed_or_foreign_session_token_silently_starts_a_fresh_session_never_someone_elses(business):
    real = client.post(f"/api/v1/widget/{business}/messages", json={"content": "My real message"})
    real_token = real.json()["session_token"]

    guessed_token = "totally-made-up-token-" + uuid.uuid4().hex
    guessed = client.post(f"/api/v1/widget/{business}/messages", json={"session_token": guessed_token, "content": "Trying to guess a token"})
    assert guessed.status_code == 200, guessed.text
    guessed_response_token = guessed.json()["session_token"]

    # Never silently attached to the real visitor's session, and never echoes
    # the attacker's own guessed string back either.
    assert guessed_response_token != real_token
    assert guessed_response_token != guessed_token

    with SessionLocal() as db:
        conversations = db.query(Conversation).filter(Conversation.business_id == uuid.UUID(business)).all()
        assert len(conversations) == 2  # two genuinely separate conversations
        customer_ids = {c.customer_id for c in conversations}
        assert len(customer_ids) == 2  # two genuinely separate customers


def test_cross_business_token_replay_never_reaches_the_other_businesss_conversation(business):
    email_b = _unique_email("widget-owner-b")
    resp_b = client.post(
        "/api/v1/auth/register",
        json={"business_name": "Widget Test Biz B", "timezone": "UTC", "email": email_b, "password": "correcthorse1"},
    )
    business_b = resp_b.json()["business_id"]
    try:
        a_resp = client.post(f"/api/v1/widget/{business}/messages", json={"content": "Hello from A"})
        token_from_a = a_resp.json()["session_token"]

        replay = client.post(f"/api/v1/widget/{business_b}/messages", json={"session_token": token_from_a, "content": "Replayed token"})
        assert replay.status_code == 200, replay.text
        replay_token = replay.json()["session_token"]
        assert replay_token != token_from_a  # never accepted as-is on a different business

        with SessionLocal() as db:
            conv_a = db.query(Conversation).filter(Conversation.business_id == uuid.UUID(business)).all()
            conv_b = db.query(Conversation).filter(Conversation.business_id == uuid.UUID(business_b)).all()
            assert len(conv_a) == 1
            assert len(conv_b) == 1
            assert conv_a[0].customer_id != conv_b[0].customer_id
    finally:
        with SessionLocal() as db:
            b = db.get(Business, uuid.UUID(business_b))
            if b is not None:
                db.delete(b)
            db.commit()


def test_business_id_that_does_not_exist_returns_a_plain_404():
    resp = client.post(f"/api/v1/widget/{uuid.uuid4()}/messages", json={"content": "hello?"})
    assert resp.status_code == 404, resp.text
    assert resp.json()["error"]["type"] == "not_found"


def test_ip_rate_limit_is_real_and_returns_429(business):
    statuses = []
    for i in range(WIDGET_IP_MAX_ATTEMPTS + 5):
        # each message uses its own fresh (no-token) request so this exercises
        # the IP limiter, not the session limiter
        resp = client.post(f"/api/v1/widget/{business}/messages", json={"content": f"message {i}"})
        statuses.append(resp.status_code)

    assert statuses[:WIDGET_IP_MAX_ATTEMPTS] == [200] * WIDGET_IP_MAX_ATTEMPTS
    assert all(s == 429 for s in statuses[WIDGET_IP_MAX_ATTEMPTS:])


def test_session_rate_limit_is_real_and_returns_429(business):
    first = client.post(f"/api/v1/widget/{business}/messages", json={"content": "start"})
    token = first.json()["session_token"]

    statuses = [first.status_code]
    for i in range(WIDGET_SESSION_MAX_ATTEMPTS + 5):
        resp = client.post(f"/api/v1/widget/{business}/messages", json={"session_token": token, "content": f"message {i}"})
        statuses.append(resp.status_code)

    assert statuses[:WIDGET_SESSION_MAX_ATTEMPTS] == [200] * WIDGET_SESSION_MAX_ATTEMPTS
    assert 429 in statuses[WIDGET_SESSION_MAX_ATTEMPTS:]


def test_widget_config_returns_real_default_branding(business):
    resp = client.get(f"/api/v1/widget/{business}/config")
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["name"] == "Widget Test Biz"
    assert body["brand_color"] == "#2563eb"  # the real DB default, not hardcoded in this test's expectation alone
    assert body["logo_url"] is None


def test_widget_config_reflects_a_real_profile_update(business):
    with SessionLocal() as db:
        b = db.get(Business, uuid.UUID(business))
        b.brand_color = "#16a34a"
        b.logo_url = "https://example.com/logo.png"
        db.commit()

    resp = client.get(f"/api/v1/widget/{business}/config")
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["brand_color"] == "#16a34a"
    assert body["logo_url"] == "https://example.com/logo.png"


def test_widget_config_never_leaks_another_businesss_branding(business):
    email_b = _unique_email("widget-owner-branding-b")
    resp_b = client.post(
        "/api/v1/auth/register",
        json={"business_name": "Widget Branding Biz B", "timezone": "UTC", "email": email_b, "password": "correcthorse1"},
    )
    business_b = resp_b.json()["business_id"]
    try:
        with SessionLocal() as db:
            a = db.get(Business, uuid.UUID(business))
            a.brand_color = "#ff0000"
            db.commit()

        resp = client.get(f"/api/v1/widget/{business_b}/config")
        assert resp.status_code == 200, resp.text
        assert resp.json()["brand_color"] != "#ff0000"
        assert resp.json()["name"] == "Widget Branding Biz B"
    finally:
        with SessionLocal() as db:
            b = db.get(Business, uuid.UUID(business_b))
            if b is not None:
                db.delete(b)
            db.commit()


def test_widget_config_business_id_that_does_not_exist_returns_a_plain_404():
    resp = client.get(f"/api/v1/widget/{uuid.uuid4()}/config")
    assert resp.status_code == 404, resp.text
    assert resp.json()["error"]["type"] == "not_found"


def test_widget_js_serves_real_file_referencing_data_business_id():
    resp = client.get("/widget.js")
    assert resp.status_code == 200
    assert "javascript" in resp.headers["content-type"]
    body = resp.text
    assert "data-business-id" in body
    assert "/api/v1/widget/" in body
    assert "session_token" in body


def test_cors_headers_present_on_widget_endpoints_but_not_elsewhere(business):
    preflight = client.options(
        f"/api/v1/widget/{business}/messages",
        headers={"Origin": "https://some-random-business-website.example", "Access-Control-Request-Method": "POST"},
    )
    assert preflight.headers.get("access-control-allow-origin") == "*"

    js_resp = client.get("/widget.js", headers={"Origin": "https://some-random-business-website.example"})
    assert js_resp.headers.get("access-control-allow-origin") == "*"

    config_resp = client.get(
        f"/api/v1/widget/{business}/config", headers={"Origin": "https://some-random-business-website.example"}
    )
    assert config_resp.headers.get("access-control-allow-origin") == "*"

    health_resp = client.get("/api/v1/health", headers={"Origin": "https://some-random-business-website.example"})
    assert "access-control-allow-origin" not in {k.lower() for k in health_resp.headers.keys()}
