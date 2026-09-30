"""Emails to the people who run a business: "a customer needs you" (new handoff), "you have a new booking" (made in
chat), and upgrade requests to the platform team.

Owner alerts never slow down or break a customer's chat: everything the email needs is read up front, then it is sent
on a background thread, and any failure is logged, never raised. Sent from the business's own Gmail when it has
connected one, otherwise from the platform account, to every owner and admin login (deduplicated). A business can
turn them off with Business.owner_alerts_enabled."""

import logging
import threading
import uuid
from zoneinfo import ZoneInfo

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import settings
from app.db.models.appointment import Appointment
from app.db.models.business import Business, BusinessUser, BusinessUserRole
from app.db.models.customer import Customer
from app.db.models.service import Service
from app.services import integration_service
from app.services.notifications.email_provider import EmailNotificationProvider

logger = logging.getLogger(__name__)


def _send(*, to: list[str], subject: str, body: str, credentials: tuple[str, str] | None = None) -> bool:
    ok = True
    for address in to:
        try:
            EmailNotificationProvider().send(to=address, subject=subject, body=body, credentials=credentials)
        except Exception:
            logger.warning("owner alert email to %s failed", address, exc_info=True)
            ok = False
    return ok and bool(to)


def _in_background(**kwargs) -> None:
    threading.Thread(target=_send, kwargs=kwargs, daemon=True).start()


def _recipients(db: Session, business_id: uuid.UUID) -> list[str]:
    emails = db.execute(
        select(BusinessUser.email).where(
            BusinessUser.business_id == business_id,
            BusinessUser.role.in_([BusinessUserRole.OWNER, BusinessUserRole.ADMIN]),
        )
    ).scalars().all()
    return sorted({e.strip().lower() for e in emails if e})


def _dashboard(path: str) -> str:
    return settings.dashboard_base_url.rstrip("/") + path


def _prepare(db: Session, business_id: uuid.UUID) -> tuple[Business, list[str], tuple[str, str] | None] | None:
    business = db.get(Business, business_id)
    if business is None or not business.owner_alerts_enabled:
        return None
    to = _recipients(db, business_id)
    if not to:
        return None
    return business, to, integration_service.email_credentials(db, business_id=business_id)


def notify_handoff(db: Session, *, business_id: uuid.UUID, conversation_id: uuid.UUID, reason: str, customer_name: str) -> None:
    """A conversation was just handed to a person. Called once per new handoff (not for an already-open one)."""
    try:
        prepared = _prepare(db, business_id)
        if prepared is None:
            return
        business, to, credentials = prepared
        body = (
            f"{customer_name} is waiting for a reply from your team.\n\n"
            f"Why: {reason}\n\n"
            f"Open the conversation: {_dashboard(f'/dashboard/inbox/{conversation_id}')}\n\n"
            "When you reply from the Inbox, the customer gets your message on the same channel they wrote on.\n\n"
            f"— Night Guard AI for {business.name}\n"
            "You get these emails because owner alerts are on (Settings > Bookings & reminders)."
        )
        _in_background(to=to, subject=f"{customer_name} needs a person — {business.name}", body=body, credentials=credentials)
    except Exception:
        logger.exception("could not prepare handoff alert for business %s", business_id)


def notify_new_booking(db: Session, *, appointment: Appointment) -> None:
    """A customer just booked through chat. Dashboard bookings don't call this: the owner made them."""
    try:
        prepared = _prepare(db, appointment.business_id)
        if prepared is None:
            return
        business, to, credentials = prepared
        customer = db.get(Customer, appointment.customer_id)
        service = db.get(Service, appointment.service_id)
        when = appointment.scheduled_at.astimezone(ZoneInfo(business.timezone))
        name = (customer.known_name if customer else None) or "A customer"
        service_name = service.name if service else "an appointment"
        body = (
            f"{name} booked {service_name}.\n\n"
            f"When: {when.strftime('%A %d %B, %I:%M %p').replace(' 0', ' ')}\n"
            f"Phone: {(customer.phone if customer else None) or 'not given'}\n"
            f"Email: {(customer.email if customer else None) or 'not given'}\n\n"
            f"See your appointments: {_dashboard('/dashboard/appointments')}\n\n"
            f"— Night Guard AI for {business.name}\n"
            "You get these emails because owner alerts are on (Settings > Bookings & reminders)."
        )
        _in_background(to=to, subject=f"New booking: {name}, {service_name} — {business.name}", body=body, credentials=credentials)
    except Exception:
        logger.exception("could not prepare booking alert for appointment %s", appointment.id)


def send_upgrade_request(*, business_name: str, business_id: uuid.UUID, requested_by: str, contact_email: str | None) -> bool:
    """Tells the platform team an owner wants Premium. Returns whether the email went out."""
    to = settings.platform_support_email or settings.gmail_address
    if not to:
        logger.warning("upgrade request from %s not emailed: no PLATFORM_SUPPORT_EMAIL or GMAIL_ADDRESS set", business_id)
        return False
    body = (
        f"{business_name} asked to upgrade to Premium.\n\n"
        f"Business ID: {business_id}\nRequested by: {requested_by}\nBusiness email: {contact_email or 'not set'}\n\n"
        "Upgrade them with PATCH /api/v1/admin/businesses/{id}/plan once payment is arranged."
    )
    return _send(to=[to], subject=f"Upgrade request: {business_name}", body=body)
