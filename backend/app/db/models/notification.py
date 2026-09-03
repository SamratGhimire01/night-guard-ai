import enum
import uuid

from sqlalchemy import Enum, ForeignKeyConstraint, String
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.database import Base
from app.db.models.mixins import CreatedAtMixin, TenantMixin, UUIDPrimaryKeyMixin


class NotificationStatus(str, enum.Enum):
    QUEUED = "queued"
    SENT = "sent"
    DELIVERED = "delivered"
    FAILED = "failed"


class Notification(UUIDPrimaryKeyMixin, TenantMixin, CreatedAtMixin, Base):
    __tablename__ = "notifications"
    __table_args__ = (
        # appointment_id, when present, must belong to the same business_id as this
        # notification. NULL appointment_id is not checked (Postgres default MATCH SIMPLE).
        ForeignKeyConstraint(
            ["appointment_id", "business_id"],
            ["appointments.id", "appointments.business_id"],
            name="fk_notifications_appointment_same_tenant",
        ),
    )

    # No inline ForeignKey here: the composite fk_notifications_appointment_same_tenant
    # constraint above already enforces appointment_id -> appointments.id.
    appointment_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), index=True)
    channel: Mapped[str] = mapped_column(String(50), nullable=False)
    status: Mapped[NotificationStatus] = mapped_column(
        Enum(NotificationStatus, name="notification_status"), nullable=False
    )
