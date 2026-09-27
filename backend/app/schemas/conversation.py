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
    # A customer explicitly asking to have their appointment confirmation
    # and/or check-in QR (re)sent, to WhatsApp, email, or both — see
    # ResendConfirmationTool (app/services/conversation/appointment_tools.py).
    RESEND_CONFIRMATION = "resend_confirmation"
    BUSINESS_HOURS = "business_hours"
    LOCATION = "location"
    COMPLAINT = "complaint"
    HUMAN_HANDOFF = "human_handoff"
    FOLLOW_UP = "follow_up"
    # Phase 24 urgent fix: anything clearly unrelated to this business (general
    # knowledge/trivia, other companies, personal advice, etc.) — never
    # answered, never treated as a knowledge gap. See handoff_service's
    # _INFO_INTENTS: deliberately NOT included there, so this can never
    # trigger a HumanHandoff — an out-of-scope question isn't something staff
    # need to follow up on.
    OFF_TOPIC = "off_topic"
    UNKNOWN = "unknown"


class ConversationLanguage(str, enum.Enum):
    """Phase 25: the customer's language+script, detected from their early
    messages and locked for the rest of the conversation
    (Conversation.detected_language) so every response — LLM-drafted or
    deterministic — stays in one consistent lane instead of drifting turn to
    turn. "mixed" (genuinely code-mixed Nepali/English) is a real locked
    choice, not a fallback — see response_templates.py for how deterministic
    sentences render each value."""
    EN = "en"
    NE_DEVA = "ne_deva"
    NE_ROMAN = "ne_roman"
    MIXED = "mixed"


class IncomingMessageCreate(BaseModel):
    content: str

    @field_validator("content")
    @classmethod
    def not_blank(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("This field must not be blank.")
        return value


class OrchestratedMessageResponse(BaseModel):
    # intent/response/agent_message_id are None when a staff member owns the conversation (Phase 52): the customer message
    # was stored, the AI drafted nothing. `intent` may still be set if the LLM had classified it before takeover was noticed.
    intent: ConversationIntent | None = None
    response: str | None = None
    customer_message_id: uuid.UUID
    agent_message_id: uuid.UUID | None = None
