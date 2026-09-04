import enum
import uuid

from sqlalchemy import Enum, ForeignKey, ForeignKeyConstraint, String, Text, UniqueConstraint
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.database import Base
from app.db.models.mixins import CreatedAtMixin, TenantMixin, UpdatedAtMixin, UUIDPrimaryKeyMixin


class MessageSenderType(str, enum.Enum):
    CUSTOMER = "customer"
    AGENT = "agent"
    STAFF = "staff"


class Conversation(UUIDPrimaryKeyMixin, TenantMixin, CreatedAtMixin, UpdatedAtMixin, Base):
    __tablename__ = "conversations"
    __table_args__ = (
        # Lets HumanHandoff/FollowUp enforce that a conversation_id they reference
        # belongs to the same business_id.
        UniqueConstraint("id", "business_id", name="uq_conversations_id_business_id"),
        # customer_id must belong to the same business_id as this conversation.
        ForeignKeyConstraint(
            ["customer_id", "business_id"],
            ["customers.id", "customers.business_id"],
            name="fk_conversations_customer_same_tenant",
        ),
        # Phase 25a: same tenant-scoped-FK discipline as every other service_id
        # column in this codebase (see Appointment.service_id) — a NULL
        # booking_draft_service_id is not checked (Postgres MATCH SIMPLE),
        # which is the desired behavior while a draft has no service yet.
        ForeignKeyConstraint(
            ["booking_draft_service_id", "business_id"],
            ["services.id", "services.business_id"],
            name="fk_conversations_booking_draft_service_same_tenant",
        ),
    )

    # No inline ForeignKey here: the composite fk_conversations_customer_same_tenant
    # constraint below already enforces customer_id -> customers.id.
    customer_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), index=True, nullable=False)
    channel: Mapped[str] = mapped_column(String(50), nullable=False)
    status: Mapped[str] = mapped_column(String(50), nullable=False)
    # Phase 7: rolling LLM-generated summary of every message older than the most
    # recent "keep_recent" window (see app/memory/summarization.py). NULL until the
    # conversation first crosses the summarization threshold.
    summary: Mapped[str | None] = mapped_column(Text)
    # How many of this conversation's oldest messages (ordered by created_at) are
    # already folded into `summary` — lets re-summarization pick up only the newly
    # aged-out messages instead of re-summarizing the whole prefix every time.
    summarized_message_count: Mapped[int] = mapped_column(nullable=False, server_default="0")
    # Phase 25: the customer's language+script, locked in once detected (one of
    # ConversationLanguage's values) so every later turn — LLM-drafted or
    # deterministic — stays consistent instead of drifting. Plain string, not a
    # Postgres enum, same "not from the original spec" convention as
    # Message.detected_intent/Conversation.status — ConversationLanguage already
    # constrains it app-side. NULL until the first message with a clear signal.
    detected_language: Mapped[str | None] = mapped_column(String(20))
    # How many consecutive customer messages in a row have used a DIFFERENT
    # language/script than detected_language — orchestrator only actually
    # relocks once this crosses a real threshold (a sustained switch), never on
    # a single stray message. Reset to 0 whenever a message matches the lock.
    language_switch_streak: Mapped[int] = mapped_column(nullable=False, server_default="0")
    # Phase 25a: real, persisted slot-tracking for an in-progress single
    # booking (see orchestrator._merge_booking_draft/_resolve_booking_draft).
    # Root-cause fix for an infinite confirmation loop: the LLM's job each
    # turn is now ONLY to report whatever service/date/time THIS message
    # mentions, never to judge whether "enough" has been collected — these
    # three columns are what actually accumulate that across turns, so
    # readiness is a real, deterministic Python check instead of an LLM
    # guess it could hedge on forever. No inline ForeignKey on
    # booking_draft_service_id: the composite
    # fk_conversations_booking_draft_service_same_tenant constraint above
    # already enforces it. date/time stored as the same raw "YYYY-MM-DD"/
    # "HH:MM" strings the LLM extracts and _resolve_booking_datetime already
    # parses — format-validated before being written, never trusted as-is.
    # All three are cleared back to NULL the moment a real booking attempt
    # (success OR failure) actually runs, so a stale slot can never silently
    # resurface for a later, unrelated booking.
    booking_draft_service_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))
    booking_draft_date: Mapped[str | None] = mapped_column(String(10))
    booking_draft_time: Mapped[str | None] = mapped_column(String(5))


class Message(UUIDPrimaryKeyMixin, CreatedAtMixin, Base):
    """No business_id: tenant context is inherited via conversation_id."""

    __tablename__ = "messages"
    __table_args__ = (
        # Phase 22: real, DB-level webhook idempotency — see external_message_id
        # below. Named explicitly so downgrade() can drop it by name (the same
        # unnamed-constraint-breaks-downgrade bug Phase 3/18's migrations hit).
        UniqueConstraint("external_message_id", name="uq_messages_external_message_id"),
    )

    conversation_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("conversations.id", ondelete="CASCADE"), index=True, nullable=False
    )
    sender_type: Mapped[MessageSenderType] = mapped_column(
        Enum(MessageSenderType, name="message_sender_type"), nullable=False
    )
    content: Mapped[str] = mapped_column(Text, nullable=False)
    # Phase 18: the real Phase 8 ConversationIntent classification for this message
    # (customer messages only — see orchestrator.py), persisted so a later query
    # (follow-up detection) can ask "did this conversation ever show real interest"
    # from real historical data instead of re-classifying or guessing. Plain string,
    # not a Postgres enum, mirroring Conversation.status/HumanHandoff.status's existing
    # "field not from the original Phase 2 spec, don't hard-code its allowed values at
    # the DB level" convention — ConversationIntent already constrains it app-side.
    # NULL for every message that predates this phase (honest: we don't know their
    # intent) and for agent messages (intent is classified from what the CUSTOMER said).
    detected_intent: Mapped[str | None] = mapped_column(String(50))
    # Phase 22: the real external message id a channel's own delivery mechanism
    # assigns (e.g. a WhatsApp Cloud API "wamid...."). NULL for every channel
    # that doesn't have this concept (website widget, the direct testing
    # endpoint). `unique=True` on a nullable column is the real, DB-level
    # idempotency guarantee for at-least-once webhook delivery (Postgres treats
    # multiple NULLs as distinct, so this only ever constrains real, non-null
    # ids) — same discipline as Phase 10/18/19's constraints, not just an
    # application-level check a retry/duplicate webhook could bypass.
    external_message_id: Mapped[str | None] = mapped_column(String(255))
