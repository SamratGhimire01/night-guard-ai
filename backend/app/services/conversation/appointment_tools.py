import logging
import uuid
from datetime import datetime

from sqlalchemy.orm import Session

from app.core.exceptions import ConflictError, NotFoundError, UnprocessableEntityError
from app.memory.appointment_context import get_appointment_context
from app.schemas.conversation import ConversationIntent
from app.services import booking_service
from app.services.conversation.tools import TOOL_REGISTRY, ConversationTool

logger = logging.getLogger(__name__)


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


TOOL_REGISTRY[ConversationIntent.CANCELLATION] = CancelAppointmentTool()
TOOL_REGISTRY[ConversationIntent.RESCHEDULING] = RescheduleAppointmentTool()
TOOL_REGISTRY[ConversationIntent.APPOINTMENT_STATUS] = AppointmentStatusTool()
