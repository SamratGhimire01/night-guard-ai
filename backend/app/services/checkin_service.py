import logging
import uuid
from datetime import datetime, timezone

from sqlalchemy import select, update
from sqlalchemy.orm import Session

from app.core.exceptions import ConflictError, NotFoundError, UnprocessableEntityError
from app.db.models.appointment import Appointment, AppointmentStatus
from app.services import google_calendar_service

logger = logging.getLogger(__name__)


def check_in_appointment(db: Session, *, business_id: uuid.UUID, token: uuid.UUID) -> Appointment:
    """The ONLY path that marks an appointment checked in. Real, tenant-scoped,
    one-time-use — the same atomic-claim discipline as Phase 45's reminder
    guard, applied to a security-sensitive credential this time.

    Tenant scoping happens INSIDE the lookup itself (`business_id` is part of
    the WHERE clause of both the claim and the fallback SELECT below), never
    checked after a successful load — a token that's real but belongs to a
    different business is indistinguishable from a token that doesn't exist
    at all. This is what makes "staff from Business B cannot check in
    Business A's appointment even with a valid token" true by construction,
    not by an extra permission check layered on top.

    One-time-use is a real, atomic DB guarantee — a single `UPDATE ... WHERE
    checked_in_at IS NULL AND status = 'CONFIRMED'` is the ONLY thing that
    decides whether this call wins the claim; Postgres's own row-level
    locking is what makes two concurrent scans of the same QR resolve to
    exactly one winner (proven live with real concurrent threads, same
    technique as Phase 45's reminder claim / Phase 30's webhook idempotency
    constraint). Only once that UPDATE reports zero rows does this function
    fall back to a read-only SELECT — purely to compose an honest, specific
    reason (already checked in at a real timestamp / not in a checkinable
    state / doesn't exist for this business) — that SELECT can never
    influence the actual state, so it introduces no race of its own."""
    now = datetime.now(timezone.utc)
    claimed_id = db.execute(
        update(Appointment)
        .where(
            Appointment.business_id == business_id,
            Appointment.checkin_token == token,
            Appointment.checked_in_at.is_(None),
            Appointment.status == AppointmentStatus.CONFIRMED,
        )
        .values(checked_in_at=now, status=AppointmentStatus.COMPLETED)
        .returning(Appointment.id)
    ).scalar_one_or_none()

    if claimed_id is not None:
        db.commit()
        appointment = db.get(Appointment, claimed_id)
        db.refresh(appointment)
        # Best-effort — a Calendar failure must never undo or fail a
        # check-in that has already committed in Postgres (same discipline
        # as every other sync_appointment_* call site).
        google_calendar_service.sync_appointment_completed(db, appointment)
        return appointment

    db.rollback()
    appointment = db.execute(
        select(Appointment).where(Appointment.business_id == business_id, Appointment.checkin_token == token)
    ).scalar_one_or_none()
    if appointment is None:
        raise NotFoundError("No appointment found for this QR code at your business.")
    if appointment.checked_in_at is not None:
        raise ConflictError(
            f"This appointment was already checked in at {appointment.checked_in_at.isoformat()}."
        )
    raise UnprocessableEntityError(
        f"This appointment is {appointment.status.value} and cannot be checked in."
    )
