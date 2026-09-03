import uuid
from datetime import datetime

from sqlalchemy import DateTime, ForeignKeyConstraint, String
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
    )

    # No inline ForeignKey on these two: the composite fk_follow_ups_*_same_tenant
    # constraints above already enforce them against customers/conversations.
    customer_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), index=True, nullable=False)
    conversation_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), index=True, nullable=False)
    status: Mapped[str] = mapped_column(String(50), nullable=False)
    scheduled_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    sent_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
