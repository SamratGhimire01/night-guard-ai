import uuid
from datetime import datetime

from sqlalchemy import DateTime, ForeignKeyConstraint, Index, String, Text, UniqueConstraint, text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.database import Base
from app.db.models.mixins import CreatedAtMixin, TenantMixin, UUIDPrimaryKeyMixin


class HumanHandoff(UUIDPrimaryKeyMixin, TenantMixin, CreatedAtMixin, Base):
    __tablename__ = "human_handoffs"
    __table_args__ = (
        UniqueConstraint("id", "business_id", name="uq_human_handoffs_id_business_id"),
        # conversation_id must belong to the same business_id as this handoff.
        ForeignKeyConstraint(
            ["conversation_id", "business_id"],
            ["conversations.id", "conversations.business_id"],
            name="fk_human_handoffs_conversation_same_tenant",
        ),
        # Phase 19: the real, DB-level anti-spam guarantee — at most one OPEN
        # (resolved_at IS NULL) handoff per conversation. Deliberately NOT a
        # flat UniqueConstraint like Phase 18's FollowUp ("at most one EVER"):
        # a handoff must be re-raisable after resolution — a customer can
        # genuinely need escalation again later in the same conversation, and
        # a flat constraint would permanently block that. A PARTIAL unique
        # index (only over still-open rows) enforces "no duplicate open
        # escalation" while still allowing a new row once the old one is
        # resolved — a real Postgres constraint a race/retry can't bypass,
        # not just an application-level check.
        Index(
            "uq_human_handoffs_conversation_id_open",
            "conversation_id",
            unique=True,
            postgresql_where=text("resolved_at IS NULL"),
        ),
    )

    # No inline ForeignKey here: the composite fk_human_handoffs_conversation_same_tenant
    # constraint above already enforces conversation_id -> conversations.id.
    conversation_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), index=True, nullable=False)
    reason: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[str] = mapped_column(String(50), nullable=False)
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
