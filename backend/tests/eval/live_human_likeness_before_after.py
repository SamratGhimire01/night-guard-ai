"""Phase 3 (cut down) — before/after human-likeness eval.

Real DB, real Azure LLM — same discipline as run_conversation_quality_eval.py
(deliberately NOT pytest, NOT run in CI, costs real money/time). Read-only
against the live system: no schema change, no new persistent flag. "Before"
(style_checks + style exemplar retrieval + persona injection all disabled)
is produced by monkeypatching the three real functions for the duration of
that one call — nothing is reverted in the working tree, nothing committed.

Usage (inside the backend container):

    python -m tests.eval.live_human_likeness_before_after [--json out.json]

For each case in human_likeness_cases.CASES: runs the customer's message
into a fresh, empty, throwaway conversation twice (once "before", once
"after"), in independent conversations so neither run's language lock or
LLM context can leak into the other. Both conversation/customer rows are
created and deleted by this script itself, same as every other live eval
here. Then asks a FRESH Azure call (no conversation context, blind to which
reply is which, random A/B order per case) to score each reply 1-5 on
"sounds like a real human receptionist, not a bot". A handful of cases are
judged twice (identical input) to sanity-check the judge itself is
consistent, reported honestly rather than trusted blindly.
"""

import json
import random
import re
import sys
from statistics import mean
from unittest.mock import patch

from app.db.database import SessionLocal
from app.db.models.appointment import Appointment
from app.db.models.business import Business
from app.db.models.conversation import Conversation, Message
from app.db.models.customer import Customer
from app.db.models.follow_up import FollowUp
from app.db.models.handoff import HumanHandoff
from app.db.models.notification import Notification
from app.db.models.payment import Payment
from app.llm.azure_openai import AzureChatProvider
from app.services.conversation.orchestrator import handle_incoming_message

from tests.eval.human_likeness_cases import CASES

# Every 6th case also gets judged a second time (same A/B order, same
# prompt) purely to check the judge's own consistency -- not part of the
# real before/after comparison.
RELIABILITY_RECHECK_STRIDE = 6

_JUDGE_SYSTEM_PROMPT = (
    "You are evaluating customer-service chat replies for one thing only: does this read like a "
    "real, attentive human receptionist wrote it, not a generic/scripted chatbot? You are shown the "
    "customer's message and two candidate replies, labeled A and B, in no particular order -- you "
    "are not told which system produced which, and must judge purely on how the text reads. Score "
    "EACH reply independently, 1-5 (5 = genuinely sounds like a thoughtful human on the other end, "
    "1 = obviously robotic/scripted), with one short sentence of reason for each. "
    'Respond with ONLY a JSON object of this exact shape, nothing else: '
    '{"reply_a": {"score": <1-5 integer>, "reason": "..."}, '
    '"reply_b": {"score": <1-5 integer>, "reason": "..."}}'
)

_JSON_OBJECT_RE = re.compile(r"\{.*\}", re.DOTALL)


def _judge(customer_message: str, reply_a: str, reply_b: str) -> dict:
    messages = [
        {"role": "system", "content": _JUDGE_SYSTEM_PROMPT},
        {
            "role": "user",
            "content": f"Customer message:\n{customer_message}\n\nReply A:\n{reply_a}\n\nReply B:\n{reply_b}",
        },
    ]
    raw = AzureChatProvider().chat(messages)
    match = _JSON_OBJECT_RE.search(raw)
    if not match:
        raise ValueError(f"Judge did not return JSON: {raw!r}")
    return json.loads(match.group(0))


def _new_conversation(db, business: Business) -> tuple[Customer, Conversation]:
    # Contact info already on file, same reasoning as run_conversation_quality_eval.py: keeps
    # booking-intent cases from stalling at the contact-info gate instead of drafting a real reply.
    customer = Customer(business_id=business.id, name="Website Visitor", phone="9800000000")
    db.add(customer)
    db.flush()
    conversation = Conversation(business_id=business.id, customer_id=customer.id, channel="website", status="open")
    db.add(conversation)
    db.commit()
    return customer, conversation


def _cleanup(db, customer: Customer, conversation: Conversation) -> None:
    db.rollback()  # discard anything left half-applied by a mid-call exception
    appt_ids = [a.id for a in db.query(Appointment).filter(Appointment.customer_id == customer.id).all()]
    if appt_ids:
        db.query(Notification).filter(Notification.appointment_id.in_(appt_ids)).delete(synchronize_session=False)
        db.query(Payment).filter(Payment.appointment_id.in_(appt_ids)).delete(synchronize_session=False)
    db.query(Appointment).filter(Appointment.customer_id == customer.id).delete(synchronize_session=False)
    db.query(HumanHandoff).filter(HumanHandoff.conversation_id == conversation.id).delete(synchronize_session=False)
    db.query(FollowUp).filter(FollowUp.conversation_id == conversation.id).delete(synchronize_session=False)
    db.query(Message).filter(Message.conversation_id == conversation.id).delete(synchronize_session=False)
    db.delete(conversation)
    db.delete(customer)
    db.commit()


def _run_one(db, business: Business, content: str) -> tuple[str, str | None, str | None]:
    """Returns (reply, intent, detected_language) from one fresh throwaway conversation."""
    customer, conversation = _new_conversation(db, business)
    try:
        result = handle_incoming_message(
            db, conversation_id=conversation.id, business_id=business.id, content=content
        )
        reply = (result or {}).get("response") or "(no result)"
        intent = (result or {}).get("intent")
        intent = intent.value if hasattr(intent, "value") else intent
        db.refresh(conversation)
        language = conversation.detected_language
    finally:
        _cleanup(db, customer, conversation)
    return reply, intent, language


def _run_after(db, business: Business, content: str) -> tuple[str, str | None, str | None]:
    return _run_one(db, business, content)


def _run_before(db, business: Business, content: str) -> tuple[str, str | None, str | None]:
    # Phase 1+2 features disabled for the duration of this one call only -- nothing reverted in
    # the working tree, nothing committed. See module docstring.
    with (
        patch("app.services.conversation.intent._persona_name_note", new=lambda business=None: ""),
        patch("app.services.style_exemplar_service.retrieve", new=lambda *a, **k: []),
        patch("app.services.conversation.orchestrator.check_response_style", new=lambda *a, **k: []),
    ):
        return _run_one(db, business, content)


def main() -> None:
    args = sys.argv[1:]
    json_out = None
    if "--json" in args:
        idx = args.index("--json")
        json_out = args[idx + 1]
    cases = CASES
    if "--cases" in args:  # comma-separated case ids, e.g. to re-run only the regressed ones
        wanted = set(args[args.index("--cases") + 1].split(","))
        cases = [c for c in CASES if c["id"] in wanted]

    db = SessionLocal()
    businesses = {b.name: b for b in db.query(Business).all() if b.name in {c["business"] for c in CASES}}
    missing = {c["business"] for c in CASES} - set(businesses)
    if missing:
        print(f"Missing businesses in DB, aborting: {missing}")
        raise SystemExit(1)

    records = []
    for i, case in enumerate(cases):
        business = businesses[case["business"]]
        print(f"[{i + 1}/{len(cases)}] {case['id']} ({business.name}): {case['message']!r}")

        before_reply, _, _ = _run_before(db, business, case["message"])
        after_reply, intent, language = _run_after(db, business, case["message"])

        a_is_before = random.random() < 0.5
        reply_a, reply_b = (before_reply, after_reply) if a_is_before else (after_reply, before_reply)
        judged = _judge(case["message"], reply_a, reply_b)
        before_score, after_score = (
            (judged["reply_a"]["score"], judged["reply_b"]["score"])
            if a_is_before
            else (judged["reply_b"]["score"], judged["reply_a"]["score"])
        )

        rerun = None
        if i % RELIABILITY_RECHECK_STRIDE == 0:
            rejudged = _judge(case["message"], reply_a, reply_b)
            rerun = {
                "reply_a_score_delta": rejudged["reply_a"]["score"] - judged["reply_a"]["score"],
                "reply_b_score_delta": rejudged["reply_b"]["score"] - judged["reply_b"]["score"],
            }

        records.append(
            {
                "case_id": case["id"],
                "business": business.name,
                "source": case["source"],
                "message": case["message"],
                "intent": intent,
                "language": language,
                "before_reply": before_reply,
                "after_reply": after_reply,
                "before_score": before_score,
                "after_score": after_score,
                "before_reason": (judged["reply_a"] if a_is_before else judged["reply_b"])["reason"],
                "after_reason": (judged["reply_b"] if a_is_before else judged["reply_a"])["reason"],
                "judge_reliability_recheck": rerun,
            }
        )
        if json_out:  # flush every case so a late crash doesn't lose the whole run
            with open(json_out, "w") as f:
                json.dump(records, f, indent=2, ensure_ascii=False)

    _print_report(records)
    if json_out:
        with open(json_out, "w") as f:
            json.dump(records, f, indent=2, ensure_ascii=False)
        print(f"\nWrote {len(records)} records to {json_out}")


def _print_report(records: list[dict]) -> None:
    print(f"\n{'=' * 78}\nAGGREGATE\n{'=' * 78}")
    before_all = [r["before_score"] for r in records]
    after_all = [r["after_score"] for r in records]
    print(f"before mean: {mean(before_all):.2f}  after mean: {mean(after_all):.2f}  delta: {mean(after_all) - mean(before_all):+.2f}")
    print(f"n={len(records)}")

    for label, key in (("LANGUAGE", "language"), ("INTENT", "intent")):
        print(f"\n{'-' * 78}\nBY {label}\n{'-' * 78}")
        groups = sorted({r[key] for r in records}, key=lambda x: (x is None, x))
        for g in groups:
            subset = [r for r in records if r[key] == g]
            b, a = mean(r["before_score"] for r in subset), mean(r["after_score"] for r in subset)
            print(f"  {g!s:20} n={len(subset):2}  before={b:.2f}  after={a:.2f}  delta={a - b:+.2f}")

    print(f"\n{'-' * 78}\nBIGGEST GAPS\n{'-' * 78}")
    ranked = sorted(records, key=lambda r: r["after_score"] - r["before_score"])
    print("Most REGRESSED (after < before):")
    for r in ranked[:5]:
        _print_gap(r)
    print("\nMost IMPROVED (after > before):")
    for r in ranked[-5:][::-1]:
        _print_gap(r)

    reliability_checks = [r["judge_reliability_recheck"] for r in records if r["judge_reliability_recheck"]]
    print(f"\n{'-' * 78}\nJUDGE RELIABILITY ({len(reliability_checks)} cases re-judged, identical input)\n{'-' * 78}")
    if reliability_checks:
        deltas = [abs(c["reply_a_score_delta"]) for c in reliability_checks] + [
            abs(c["reply_b_score_delta"]) for c in reliability_checks
        ]
        max_delta = max(deltas)
        print(f"max |score delta| on an identical re-judge: {max_delta}")
        if max_delta >= 2:
            print("FLAG: judge gave a >=2-point different score on an IDENTICAL input on re-judge — treat scores as noisy.")
        elif max_delta == 1:
            print("Judge is mostly but not perfectly consistent (off-by-1 on re-judge for some case).")
        else:
            print("Judge was perfectly consistent on every re-judged case.")


def _print_gap(r: dict) -> None:
    delta = r["after_score"] - r["before_score"]
    print(f"\n  [{r['case_id']}] delta={delta:+d}  before={r['before_score']} after={r['after_score']}  ({r['business']}, {r['intent']}, {r['language']})")
    print(f"    CUSTOMER: {r['message']}")
    print(f"    BEFORE ({r['before_score']}): {r['before_reply']}")
    print(f"      judge: {r['before_reason']}")
    print(f"    AFTER  ({r['after_score']}): {r['after_reply']}")
    print(f"      judge: {r['after_reason']}")


if __name__ == "__main__":
    main()
