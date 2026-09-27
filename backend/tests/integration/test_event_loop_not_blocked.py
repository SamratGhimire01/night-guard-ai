"""Phase 52 stage 1 — a slow conversation turn must not freeze the server.

The three Meta webhook handlers (and the knowledge upload) are `async def`; they used to call blocking work (embedding +
LLM + urllib send, seconds long) directly, which stalls the single event loop, so EVERY other request in the process
waited for the turn. Each test starts a deliberately slow (blocking `time.sleep`) handler body in flight, then proves an
unrelated request is answered promptly while it is still running. Real crypto for the signatures; nothing external.
"""

import asyncio
import hashlib
import hmac
import json
import time
import uuid

import httpx
import pytest
from fastapi.testclient import TestClient

from app.core.config import settings
from app.main import app

SLOW_SECONDS = 1.5
PAUSE = 0.3
MAX_LOOP_DELAY_SECONDS = 0.5  # extra delay tolerated; a blocked loop adds ~SLOW_SECONDS


def _sig(secret: str, raw: bytes) -> str:
    return "sha256=" + hmac.new(secret.encode(), raw, hashlib.sha256).hexdigest()


async def _health_latency_while_in_flight(slow_request) -> tuple[float, float]:
    """Returns (extra_delay, slow_request_total). `slow_request(client)` is the coroutine that hits the slow route.

    extra_delay = how much LONGER than its nominal PAUSE a sleep + a /health round trip took while the slow handler was in
    flight. It is measured from BEFORE the sleep on purpose: a handler that blocks the loop does so right when it starts
    (during the sleep), so timing only the health call afterwards would miss it."""
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
        started = time.perf_counter()
        slow = asyncio.create_task(slow_request(client))
        await asyncio.sleep(PAUSE)  # the slow handler starts running (and, if it blocks the loop, freezes it) here
        resp = await client.get("/api/v1/health")
        extra_delay = time.perf_counter() - started - PAUSE
        assert resp.status_code == 200
        result = await slow
        assert result.status_code in (200, 201), result.text
        return extra_delay, time.perf_counter() - started


@pytest.mark.parametrize(
    ("channel", "patch_name", "secret_attr"),
    [
        ("whatsapp", "process_webhook_payload", "whatsapp_app_secret"),
        ("messenger", "process_messenger_webhook_payload", "messenger_app_secret"),
        ("instagram", "process_instagram_webhook_payload", "instagram_app_secret"),
    ],
)
def test_slow_webhook_turn_does_not_block_other_requests(monkeypatch, channel, patch_name, secret_attr):
    import app.api.routes.webhooks as webhooks_module

    def slow_process(db, payload):
        time.sleep(SLOW_SECONDS)  # stands in for the blocking embed + LLM + send
        return []

    monkeypatch.setattr(webhooks_module, patch_name, slow_process)
    raw = json.dumps({"object": "x", "entry": []}).encode()
    headers = {"content-type": "application/json", "x-hub-signature-256": _sig(getattr(settings, secret_attr), raw)}

    async def slow_request(client):
        return await client.post(f"/api/v1/webhooks/{channel}", content=raw, headers=headers)

    health, total = asyncio.run(_health_latency_while_in_flight(slow_request))
    assert total >= SLOW_SECONDS  # the slow handler really did run its blocking body to completion
    assert health < MAX_LOOP_DELAY_SECONDS, f"event loop stalled {health:.2f}s by a {channel} webhook turn"


def test_slow_knowledge_upload_does_not_block_other_requests(monkeypatch):
    from app.services import knowledge_service

    email = f"loop-{uuid.uuid4().hex[:8]}@example.com"
    reg = TestClient(app).post(
        "/api/v1/auth/register",
        json={"business_name": "Loop Test Biz", "timezone": "UTC", "email": email, "password": "correcthorse1"},
    )
    assert reg.status_code == 201, reg.text
    token = TestClient(app).post("/api/v1/auth/login", json={"email": email, "password": "correcthorse1"}).json()[
        "access_token"
    ]

    real_create = knowledge_service.create_document

    def slow_create(db, **kwargs):
        time.sleep(SLOW_SECONDS)  # stands in for the embedding calls
        return real_create(db, **kwargs)

    monkeypatch.setattr(knowledge_service, "create_document", slow_create)
    # the real create_document embeds via the provider — stub it out like every other knowledge test
    class _Embed:
        def embed(self, texts):
            return [[0.01] * 1536 for _ in texts]

    monkeypatch.setattr(knowledge_service, "get_embedding_provider", lambda: _Embed())

    async def slow_request(client):
        return await client.post(
            "/api/v1/knowledge/upload",
            files={"file": ("faq.txt", b"We are open Monday to Friday.", "text/plain")},
            headers={"Authorization": f"Bearer {token}"},
        )

    try:
        health, total = asyncio.run(_health_latency_while_in_flight(slow_request))
        assert total >= SLOW_SECONDS
        assert health < MAX_LOOP_DELAY_SECONDS, f"event loop stalled {health:.2f}s by a knowledge upload"
    finally:
        from app.db.database import SessionLocal
        from app.db.models.business import Business

        with SessionLocal() as db:
            for b in db.query(Business).filter(Business.name == "Loop Test Biz"):
                db.delete(b)
            db.commit()
