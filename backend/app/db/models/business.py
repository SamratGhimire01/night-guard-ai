import enum
from datetime import date, time

from sqlalchemy import Boolean, CheckConstraint, Date, Enum, String, Text, Time, UniqueConstraint
from sqlalchemy.dialects.postgresql import ARRAY
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
    description: Mapped[str | None] = mapped_column(Text)
    address: Mapped[str | None] = mapped_column(String(500))
    phone: Mapped[str | None] = mapped_column(String(50))
    email: Mapped[str | None] = mapped_column(String(255))
    website: Mapped[str | None] = mapped_column(String(255))
    languages: Mapped[list[str] | None] = mapped_column(ARRAY(String(16)))
    tone: Mapped[str | None] = mapped_column(String(100))
    # Phase 15: premium-tier toggle. Off by default — enabling it alone still
    # doesn't send a real text to any given customer unless that customer has
    # ALSO opted in (Customer.sms_opt_in) — see that column's comment for why.
    sms_enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default="false")
    # Phase 18: follow-up messages carry real spam risk (an unwanted "are you still
    # interested" nudge), so — same as sms_enabled — this defaults OFF and requires
    # explicit opt-in, never on by default.
    follow_ups_enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default="false")


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


_VALID_HOURS_RANGE_SQL = "closed OR (open_time IS NOT NULL AND close_time IS NOT NULL AND close_time > open_time)"


class BusinessHours(UUIDPrimaryKeyMixin, TenantMixin, Base):
    """Weekly operating hours. One row per day of the week per business (PUT replaces all 7)."""

    __tablename__ = "business_hours"
    __table_args__ = (
        CheckConstraint("day_of_week >= 0 AND day_of_week <= 6", name="ck_business_hours_day_of_week"),
        CheckConstraint(_VALID_HOURS_RANGE_SQL, name="ck_business_hours_valid_range"),
        UniqueConstraint("business_id", "day_of_week", name="uq_business_hours_business_day"),
    )

    day_of_week: Mapped[int] = mapped_column(nullable=False)
    closed: Mapped[bool] = mapped_column(nullable=False, default=False, server_default="false")
    open_time: Mapped[time | None] = mapped_column(Time)
    close_time: Mapped[time | None] = mapped_column(Time)


class BusinessHoursException(UUIDPrimaryKeyMixin, TenantMixin, Base):
    """A one-off override for a single date (holiday closure or custom hours)."""

    __tablename__ = "business_hours_exceptions"
    __table_args__ = (
        CheckConstraint(_VALID_HOURS_RANGE_SQL, name="ck_business_hours_exceptions_valid_range"),
        UniqueConstraint("business_id", "date", name="uq_business_hours_exceptions_business_date"),
    )

    date: Mapped[date] = mapped_column(Date, nullable=False)
    closed: Mapped[bool] = mapped_column(nullable=False, default=True, server_default="true")
    open_time: Mapped[time | None] = mapped_column(Time)
    close_time: Mapped[time | None] = mapped_column(Time)
