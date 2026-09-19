"""Runner for the literal spec-conformance case set (spec_conformance_cases.py).
Real DB, real Azure LLM — deliberately NOT pytest, NOT CI-wired, same reason
as run_conversation_quality_eval.py. Computes real, objective metrics
(word/sentence count, ends-with-question, emoji count, banned-phrase hits)
alongside each real transcript so a human can score PASS/PARTIAL/FAIL against
the spec's own stated expectation — response naturalness itself is still read
by a human, not auto-graded.

Usage (inside the backend container):
    python -m tests.eval.run_spec_conformance_eval [business name] [case_id ...]

With no case_id args, runs every case. Pass one or more case ids to re-run
just those (used for fix-and-reverify rounds).
"""

import re
import sys

from app.db.database import SessionLocal
from app.db.models.appointment import Appointment
from app.db.models.business import Business
from app.db.models.conversation import Conversation, Message
from app.db.models.customer import Customer
from app.db.models.follow_up import FollowUp
from app.db.models.handoff import HumanHandoff
from app.db.models.notification import Notification
from app.services import service_service
from app.services.conversation.orchestrator import handle_incoming_message

from tests.eval.spec_conformance_cases import CASES, CORPORATE_PHRASES, EMOJI_SAMPLE_GROUPS

_EMOJI_RE = re.compile(
    "[\U0001F300-\U0001FAFF\U00002600-\U000027BF\U0001F1E6-\U0001F1FF]"
)
_SENTENCE_SPLIT_RE = re.compile(r"[.!?।]+")


def _metrics(text: str) -> dict:
    words = text.split()
    sentences = [s for s in _SENTENCE_SPLIT_RE.split(text) if s.strip()]
    lower = text.lower()
    hits = [p for p in CORPORATE_PHRASES if p in lower]
    return {
        "word_count": len(words),
        "sentence_count": max(len(sentences), 1),
        "ends_with_question": text.strip().endswith("?"),
        "emoji_count": len(_EMOJI_RE.findall(text)),
        "corporate_phrase_hits": hits,
    }


def _run_case(db, business, case: dict) -> dict:
    customer = Customer(business_id=business.id, name="Website Visitor")
    db.add(customer)
    db.flush()
    conversation = Conversation(business_id=business.id, customer_id=customer.id, channel="website", status="open")
    db.add(conversation)
    db.commit()

    print(f"\n{'=' * 78}\n[{case['id']}] {case['spec_ref']}\n{'=' * 78}")
    if case.get("notes"):
        print(f"NOTES: {case['notes']}\n")

    last_response = ""
    try:
        for turn in case["turns"]:
            result = handle_incoming_message(
                db, conversation_id=conversation.id, business_id=business.id, content=turn
            )
            last_response = result["response"] if result else ""
            print(f"CUSTOMER: {turn}")
            print(f"AGENT:    {last_response}")
    finally:
        db.rollback()
        db.refresh(conversation)
        appt_ids = [a.id for a in db.query(Appointment).filter(Appointment.customer_id == customer.id).all()]
        if appt_ids:
            db.query(Notification).filter(Notification.appointment_id.in_(appt_ids)).delete(synchronize_session=False)
        db.query(Appointment).filter(Appointment.customer_id == customer.id).delete(synchronize_session=False)
        db.query(HumanHandoff).filter(HumanHandoff.conversation_id == conversation.id).delete(synchronize_session=False)
        db.query(FollowUp).filter(FollowUp.conversation_id == conversation.id).delete(synchronize_session=False)
        db.query(Message).filter(Message.conversation_id == conversation.id).delete(synchronize_session=False)
        db.delete(conversation)
        db.delete(customer)
        db.commit()

    m = _metrics(last_response)
    print(
        f"\nMETRICS (final turn): words={m['word_count']} sentences={m['sentence_count']} "
        f"ends_with_question={m['ends_with_question']} emoji_count={m['emoji_count']} "
        f"corporate_phrase_hits={m['corporate_phrase_hits']}"
    )
    expect = case.get("expect", {})
    if expect:
        print(f"EXPECT: {expect}")
    return {"id": case["id"], "last_response": last_response, "metrics": m}


def main() -> None:
    args = sys.argv[1:]
    business_name = "Samaj Dental Clinic"
    case_ids = None
    if args and not args[0].startswith("sec"):
        business_name = args[0]
        args = args[1:]
    if args:
        case_ids = set(args)

    db = SessionLocal()
    business = db.query(Business).filter(Business.name == business_name).first()
    if business is None:
        print(f"No business named {business_name!r} found.")
        raise SystemExit(1)
    service_service.list_services(db, business_id=business.id)

    cases = [c for c in CASES if case_ids is None or c["id"] in case_ids]
    results = {}
    for case in cases:
        results[case["id"]] = _run_case(db, business, case)

    print(f"\n{'=' * 78}\n§23 EMOJI POLICY — real counts by spec category\n{'=' * 78}")
    for group, ids in EMOJI_SAMPLE_GROUPS.items():
        counts = [results[i]["metrics"]["emoji_count"] for i in ids if i in results]
        if counts:
            print(f"{group}: counts={counts} (n={len(counts)})")


if __name__ == "__main__":
    main()
