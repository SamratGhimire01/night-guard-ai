import logging
import uuid
from datetime import datetime, timedelta

from sqlalchemy.orm import Session

from app.core.exceptions import ConflictError, NotFoundError, UnprocessableEntityError
from app.schemas.conversation import ConversationIntent
from app.services import booking_service
from app.services.conversation.tools import TOOL_REGISTRY, ConversationTool

logger = logging.getLogger(__name__)

# How many real alternative slots to offer back when a requested slot turns out
# to be unavailable — small and fixed, this is a chat reply, not a slot picker UI.
_ALTERNATIVES_COUNT = 5
_ALTERNATIVES_SEARCH_DAYS = 7


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
        **kwargs,
    ) -> dict:
        try:
            appointment = booking_service.create_appointment(
                db,
                business_id=business_id,
                customer_id=customer_id,
                service_id=service_id,
                staff_id=staff_id,
                scheduled_at=scheduled_at,
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
                "service_id": str(appointment.service_id),
                "staff_id": str(appointment.staff_id) if appointment.staff_id else None,
                "scheduled_at": appointment.scheduled_at,
                "duration_minutes": appointment.duration_minutes,
            },
            "message": None,
            "alternative_slots": [],
        }

    def run_group(
        self,
        db: Session,
        *,
        business_id: uuid.UUID,
        customer_id: uuid.UUID,
        people: list[dict],
        all_or_nothing: bool,
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
