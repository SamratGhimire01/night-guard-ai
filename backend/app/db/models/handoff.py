import uuid
from datetime import datetime

from sqlalchemy import DateTime, ForeignKeyConstraint, String, Text, UniqueConstraint
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
    )

    # No inline ForeignKey here: the composite fk_human_handoffs_conversation_same_tenant
    # constraint above already enforces conversation_id -> conversations.id.
    conversation_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), index=True, nullable=False)
    reason: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[str] = mapped_column(String(50), nullable=False)
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
