"""Real end-to-end latency bench (real orchestrator + real Azure LLM + real embeddings + real DB), one FIXED set of 10 real
customer messages, each sent as the FIRST message of a fresh conversation (so no history/summarization confound), for a chosen
business. Per turn it records the orchestrator's own stage timings (embedding, knowledge search, LLM call) and the total wall
time; "compose + dispatch + persist" = total - pre-dispatch stages. Arms are interleaved (A B A B ...) so Azure drift hits both.
Cleans up every row it creates. Not collected by pytest.
  python -m tests.eval.latency_bench <effort_a> <effort_b> [rounds] [business name]      (efforts: default|minimal|low|medium|high)
"""
import logging
import statistics
import sys
import time

from app.core.config import settings
from app.db.database import SessionLocal
from app.db.models.business import Business
from app.db.models.conversation import Conversation, Message
from app.db.models.customer import Customer
from app.db.models.handoff import HumanHandoff
from app.services.conversation.orchestrator import handle_incoming_message

# 10 real customer messages (verbatim from real transcripts in this project: the 2026-09-20 live conversations, the spec-conformance
# and conversation-quality sets). Mixed language, mixed intent, all first-turn.
MESSAGES = [
    "hlo, malai teeth cleaning ko barema janna man cha",
    "kati ho price",
    "Do you have an appointment tomorrow?",
    "Actually, can you tell me what time you open on weekends?",
    "open cha?",
    "Great, can you book that for me?",
    "भोलि दाँत सफा गर्न मिल्छ?",
    "I want to cancel my appointment, I can't make it",
    "thanks!",
    "My tooth has been hurting for two days, what should I do?",
]

_STAGES = ("turn_summarize_ms", "turn_context_assembly_ms", "turn_embed_ms", "turn_knowledge_search_ms", "turn_llm_chat_ms",
           "turn_total_pre_dispatch_ms")


class _Capture(logging.Handler):
    def __init__(self):
        super().__init__()
        self.stage: dict = {}

    def emit(self, record):
        if "turn_llm_chat_ms" in record.__dict__:
            self.stage = {k: record.__dict__[k] for k in _STAGES}


def _turn(db, business, text, cap):
    customer = Customer(business_id=business.id, name="LatencyBench Visitor")
    db.add(customer)
    db.flush()
    conv = Conversation(business_id=business.id, customer_id=customer.id, channel="website", status="open")
    db.add(conv)
    db.commit()
    cap.stage = {}
    t0 = time.perf_counter()
    result = handle_incoming_message(db, conversation_id=conv.id, business_id=business.id, content=text)
    wall = (time.perf_counter() - t0) * 1000
    reply = result["response"] if result else ""
    db.query(HumanHandoff).filter(HumanHandoff.conversation_id == conv.id).delete(synchronize_session=False)
    db.query(Message).filter(Message.conversation_id == conv.id).delete(synchronize_session=False)
    db.delete(conv)
    db.delete(customer)
    db.commit()
    return wall, dict(cap.stage), reply


def main():
    a, b = sys.argv[1], sys.argv[2]
    rounds = int(sys.argv[3]) if len(sys.argv) > 3 else 2
    name = sys.argv[4] if len(sys.argv) > 4 else "Samaj Dental Clinic"
    cap = _Capture()
    logging.getLogger("app.services.conversation.orchestrator").addHandler(cap)
    logging.getLogger("app.services.conversation.orchestrator").setLevel(logging.INFO)
    db = SessionLocal()
    business = db.query(Business).filter(Business.name == name).first()
    rows = {a: [], b: []}
    for r in range(rounds):
        for i, text in enumerate(MESSAGES):
            for arm in (a, b) if (i + r) % 2 == 0 else (b, a):  # alternate which arm goes first
                settings.azure_openai_reasoning_effort = arm
                wall, stage, reply = _turn(db, business, text, cap)
                rows[arm].append({"i": i, "wall": wall, **stage, "reply": reply})
                print(f"r{r} m{i} {arm:8} wall={wall:7.0f}ms llm={stage.get('turn_llm_chat_ms', 0):7.0f}ms  {text[:38]!r}", flush=True)
    print("\n=== per-stage means over %d turns per arm (ms) ===" % len(rows[a]))
    print(f"{'stage':28}{a:>12}{b:>12}")
    for k in ("wall",) + _STAGES:
        va, vb = (statistics.mean(x[k] for x in rows[arm] if k in x) for arm in (a, b))
        print(f"{k:28}{va:>12.0f}{vb:>12.0f}")
    for arm in (a, b):
        w = sorted(x["wall"] for x in rows[arm])
        post = [x["wall"] - x["turn_total_pre_dispatch_ms"] for x in rows[arm]]
        print(f"{arm:8} wall: mean={statistics.mean(w):.0f} median={statistics.median(w):.0f} min={w[0]:.0f} max={w[-1]:.0f} "
              f"p90={w[int(0.9 * (len(w) - 1))]:.0f} | post-LLM dispatch+compose+persist mean={statistics.mean(post):.0f}ms")
    print("\n=== per-message mean wall (ms) ===")
    for i, text in enumerate(MESSAGES):
        print(f"m{i} {text[:40]!r:44}" + "".join(f"{arm}={statistics.mean(x['wall'] for x in rows[arm] if x['i'] == i):7.0f}  " for arm in (a, b)))
    print("\n=== replies (last round) ===")
    for i, text in enumerate(MESSAGES):
        for arm in (a, b):
            r = [x for x in rows[arm] if x["i"] == i][-1]
            print(f"m{i} [{arm}] {r['reply'][:160]!r}")


if __name__ == "__main__":
    main()
