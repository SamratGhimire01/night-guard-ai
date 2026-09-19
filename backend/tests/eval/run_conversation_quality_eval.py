"""Runner for the fixed conversation-quality eval set (conversation_quality_
cases.py). Real DB, real Azure LLM — deliberately NOT pytest, NOT run in CI,
same reason Phase 6/7/9's real-API tests are never auto-run: it costs real
money and time, and response quality is judged by a human, not asserted.

Usage (inside the backend container, against a real business already in the
DB — defaults to "Samaj Dental Clinic", the same real business this whole
project's live testing has used throughout):

    python -m tests.eval.run_conversation_quality_eval [business name]

Each case runs in a fresh, throwaway conversation/customer that this script
creates and deletes itself — real reproduction artifacts only, never left
behind as fake customer traffic (same discipline as every other live
verification script in this project).
"""

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

from tests.eval.conversation_quality_cases import CASES


def _run_case(db, business, case: dict) -> None:
    # Contact info already on file (a returning-customer shape) so cases that
    # exercise booking/availability/cancellation reach the real flow instead
    # of stalling at the contact-info gate — most real transcripts this eval
    # set is seeded from already had a phone/email by this point too.
    customer = Customer(business_id=business.id, name="Website Visitor", phone="9800000000")
    db.add(customer)
    db.flush()
    conversation = Conversation(business_id=business.id, customer_id=customer.id, channel="website", status="open")
    db.add(conversation)
    db.commit()

    print(f"\n{'=' * 78}\n[{case['id']}] ({case['category']})\n{'=' * 78}")
    if case.get("real_before"):
        print(f"REAL BEFORE: {case['real_before']}\n")

    try:
        for turn in case["turns"]:
            result = handle_incoming_message(
                db, conversation_id=conversation.id, business_id=business.id, content=turn
            )
            print(f"CUSTOMER: {turn}")
            print(f"AGENT:    {result['response'] if result else '(no result)'}")
    finally:
        db.rollback()  # discard anything left half-applied by a mid-case exception
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

    print("\nCHECK FOR (human review, not asserted):")
    for item in case["check_for"]:
        print(f"  - {item}")


def main() -> None:
    business_name = sys.argv[1] if len(sys.argv) > 1 else "Samaj Dental Clinic"
    db = SessionLocal()
    business = db.query(Business).filter(Business.name == business_name).first()
    if business is None:
        print(f"No business named {business_name!r} found — pass a real business name as argv[1].")
        raise SystemExit(1)
    service_service.list_services(db, business_id=business.id)  # fail fast if the business has none configured

    for case in CASES:
        _run_case(db, business, case)


if __name__ == "__main__":
    main()
