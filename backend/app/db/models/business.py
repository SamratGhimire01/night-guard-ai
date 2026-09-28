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


class LanguageMode(str, enum.Enum):
    """How a business's chat handles the customer's language. AUTOMATIC = today's behavior (match the customer's own
    language, lock it, follow a sustained change). ASK = the very first reply of a new conversation asks the customer which
    language they prefer and locks to the answer; only an explicit "switch to X" request changes it afterwards."""

    AUTOMATIC = "automatic"
    ASK = "ask"


class BusinessFormality(str, enum.Enum):
    """Phase 2 (style exemplars): a small, fixed formality register the persona
    card nudges the system prompt with. NEUTRAL is the default and, since
    intent.py only appends an instruction when this differs from NEUTRAL, is
    exactly today's unmodified behavior."""

    CASUAL = "casual"
    NEUTRAL = "neutral"
    FORMAL = "formal"


class EmojiPolicy(str, enum.Enum):
    """DEFAULT keeps intent.py rule 4's existing single-emoji-in-warm-moments
    behavior unchanged (the default for every business). NONE hard-overrides
    it to never use emoji at all, regardless of rule 4."""

    DEFAULT = "default"
    NONE = "none"


class ContentScope(str, enum.Enum):
    """Phase 54: whether naming another named organization/institution in a customer
    question is itself a sign of real scope drift. SINGLE_BUSINESS (the default,
    every existing tenant) is today's behavior — a single local business (a dental
    clinic, a salon) where that really is out of scope, so intent.py's off_topic
    rule fires on it. AGGREGATOR is for an info-hub tenant whose own real content
    is inherently ABOUT other named institutions (a college/exam/notice aggregator
    naming Kathmandu University, Tribhuvan University, etc.) — see intent.py's
    system prompt for exactly how this relaxes the off_topic rule. See
    PHASE_STATUS.md Phase 53/54 for the real SikshyaNepal false-positive this
    fixes."""

    SINGLE_BUSINESS = "single_business"
    AGGREGATOR = "aggregator"


class Business(UUIDPrimaryKeyMixin, CreatedAtMixin, UpdatedAtMixin, Base):
    """A tenant. Every other tenant-owned table hangs off this via business_id."""

    __tablename__ = "businesses"

    name: Mapped[str] = mapped_column(String(255), nullable=False)
    timezone: Mapped[str] = mapped_column(String(64), nullable=False)
    # A real, business-owned currency code (e.g. "USD", "NPR") — a plain
    # string column, no Postgres enum, so growing the supported set never
    # needs a migration. Validated at the API layer instead
    # (BusinessUpdate.valid_currency / valid_timezone, app/schemas/
    # business.py) against a curated allowlist / the real IANA tz database —
    # added by the Business Profile Settings page (2026-09-07) to close the
    # free-text-typo class of bug. Defaults to "USD" so every pre-existing
    # business's price
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
    # Phase 44: real eSewa/Khalti payment collection — a Premium-gated toggle,
    # off by default (same "never on by default" discipline as sms_enabled/
    # follow_ups_enabled above). Only writable via the dedicated, plan-gated
    # PATCH /business/payment-settings route (app/api/routes/payments.py),
    # never the generic PATCH /business/me — a Free-plan business must never
    # be able to flip this on itself, the same reasoning that keeps `plan`
    # itself off BusinessUpdate.
    payment_collection_enabled: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default="false"
    )
    # Which gateways this business offers, any subset of {"esewa", "khalti"} — both may be on at once, in which case a
    # chat customer is asked which they'd like (see payment_service.create_payment_for_appointment). Empty whenever
    # payment_collection_enabled is false — enforced at the schema layer (PaymentSettingsUpdate), not a DB CHECK.
    payment_providers: Mapped[list[str]] = mapped_column(
        ARRAY(String(20)), nullable=False, default=list, server_default="{}"
    )
    # Phase 45: appointment reminders — off by default (same "never on by
    # default" discipline as sms_enabled/follow_ups_enabled), and, unlike
    # payment_collection_enabled, NOT plan-gated: Phase 34's own PLAN_FEATURES
    # already lists "Automated email notifications and reminders" under the
    # FREE tier (app/core/entitlements.py), so this is a plain owner/admin
    # toggle on the existing PATCH /business/me, available to every plan.
    reminder_enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default="false")
    # NOT NULL with a sane default (unlike Service.deposit_percentage) —
    # there's no invalid-combination risk here worth a conditional-nullable
    # field: a harmless default value sitting unused while reminder_enabled
    # is false needs no cross-field validation at all.
    reminder_minutes_before: Mapped[int] = mapped_column(nullable=False, default=60, server_default="60")
    # Phase 16: per-business language mode (see LanguageMode). Every existing business keeps today's behavior.
    language_mode: Mapped[LanguageMode] = mapped_column(
        Enum(LanguageMode, name="business_language_mode"),
        nullable=False,
        default=LanguageMode.AUTOMATIC,
        server_default="AUTOMATIC",
    )
    # Phase 54: per-business content scope (see ContentScope). Every existing business defaults to
    # SINGLE_BUSINESS on migration — zero behavior change unless explicitly set to AGGREGATOR.
    content_scope: Mapped[ContentScope] = mapped_column(
        Enum(ContentScope, name="business_content_scope"),
        nullable=False,
        default=ContentScope.SINGLE_BUSINESS,
        server_default="SINGLE_BUSINESS",
    )
    # Phase 58: booking as a real optional module. Defaults True so every pre-existing
    # (bookable) business is unchanged after migration. When False, intent.py excludes
    # every booking-family intent (booking/rescheduling/cancellation/appointment_status/
    # resend_confirmation) from what the LLM is even offered to classify, AND
    # orchestrator.py's find_tool() call sites hard-refuse to run the corresponding tool
    # regardless of what the LLM returns — a real code-level gate, not just a prompt
    # instruction the model could be talked out of. See PHASE_STATUS.md Phase 53 "Gap 1"
    # for the pure-Q&A-tenant UX bug this closes.
    booking_enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True, server_default="true")
    # Phase 2 (style exemplars): this tenant's category flavor (e.g. "dental",
    # "trekking"), used ONLY to widen style_exemplars retrieval to shared exemplars
    # authored for that flavor (see style_exemplar_service.retrieve) -- an open,
    # free-text set (not a Postgres enum) so a new category never needs a migration.
    # Null (every pre-existing business on migration) means only truly universal
    # (business_type IS NULL) shared exemplars are eligible -- zero behavior change
    # until an owner/admin sets this.
    business_type: Mapped[str | None] = mapped_column(String(50))
    # Persona card (Phase 2): all additive, all defaulted to today's exact behavior
    # -- see intent.py._build_system_prompt for how each one is (or isn't) folded in.
    persona_name: Mapped[str | None] = mapped_column(String(100))
    formality: Mapped[BusinessFormality] = mapped_column(
        Enum(BusinessFormality, name="business_formality"),
        nullable=False, default=BusinessFormality.NEUTRAL, server_default="NEUTRAL",
    )
    emoji_policy: Mapped[EmojiPolicy] = mapped_column(
        Enum(EmojiPolicy, name="business_emoji_policy"),
        nullable=False, default=EmojiPolicy.DEFAULT, server_default="DEFAULT",
    )
    sign_off: Mapped[str | None] = mapped_column(String(200))


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
