from datetime import datetime
from zoneinfo import ZoneInfo

from app.db.models.appointment import Appointment
from app.db.models.business import Business
from app.db.models.service import Service

# Deliberately duplicates orchestrator._format_local's formatting (same
# discipline as booking_service._fresh_alternatives duplicating
# BookAppointmentTool._alternatives — see Phase 12's PHASE_STATUS.md note):
# this is a lower service-layer module and app/services/conversation is a
# higher one, so importing across that boundary would point the dependency
# the wrong way for a few lines of strftime.
_TIME_FORMAT = "%A, %B %-d at %-I:%M %p"


def _format_local(dt: datetime, tz: ZoneInfo) -> str:
    return dt.astimezone(tz).strftime(_TIME_FORMAT)


def compose_email(*, event_type: str, appointment: Appointment, business: Business, service: Service) -> tuple[str, str]:
    """Deterministic subject/body for a booking/cancellation/reschedule email —
    no LLM involvement, the same discipline this codebase already applies to
    every other customer-facing confirmation string (see orchestrator.py's
    _format_*_result functions). Composed fresh from the real rows every time,
    never from anything cached or LLM-authored."""
    tz = ZoneInfo(business.timezone)
    when = _format_local(appointment.scheduled_at, tz)
    booking_id = str(appointment.id)

    if event_type == "booking_confirmed":
        subject = f"Your appointment at {business.name} is confirmed"
        headline = "Your appointment is confirmed."
    elif event_type == "appointment_cancelled":
        subject = f"Your appointment at {business.name} has been cancelled"
        headline = "This confirms your appointment has been cancelled."
    elif event_type == "appointment_rescheduled":
        subject = f"Your appointment at {business.name} has been rescheduled"
        headline = "Your appointment has been rescheduled."
    else:
        raise ValueError(f"Unknown notification event_type: {event_type!r}")

    body = (
        f"Hi,\n\n{headline}\n\n"
        f"Business: {business.name}\n"
        f"Service: {service.name}\n"
        f"When: {when}\n"
        f"Booking ID: {booking_id}\n"
    )
    return subject, body
