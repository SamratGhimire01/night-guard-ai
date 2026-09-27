import uuid
from datetime import datetime

from pydantic import BaseModel, Field


class TakeoverState(BaseModel):
    """Who, if anyone, currently owns a conversation instead of the AI. `active` is derived from the clock, so a takeover
    whose 2h window has run out reads as inactive even though the columns still hold the last values."""

    active: bool
    until: datetime | None
    taken_over_by: uuid.UUID | None


class ReplyWindow(BaseModel):
    """Whether a staff reply can reach the customer right now. `reason` is shown to staff as-is when `can_reply` is false."""

    can_reply: bool
    reason: str | None = None
    window_closes_at: datetime | None = None


class InboxHandoff(BaseModel):
    id: uuid.UUID
    reason: str


class InboxConversation(BaseModel):
    id: uuid.UUID
    channel: str
    customer_id: uuid.UUID
    customer_name: str
    customer_phone: str | None = None
    customer_email: str | None = None
    takeover: TakeoverState
    takeover_by_email: str | None = None  # who owns it (only while the takeover is active), for "Sita is handling this"
    reply: ReplyWindow
    open_handoff: InboxHandoff | None = None
    last_customer_message_at: datetime | None = None
    lead_signal: str | None = None  # "high" | "medium" | "low" | None -- see app/services/lead_service.py
    lead_summary: str | None = None


class InboxMessage(BaseModel):
    id: uuid.UUID
    sender_type: str  # customer | agent (the AI) | staff
    content: str
    created_at: datetime
    delivery_status: str | None = None  # sent | simulated | failed | suppressed | pending | None (no delivery info)
    delivery_detail: str | None = None
    sent_by_user_id: uuid.UUID | None = None
    sent_by_email: str | None = None


class ReplyRequest(BaseModel):
    content: str
    # client-generated idempotency key (e.g. a uuid per composer submit): retrying the SAME key never sends twice
    client_msg_id: str | None = Field(default=None, min_length=1, max_length=64)


class InboxListItem(BaseModel):
    id: uuid.UUID
    channel: str
    customer_name: str
    last_message_preview: str
    last_message_sender: str  # customer | agent | staff
    last_message_at: datetime
    last_message_delivery_status: str | None = None
    needs_reply: bool  # a human owns it / it was escalated, and the customer spoke last
    unread: bool  # the customer's latest message is newer than the last time staff opened it
    open_handoff: bool
    takeover_active: bool
    takeover_by_email: str | None = None
    lead_signal: str | None = None  # "high" | "medium" | "low" | None -- see app/services/lead_service.py


class InboxSummary(BaseModel):
    needs_reply: int
    handoffs: int
    leads: int
