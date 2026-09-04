import uuid

from sqlalchemy import ForeignKeyConstraint, String, UniqueConstraint
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.database import Base
from app.db.models.mixins import CreatedAtMixin, TenantMixin, UUIDPrimaryKeyMixin


class ChannelIdentity(UUIDPrimaryKeyMixin, TenantMixin, CreatedAtMixin, Base):
    """Phase 21: the real, generic "which Customer is this external contact"
    mapping every ChannelAdapter (website widget now; WhatsApp/Messenger/
    Instagram later) shares — this table, not a channel-specific column
    bolted onto Customer, is what lets a future channel plug into the SAME
    conversation engine without inventing its own identity-resolution logic.

    `external_ref` is whatever a channel's adapter uses to recognize the same
    real-world contact across messages: a WhatsApp phone number, a Messenger
    PSID — or, for the website widget, the SHA-256 hash of a random session
    token (never the raw token itself; see channels/widget_service.py for why
    hashing at rest matters specifically for a bearer-style secret like this,
    unlike a phone number which isn't a secret).
    """

    __tablename__ = "channel_identities"
    __table_args__ = (
        # One identity per (business, channel, external contact) — this is
        # what "find-or-create" actually keys off; a second insert attempt
        # for the same triple is a real bug, not something app logic should
        # paper over.
        UniqueConstraint("business_id", "channel", "external_ref", name="uq_channel_identities_business_channel_ref"),
        ForeignKeyConstraint(
            ["customer_id", "business_id"],
            ["customers.id", "customers.business_id"],
            name="fk_channel_identities_customer_same_tenant",
        ),
    )

    channel: Mapped[str] = mapped_column(String(50), nullable=False)
    external_ref: Mapped[str] = mapped_column(String(255), nullable=False)
    # No inline ForeignKey here: the composite fk_channel_identities_customer_same_tenant
    # constraint above already enforces customer_id -> customers.id.
    customer_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), index=True, nullable=False)
