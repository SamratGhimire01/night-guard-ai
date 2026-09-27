import uuid
from abc import ABC, abstractmethod
from typing import TYPE_CHECKING

from sqlalchemy.orm import Session

from app.schemas.conversation import ConversationIntent

if TYPE_CHECKING:
    from app.db.models.business import Business

# Master-plan rule: the LLM is never the source of truth and never mutates data
# directly. A ConversationTool is the only thing allowed to touch business data
# on the LLM's behalf — the orchestrator calls tool.run() itself, hands the LLM
# only the structured result, and the LLM never gets a write path of its own.
#
# TOOL_REGISTRY was deliberately EMPTY in Phase 8, which is what made the
# orchestrator's honesty guardrail testable then rather than something bolted
# on later. Phase 10 registered the first real tool (BookAppointmentTool, in
# booking_tool.py, against ConversationIntent.BOOKING); Phase 11 registers
# CancelAppointmentTool / RescheduleAppointmentTool (in appointment_tools.py)
# against CANCELLATION/RESCHEDULING the same way — this file and the
# orchestrator's find_tool() call never needed to change, exactly as planned.


class ConversationTool(ABC):
    name: str
    handles_intents: frozenset[ConversationIntent]

    @abstractmethod
    def run(self, db: Session, *, business_id: uuid.UUID, customer_id: uuid.UUID, **kwargs) -> dict:
        """Executes the real action and returns a structured result describing
        what actually happened. Never invoked by the LLM directly."""


TOOL_REGISTRY: dict[ConversationIntent, ConversationTool] = {}


def find_tool(intent: ConversationIntent, business: "Business | None" = None) -> ConversationTool | None:
    """Phase 58: every tool ever registered here is booking-family (booking/cancel/
    reschedule/appointment-status/resend-confirmation — see TOOL_REGISTRY above), so
    `business.booking_enabled == False` hard-refuses ALL of them, regardless of what the
    LLM classified this turn. This is the real code-level backstop; intent.py's
    exclusion of these intents from the LLM's own intent_list is the (best-effort, not
    load-bearing) prompt-level half of the same gate."""
    if business is not None and not business.booking_enabled:
        return None
    return TOOL_REGISTRY.get(intent)
