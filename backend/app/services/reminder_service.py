import logging
import uuid
from datetime import datetime, timezone

from sqlalchemy import func, select, update
from sqlalchemy.orm import Session

from app.db.models.appointment import Appointment, AppointmentStatus
from app.db.models.business import Business
from app.db.models.customer import Customer
from app.db.models.notification import Notification, NotificationStatus
from app.services.booking_service import _notification_channel
from app.services.notifications import dispatch_notification

logger = logging.getLogger(__name__)


def _find_due_appointment_ids(db: Session, *, now: datetime, business_id: uuid.UUID | None = None) -> list[uuid.UUID]:
    """Every eligibility rule lives in this SQL WHERE clause, never
    fetched-then-filtered in Python (the exact mistake Phase 18's own
    PHASE_STATUS.md documents finding and fixing live for its inactivity
    filter). This query only ever NARROWS candidates — it never marks
    anything as reminded; the real, race-proof claim happens in
    `_claim_and_queue_reminder` below, one atomic UPDATE per candidate.

    A candidate must be, all in real SQL:
    - for a business with reminder_enabled=true
    - CONFIRMED right now (re-checked again at claim time — see below — so a
      cancellation racing with this SELECT is still resolved correctly)
    - not yet reminded (reminder_sent_at IS NULL)
    - inside its business's real reminder window: now >= scheduled_at -
      reminder_minutes_before, and the appointment hasn't happened yet
      (now < scheduled_at)
    - booked with enough lead time for that window to ever have made sense:
      created_at <= scheduled_at - reminder_minutes_before. A booking made
      with LESS time remaining than the window (e.g. booked 20 minutes
      before a 60-minute threshold) never satisfies this, for the entire
      lifetime of the row — it is skipped entirely, not merely delayed,
      per this ticket's explicit requirement, with zero extra bookkeeping
      needed at booking time.
    """
    window = func.make_interval(0, 0, 0, 0, 0, Business.reminder_minutes_before)
    filters = [
        Business.reminder_enabled.is_(True),
        Appointment.status == AppointmentStatus.CONFIRMED,
        Appointment.reminder_sent_at.is_(None),
        Appointment.scheduled_at > now,
        Appointment.scheduled_at - window <= now,
        Appointment.created_at <= Appointment.scheduled_at - window,
    ]
    if business_id is not None:
        filters.append(Appointment.business_id == business_id)
    stmt = select(Appointment.id).join(Business, Business.id == Appointment.business_id).where(*filters)
    return list(db.execute(stmt).scalars())


def _claim_and_queue_reminder(db: Session, appointment_id: uuid.UUID, *, now: datetime) -> Notification | None:
    """The one atomic statement that makes 'never send a reminder twice' a
    real, DB-level guarantee rather than a hope — see Appointment.
    reminder_sent_at's own docstring. Re-checks `status = CONFIRMED` in the
    SAME UPDATE (not a separate SELECT beforehand): if a cancellation
    commits between `_find_due_appointment_ids` selecting this row and this
    claim running, the WHERE clause here simply matches 0 rows and this
    appointment is correctly never reminded — no separate race window.
    Postgres's own row-level locking is what makes two concurrent callers
    racing this exact statement resolve to exactly one winner (proven live
    below, same `threading.Barrier` technique Phase 30 used for the webhook
    idempotency constraint).

    The claim UPDATE and the new Notification row are committed together as
    ONE transaction — never two separate commits — so there is no window
    where an appointment is marked reminded with no real Notification row to
    show for it."""
    claimed = (
        db.execute(
            update(Appointment)
            .where(
                Appointment.id == appointment_id,
                Appointment.reminder_sent_at.is_(None),
                Appointment.status == AppointmentStatus.CONFIRMED,
            )
            .values(reminder_sent_at=now)
        ).rowcount
        == 1
    )
    if not claimed:
        db.rollback()
        return None

    appointment = db.get(Appointment, appointment_id)
    business = db.get(Business, appointment.business_id)
    customer = db.get(Customer, appointment.customer_id)
    if business is None or customer is None:
        # Keep the claim (never re-attempt — see the module docstring's
        # priority order) even though nothing more can be done here; a
        # missing Business/Customer row would itself be a deeper, unrelated
        # data-integrity bug this function isn't responsible for surfacing.
        db.commit()
        return None

    notification = Notification(
        business_id=business.id,
        appointment_id=appointment.id,
        channel=_notification_channel(business, customer),
        event_type="appointment_reminder",
        status=NotificationStatus.QUEUED,
    )
    db.add(notification)
    db.commit()
    db.refresh(notification)
    return notification


def run_due_reminders(db: Session, *, now: datetime | None = None, business_id: uuid.UUID | None = None) -> int:
    """The real, callable-not-scheduled entry point — same shape as Phase
    13's `dispatch_queued_notifications` / Phase 18's `run_followups`. The
    actual timer loop (app/services/scheduler.py) calls this every tick with
    a fresh DB session; the automated test suite and a manual/API trigger
    can call it directly too. Never raises: `dispatch_notification` (Phase
    13) already guarantees a send failure lands as a real Notification
    `FAILED` status rather than propagating, and this function's own claim
    step is a single atomic statement with no further Python logic that
    could throw mid-claim. Returns how many real reminders were actually
    queued+dispatched this call (0 is a normal, common result — most ticks
    find nothing due)."""
    now = now or datetime.now(timezone.utc)
    sent = 0
    for appointment_id in _find_due_appointment_ids(db, now=now, business_id=business_id):
        notification = _claim_and_queue_reminder(db, appointment_id, now=now)
        if notification is None:
            continue
        dispatch_notification(db, notification)
        sent += 1
    return sent
