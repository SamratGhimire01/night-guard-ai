from datetime import datetime
from zoneinfo import ZoneInfo

from app.db.models.appointment import Appointment
from app.db.models.business import Business
from app.db.models.customer import Customer
from app.db.models.payment import Payment
from app.db.models.service import Service
from app.services.notifications.qr import PAYMENT_QR_CONTENT_ID, QR_CONTENT_ID, generate_qr_png
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
    # Phase 45: the underlying appointment genuinely still IS confirmed at
    # send time (claim_and_queue_reminder only ever fires for a real-time
    # re-checked CONFIRMED row) — same green pill as booking_confirmed, this
    # is honest, not a placeholder.
    "appointment_reminder": ("Confirmed", "#065f46", "#d1fae5"),
    # Sent after the customer picks eSewa/Khalti in chat: the appointment is confirmed, the deposit is what's due.
    "payment_requested": ("Deposit due", "#92400e", "#fef3c7"),
}


# the events whose email/SMS carries the deposit link (and its QR)
_PAYMENT_EVENTS = frozenset({"booking_confirmed", "payment_requested"})


def _format_local(dt: datetime, tz: ZoneInfo) -> str:
    return dt.astimezone(tz).strftime(_TIME_FORMAT)


def _payment_context(payment: Payment | None, service: Service) -> dict | None:
    """Phase 44: the same real deposit/remainder numbers the chat confirmation
    states (booking_tool._payment_info) — recomputed here from the real
    Payment/Service rows rather than threaded through as a third shape, so
    email/SMS and chat can never honestly disagree. None whenever there's no
    real pending payment to mention — never a bare number with no context."""
    if payment is None or payment.status.value != "pending":
        return None
    return {
        "amount": payment.amount,
        "currency": payment.currency,
        "percentage": service.deposit_percentage,
        "remaining": service.price - payment.amount,
        "payment_url": payment.payment_url,
    }


def compose_email(
    *,
    event_type: str,
    appointment: Appointment,
    business: Business,
    service: Service,
    customer: Customer,
    payment: Payment | None = None,
) -> tuple[str, str, str, list[tuple[str, bytes, str]] | None]:
    """Deterministic subject/plain-text/HTML for a booking/cancellation/
    reschedule email — no LLM involvement, the same discipline this codebase
    already applies to every other customer-facing confirmation string (see
    orchestrator.py's _format_*_result functions). Both bodies are composed
    fresh from the same real rows every time, never from anything cached or
    LLM-authored — Phase 17 changes presentation only, not what data is shown.
    Returns (subject, plain_text_body, html_body, inline_images) — the last
    element is a real CID-embeddable image list (Phase 46's fix for the real
    "Gmail doesn't render data: URIs" bug; see qr.py's own docstring), always
    `None` except for a real booking_confirmed check-in QR."""
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
    elif event_type == "appointment_reminder":
        subject = f"Reminder: your appointment at {business.name} is coming up"
        headline = "This is a reminder about your upcoming appointment."
    elif event_type == "payment_requested":
        subject = f"Your deposit payment link for {business.name}"
        headline = "Here is the link to pay your appointment deposit."
    else:
        raise ValueError(f"Unknown notification event_type: {event_type!r}")

    customer_contact = ", ".join(filter(None, [customer.phone, customer.email]))
    business_contact = " · ".join(filter(None, [business.address, business.phone, business.email]))

    greeting = f"Hi {customer.name}," if customer.name else "Hi,"
    body = (
        f"{greeting}\n\n{headline}\n\n"
        f"Business: {business.name}\n"
        f"Service: {service.name}\n"
        f"When: {when}\n"
        f"Booking ID: {booking_id}\n"
        f"Booked for: {customer.name}" + (f", {customer_contact}" if customer_contact else "") + "\n"
    )
    if business_contact:
        body += f"\n{business.name} · {business_contact}\n"

    payment_ctx = _payment_context(payment, service) if event_type in _PAYMENT_EVENTS else None
    inline_images: list[tuple[str, bytes, str]] | None = None
    payment_qr_cid: str | None = None
    if payment_ctx is not None:
        # the same real payment link, also as a scannable QR (CID-embedded like the check-in QR — see below)
        payment_qr_cid = PAYMENT_QR_CONTENT_ID
        inline_images = [(PAYMENT_QR_CONTENT_ID, generate_qr_png(payment_ctx["payment_url"]), "image/png")]
        body += (
            f"\nA {payment_ctx['percentage']}% deposit of {payment_ctx['currency']} {payment_ctx['amount']} is "
            f"required to confirm this appointment — the remaining {payment_ctx['currency']} "
            f"{payment_ctx['remaining']} is due at the clinic.\nPay here: {payment_ctx['payment_url']}\n"
            "The same link is also a QR code in the HTML version of this email — scan it with your phone camera.\n"
        )

    # Phase 46: a real, scannable check-in QR only makes sense on the
    # original confirmation — never re-sent on cancel/reschedule (a
    # rescheduled appointment keeps the SAME checkin_token/QR, since only the
    # time changed; a cancelled one has nothing to check into). The plain-
    # text body can't render an image at all, so it just tells the customer
    # the HTML version has one — an honest statement about a real medium
    # limitation, not a missing feature.
    #
    # Real bug found via live Gmail testing, fixed here: a base64 `data:` URI
    # image (the original approach) never actually renders in a real Gmail
    # inbox — confirmed by a real screenshot showing a broken-image icon,
    # even though the raw HTML genuinely contained a valid, independently
    # decodable image (which is why the earlier jsQR-on-raw-HTML proof looked
    # like success but didn't reflect what a real recipient sees). The real
    # fix is CID (Content-ID) embedding — a real inline MIME part referenced
    # by the HTML as `cid:...`, the standard, universally-supported mechanism
    # for images in HTML email (RFC 2392). See qr.py and
    # EmailNotificationProvider.send's `inline_images` parameter.
    qr_cid: str | None = None
    if event_type == "booking_confirmed":
        qr_png = generate_qr_png(str(appointment.checkin_token))
        qr_cid = QR_CONTENT_ID
        inline_images = [*(inline_images or []), (QR_CONTENT_ID, qr_png, "image/png")]
        body += "\nA check-in QR code is included in the HTML version of this email — please show it at the clinic.\n"

    status_label, status_color, status_bg = _STATUS_STYLE[event_type]
    html_body = render_appointment_email(
        business_name=business.name,
        business_address=business.address,
        business_phone=business.phone,
        business_email=business.email,
        customer_name=customer.name,
        customer_phone=customer.phone,
        customer_email=customer.email,
        headline=headline,
        service_name=service.name,
        when=when,
        status_label=status_label,
        status_color=status_color,
        status_bg=status_bg,
        booking_id=booking_id,
        qr_cid=qr_cid,
        payment=payment_ctx,
        payment_qr_cid=payment_qr_cid,
    )
    return subject, body, html_body, inline_images


def compose_sms(
    *,
    event_type: str,
    appointment: Appointment,
    business: Business,
    service: Service,
    payment: Payment | None = None,
) -> str:
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
    elif event_type == "appointment_reminder":
        verb = "coming up"
    elif event_type == "payment_requested":
        verb = "confirmed"
    else:
        raise ValueError(f"Unknown notification event_type: {event_type!r}")

    text = f"{business.name}: your {service.name} appointment on {when} is {verb}. Booking ID {booking_id}."
    payment_ctx = _payment_context(payment, service) if event_type in _PAYMENT_EVENTS else None
    if payment_ctx is not None:
        text += (
            f" A {payment_ctx['percentage']}% deposit of {payment_ctx['currency']} {payment_ctx['amount']} is "
            f"required — pay: {payment_ctx['payment_url']}"
        )
    return text
