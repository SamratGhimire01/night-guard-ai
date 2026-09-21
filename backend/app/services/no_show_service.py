import logging
import uuid
from datetime import datetime, timedelta, timezone

from sqlalchemy import func, update
from sqlalchemy.orm import Session

from app.core.config import settings
from app.db.models.appointment import Appointment, AppointmentStatus
from app.db.models.payment import Payment, PaymentStatus

logger = logging.getLogger(__name__)


def flag_no_shows(db: Session, *, now: datetime | None = None, business_id: uuid.UUID | None = None) -> int:
    """Flips every CONFIRMED appointment whose whole slot (scheduled_at + duration) has passed to NO_SHOW, and returns
    how many. ONE set-based `UPDATE ... WHERE status = 'CONFIRMED' AND <slot over> RETURNING id` — never
    select-then-update — so the guarantee lives in the statement's own WHERE clause, same discipline as
    reminder_sent_at (Phase 45) and checked_in_at (Phase 46):
      * a check-in (CONFIRMED -> ARRIVED) or a cancel that commits first makes this row stop matching, so it can
        never end up NO_SHOW;
      * two concurrent scans (two workers, a slow tick overlapping the next) block on each row's lock and the loser
        re-evaluates the WHERE against the committed row and matches nothing — each appointment is flagged exactly
        once.
    Deposits (Phase 49): in the SAME transaction, a COMPLETED Payment belonging to a newly flagged appointment gets
    `forfeited_due_to_no_show_at` — one conditional UPDATE (`status = COMPLETED AND forfeited... IS NULL`), so it is set
    exactly once and only if the status flip itself committed (one commit covers both; a failure rolls both back). It is
    a record of why the clinic keeps money it already received: no refund attempt, `Payment.status` untouched, and NO
    message of any kind goes to the customer — this function sends nothing. A deposit still PENDING (or FAILED) is
    left exactly as it was. A deposit that completes only AFTER the appointment was flagged is not forfeited
    retroactively (the customer paid a live link late — the clinic decides what that means).

    `no_show_lookback_hours` bounds how far back a scan looks: a long outage, or the first run after this shipped, must
    not relabel weeks of history (appointments from before check-in was in use were never scanned, so "never checked
    in" says nothing about them). Older CONFIRMED rows simply stay CONFIRMED.
    PERMANENT DECISION (Phase 49): those old pre-feature rows are NEVER back-filled as NO_SHOW — not by raising the
    lookback (settings caps it at 72 h, so an env change cannot do it), not by a script, not manually. Whether a
    historical appointment was a real no-show or just an un-scanned visit is unknowable, and a wrong NO_SHOW label (and,
    with Phase 49, a "forfeited deposit") on a real customer is worse than an honest "unknown". Any future manual
    flagging path must keep this rule.

    Never raises for the caller's sake beyond the DB itself: one transaction, one commit."""
    now = now or datetime.now(timezone.utc)
    slot_end = Appointment.scheduled_at + func.make_interval(0, 0, 0, 0, 0, Appointment.duration_minutes)
    filters = [
        Appointment.status == AppointmentStatus.CONFIRMED,
        slot_end < now,
        slot_end >= now - timedelta(hours=settings.no_show_lookback_hours),
    ]
    if business_id is not None:
        filters.append(Appointment.business_id == business_id)
    flagged = list(
        db.execute(
            update(Appointment).where(*filters).values(status=AppointmentStatus.NO_SHOW).returning(Appointment.id)
        ).scalars()
    )
    forfeited = []
    if flagged:
        forfeited = list(
            db.execute(
                update(Payment)
                .where(
                    Payment.appointment_id.in_(flagged),
                    Payment.status == PaymentStatus.COMPLETED,
                    Payment.forfeited_due_to_no_show_at.is_(None),
                )
                .values(forfeited_due_to_no_show_at=now)
                .returning(Payment.id)
            ).scalars()
        )
    db.commit()
    for appointment_id in flagged:
        logger.info("appointment flagged NO_SHOW: appointment_id=%s", appointment_id)
    for payment_id in forfeited:
        logger.info("deposit recorded as forfeited due to no-show: payment_id=%s", payment_id)
    return len(flagged)
