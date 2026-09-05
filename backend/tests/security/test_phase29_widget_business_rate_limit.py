"""Phase 29 — TIER 1 ITEM 5 fix verification, live against the real running
app (not the isolated RateLimiter objects in
test_phase29_widget_distributed_flood.py — this hits the actual HTTP route).

Proves the new widget_business_rate_limiter in app/core/rate_limit.py
actually engages on real requests. LLM/embedding providers are stubbed
(same discipline as tests/integration/test_widget.py) — this test is about
rate-limiter wiring, not LLM behavior, and 210 real Azure calls would be slow
and costly for zero additional signal."""

import json as jsonlib
import uuid

import pytest
from fastapi.testclient import TestClient

import app.api.routes.widget as widget_module
from app.core.rate_limit import WIDGET_BUSINESS_MAX_ATTEMPTS, WIDGET_WINDOW_SECONDS, RateLimiter
from app.db.database import SessionLocal
from app.db.models.business import Business
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
def _fresh_business_rate_limiter(monkeypatch):
    """Process-wide singleton — fresh instance per test so this test's budget
    never leaks into/from any other test."""
    fresh = RateLimiter(max_attempts=WIDGET_BUSINESS_MAX_ATTEMPTS, window_seconds=WIDGET_WINDOW_SECONDS)
    monkeypatch.setattr(widget_module, "widget_business_rate_limiter", fresh)
    return fresh


@pytest.fixture
def business():
    resp = client.post(
        "/api/v1/auth/register",
        json={
            "business_name": "Rate Limit Fix Co",
            "timezone": "UTC",
            "email": f"ratelimit-{uuid.uuid4().hex[:10]}@example.com",
            "password": "correcthorse1",
        },
    )
    assert resp.status_code == 201, resp.text
    business_id = resp.json()["business_id"]
    yield business_id
    with SessionLocal() as db:
        b = db.get(Business, uuid.UUID(business_id))
        if b is not None:
            db.delete(b)
        db.commit()


def test_business_wide_limit_engages_even_with_a_distinct_session_per_request(
    business, monkeypatch, _fresh_business_rate_limiter
):
    """Every request below uses a BRAND NEW session (no session_token sent,
    so widget_service mints a fresh one each time — confirmed real behavior
    in test_widget.py) — the realistic "no token persistence" shape of a
    hostile third-party page's hidden fetch(). The per-IP limiter is
    bypassed here (monkeypatched to never block) to isolate the NEW
    business-wide limiter specifically; the real-world equivalent of "many
    IPs" is proven mathematically against the real limiter class in
    test_phase29_widget_distributed_flood.py. This test is the live-HTTP
    complement: real requests through TestClient against the real running
    app, real route code, real DB writes — everything except the source IP
    is exactly production behavior."""
    from app.core.rate_limit import widget_ip_rate_limiter

    monkeypatch.setattr(widget_ip_rate_limiter, "is_blocked", lambda key: False)

    results = []
    for i in range(WIDGET_BUSINESS_MAX_ATTEMPTS + 10):
        resp = client.post(f"/api/v1/widget/{business}/messages", json={"content": f"flood message {i}"})
        results.append(resp.status_code)

    ok_count = results.count(200)
    blocked_count = results.count(429)

    print(
        f"\n=== TIER 1 ITEM 5 FIX VERIFICATION — LIVE HTTP ===\n"
        f"{len(results)} requests, each with a brand-new session (no token reuse), IP limiter "
        f"bypassed to isolate the business-wide check, against ONE business_id: {ok_count} "
        f"succeeded, {blocked_count} blocked with 429 once the business-wide ceiling "
        f"({WIDGET_BUSINESS_MAX_ATTEMPTS}/{WIDGET_WINDOW_SECONDS}s) was hit."
    )
    assert blocked_count > 0, (
        "SECURITY FAILURE — the per-business_id limiter did not engage; a distributed "
        f"flood with a fresh session per request was NOT throttled. Status codes: {results}"
    )
    assert ok_count <= WIDGET_BUSINESS_MAX_ATTEMPTS
    assert results[-1] == 429, "the request right after the ceiling was crossed should still be blocked"
