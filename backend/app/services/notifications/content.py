from datetime import datetime
from zoneinfo import ZoneInfo

from app.db.models.appointment import Appointment
from app.db.models.business import Business
from app.db.models.customer import Customer
from app.db.models.service import Service
from app.services.notifications.templates.render import render_appointment_email

# Deliberately duplicates orchestrator._format_local's formatting (same
# discipline as booking_service._fresh_alternatives duplicating
# BookAppointmentTool._alternatives — see Phase 12's PHASE_STATUS.md note):
# this is a lower service-layer module and app/services/conversation is a
# higher one, so importing across that boundary would point the dependency
# the wrong way for a few lines of strftime.
_TIME_FORMAT = "%A, %B %-d at %-I:%M %p"

# (status_label, status_text_color, status_pill_background) per event_type —
# Phase 17's shared HTML status pill. Kept next to compose_email since it's
# the only caller; not worth its own module for three tuples.
_STATUS_STYLE = {
    "booking_confirmed": ("Confirmed", "#065f46", "#d1fae5"),
    "appointment_cancelled": ("Cancelled", "#991b1b", "#fee2e2"),
    "appointment_rescheduled": ("Rescheduled", "#1e40af", "#dbeafe"),
}


def _format_local(dt: datetime, tz: ZoneInfo) -> str:
    return dt.astimezone(tz).strftime(_TIME_FORMAT)


def compose_email(
    *, event_type: str, appointment: Appointment, business: Business, service: Service, customer: Customer
) -> tuple[str, str, str]:
    """Deterministic subject/plain-text/HTML for a booking/cancellation/
    reschedule email — no LLM involvement, the same discipline this codebase
    already applies to every other customer-facing confirmation string (see
    orchestrator.py's _format_*_result functions). Both bodies are composed
    fresh from the same real rows every time, never from anything cached or
    LLM-authored — Phase 17 changes presentation only, not what data is shown.
    Returns (subject, plain_text_body, html_body)."""
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

    greeting = f"Hi {customer.name}," if customer.name else "Hi,"
    body = (
        f"{greeting}\n\n{headline}\n\n"
        f"Business: {business.name}\n"
        f"Service: {service.name}\n"
        f"When: {when}\n"
        f"Booking ID: {booking_id}\n"
    )

    status_label, status_color, status_bg = _STATUS_STYLE[event_type]
    html_body = render_appointment_email(
        business_name=business.name,
        customer_name=customer.name,
        headline=headline,
        service_name=service.name,
        when=when,
        status_label=status_label,
        status_color=status_color,
        status_bg=status_bg,
        booking_id=booking_id,
    )
    return subject, body, html_body


def compose_sms(*, event_type: str, appointment: Appointment, business: Business, service: Service) -> str:
    """Deterministic one-line SMS body — same real-row/no-LLM discipline as
    compose_email, just short (SMS has no subject line and carriers/Twilio
    charge per ~160-char segment)."""
    tz = ZoneInfo(business.timezone)
    when = _format_local(appointment.scheduled_at, tz)
    booking_id = str(appointment.id)[:8]

    if event_type == "booking_confirmed":
        verb = "confirmed"
    elif event_type == "appointment_cancelled":
        verb = "cancelled"
    elif event_type == "appointment_rescheduled":
        verb = "rescheduled"
    else:
        raise ValueError(f"Unknown notification event_type: {event_type!r}")

    return f"{business.name}: your {service.name} appointment on {when} is {verb}. Booking ID {booking_id}."
