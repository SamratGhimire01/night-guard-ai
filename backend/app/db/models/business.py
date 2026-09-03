import enum
from datetime import time

from sqlalchemy import CheckConstraint, Enum, String, Time, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.db.database import Base
from app.db.models.mixins import CreatedAtMixin, TenantMixin, UpdatedAtMixin, UUIDPrimaryKeyMixin


class BusinessUserRole(str, enum.Enum):
    OWNER = "owner"
    ADMIN = "admin"
    STAFF = "staff"


class Business(UUIDPrimaryKeyMixin, CreatedAtMixin, UpdatedAtMixin, Base):
    """A tenant. Every other tenant-owned table hangs off this via business_id."""

    __tablename__ = "businesses"

    name: Mapped[str] = mapped_column(String(255), nullable=False)
    timezone: Mapped[str] = mapped_column(String(64), nullable=False)
    address: Mapped[str | None] = mapped_column(String(500))
    phone: Mapped[str | None] = mapped_column(String(50))
    email: Mapped[str | None] = mapped_column(String(255))
    website: Mapped[str | None] = mapped_column(String(255))


class BusinessUser(UUIDPrimaryKeyMixin, TenantMixin, CreatedAtMixin, Base):
    """A login for a business's own staff/owner/admin.

    email is globally unique (not just per-business): login resolves a user by
    email alone, with no business_id available yet at that point, so two
    businesses cannot register the same email.
    """

    __tablename__ = "business_users"
    __table_args__ = (UniqueConstraint("email", name="uq_business_users_email"),)

    email: Mapped[str] = mapped_column(String(255), nullable=False)
    hashed_password: Mapped[str] = mapped_column(String(255), nullable=False)
    role: Mapped[BusinessUserRole] = mapped_column(
        Enum(BusinessUserRole, name="business_user_role"), nullable=False
    )


class BusinessHours(UUIDPrimaryKeyMixin, TenantMixin, Base):
    """Weekly operating hours. One row per open day per business."""

    __tablename__ = "business_hours"
    __table_args__ = (
        CheckConstraint("day_of_week >= 0 AND day_of_week <= 6", name="ck_business_hours_day_of_week"),
    )

    day_of_week: Mapped[int] = mapped_column(nullable=False)
    open_time: Mapped[time] = mapped_column(Time, nullable=False)
    close_time: Mapped[time] = mapped_column(Time, nullable=False)
