import logging
import time
import uuid

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import settings
from app.db.models.appointment import Appointment
from app.db.models.business import Business
from app.db.models.customer import Customer
from app.db.models.notification import Notification, NotificationStatus
from app.db.models.payment import Payment
from app.db.models.service import Service
from app.services.notifications.base import NotificationDeliveryError
from app.services.notifications.content import compose_email, compose_sms
from app.services import integration_service
from app.services.notifications.email_provider import EmailNotificationProvider
from app.services.notifications.sms_provider import SMSNotificationProvider, TwilioSMSProvider

logger = logging.getLogger(__name__)

_MAX_SEND_ATTEMPTS = 3
_RETRY_DELAY_SECONDS = 1

_PROVIDERS = {"email": EmailNotificationProvider(), "sms": SMSNotificationProvider()}


def _resolve_sms_provider():
    """Real Twilio only when all three env vars are actually set (checked live,
    not cached, so a test/monkeypatch of `settings` takes effect immediately);
    otherwise the same safe Phase 13 stub via _PROVIDERS["sms"] — never crashes
    on missing config, regardless of a business's sms_enabled flag."""
    if settings.twilio_account_sid and settings.twilio_auth_token and settings.twilio_from_number:
        return TwilioSMSProvider()
    return _PROVIDERS["sms"]


def dispatch_notification(db: Session, notification: Notification) -> None:
    """Sends one queued Notification for real and moves its status to a real,
    provider-confirmed outcome — sent / simulated / failed, never left QUEUED
    and never assumed. Retries a bounded number of times on a transient
    provider failure before giving up.

    Never raises: this is called inline right after a booking/cancel/
    reschedule commits, and a notification failure must never break that
    already-successful customer-facing action. Every failure — even a bug in
    this function itself — is caught, logged, and reflected as a real FAILED
    status rather than propagating.
    """
    try:
        _dispatch(db, notification)
    except Exception:
        logger.exception("notification dispatch crashed for notification_id=%s", notification.id)
        try:
            notification.status = NotificationStatus.FAILED
            db.commit()
        except Exception:
            db.rollback()


def _mark_failed(db: Session, notification: Notification, reason: str) -> None:
    logger.error("notification_id=%s failed: %s", notification.id, reason)
    notification.status = NotificationStatus.FAILED
    db.commit()


def _dispatch(db: Session, notification: Notification) -> None:
    appointment = db.get(Appointment, notification.appointment_id)
    business = db.get(Business, notification.business_id)
    service = db.get(Service, appointment.service_id) if appointment else None
    customer = db.get(Customer, appointment.customer_id) if appointment else None
    if appointment is None or business is None or service is None or customer is None:
        _mark_failed(db, notification, "missing appointment/business/service/customer data")
        return

    # Phase 44: only relevant for booking_confirmed (the only event a Payment
    # is ever created against — see payment_service.
    # create_payment_for_appointment), and None whenever no real Payment row
    # exists for this appointment. compose_email/compose_sms both already
    # treat payment=None as "say nothing about payment."
    payment = (
        db.execute(select(Payment).where(Payment.appointment_id == appointment.id)).scalar_one_or_none()
        if notification.event_type == "booking_confirmed"
        else None
    )

    send_kwargs: dict = {}
    if notification.channel == "email":
        provider = _PROVIDERS["email"]
        recipient = customer.email or ""
        subject, body, html_body, inline_images = compose_email(
            event_type=notification.event_type,
            appointment=appointment,
            business=business,
            service=service,
            customer=customer,
            payment=payment,
        )
        send_kwargs = {
            "html_body": html_body,
            "inline_images": inline_images,
            "credentials": integration_service.email_credentials(db, business_id=business.id),
        }
    elif notification.channel == "sms":
        provider = _resolve_sms_provider()
        recipient = customer.phone or ""
        subject, body = "", compose_sms(
            event_type=notification.event_type,
            appointment=appointment,
            business=business,
            service=service,
            payment=payment,
        )
    else:
        _mark_failed(db, notification, f"no provider registered for channel={notification.channel!r}")
        return

    # Real providers (email, real Twilio) confirm SENT — a real network
    # acceptance response, never a delivery receipt (see each provider's
    # docstring for why DELIVERED is unreachable). The stub SMS provider
    # confirms only SIMULATED, so it can never be mistaken for a real send.
    success_status = (
        NotificationStatus.SIMULATED if getattr(provider, "SIMULATED", False) else NotificationStatus.SENT
    )

    last_error: NotificationDeliveryError | None = None
    attempts_made = 0
    for attempt in range(1, _MAX_SEND_ATTEMPTS + 1):
        attempts_made = attempt
        try:
            detail = provider.send(to=recipient, subject=subject, body=body, **send_kwargs)
        except NotificationDeliveryError as exc:
            last_error = exc
            if not exc.transient or attempt == _MAX_SEND_ATTEMPTS:
                break
            logger.warning(
                "notification_id=%s send attempt %d/%d failed transiently, retrying: %s",
                notification.id,
                attempt,
                _MAX_SEND_ATTEMPTS,
                exc,
            )
            time.sleep(_RETRY_DELAY_SECONDS)
            continue
        else:
            logger.info(
                "notification_id=%s %s on attempt %d/%d: %s",
                notification.id,
                success_status.value,
                attempt,
                _MAX_SEND_ATTEMPTS,
                detail,
            )
            notification.status = success_status
            db.commit()
            return

    # `attempts_made` — not the configured max — so a permanent failure that
    # broke out after its first (and only) try is never misreported as having
    # exhausted every retry it never actually attempted.
    _mark_failed(db, notification, f"failed after {attempts_made} attempt(s): {last_error}")


def dispatch_queued_notifications(db: Session, *, business_id: uuid.UUID | None = None) -> int:
    """Sends every currently-QUEUED Notification for real (optionally scoped to
    one business). The inline dispatch_notification calls in booking_service
    cover the normal booking/cancel/reschedule path; this is the pickup path
    for anything that was queued but never got dispatched inline (e.g. the
    process restarted between the two) — no new worker/queue infrastructure,
    just a function a future cron job or admin route can call. Returns how
    many notifications were picked up."""
    filters = [Notification.status == NotificationStatus.QUEUED]
    if business_id is not None:
        filters.append(Notification.business_id == business_id)
    queued = list(db.execute(select(Notification).where(*filters)).scalars())
    for notification in queued:
        dispatch_notification(db, notification)
    return len(queued)
