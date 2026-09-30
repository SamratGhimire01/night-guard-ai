import logging
import uuid
from datetime import datetime, timedelta, timezone

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.db.models.appointment import Appointment
from app.db.models.business import Business
from app.db.models.conversation import Conversation, Message, MessageSenderType
from app.db.models.customer import Customer
from app.db.models.follow_up import FollowUp
from app.schemas.conversation import ConversationIntent
from app.services.followups.content import compose_followup_email
from app.services.notifications.base import NotificationDeliveryError
from app.services import integration_service
from app.services.notifications.email_provider import EmailNotificationProvider

logger = logging.getLogger(__name__)

# "Configurable threshold" per the ticket — a function/route parameter rather
# than a new persisted per-business column, same minimalism precedent as
# Phase 16/17's report parameters (no new schema for something a caller can
# already pass in at trigger time).
DEFAULT_INACTIVITY_HOURS = 24

# Real interest signal: the customer asked about pricing or a service, per
# Phase 8's real intent classification (now persisted on Message.detected_intent
# — see orchestrator.py). GREETING/GENERAL_QUESTION/etc. don't qualify: someone
# who only said "hi" and left is not a warm lead, and following up on them
# would be exactly the kind of spam the master plan warns against.
_INTEREST_INTENTS = (ConversationIntent.PRICING_QUESTION.value, ConversationIntent.SERVICE_QUESTION.value)


def identify_followup_candidates(
    db: Session, *, business_id: uuid.UUID, inactivity_hours: int = DEFAULT_INACTIVITY_HOURS
) -> list[dict]:
    """Real query, real timestamps, no guessing. A conversation qualifies only
    when ALL of these are true:
    1. business.follow_ups_enabled is True (explicit opt-in — see Business model).
    2. A customer message in this conversation has a real, persisted
       detected_intent of PRICING_QUESTION or SERVICE_QUESTION (real interest,
       not just any message).
    3. The conversation's real last message (customer or agent) is older than
       `inactivity_hours` — it has genuinely gone cold, not assumed.
    4. No Appointment for this conversation's customer was created at or after
       this conversation started. Appointment has no conversation_id (nothing
       in this codebase links a booking back to the conversation that produced
       it — confirmed by inspecting the schema), so this is a real, honest
       PROXY for "never booked because of this conversation": if the customer
       booked anything at all around the same time this conversation was
       happening, treat the interest as converted rather than risk nagging
       someone who already booked (via this conversation, a different
       channel, or a direct call — any of those means a follow-up here would
       be actively unhelpful, not just superfluous).
    5. No FollowUp row already exists for this conversation (the real,
       DB-level enforcement is the unique constraint on
       FollowUp.conversation_id — this check is just the detection-side
       optimization that skips already-handled conversations early; see
       _commit_followup for the actual backstop).

    Returns real ORM objects (Conversation/Message), not just IDs, so the
    caller (run_followups) doesn't need to re-query them.
    """
    business = db.get(Business, business_id)
    if business is None or not business.follow_ups_enabled:
        return []

    cutoff = datetime.now(timezone.utc) - timedelta(hours=inactivity_hours)
    conversations = db.execute(select(Conversation).where(Conversation.business_id == business_id)).scalars()

    candidates = []
    for conversation in conversations:
        already = db.execute(
            select(FollowUp.id).where(FollowUp.conversation_id == conversation.id)
        ).scalar_one_or_none()
        if already is not None:
            continue

        # The cutoff comparison must happen IN SQL, not in Python: Message.created_at
        # is a naive `timestamp without time zone` column (CreatedAtMixin), and
        # comparing an already-fetched naive datetime against a tz-aware `cutoff` in
        # Python raises TypeError — the same reason every other real-timestamp filter
        # in this codebase (e.g. report_service's day-boundary queries) builds the
        # comparison into the WHERE clause and lets the DB/driver handle it, never
        # fetches-then-compares client-side.
        any_message = db.execute(
            select(Message.id).where(Message.conversation_id == conversation.id).limit(1)
        ).scalar_one_or_none()
        if any_message is None:
            continue  # no messages at all
        still_active = db.execute(
            select(Message.id).where(Message.conversation_id == conversation.id, Message.created_at > cutoff).limit(1)
        ).scalar_one_or_none()
        if still_active is not None:
            continue  # a message newer than the cutoff exists — not cold yet

        interest_message = db.execute(
            select(Message)
            .where(
                Message.conversation_id == conversation.id,
                Message.sender_type == MessageSenderType.CUSTOMER,
                Message.detected_intent.in_(_INTEREST_INTENTS),
            )
            .order_by(Message.created_at.desc())
            .limit(1)
        ).scalar_one_or_none()
        if interest_message is None:
            continue  # never showed real interest

        booked_since = db.execute(
            select(Appointment.id)
            .where(
                Appointment.business_id == business_id,
                Appointment.customer_id == conversation.customer_id,
                Appointment.created_at >= conversation.created_at,
            )
            .limit(1)
        ).scalar_one_or_none()
        if booked_since is not None:
            continue  # already converted — never follow up on a real booking

        candidates.append({"conversation": conversation, "interest_message": interest_message})

    return candidates


def _commit_followup(db: Session, follow_up: FollowUp) -> str:
    """Commits the FollowUp row — the real DB-level anti-spam backstop. If a
    row for this conversation_id already exists (a genuine race between two
    concurrent/retried runs, not just detection's own earlier check), the
    unique constraint on FollowUp.conversation_id rejects the second insert;
    caught here as "already handled" rather than retried or crashed. This is
    what makes "at most one follow-up per conversation, ever" airtight at the
    database level, not just something application logic promises."""
    db.add(follow_up)
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        return "already_sent"
    return follow_up.status


def _process_candidate(
    db: Session, *, business: Business, candidate: dict, inactivity_hours: int
) -> dict:
    conversation = candidate["conversation"]
    interest_message = candidate["interest_message"]
    customer = db.get(Customer, conversation.customer_id)
    scheduled_at = interest_message.created_at + timedelta(hours=inactivity_hours)

    # CONSENT SAFETY (explicit reasoning, per the ticket's ask): follow-ups
    # NEVER use SMS, full stop — regardless of business.sms_enabled or
    # customer.sms_opt_in (Phase 15). Those flags were collected for
    # booking-related transactional notifications (a confirmation the
    # customer's own action triggered); a follow-up is a different kind of
    # message the business initiates unprompted, and reusing a different
    # consent's flag for this new purpose would be exactly the kind of
    # consent-scope creep the master plan's "never spam" rule exists to
    # prevent. Email is the only channel, and only when the customer actually
    # has one on file — no workaround, no fallback to any other channel.
    if not customer.email:
        follow_up = FollowUp(
            business_id=business.id,
            customer_id=customer.id,
            conversation_id=conversation.id,
            status="skipped_no_consent",
            scheduled_at=scheduled_at,
            sent_at=datetime.now(timezone.utc),
            channel=None,
            trigger_message_id=interest_message.id,
        )
        outcome = _commit_followup(db, follow_up)
        logger.info("followup skipped_no_consent: conversation_id=%s (no email on file)", conversation.id)
        return {"conversation_id": str(conversation.id), "status": outcome, "channel": None}

    subject, body, html_body = compose_followup_email(business=business, customer=customer, interest_message=interest_message)
    try:
        detail = EmailNotificationProvider().send(
            to=customer.email,
            subject=subject,
            body=body,
            html_body=html_body,
            credentials=integration_service.email_credentials(db, business_id=business.id),
        )
        status = "sent"
    except NotificationDeliveryError as exc:
        detail = str(exc)
        status = "failed"

    follow_up = FollowUp(
        business_id=business.id,
        customer_id=customer.id,
        conversation_id=conversation.id,
        status=status,
        scheduled_at=scheduled_at,
        sent_at=datetime.now(timezone.utc),
        channel="email",
        trigger_message_id=interest_message.id,
    )
    outcome = _commit_followup(db, follow_up)
    logger.info("followup %s: conversation_id=%s detail=%s", outcome, conversation.id, detail)
    return {"conversation_id": str(conversation.id), "status": outcome, "channel": "email", "detail": detail}


def run_followups(
    db: Session, *, business_id: uuid.UUID, inactivity_hours: int = DEFAULT_INACTIVITY_HOURS
) -> list[dict]:
    """Detects and sends follow-ups for one business, right now. Called automatically by the background scheduler
    for every business with follow-ups on (run_due_followups below), and on demand from the dashboard's "Run now"."""
    business = db.get(Business, business_id)
    if business is None:
        return []
    candidates = identify_followup_candidates(db, business_id=business_id, inactivity_hours=inactivity_hours)
    return [
        _process_candidate(db, business=business, candidate=candidate, inactivity_hours=inactivity_hours)
        for candidate in candidates
    ]


def run_due_followups(db: Session) -> int:
    """One scheduler pass: runs follow-ups for every business that turned them on. Returns how many were sent. Safe to
    call often: each conversation gets at most one follow-up, ever (see identify_followup_candidates)."""
    business_ids = db.execute(select(Business.id).where(Business.follow_ups_enabled.is_(True))).scalars().all()
    sent = 0
    for business_id in business_ids:
        try:
            results = run_followups(db, business_id=business_id)
        except Exception:  # one business's failure must never stop the others
            logger.exception("follow-up run failed for business %s", business_id)
            db.rollback()
            continue
        sent += sum(1 for r in results if r.get("status") == "sent")
    return sent
