import enum
import uuid

from pydantic import BaseModel, field_validator


class ConversationIntent(str, enum.Enum):
    GREETING = "greeting"
    GENERAL_QUESTION = "general_question"
    SERVICE_QUESTION = "service_question"
    PRICING_QUESTION = "pricing_question"
    BOOKING = "booking"
    RESCHEDULING = "rescheduling"
    CANCELLATION = "cancellation"
    APPOINTMENT_STATUS = "appointment_status"
    BUSINESS_HOURS = "business_hours"
    LOCATION = "location"
    COMPLAINT = "complaint"
    HUMAN_HANDOFF = "human_handoff"
    FOLLOW_UP = "follow_up"
    UNKNOWN = "unknown"


class IncomingMessageCreate(BaseModel):
    content: str

    @field_validator("content")
    @classmethod
    def not_blank(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("This field must not be blank.")
        return value


class OrchestratedMessageResponse(BaseModel):
    intent: ConversationIntent
    response: str
    customer_message_id: uuid.UUID
    agent_message_id: uuid.UUID
