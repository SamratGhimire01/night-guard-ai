"""The regression suite: every real conversation (replayed) + every synthetic case,
run through the actual orchestrator (real Azure LLM, real DB, a fresh throwaway
business per case -- never a live tenant, see _provision_business) and checked
against exact, code-checkable conditions -- not "does this feel right". See
regression_cases.py for how cases/expectations are built, and PHASE_STATUS.md for
the read-through this dataset came from.

Deliberately gated behind RUN_LIVE_REGRESSION=1: same discipline as every other
file in tests/eval/ (real Azure cost per case), so a bare `pytest tests/` -- unit
and integration suites included -- never fires it by accident. Run deliberately,
before shipping a prompt/orchestrator change:

    RUN_LIVE_REGRESSION=1 pytest tests/eval/test_regression_suite.py -q
    RUN_LIVE_REGRESSION=1 pytest tests/eval/test_regression_suite.py -k syn-booking-easy-1 -q

`-n auto` (pytest-xdist) works too if installed; not required.
"""

import os
import re
import uuid

import pytest
from sqlalchemy.orm import Session

from app.db.database import SessionLocal
from app.db.models.appointment import Appointment
from app.db.models.business import Business, BusinessHours
from app.db.models.conversation import Conversation, Message
from app.db.models.customer import Customer
from app.db.models.follow_up import FollowUp
from app.db.models.handoff import HumanHandoff
from app.db.models.notification import Notification
from app.db.models.payment import Payment
from app.db.models.service import Service
from app.services.conversation.fact_validator import check_no_internal_ids, check_price_and_deposit, check_weekday_hours
from app.services.conversation.orchestrator import handle_incoming_message

from tests.eval.regression_cases import load_all_cases

pytestmark = pytest.mark.skipif(
    not os.environ.get("RUN_LIVE_REGRESSION"),
    reason="hits the real Azure LLM per case -- opt in with RUN_LIVE_REGRESSION=1 (see module docstring)",
)

CASES = load_all_cases()

CORPORATE_PHRASES = [
    "thank you for reaching out",
    "i would be happy to assist",
    "happy to assist you",
    "is there anything else i can assist you with",
    "your request has been successfully processed",
]
DEVANAGARI_RE = re.compile(r"[ऀ-ॿ]")


def _provision_business(db: Session, cfg: dict) -> Business:
    """A fresh, throwaway business cloned from a case's config snapshot -- NEVER a live
    tenant looked up by name. Real conversations already carry their tenant's exact
    historical config inline (see pull_real_conversations.py), so replaying against a
    clone keeps the case's expectations pinned to that snapshot even if the real tenant's
    prices/hours/services change later, and never risks a synthetic test customer or
    appointment briefly showing up on a real pilot business's live dashboard."""
    business = Business(
        name=f"[regression] {cfg['name']} {uuid.uuid4().hex[:8]}",
        timezone=cfg["timezone"],
        currency=cfg.get("currency", "USD"),
        languages=cfg.get("languages"),
        language_mode=cfg.get("language_mode", "automatic"),
        tone=cfg.get("tone"),
        content_scope=cfg.get("content_scope", "single_business"),
        payment_collection_enabled=cfg.get("payment_collection_enabled", False),
        payment_providers=cfg.get("payment_providers", []),
    )
    db.add(business)
    db.flush()

    for s in cfg.get("services", []):
        db.add(
            Service(
                business_id=business.id,
                name=s["name"],
                description=s.get("description"),
                price=s["price"],
                duration_minutes=s["duration_minutes"],
                deposit_enabled=s.get("deposit_enabled", False),
                deposit_percentage=s.get("deposit_percentage"),
            )
        )
    for h in cfg.get("hours", []):
        db.add(
            BusinessHours(
                business_id=business.id,
                day_of_week=h["day_of_week"],
                closed=h["closed"],
                open_time=h.get("open_time"),
                close_time=h.get("close_time"),
            )
        )
    db.commit()
    return business


def _teardown_business(db: Session, business: Business, customer_id: uuid.UUID | None) -> None:
    db.rollback()
    appt_ids = [a.id for a in db.query(Appointment).filter(Appointment.business_id == business.id).all()]
    if appt_ids:
        db.query(Payment).filter(Payment.appointment_id.in_(appt_ids)).delete(synchronize_session=False)
        db.query(Notification).filter(Notification.appointment_id.in_(appt_ids)).delete(synchronize_session=False)
    db.query(Appointment).filter(Appointment.business_id == business.id).delete(synchronize_session=False)
    conv_ids = [c.id for c in db.query(Conversation).filter(Conversation.business_id == business.id).all()]
    if conv_ids:
        db.query(HumanHandoff).filter(HumanHandoff.conversation_id.in_(conv_ids)).delete(synchronize_session=False)
        db.query(FollowUp).filter(FollowUp.conversation_id.in_(conv_ids)).delete(synchronize_session=False)
        db.query(Message).filter(Message.conversation_id.in_(conv_ids)).delete(synchronize_session=False)
    db.query(Conversation).filter(Conversation.business_id == business.id).delete(synchronize_session=False)
    if customer_id is not None:
        db.query(Customer).filter(Customer.id == customer_id).delete(synchronize_session=False)
    db.query(Service).filter(Service.business_id == business.id).delete(synchronize_session=False)
    db.query(BusinessHours).filter(BusinessHours.business_id == business.id).delete(synchronize_session=False)
    db.delete(business)
    db.commit()


def _create_customer_and_conversation(db: Session, business: Business) -> tuple[uuid.UUID, uuid.UUID]:
    """Split out from _run_turns and always called first, so the caller has a real
    customer_id to hand to _teardown_business BEFORE any LLM call that could raise --
    otherwise an exception mid-conversation leaves the caller's customer_id at None,
    teardown skips deleting that (already-flushed) Customer row, and the later
    `db.delete(business)` then fails on the dangling FK, silently orphaning the whole
    business. Real bug, found via a caught leftover-row audit -- see PHASE_STATUS.md."""
    customer = Customer(business_id=business.id, name="Regression Customer")
    db.add(customer)
    db.flush()
    conversation = Conversation(business_id=business.id, customer_id=customer.id, channel="website", status="open")
    db.add(conversation)
    db.commit()
    return customer.id, conversation.id


def _run_turns(db: Session, business: Business, conversation_id: uuid.UUID, turns: list[str]) -> list[str]:
    replies = []
    for turn in turns:
        result = handle_incoming_message(db, conversation_id=conversation_id, business_id=business.id, content=turn)
        replies.append(result["response"] if result and result.get("response") else "")
    return replies


def _generic_check_failures(reply: str, business_cfg: dict) -> list[str]:
    # id-leak check: the SAME check the live orchestrator runs as a pre-send guard
    # (fact_validator.check_no_internal_ids) -- one set of rules, checked the same way in
    # both places (see fact_validator's module docstring). Since Phase 55, the only
    # appointment identifier ever shown to a customer is the short confirmation_code, so
    # there's no more legitimate case for a raw UUID surviving in prose.
    failures = check_no_internal_ids(reply)
    lower = reply.lower()
    for phrase in CORPORATE_PHRASES:
        if phrase in lower:
            failures.append(f"reply uses a banned corporate/chatbot phrase: {phrase!r}")

    # Price/deposit/hours grounding -- the SAME check the live orchestrator runs as a
    # pre-send guard (app/services/conversation/fact_validator.py), so a passing case
    # here is a real guarantee about production behavior, not a parallel
    # reimplementation that could drift. The #1 confirmed real failure in this dataset
    # (PHASE_STATUS.md): a fabricated 20% deposit quoted for a service never configured
    # to require one (Samaj Dental Clinic).
    services = business_cfg.get("services", [])
    failures.extend(check_price_and_deposit(reply, currency=business_cfg.get("currency", "USD"), services=services))
    hours_by_day = {h["day_of_week"]: h["closed"] for h in business_cfg.get("hours", [])}
    failures.extend(check_weekday_hours(reply, hours_by_day=hours_by_day))

    return failures


def _case_specific_failures(db: Session, business: Business, replies: list[str], expect: dict) -> list[str]:
    failures = []
    final_reply = replies[-1] if replies else ""

    if expect.get("expect_max_questions") is not None:
        limit = expect["expect_max_questions"]
        qcount = final_reply.count("?")
        if qcount > limit:
            failures.append(f"final reply asks {qcount} questions, expected at most {limit}")

    for phrase in expect.get("expect_reply_not_contains", []):
        if phrase.lower() in final_reply.lower():
            failures.append(f"final reply contains disallowed text: {phrase!r}")

    contains_any = expect.get("expect_reply_contains_any")
    if contains_any and not any(p.lower() in final_reply.lower() for p in contains_any):
        failures.append(f"final reply contains none of the expected phrases: {contains_any}")

    if "expect_language_script" in expect:
        want = expect["expect_language_script"]
        has_deva = bool(DEVANAGARI_RE.search(final_reply))
        if want == "devanagari" and not has_deva:
            failures.append(f"expected Devanagari script in final reply, got latin-only: {final_reply!r}")
        elif want == "latin" and has_deva:
            failures.append(f"expected latin-only final reply, got Devanagari script: {final_reply!r}")

    if "expect_price_mentioned" in expect:
        want = expect["expect_price_mentioned"]
        amount = want["amount"]
        if not any(str(int(amount)) in r or f"{amount:.2f}" in r or f"{amount:,.0f}" in r for r in replies):
            failures.append(f"no reply mentions the expected price {amount} for {want['service_name']}")

    appt_count = db.query(Appointment).filter(Appointment.business_id == business.id).count()
    if expect.get("expect_no_appointment"):
        if appt_count > 0:
            failures.append("an appointment was created but none was expected")
    if "expect_appointment" in expect:
        want_service = expect["expect_appointment"]["service_name"].lower()
        appts = db.query(Appointment).filter(Appointment.business_id == business.id).all()
        if not appts:
            failures.append(f"expected a booked appointment for {want_service!r}, but none was created")
        else:
            svc_by_appt = {a.id: db.query(Service).filter(Service.id == a.service_id).first() for a in appts}
            if not any(svc and want_service in svc.name.lower() for svc in svc_by_appt.values()):
                got = [svc.name for svc in svc_by_appt.values() if svc]
                failures.append(f"expected an appointment for {want_service!r}, got {got}")

    if expect.get("expect_escalation"):
        conv = db.query(Conversation).filter(Conversation.business_id == business.id).first()
        has_handoff = (
            conv is not None and db.query(HumanHandoff).filter(HumanHandoff.conversation_id == conv.id).count() > 0
        )
        has_takeover = conv is not None and conv.human_takeover_until is not None
        if not (has_handoff or has_takeover):
            failures.append("expected escalation to a human (handoff or takeover), neither happened")

    return failures


@pytest.mark.parametrize("case", CASES, ids=[c["id"] for c in CASES])
def test_case(case: dict) -> None:
    db = SessionLocal()
    business = None
    customer_id = None
    try:
        business = _provision_business(db, case["business"])
        customer_id, conversation_id = _create_customer_and_conversation(db, business)
        replies = _run_turns(db, business, conversation_id, case["turns"])

        failures: list[str] = []
        for reply in replies:
            failures.extend(_generic_check_failures(reply, case["business"]))
        failures.extend(_case_specific_failures(db, business, replies, case["expect"]))

        assert not failures, (
            f"case {case['id']} (source={case['source']}) failed:\n"
            + "\n".join(f"  - {f}" for f in failures)
            + f"\nreplies: {replies}"
        )
    finally:
        if business is not None:
            _teardown_business(db, business, customer_id)
        db.close()
