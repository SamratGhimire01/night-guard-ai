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


class BusinessPlan(str, enum.Enum):
    """Phase 34: the real subscription tier every V2 premium feature (Google
    Calendar, payments, voice, yearly reports) will gate on. Two tiers, not a
    separate `Plan` table with its own rows — there is no real per-plan data
    to store yet (no price, no numeric limits; those aren't real requirements
    today, only speculative ones), so a table would just be wrapping this
    same enum with extra indirection. See `app.core.entitlements` for the
    ranking/gating logic and `PHASE_STATUS.md` Phase 34 for the full
    reasoning. If a third tier ever needs its own real configuration (not
    just a name), converting this into a proper table then is a normal,
    contained migration — not a rewrite."""

    FREE = "free"
    PREMIUM = "premium"


class Business(UUIDPrimaryKeyMixin, CreatedAtMixin, UpdatedAtMixin, Base):
    """A tenant. Every other tenant-owned table hangs off this via business_id."""

    __tablename__ = "businesses"

    name: Mapped[str] = mapped_column(String(255), nullable=False)
    timezone: Mapped[str] = mapped_column(String(64), nullable=False)
    # A real, business-owned currency code (e.g. "USD", "NPR") — a plain
    # freeform string, not an enum/ISO-4217-validated column, same "store
    # what's actually needed, no premature validation" precedent `timezone`
    # above already sets (that isn't checked against the IANA tz database
    # either). Defaults to "USD" so every pre-existing business's price
    # display is unchanged after migration; the LLM prompt and every price
    # display in chat/dashboard reads this instead of a hardcoded "$" — see
    # PHASE_STATUS.md for the real bug this fixes (a business's real prices
    # were shown with a hardcoded "$" regardless of this field's value,
    # because until this column existed there was no per-business currency
    # concept to read from at all).
    currency: Mapped[str] = mapped_column(String(10), nullable=False, default="USD", server_default="USD")
    description: Mapped[str | None] = mapped_column(Text)
    address: Mapped[str | None] = mapped_column(String(500))
    phone: Mapped[str | None] = mapped_column(String(50))
    email: Mapped[str | None] = mapped_column(String(255))
    website: Mapped[str | None] = mapped_column(String(255))
    languages: Mapped[list[str] | None] = mapped_column(ARRAY(String(16)))
    tone: Mapped[str | None] = mapped_column(String(100))
    # Phase 15: a raw, business-configurable feature toggle — NOT gated by
    # Business.plan below. Off by default — enabling it alone still doesn't
    # send a real text to any given customer unless that customer has ALSO
    # opted in (Customer.sms_opt_in) — see that column's comment for why.
    sms_enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default="false")
    # Phase 18: follow-up messages carry real spam risk (an unwanted "are you still
    # interested" nudge), so — same as sms_enabled — this defaults OFF and requires
    # explicit opt-in, never on by default.
    follow_ups_enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default="false")
    # Phase 34: the real subscription tier — every existing business defaults
    # to FREE (the lowest tier) on migration, never silently upgraded. Never
    # settable via BusinessUpdate/PATCH /business/me — the only writer is
    # app.services.plan_service.change_plan, reached only through the
    # superadmin-gated admin endpoints, so a business can never upgrade
    # itself for free.
    plan: Mapped[BusinessPlan] = mapped_column(
        Enum(BusinessPlan, name="business_plan"), nullable=False, default=BusinessPlan.FREE, server_default="FREE"
    )
    # Phase 38: widget branding, shown to anonymous visitors via the public
    # widget config endpoint (app/api/routes/widget.py) — same public-data
    # tier as `name` itself, not a secret. brand_color defaults to the
    # widget's original hardcoded blue so every pre-existing business keeps
    # the exact same look after migration.
    brand_color: Mapped[str] = mapped_column(String(7), nullable=False, default="#2563eb", server_default="#2563eb")
    logo_url: Mapped[str | None] = mapped_column(String(500))


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
    # Phase 34: a PLATFORM-level admin — unrelated to `role` above (owner/
    # admin/staff are scoped to this user's own single business; this is
    # scoped to nothing, it can act on ANY business). Deliberately reuses the
    # entire existing BusinessUser/login/JWT mechanism rather than a second
    # parallel auth system — a superadmin is just a BusinessUser row with
    # this flag set, still belonging to some ordinary business for login
    # purposes, but checked independently by `require_superadmin` (see
    # app/api/dependencies.py). Off by default; there is deliberately no API
    # to grant this to anyone — see PHASE_STATUS.md Phase 34 for why that's
    # an explicit, documented bootstrapping gap, not an oversight.
    is_superadmin: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default="false")


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
