import logging
import uuid
from datetime import datetime

from sqlalchemy import select, update
from sqlalchemy.orm import Session

from app.core.exceptions import ConflictError, NotFoundError, UnprocessableEntityError
from app.db.models.appointment import Appointment, AppointmentStatus
from app.db.models.business import Business
from app.db.models.channel_identity import ChannelIdentity
from app.db.models.customer import Customer
from app.db.models.integration import Integration
from app.db.models.notification import Notification, NotificationStatus
from app.memory.appointment_context import get_appointment_context
from app.schemas.conversation import ConversationIntent
from app.services import booking_service
from app.services.conversation.tools import TOOL_REGISTRY, ConversationTool
from app.services.notifications import dispatch_notification
from app.services.notifications.qr import generate_qr_png

logger = logging.getLogger(__name__)

# Real abuse guard, same "cap, not unlimited" discipline as Phase 18's
# follow-up limit — enforced by a single atomic UPDATE (see
# ResendConfirmationTool.run), never a check-then-act race.
_MAX_RESEND_ATTEMPTS = 3


def _serialize(appointment) -> dict:
    return {
        "id": str(appointment.id),
        "service_id": str(appointment.service_id),
        "staff_id": str(appointment.staff_id) if appointment.staff_id else None,
        "scheduled_at": appointment.scheduled_at,
        "duration_minutes": appointment.duration_minutes,
        "status": appointment.status.value,
    }


class CancelAppointmentTool(ConversationTool):
    """The Phase 11 real cancellation write path. `run()` never trusts that the
    appointment is cancellable — it always re-derives that from
    booking_service.cancel_appointment, the only function allowed to write a
    CANCELLED status."""

    name = "cancel_appointment"
    handles_intents = frozenset({ConversationIntent.CANCELLATION})

    def run(
        self, db: Session, *, business_id: uuid.UUID, customer_id: uuid.UUID, appointment_id: uuid.UUID, **kwargs
    ) -> dict:
        try:
            appointment = booking_service.cancel_appointment(
                db, business_id=business_id, appointment_id=appointment_id
            )
        except (NotFoundError, UnprocessableEntityError) as exc:
            logger.info(
                "cancel_appointment failed: business_id=%s appointment_id=%s reason=%s",
                business_id,
                appointment_id,
                exc.message,
            )
            return {"success": False, "appointment": None, "message": exc.message}

        return {"success": True, "appointment": _serialize(appointment), "message": None}


class RescheduleAppointmentTool(ConversationTool):
    """The Phase 11 real reschedule write path. `run()` never trusts that the new
    slot is free — it always re-derives that from
    booking_service.reschedule_appointment, which is itself backed by the same
    Phase 10 exclusion constraint (Postgres enforces it on UPDATE too)."""

    name = "reschedule_appointment"
    handles_intents = frozenset({ConversationIntent.RESCHEDULING})

    def run(
        self,
        db: Session,
        *,
        business_id: uuid.UUID,
        customer_id: uuid.UUID,
        appointment_id: uuid.UUID,
        new_scheduled_at: datetime,
        **kwargs,
    ) -> dict:
        try:
            appointment = booking_service.reschedule_appointment(
                db, business_id=business_id, appointment_id=appointment_id, new_scheduled_at=new_scheduled_at
            )
        except (NotFoundError, UnprocessableEntityError, ConflictError) as exc:
            logger.info(
                "reschedule_appointment failed: business_id=%s appointment_id=%s new_scheduled_at=%s reason=%s",
                business_id,
                appointment_id,
                new_scheduled_at,
                exc.message,
            )
            return {"success": False, "appointment": None, "message": exc.message}

        return {"success": True, "appointment": _serialize(appointment), "message": None}


class AppointmentStatusTool(ConversationTool):
    """Phase 14: answers "what's my appointment status" from a REAL, fresh query
    every single time — never from Phase 7's conversation summary, which can go
    stale the instant an appointment changes through a different
    request/channel after the summary text was generated. `get_appointment_context`
    is the exact same tenant/customer-scoped query Phase 7 already re-runs fresh
    on every turn to build the LLM's own prompt context — this tool doesn't
    duplicate that query, it just makes sure the intent's actual *response* is
    built deterministically from that same real data (orchestrator's
    `_format_appointment_status_result`), instead of trusting the LLM to read
    it correctly out of everything else in the prompt."""

    name = "appointment_status"
    handles_intents = frozenset({ConversationIntent.APPOINTMENT_STATUS})

    def run(self, db: Session, *, business_id: uuid.UUID, customer_id: uuid.UUID, **kwargs) -> dict:
        return get_appointment_context(db, customer_id=customer_id, business_id=business_id)


class ResendConfirmationTool(ConversationTool):
    """The real write path for a customer explicitly asking to have their
    appointment confirmation and/or check-in QR (re)sent — to email,
    WhatsApp, or both. Same master-plan discipline as every other tool: the
    LLM only ever identifies the intent + which appointment/channel (see
    intent.py rule 18); this class is the only thing that actually sends
    anything or touches `confirmation_resend_count`.

    Rate limit is a single atomic UPDATE (`confirmation_resend_count < 3`),
    same "the guarantee lives in one SQL statement's WHERE clause, not
    application logic a race could slip past" discipline as
    reminder_sent_at/checked_in_at (app/db/models/appointment.py) — claimed
    BEFORE any real send is attempted, so a customer can never be double-
    charged against the cap by retrying a slow request.

    Email reuses the exact existing Phase 13/44/46 dispatch pipeline
    unchanged (a real Notification row + dispatch_notification) — the same
    CID-embedded QR content.py already composes for booking_confirmed.
    WhatsApp has no equivalent "attach to an existing pipeline" path (it's a
    genuinely different delivery mechanism, not just a different provider —
    see WhatsAppChannelAdapter.send_image_message), so that side is sent
    directly here and recorded as its own real Notification row for the same
    audit trail email already gets.
    """

    name = "resend_confirmation"
    handles_intents = frozenset({ConversationIntent.RESEND_CONFIRMATION})

    def run(
        self,
        db: Session,
        *,
        business_id: uuid.UUID,
        customer_id: uuid.UUID,
        appointment_id: uuid.UUID,
        channel: str | None = None,
        conversation_channel: str | None = None,
        **kwargs,
    ) -> dict:
        appointment = db.get(Appointment, appointment_id)
        if appointment is None or appointment.business_id != business_id or appointment.customer_id != customer_id:
            return {"success": False, "rate_limited": False, "message": "Appointment not found.", "channels": {}}
        if appointment.status not in (AppointmentStatus.CONFIRMED, AppointmentStatus.ARRIVED):
            return {
                "success": False,
                "rate_limited": False,
                "message": f"This appointment is {appointment.status.value}, so there's nothing to resend.",
                "channels": {},
            }

        claimed = (
            db.execute(
                update(Appointment)
                .where(Appointment.id == appointment_id, Appointment.confirmation_resend_count < _MAX_RESEND_ATTEMPTS)
                .values(confirmation_resend_count=Appointment.confirmation_resend_count + 1)
            ).rowcount
            == 1
        )
        if not claimed:
            db.rollback()
            logger.info("resend_confirmation rate-limited: appointment_id=%s", appointment_id)
            return {"success": False, "rate_limited": True, "message": None, "channels": {}}
        db.commit()
        db.refresh(appointment)

        business = db.get(Business, business_id)
        customer = db.get(Customer, customer_id)

        channels = self._resolve_channels(channel, conversation_channel)
        results = {}
        if "email" in channels:
            results["email"] = self._send_email(db, appointment=appointment, business=business, customer=customer)
        if "whatsapp" in channels:
            results["whatsapp"] = self._send_whatsapp(db, appointment=appointment, business=business, customer=customer)

        logger.info(
            "resend_confirmation tool executed: appointment_id=%s attempt=%d channels=%s",
            appointment_id,
            appointment.confirmation_resend_count,
            {k: v["status"] for k, v in results.items()},
        )
        return {
            "success": any(r["status"] in ("sent", "simulated") for r in results.values()),
            "rate_limited": False,
            "message": None,
            "channels": results,
            "resend_count": appointment.confirmation_resend_count,
        }

    @staticmethod
    def _resolve_channels(channel: str | None, conversation_channel: str | None) -> set[str]:
        if channel == "both":
            return {"email", "whatsapp"}
        if channel in ("email", "whatsapp"):
            return {channel}
        # No explicit channel named — the sensible lazy default is "wherever
        # they're already talking to us", falling back to email (the
        # original delivery method) for every non-WhatsApp channel.
        return {"whatsapp"} if conversation_channel == "whatsapp" else {"email"}

    @staticmethod
    def _send_email(db: Session, *, appointment: Appointment, business: Business, customer: Customer) -> dict:
        if not customer.email:
            return {"attempted": False, "status": "no_recipient"}
        notification = Notification(
            business_id=business.id,
            appointment_id=appointment.id,
            channel="email",
            event_type="booking_confirmed",
            status=NotificationStatus.QUEUED,
        )
        db.add(notification)
        db.commit()
        db.refresh(notification)
        dispatch_notification(db, notification)
        db.refresh(notification)
        return {"attempted": True, "status": notification.status.value, "notification_id": str(notification.id)}

    @staticmethod
    def _send_whatsapp(db: Session, *, appointment: Appointment, business: Business, customer: Customer) -> dict:
        # Deferred import: whatsapp.py imports handle_incoming_message from
        # THIS module's own caller (orchestrator.py), which is what imports
        # appointment_tools.py in the first place to register its tools — a
        # module-top import here would be a real circular import at load
        # time. By the time this method actually runs, orchestrator.py has
        # long since finished importing.
        from app.services.channels.whatsapp import WhatsAppChannelAdapter

        # Prefer this customer's own real WhatsApp wa_id (ChannelIdentity,
        # channel="whatsapp") over customer.phone: the wa_id is Meta's own
        # real, already-country-coded identifier for them (confirmed the
        # moment they ever messaged in on WhatsApp), whereas customer.phone
        # may have been typed into a booking form on a different channel
        # with no country code at all — same real ambiguity
        # TwilioSMSProvider._normalize_phone already discloses for SMS, just
        # solved here with real, already-known data instead of a guess.
        whatsapp_identity = db.execute(
            select(ChannelIdentity.external_ref).where(
                ChannelIdentity.business_id == business.id,
                ChannelIdentity.channel == "whatsapp",
                ChannelIdentity.customer_id == customer.id,
            )
        ).scalar_one_or_none()
        to = whatsapp_identity or customer.phone
        if not to:
            return {"attempted": False, "status": "no_recipient"}
        integration = db.execute(
            select(Integration).where(
                Integration.business_id == business.id,
                Integration.type == "whatsapp",
                Integration.enabled.is_(True),
            )
        ).scalar_one_or_none()
        if integration is None or not (integration.config or {}).get("phone_number_id"):
            return {"attempted": False, "status": "not_connected"}
        config = integration.config or {}

        qr_png = generate_qr_png(str(appointment.checkin_token))
        detail = WhatsAppChannelAdapter().send_image_message(
            to=to,
            image_bytes=qr_png,
            mime_type="image/png",
            caption=f"Your check-in QR for {business.name}. Please show this at the clinic.",
            phone_number_id=config["phone_number_id"],
            access_token=config.get("access_token") or "",
        )
        if detail.startswith("sent "):
            status, notif_status = "sent", NotificationStatus.SENT
        elif detail.startswith("simulated"):
            status, notif_status = "simulated", NotificationStatus.SIMULATED
        else:
            status, notif_status = "failed", NotificationStatus.FAILED

        notification = Notification(
            business_id=business.id,
            appointment_id=appointment.id,
            channel="whatsapp",
            event_type="booking_confirmed",
            status=notif_status,
        )
        db.add(notification)
        db.commit()
        logger.info("resend_confirmation whatsapp send: appointment_id=%s detail=%s", appointment.id, detail)
        return {"attempted": True, "status": status, "notification_id": str(notification.id)}


TOOL_REGISTRY[ConversationIntent.CANCELLATION] = CancelAppointmentTool()
TOOL_REGISTRY[ConversationIntent.RESCHEDULING] = RescheduleAppointmentTool()
TOOL_REGISTRY[ConversationIntent.APPOINTMENT_STATUS] = AppointmentStatusTool()
TOOL_REGISTRY[ConversationIntent.RESEND_CONFIRMATION] = ResendConfirmationTool()
