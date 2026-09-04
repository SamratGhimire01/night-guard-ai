import uuid
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, ForeignKeyConstraint, String, UniqueConstraint
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.database import Base
from app.db.models.mixins import CreatedAtMixin, TenantMixin, UUIDPrimaryKeyMixin


class FollowUp(UUIDPrimaryKeyMixin, TenantMixin, CreatedAtMixin, Base):
    __tablename__ = "follow_ups"
    __table_args__ = (
        # customer_id and conversation_id must both belong to the same business_id as
        # this follow-up.
        ForeignKeyConstraint(
            ["customer_id", "business_id"],
            ["customers.id", "customers.business_id"],
            name="fk_follow_ups_customer_same_tenant",
        ),
        ForeignKeyConstraint(
            ["conversation_id", "business_id"],
            ["conversations.id", "conversations.business_id"],
            name="fk_follow_ups_conversation_same_tenant",
        ),
        # Phase 18: the real, DB-level anti-spam guarantee — at most ONE FollowUp
        # row can ever exist for a given conversation, full stop. This is what makes
        # "never send a duplicate follow-up" airtight even under a retried/duplicate
        # call, not just something application logic promises and could get wrong;
        # a second attempt hits IntegrityError and is handled as "already done."
        UniqueConstraint("conversation_id", name="uq_follow_ups_conversation_id"),
    )

    # No inline ForeignKey on these two: the composite fk_follow_ups_*_same_tenant
    # constraints above already enforce them against customers/conversations.
    customer_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), index=True, nullable=False)
    conversation_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), index=True, nullable=False)
    # Real values used by Phase 18: "sent" (real email sent), "failed" (real send
    # attempt failed), "skipped_no_consent" (no real, consented contact method —
    # see followup_service.py's consent-safety reasoning). Once written, permanent —
    # the unique constraint above means a conversation is never retried regardless
    # of outcome, matching "at most one follow-up per conversation, ever."
    status: Mapped[str] = mapped_column(String(50), nullable=False)
    scheduled_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    sent_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    # Phase 18: which channel was actually used — always "email" today (see
    # followup_service.py's consent-safety reasoning for why SMS is never used for
    # follow-ups), NULL when status="skipped_no_consent" (no channel was ever used).
    channel: Mapped[str | None] = mapped_column(String(50))
    # The real customer message whose detected_intent made this conversation a
    # candidate — real audit trail for "why did we follow up on this one." No
    # same-tenant composite FK is possible here (Message carries no business_id of
    # its own — tenant context is inherited via conversation_id, see Message's own
    # docstring), so this is a plain FK, not the composite pattern used elsewhere.
    trigger_message_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("messages.id", ondelete="SET NULL")
    )
