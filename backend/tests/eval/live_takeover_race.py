"""Live proof: a staff claim fired INTO the window between the AI's final takeover check and its reply being sent.
Needs tests/eval/live_race_server.py running on :8001 (slow outbound send). Throwaway tenant, fake WhatsApp number.

    docker exec -e PYTHONPATH=/app night_guard_ai-backend-1 python tests/eval/live_takeover_race.py
"""
import threading
import time
import uuid

import httpx

import tests.eval.live_takeover as lt
from app.db.database import SessionLocal
from app.db.models.business import Business
from app.db.models.conversation import Conversation, Message

lt.BASE = "http://127.0.0.1:8001"
t0 = time.perf_counter()


def stamp(msg: str) -> None:
    print(f"  [{time.perf_counter() - t0:6.2f}s] {msg}")


def main() -> None:
    business_id, token, pnid = lt.setup()
    try:
        stamp("baseline turn (the AI answers; its send takes ~5s)")
        lt.webhook(pnid, "Hello, are you open on Saturdays?")
        cid = lt.conversation_id(business_id)
        n_agent_before = sum(1 for m in lt.transcript(business_id) if m.startswith("agent"))

        result = {}
        stamp("message 2 -> real LLM turn starts")
        th = threading.Thread(target=lambda: result.update(secs=lt.webhook(pnid, "Do you do teeth whitening, and how much?")))
        th.start()
        # The AI persists its reply INSIDE the lock, right before the (slow) send: seeing a 2nd agent row = "past the final check".
        while True:
            with SessionLocal() as db:
                n_agent = db.query(Message).filter(Message.conversation_id == cid, Message.sender_type == "AGENT").count()
            if n_agent > n_agent_before:
                break
            time.sleep(0.05)
        stamp("AI reply persisted, its send is in flight (past the final takeover check) -> firing the staff claim NOW")
        claim_start = time.perf_counter()
        claim = lt.api(token, f"/inbox/conversations/{cid}/takeover")
        claim_secs = time.perf_counter() - claim_start
        stamp(f"claim answered after {claim_secs:.1f}s -> active={claim['active']}")
        th.join()
        stamp(f"webhook 2 finished ({result['secs']:.1f}s total)")

        with SessionLocal() as db:
            rows = db.query(Message).filter_by(conversation_id=cid).order_by(Message.created_at).all()
            print("  messages:")
            for m in rows:
                print(f"    {m.sender_type.value:8} status={m.delivery_status!s:9} detail={m.delivery_detail!s:22} {m.content[:50]!r}")
        stamp("message 3 (after the claim) -> must be silent")
        secs = lt.webhook(pnid, "hello? anyone there?")
        stamp(f"webhook 3 returned in {secs:.2f}s (no LLM, no send)")
        n_agent_end = sum(1 for m in lt.transcript(business_id) if m.startswith("agent"))
        print(f"  agent messages: before={n_agent_before} after-turn-2={n_agent_before + 1} final={n_agent_end} (expect final == after-turn-2)")
    finally:
        with SessionLocal() as db:
            b = db.get(Business, business_id)
            if b is not None:
                db.delete(b)
            db.commit()


main()
