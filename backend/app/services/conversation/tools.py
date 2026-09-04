import uuid
from abc import ABC, abstractmethod

from sqlalchemy.orm import Session

from app.schemas.conversation import ConversationIntent

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


def find_tool(intent: ConversationIntent) -> ConversationTool | None:
    return TOOL_REGISTRY.get(intent)
