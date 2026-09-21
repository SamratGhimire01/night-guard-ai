import uuid

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.models.appointment import Appointment, AppointmentStatus
from app.db.models.service import Service
from app.db.models.staff import Staff

_ACTIVE_STATUSES = (AppointmentStatus.PENDING, AppointmentStatus.CONFIRMED, AppointmentStatus.ARRIVED)
_PAST_STATUSES = (AppointmentStatus.COMPLETED, AppointmentStatus.CANCELLED, AppointmentStatus.NO_SHOW)
RECENT_PAST_LIMIT = 3


def _serialize(appointment: Appointment, service_name: str, staff_name: str | None) -> dict:
    return {
        "id": str(appointment.id),
        "service": service_name,
        "staff": staff_name,
        "scheduled_at": appointment.scheduled_at.isoformat(),
        "duration_minutes": appointment.duration_minutes,
        "status": appointment.status.value,
    }


def get_appointment_context(db: Session, *, customer_id: uuid.UUID, business_id: uuid.UUID) -> dict:
    """Active/upcoming appointments (always included, unbounded) plus a bounded
    recent-past window (last RECENT_PAST_LIMIT, not the customer's entire
    history). Tenant-scoped via business_id on every row."""
    base = (
        select(Appointment, Service.name, Staff.name)
        .join(Service, Appointment.service_id == Service.id)
        .outerjoin(Staff, Appointment.staff_id == Staff.id)
        .where(Appointment.customer_id == customer_id, Appointment.business_id == business_id)
    )

    active_rows = db.execute(
        base.where(Appointment.status.in_(_ACTIVE_STATUSES)).order_by(Appointment.scheduled_at.asc())
    ).all()
    past_rows = db.execute(
        base.where(Appointment.status.in_(_PAST_STATUSES))
        .order_by(Appointment.scheduled_at.desc())
        .limit(RECENT_PAST_LIMIT)
    ).all()

    return {
        "active": [_serialize(a, s, st) for a, s, st in active_rows],
        "recent_past": [_serialize(a, s, st) for a, s, st in past_rows],
    }
