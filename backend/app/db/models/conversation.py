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
    )

    # No inline ForeignKey here: the composite fk_conversations_customer_same_tenant
    # constraint below already enforces customer_id -> customers.id.
    customer_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), index=True, nullable=False)
    channel: Mapped[str] = mapped_column(String(50), nullable=False)
    status: Mapped[str] = mapped_column(String(50), nullable=False)


class Message(UUIDPrimaryKeyMixin, CreatedAtMixin, Base):
    """No business_id: tenant context is inherited via conversation_id."""

    __tablename__ = "messages"

    conversation_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("conversations.id", ondelete="CASCADE"), index=True, nullable=False
    )
    sender_type: Mapped[MessageSenderType] = mapped_column(
        Enum(MessageSenderType, name="message_sender_type"), nullable=False
    )
    content: Mapped[str] = mapped_column(Text, nullable=False)
