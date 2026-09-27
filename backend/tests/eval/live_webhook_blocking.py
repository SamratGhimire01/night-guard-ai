"""Live proof for the Meta-webhook event-loop-blocking fix (Phase 52, stage 1).

Run against the REAL running server (real Azure LLM turn, real uvicorn process):
    docker exec night_guard_ai-backend-1 python tests/eval/live_webhook_blocking.py

Registers a throwaway tenant, wires a WhatsApp Integration (phone_number_id only), POSTs one correctly HMAC-signed
WhatsApp webhook (a real, multi-second LLM turn) from a background thread, and meanwhile hits GET /api/v1/health every 100 ms
from the main thread. If the webhook handler blocks the event loop, /health stalls for the whole turn; if the turn runs
in a worker thread, /health stays at a few ms. The tenant is deleted at the end.
"""

import hashlib
import hmac
import json
import statistics
import sys
import threading
import time
import uuid

import httpx

from app.core.config import settings
from app.db.database import SessionLocal
from app.db.models.business import Business
from app.db.models.integration import Integration

BASE = "http://127.0.0.1:8000"


def main() -> int:
    email = f"blocking-probe-{uuid.uuid4().hex[:8]}@example.com"
    r = httpx.post(
        f"{BASE}/api/v1/auth/register",
        json={"business_name": "Blocking Probe Biz", "timezone": "UTC", "email": email, "password": "correcthorse1"},
    )
    r.raise_for_status()
    business_id = uuid.UUID(r.json()["business_id"])
    pnid = f"probe-{uuid.uuid4().hex[:10]}"
    with SessionLocal() as db:
        db.add(Integration(business_id=business_id, type="whatsapp", config={"phone_number_id": pnid}, enabled=True))
        db.commit()

    try:
        payload = {
            "object": "whatsapp_business_account",
            "entry": [{"id": "WABA", "changes": [{"field": "messages", "value": {
                "messaging_product": "whatsapp",
                "metadata": {"display_phone_number": "1", "phone_number_id": pnid},
                "contacts": [{"profile": {"name": "Probe"}, "wa_id": "0000000000"}],
                "messages": [{"from": "0000000000", "id": f"wamid.probe{uuid.uuid4().hex}", "timestamp": "1",
                              "text": {"body": "Hi, what are your opening hours and do you offer teeth whitening?"},
                              "type": "text"}],
            }}]}],
        }
        raw = json.dumps(payload).encode()
        sig = "sha256=" + hmac.new(settings.whatsapp_app_secret.encode(), raw, hashlib.sha256).hexdigest()
        webhook = {}

        def fire():
            t0 = time.perf_counter()
            resp = httpx.post(
                f"{BASE}/api/v1/webhooks/whatsapp", content=raw, timeout=120,
                headers={"content-type": "application/json", "x-hub-signature-256": sig},
            )
            webhook["status"], webhook["secs"] = resp.status_code, time.perf_counter() - t0

        th = threading.Thread(target=fire)
        latencies = []
        th.start()
        time.sleep(0.3)  # let the webhook request reach the server first
        while th.is_alive():
            t0 = time.perf_counter()
            try:
                httpx.get(f"{BASE}/api/v1/health", timeout=60).raise_for_status()
                latencies.append(time.perf_counter() - t0)
            except Exception as exc:  # a stalled loop shows up as a timeout/very long sample
                latencies.append(time.perf_counter() - t0)
                print("health probe error:", type(exc).__name__)
            time.sleep(0.1)
        th.join()

        print(f"webhook: HTTP {webhook['status']} in {webhook['secs']:.2f}s")
        print(f"/health probes during the turn: n={len(latencies)} "
              f"median={statistics.median(latencies) * 1000:.0f}ms max={max(latencies) * 1000:.0f}ms "
              f">1s: {sum(1 for x in latencies if x > 1)}")
        return 0
    finally:
        with SessionLocal() as db:
            b = db.get(Business, business_id)
            if b is not None:
                db.delete(b)
            db.commit()


if __name__ == "__main__":
    sys.exit(main())
