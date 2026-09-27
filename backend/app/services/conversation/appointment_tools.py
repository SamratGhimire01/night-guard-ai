import logging
import uuid
from datetime import datetime

from sqlalchemy import update
from sqlalchemy.orm import Session

from app.core.exceptions import ConflictError, NotFoundError, UnprocessableEntityError
from app.core.rate_limit import RateLimiter
from app.db.models.appointment import Appointment, AppointmentStatus
from app.db.models.business import Business
from app.db.models.customer import Customer
from app.db.models.notification import Notification, NotificationStatus
from app.memory.appointment_context import get_appointment_context
from app.schemas.conversation import ConversationIntent
from app.services import booking_service, qr_link_service
from app.services.conversation.tools import TOOL_REGISTRY, ConversationTool
from app.services.notifications import dispatch_notification

logger = logging.getLogger(__name__)

# Real abuse guard, same "cap, not unlimited" discipline as Phase 18's
# follow-up limit — enforced by a single atomic UPDATE (see
# ResendConfirmationTool.run), never a check-then-act race.
_MAX_RESEND_ATTEMPTS = 3
# Failed sends are refunded (below) so an outage can't burn a customer's real 3; this separate guard bounds the retries
# a refund would otherwise make free. ponytail: in-memory, per process (rate_limit.py's documented limitation), Redis if scaled.
_MAX_FAILED_RESENDS = 5
_FAILED_RESEND_WINDOW_SECONDS = 300
_failed_resend_limiter = RateLimiter(max_attempts=_MAX_FAILED_RESENDS, window_seconds=_FAILED_RESEND_WINDOW_SECONDS)

# Conversation channels where the QR link can simply be answered in the chat itself.
_CHAT_CHANNELS = frozenset({"whatsapp", "messenger", "instagram", "website"})  # "website" = the embedded widget (widget_service)
# A resend's destination is never an input — see ResendConfirmationTool's docstring.
_CALLER_SUPPLIED_DESTINATIONS = frozenset({"to", "email", "phone", "destination", "recipient", "address"})


def _serialize(appointment) -> dict:
    return {
        "id": str(appointment.id),
        "confirmation_code": appointment.confirmation_code,
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
    """The real write path for a customer explicitly asking to have their appointment confirmation and/or check-in QR
    (re)sent. Same master-plan discipline as every other tool: the LLM only ever identifies the intent + which
    appointment/channel (see intent.py rule 18); this class is the only thing that actually sends anything or touches
    `confirmation_resend_count`.

    Two delivery types, both derived ONLY from data already in the database:
      * "email"  — the existing Phase 13/44/46 pipeline (a real Notification row + dispatch_notification, the
        CID-embedded QR content.py already composes for booking_confirmed), sent to the email ALREADY ON FILE.
      * "chat"   — "QR in chat": a signed, expiring link (qr_link_service) to a small page that shows the same QR. The
        link is returned to the orchestrator, which puts it in the reply, so it reaches the customer in the very chat
        they're using — identically on WhatsApp, Messenger, Instagram and the website widget (a plain https link; the
        Meta Media API image-upload flow is deliberately not used).

    SECURITY (non-negotiable): the destination of a resend is never a caller input. `run()` takes no `to`/`email`/
    `phone` and refuses them outright; email always goes to `Customer.email` as it is in the database at send time,
    and the chat link goes into the requesting conversation's own reply. A destination typed into the chat is at most a
    separate "update my contact info" action (the orchestrator ignores any contact update on a resend turn and says so).

    Rate limit is ONE shared counter per appointment: a single atomic UPDATE (`confirmation_resend_count < 3`) claims a
    slot per REQUEST, however many delivery types it covers, same "the guarantee lives in one SQL statement's WHERE
    clause, not application logic a race could slip past" discipline as reminder_sent_at/checked_in_at
    (app/db/models/appointment.py) — claimed BEFORE any real send is attempted, so retrying a slow request can never
    double-charge the cap. If the send then FAILS on every
    channel (nothing delivered), the slot is refunded; a separate in-memory guard (5 failed sends / 5 min per
    appointment) stops that refund becoming unlimited retries.
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
        forbidden = kwargs.keys() & _CALLER_SUPPLIED_DESTINATIONS
        if forbidden:
            raise ValueError(f"a resend destination is never caller-supplied (got {sorted(forbidden)})")
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

        if _failed_resend_limiter.is_blocked(str(appointment_id)):
            logger.info("resend_confirmation throttled after repeated failed sends: appointment_id=%s", appointment_id)
            return {"success": False, "rate_limited": False, "throttled": True, "message": None, "channels": {}}

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
        if "chat" in channels:
            results["chat"] = self._chat_link(appointment)

        success = any(r["status"] in ("sent", "simulated") for r in results.values())
        if not success and any(r["status"] == "failed" for r in results.values()):
            # A real send was attempted and nothing was delivered: give the customer their slot back (atomic, floor 0).
            db.execute(
                update(Appointment)
                .where(Appointment.id == appointment_id, Appointment.confirmation_resend_count > 0)
                .values(confirmation_resend_count=Appointment.confirmation_resend_count - 1)
            )
            db.commit()
            db.refresh(appointment)
            _failed_resend_limiter.record_attempt(str(appointment_id))

        logger.info(
            "resend_confirmation tool executed: appointment_id=%s attempt=%d channels=%s",
            appointment_id,
            appointment.confirmation_resend_count,
            {k: v["status"] for k, v in results.items()},
        )
        return {
            "success": success,
            "rate_limited": False,
            "message": None,
            "channels": results,
            "resend_count": appointment.confirmation_resend_count,
        }

    @staticmethod
    def _resolve_channels(channel: str | None, conversation_channel: str | None) -> set[str]:
        """"email" = the on-file email; "chat" = the QR link in this very conversation. The LLM's "whatsapp" (or an
        unset channel on a chat channel) means "here, in the chat": we can only ever answer in the conversation the
        request came from, never push to a destination the customer named."""
        if channel == "both":
            return {"email", "chat"}
        if channel == "email":
            return {"email"}
        if channel in ("whatsapp", "chat"):
            return {"chat"}
        return {"chat"} if conversation_channel in _CHAT_CHANNELS else {"email"}

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
        return {
            "attempted": True,
            "status": notification.status.value,
            "notification_id": str(notification.id),
            "to": qr_link_service.mask_email(customer.email),
        }

    @staticmethod
    def _chat_link(appointment: Appointment) -> dict:
        return {
            "attempted": True,
            "status": "sent",
            "url": qr_link_service.build_url(appointment.id, appointment.scheduled_at),
        }


TOOL_REGISTRY[ConversationIntent.CANCELLATION] = CancelAppointmentTool()
TOOL_REGISTRY[ConversationIntent.RESCHEDULING] = RescheduleAppointmentTool()
TOOL_REGISTRY[ConversationIntent.APPOINTMENT_STATUS] = AppointmentStatusTool()
TOOL_REGISTRY[ConversationIntent.RESEND_CONFIRMATION] = ResendConfirmationTool()
