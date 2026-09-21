import logging
import uuid
from datetime import datetime, timedelta, timezone

from sqlalchemy import func, update
from sqlalchemy.orm import Session

from app.core.config import settings
from app.db.models.appointment import Appointment, AppointmentStatus

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
    Touches only `status`. Deliberately nothing about payments/deposits (Phase 44) — what a no-show means for a paid
    deposit is a separate business-policy question.

    `no_show_lookback_hours` bounds how far back a scan looks: a long outage, or the first run after this shipped, must
    not relabel weeks of history (appointments from before check-in was in use were never scanned, so "never checked
    in" says nothing about them). Older CONFIRMED rows simply stay CONFIRMED.

    Never raises for the caller's sake beyond the DB itself: one statement, one commit."""
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
    db.commit()
    for appointment_id in flagged:
        logger.info("appointment flagged NO_SHOW: appointment_id=%s", appointment_id)
    return len(flagged)
