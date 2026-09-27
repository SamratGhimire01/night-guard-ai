import logging
import uuid
from datetime import datetime, timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.exceptions import ConflictError, NotFoundError, UnprocessableEntityError
from app.db.models.appointment import Appointment
from app.db.models.business import Business
from app.db.models.conversation import Conversation
from app.db.models.customer import Customer
from app.db.models.notification import Notification, NotificationStatus
from app.db.models.payment import PaymentStatus
from app.schemas.conversation import ConversationIntent
from app.services import booking_service, payment_service, qr_link_service, service_service
from app.services.notifications import dispatch_notification
from app.services.conversation.tools import TOOL_REGISTRY, ConversationTool

logger = logging.getLogger(__name__)

# How many real alternative slots to offer back when a requested slot turns out
# to be unavailable — small and fixed, this is a chat reply, not a slot picker UI.
_ALTERNATIVES_COUNT = 5
_ALTERNATIVES_SEARCH_DAYS = 7


def queue_payment_request_email(db: Session, *, appointment: Appointment) -> None:
    """After the customer picks a gateway in chat, the booking-confirmation email (already sent, before there was a
    payment to mention) is followed by a `payment_requested` one carrying the real link and its QR — same
    Notification/dispatch pipeline and channel choice as every other booking notice. Never raises (dispatch itself
    doesn't)."""
    business = db.get(Business, appointment.business_id)
    customer = db.get(Customer, appointment.customer_id)
    notification = Notification(
        business_id=appointment.business_id,
        appointment_id=appointment.id,
        channel=booking_service._notification_channel(business, customer),
        event_type="payment_requested",
        status=NotificationStatus.QUEUED,
    )
    db.add(notification)
    db.commit()
    dispatch_notification(db, notification)


class BookAppointmentTool(ConversationTool):
    """The Phase 10 real write path. `run()` NEVER trusts that the requested slot
    is free — it always re-derives that from booking_service.create_appointment,
    which is itself backed by a DB exclusion constraint that makes the real
    race-condition guarantee (see the migration). This is the only thing in the
    whole orchestration flow allowed to write an Appointment row; the LLM only
    ever sees this method's return value, never a write path of its own."""

    name = "book_appointment"
    handles_intents = frozenset({ConversationIntent.BOOKING})

    def run(
        self,
        db: Session,
        *,
        business_id: uuid.UUID,
        customer_id: uuid.UUID,
        service_id: uuid.UUID,
        staff_id: uuid.UUID | None,
        scheduled_at: datetime,
        conversation_id: uuid.UUID | None = None,
        **kwargs,
    ) -> dict:
        conversation = db.get(Conversation, conversation_id) if conversation_id else None
        try:
            appointment = booking_service.create_appointment(
                db,
                business_id=business_id,
                customer_id=customer_id,
                service_id=service_id,
                staff_id=staff_id,
                scheduled_at=scheduled_at,
                source_channel=conversation.channel if conversation else None,
                # a chat booking can ask the customer which gateway to use; nothing else can
                defer_payment_choice=conversation_id is not None,
            )
        except (NotFoundError, UnprocessableEntityError, ConflictError) as exc:
            logger.info(
                "book_appointment failed: business_id=%s service_id=%s scheduled_at=%s reason=%s",
                business_id,
                service_id,
                scheduled_at,
                exc.message,
            )
            return {
                "success": False,
                "appointment": None,
                "message": exc.message,
                "alternative_slots": self._alternatives(
                    db, business_id=business_id, service_id=service_id, staff_id=staff_id, around=scheduled_at
                ),
            }

        return {
            "success": True,
            "appointment": {
                "id": str(appointment.id),
                "confirmation_code": appointment.confirmation_code,
                "service_id": str(appointment.service_id),
                "staff_id": str(appointment.staff_id) if appointment.staff_id else None,
                "scheduled_at": appointment.scheduled_at,
                "duration_minutes": appointment.duration_minutes,
            },
            "message": None,
            "alternative_slots": [],
            "confirmation": self._confirmation_info(db, appointment=appointment),
            "payment": self._payment_info(
                db,
                business_id=business_id,
                appointment=appointment,
                service_id=service_id,
                conversation_id=conversation_id,
            ),
        }

    @staticmethod
    def _confirmation_info(db: Session, *, appointment: Appointment) -> dict:
        """What the chat confirmation adds so it matches the confirmation email: the business's name/address/phone, the
        SAME signed check-in QR link a resend returns (qr_link_service — valid for a CONFIRMED appointment, deposit
        pending or not), and the customer's on-file email masked as a resend does — but only if the confirmation email
        was actually sent (booking_service queued and dispatched it just before this), so chat never claims an email
        that didn't go out."""
        business = db.get(Business, appointment.business_id)
        customer = db.get(Customer, appointment.customer_id)
        email_sent = customer.email and db.execute(
            select(Notification.id).where(
                Notification.appointment_id == appointment.id,
                Notification.event_type == "booking_confirmed",
                Notification.channel == "email",
                Notification.status.in_([NotificationStatus.SENT, NotificationStatus.SIMULATED]),
            )
        ).first()
        return {
            "place": " · ".join(filter(None, [business.name, business.address, business.phone])),
            "checkin_qr_url": qr_link_service.build_url(appointment.id, appointment.scheduled_at),
            "email_to": qr_link_service.mask_email(customer.email) if email_sent else None,
        }

    def _payment_info(
        self,
        db: Session,
        *,
        business_id: uuid.UUID,
        appointment: Appointment,
        service_id: uuid.UUID,
        conversation_id: uuid.UUID | None,
    ) -> dict | None:
        """Phase 44: reads back whatever payment_service.
        create_payment_for_appointment already decided during
        booking_service.create_appointment's own commit — never re-decides
        anything here. None whenever no real Payment row exists (free plan,
        toggle off, or this service has no deposit configured) — the ONLY
        thing that makes _format_booking_result able to honestly say nothing
        about payment for a booking that doesn't need it (see
        response_templates.py).

        Two shapes otherwise: a real pending Payment (`payment_url` + `qr_url` set), or — the business offers both
        eSewa and Khalti and none is chosen yet — `payment_url` None, which _format_booking_result turns into the
        "which one?" question. The conversation is remembered either way (on the Payment row, or as
        Conversation.payment_choice_appointment_id) so the customer's answer, and later the gateway-verified
        "payment received" message, both find their way back to this chat."""
        payment = payment_service.get_payment_for_appointment(
            db, business_id=business_id, appointment_id=appointment.id
        )
        service = service_service.get_service(db, business_id=business_id, service_id=service_id)
        if payment is None:
            conversation = db.get(Conversation, conversation_id) if conversation_id else None
            if conversation is None or not payment_service.awaits_provider_choice(db, appointment):
                return None
            conversation.payment_choice_appointment_id = appointment.id
            db.commit()
            amount = payment_service.deposit_amount(service)
            return {
                "amount": amount,
                "currency": db.get(Business, business_id).currency,
                "payment_url": None,
                "qr_url": None,
                "percentage": service.deposit_percentage,
                "remaining": service.price - amount,
            }
        if payment.status != PaymentStatus.PENDING:
            # A FAILED payment_url is never shown to a customer as something
            # to pay — the appointment is confirmed regardless (see Payment's
            # own docstring); staff sees the real failure in the dashboard's
            # pending-payments view instead.
            return None
        if conversation_id is not None and payment.conversation_id is None:
            payment.conversation_id = conversation_id
            db.commit()
        return {
            "amount": payment.amount,
            "currency": payment.currency,
            "payment_url": payment.payment_url,
            "qr_url": payment_service.qr_page_url(payment),
            "percentage": service.deposit_percentage if service else None,
            "remaining": (service.price - payment.amount) if service else None,
        }

    def run_group(
        self,
        db: Session,
        *,
        business_id: uuid.UUID,
        customer_id: uuid.UUID,
        people: list[dict],
        all_or_nothing: bool,
        source_channel: str | None = None,
        **kwargs,
    ) -> dict:
        """Phase 12: the group-booking write path. Every person's slot goes
        through the exact same booking_service.create_appointment validation as
        a solo booking — this only adds clustering (people sharing one slot
        share one Appointment row, see booking_service._cluster_group_people)
        and, when requested, all-or-nothing atomicity. Never trusts the LLM's
        claim that any of these slots are free."""
        return booking_service.create_group_appointments(
            db,
            business_id=business_id,
            customer_id=customer_id,
            people=people,
            all_or_nothing=all_or_nothing,
            source_channel=source_channel,
        )

    def _alternatives(
        self,
        db: Session,
        *,
        business_id: uuid.UUID,
        service_id: uuid.UUID,
        staff_id: uuid.UUID | None,
        around: datetime,
    ) -> list[datetime]:
        """A fresh, real get_available_slots call — never the LLM's guess — so a
        failure response can honestly offer real alternatives instead of just a
        bare "no"."""
        try:
            slots = booking_service.get_available_slots(
                db,
                business_id=business_id,
                service_id=service_id,
                staff_id=staff_id,
                date_from=around.date(),
                date_to=around.date() + timedelta(days=_ALTERNATIVES_SEARCH_DAYS),
            )
        except NotFoundError:
            return []
        return slots[:_ALTERNATIVES_COUNT]


TOOL_REGISTRY[ConversationIntent.BOOKING] = BookAppointmentTool()
