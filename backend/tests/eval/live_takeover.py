"""Live proof for human takeover (Phase 52, stage 2) against the REAL running server and the REAL Azure LLM.

    docker exec -e PYTHONPATH=/app night_guard_ai-backend-1 python tests/eval/live_takeover.py adversarial
    docker exec -e PYTHONPATH=/app night_guard_ai-backend-1 python tests/eval/live_takeover.py expiry

Both use a throwaway tenant + a fake WhatsApp number (Meta rejects sends to it: harmless) and delete the tenant afterwards.

adversarial: the customer's 2nd WhatsApp message starts a real (~6 s) LLM turn; 2.5 s in, while the LLM call is running, a
    staff member claims the conversation over the real HTTP API. Expected: the AI's finished draft is discarded — the
    customer message is stored, NO agent message exists for it, nothing is sent. Then hand-back -> the AI answers again.
expiry: run against a server started with HUMAN_TAKEOVER_SECONDS=20 (short-interval-then-revert, same technique as the
    reminder scheduler). Claim -> AI silent -> after the window lapses with no action, the AI answers again by itself.
"""

import hashlib
import hmac
import json
import sys
import threading
import time
import uuid
from datetime import datetime, timezone

import httpx

from app.core.config import settings
from app.db.database import SessionLocal
from app.db.models.business import Business
from app.db.models.conversation import Conversation, Message
from app.db.models.integration import Integration

BASE = "http://127.0.0.1:8000"
WA_ID = "0000000000"


def setup() -> tuple[uuid.UUID, str, str]:
    email = f"takeover-probe-{uuid.uuid4().hex[:8]}@example.com"
    r = httpx.post(
        f"{BASE}/api/v1/auth/register",
        json={"business_name": "Takeover Probe Biz", "timezone": "UTC", "email": email, "password": "correcthorse1"},
    )
    r.raise_for_status()
    business_id = uuid.UUID(r.json()["business_id"])
    token = httpx.post(f"{BASE}/api/v1/auth/login", json={"email": email, "password": "correcthorse1"}).json()["access_token"]
    pnid = f"probe-{uuid.uuid4().hex[:10]}"
    with SessionLocal() as db:
        db.add(Integration(business_id=business_id, type="whatsapp", config={"phone_number_id": pnid}, enabled=True))
        db.commit()
    return business_id, token, pnid


def webhook(pnid: str, text: str) -> float:
    payload = {"object": "whatsapp_business_account", "entry": [{"id": "W", "changes": [{"field": "messages", "value": {
        "messaging_product": "whatsapp", "metadata": {"display_phone_number": "1", "phone_number_id": pnid},
        "contacts": [{"profile": {"name": "Probe"}, "wa_id": WA_ID}],
        "messages": [{"from": WA_ID, "id": f"wamid.probe{uuid.uuid4().hex}", "timestamp": "1",
                      "text": {"body": text}, "type": "text"}]}}]}]}
    raw = json.dumps(payload).encode()
    sig = "sha256=" + hmac.new(settings.whatsapp_app_secret.encode(), raw, hashlib.sha256).hexdigest()
    t0 = time.perf_counter()
    r = httpx.post(f"{BASE}/api/v1/webhooks/whatsapp", content=raw, timeout=120,
                   headers={"content-type": "application/json", "x-hub-signature-256": sig})
    r.raise_for_status()
    return time.perf_counter() - t0


def transcript(business_id: uuid.UUID) -> list[str]:
    with SessionLocal() as db:
        conv = db.query(Conversation).filter_by(business_id=business_id).order_by(Conversation.created_at).first()
        rows = db.query(Message).filter_by(conversation_id=conv.id).order_by(Message.created_at).all()
        return [f"{m.sender_type.value:8} intent={m.detected_intent!s:17} {m.content[:70]!r}" for m in rows]


def conversation_id(business_id: uuid.UUID) -> uuid.UUID:
    with SessionLocal() as db:
        return db.query(Conversation).filter_by(business_id=business_id).first().id


def api(token: str, path: str) -> dict:
    r = httpx.post(f"{BASE}/api/v1{path}", headers={"Authorization": f"Bearer {token}"}, timeout=60)
    r.raise_for_status()
    return r.json()


def show(title: str, business_id: uuid.UUID) -> None:
    print(f"--- {title}")
    for line in transcript(business_id):
        print("   ", line)


def adversarial(business_id, token, pnid) -> None:
    print(f"webhook 1 (baseline) took {webhook(pnid, 'Hi, what are your opening hours?'):.1f}s")
    cid = conversation_id(business_id)
    result = {}
    th = threading.Thread(target=lambda: result.update(secs=webhook(pnid, "Do you do teeth whitening, and how much is it?")))
    th.start()
    time.sleep(2.5)  # inside the LLM call (embed ~0.8s, then the ~5s chat call)
    claim = api(token, f"/inbox/conversations/{cid}/takeover")
    print(f"staff claimed at +2.5s, mid-LLM-call -> active={claim['active']} until={claim['until']}")
    th.join()
    print(f"webhook 2 (real LLM turn, takeover landed mid-call) finished after {result['secs']:.1f}s")
    show("transcript after the adversarial turn (expect: NO agent message after the 2nd customer message)", business_id)
    time.sleep(0)
    api(token, f"/inbox/conversations/{cid}/release")
    print(f"released; webhook 3 took {webhook(pnid, 'ok thanks, and do you take walk-ins?'):.1f}s")
    show("transcript after hand-back (expect: the AI answers message 3)", business_id)


def expiry(business_id, token, pnid) -> None:
    print(f"server window = HUMAN_TAKEOVER_SECONDS -> check below; webhook 1 took {webhook(pnid, 'Hello!'):.1f}s")
    cid = conversation_id(business_id)
    claim = api(token, f"/inbox/conversations/{cid}/takeover")
    until = datetime.fromisoformat(claim["until"])
    window = (until - datetime.now(timezone.utc)).total_seconds()
    print(f"claimed; window remaining = {window:.1f}s")
    print(f"customer writes during takeover -> webhook returned in {webhook(pnid, 'Are you there?'):.2f}s (no LLM call)")
    wait = (until - datetime.now(timezone.utc)).total_seconds() + 1.5
    print(f"doing nothing for {wait:.1f}s (staff walked away)...")
    time.sleep(max(wait, 0))
    print(f"customer writes after expiry -> webhook took {webhook(pnid, 'Hello again, are you open today?'):.1f}s (LLM turn)")
    show("transcript (expect: silent during the window, AI answer after it lapsed by itself)", business_id)


def main() -> int:
    mode = sys.argv[1] if len(sys.argv) > 1 else "adversarial"
    business_id, token, pnid = setup()
    try:
        {"adversarial": adversarial, "expiry": expiry}[mode](business_id, token, pnid)
        return 0
    finally:
        with SessionLocal() as db:
            b = db.get(Business, business_id)
            if b is not None:
                db.delete(b)
            db.commit()


if __name__ == "__main__":
    sys.exit(main())
