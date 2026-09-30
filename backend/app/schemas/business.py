import re
import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict, field_validator, model_validator

from app.core.timezones import AVAILABLE_TIMEZONES, canonical_timezone
from app.db.models.business import BusinessFormality, BusinessPlan, ContentScope, EmojiPolicy, LanguageMode
from app.schemas.common import safe_str

# description is a Text column (unbounded in the DB) — a DoS/sanity ceiling,
# not a real business-description-length constraint (Phase 29).
_MAX_DESCRIPTION_CHARS = 10_000

_HEX_COLOR_RE = re.compile(r"^#[0-9A-Fa-f]{6}$")
_EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
_AVAILABLE_TIMEZONES = AVAILABLE_TIMEZONES

# The dashboard's Business Profile currency picker (Settings page) only ever
# offers these — kept as a curated allowlist, not the full ~180-code ISO 4217
# standard, so it stays a short, sane dropdown. Must match
# frontend/src/pages/dashboard/SettingsPage.tsx's CURRENCY_OPTIONS exactly:
# a value the UI can produce is always accepted, a value it can't is always
# rejected. Closes the free-text-typo class of bug (Business Profile ticket,
# 2026-09-07) the same way `_AVAILABLE_TIMEZONES` closes it for timezone.
SUPPORTED_CURRENCIES = frozenset(
    {"USD", "NPR", "EUR", "GBP", "INR", "AUD", "CAD", "JPY", "CNY", "SGD"}
)


class BusinessRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    name: str
    description: str | None
    address: str | None
    phone: str | None
    email: str | None
    website: str | None
    timezone: str
    currency: str
    languages: list[str] | None
    tone: str | None
    sms_enabled: bool
    follow_ups_enabled: bool
    # Phase 34 — read-only here on purpose: intentionally absent from
    # BusinessUpdate below. The only writer is app.services.plan_service.
    # change_plan, reached only through the superadmin-gated admin endpoints
    # — a business must never be able to upgrade itself via its own PATCH.
    plan: BusinessPlan
    # Phase 38 — widget branding. Writable via BusinessUpdate below (unlike
    # plan): this is display styling, not an entitlement.
    brand_color: str
    logo_url: str | None
    # Phase 44 — read-only here on purpose, same reasoning as `plan`: the
    # only writer is PATCH /business/payment-settings (app/api/routes/
    # payments.py), which re-checks the Premium gate on every call.
    payment_collection_enabled: bool
    payment_providers: list[str]
    # Phase 45 — writable via BusinessUpdate below (unlike payment_collection_
    # enabled): not plan-gated, see Business.reminder_enabled's own comment.
    reminder_enabled: bool
    reminder_minutes_before: int
    # Phase 16 — writable via BusinessUpdate below (a plain owner/admin setting, not plan-gated).
    language_mode: LanguageMode
    # Phase 54 — writable via BusinessUpdate below (a plain owner/admin setting, not plan-gated).
    content_scope: ContentScope
    # Phase 58 — writable via BusinessUpdate below (a plain owner/admin setting, not plan-gated).
    booking_enabled: bool
    # Phase 2 (style exemplars) — this tenant's category flavor, used only to widen
    # style_exemplars retrieval to shared exemplars authored for that flavor.
    business_type: str | None
    # Persona card (Phase 2) — all writable via BusinessUpdate below, all optional.
    persona_name: str | None
    formality: BusinessFormality
    emoji_policy: EmojiPolicy
    sign_off: str | None
    upgrade_requested_at: datetime | None = None
    owner_alerts_enabled: bool = True


class BusinessUpdate(BaseModel):
    """PATCH — a field omitted entirely is left unchanged; a field sent as an
    explicit null clears it (only valid for the nullable ones below). name/timezone
    are NOT NULL in the DB, so an explicit null on either is rejected with a 422
    rather than reaching the DB as an IntegrityError."""

    # max_length values match businesses.*'s real VARCHAR column widths, or
    # (description) a generous DoS ceiling on its unbounded Text column
    # (Phase 29 — see app/schemas/common.py).
    name: safe_str(255) | None = None
    description: safe_str(_MAX_DESCRIPTION_CHARS) | None = None
    address: safe_str(500) | None = None
    phone: safe_str(50) | None = None
    email: safe_str(255) | None = None
    website: safe_str(255) | None = None
    timezone: safe_str(64) | None = None
    currency: safe_str(10) | None = None
    languages: list[safe_str(16)] | None = None
    tone: safe_str(100) | None = None
    sms_enabled: bool | None = None
    follow_ups_enabled: bool | None = None
    brand_color: safe_str(7) | None = None
    logo_url: safe_str(500) | None = None
    reminder_enabled: bool | None = None
    reminder_minutes_before: int | None = None
    language_mode: LanguageMode | None = None
    content_scope: ContentScope | None = None
    booking_enabled: bool | None = None
    business_type: safe_str(50) | None = None
    persona_name: safe_str(100) | None = None
    formality: BusinessFormality | None = None
    emoji_policy: EmojiPolicy | None = None
    sign_off: safe_str(200) | None = None
    owner_alerts_enabled: bool | None = None

    @field_validator("brand_color")
    @classmethod
    def valid_hex_color(cls, value: str | None) -> str | None:
        if value is not None and not _HEX_COLOR_RE.match(value):
            raise ValueError("Must be a hex color like #2563eb.")
        return value

    @field_validator("email")
    @classmethod
    def valid_email(cls, value: str | None) -> str | None:
        # Empty string / None both mean "leave alone or clear" — only a
        # genuinely non-empty, malformed value is rejected.
        if value and not _EMAIL_RE.match(value):
            raise ValueError("Must be a valid email address.")
        return value

    @field_validator("timezone")
    @classmethod
    def valid_timezone(cls, value: str | None) -> str | None:
        if value is None:
            return None
        canonical = canonical_timezone(value)
        if canonical is None:
            raise ValueError("Must be a real IANA timezone, e.g. America/New_York.")
        return canonical

    @field_validator("currency")
    @classmethod
    def valid_currency(cls, value: str | None) -> str | None:
        if value is not None and value not in SUPPORTED_CURRENCIES:
            raise ValueError(f"Must be one of: {', '.join(sorted(SUPPORTED_CURRENCIES))}.")
        return value

    @field_validator("name", "timezone", "currency", "brand_color")
    @classmethod
    def required_field_not_null(cls, value: str | None) -> str:
        if value is None:
            raise ValueError("This field is required and cannot be cleared to null.")
        return value

    @field_validator("sms_enabled", "follow_ups_enabled", "reminder_enabled", "booking_enabled", "owner_alerts_enabled")
    @classmethod
    def bool_toggle_not_null(cls, value: bool | None) -> bool:
        if value is None:
            raise ValueError("This field cannot be cleared to null — pass true or false.")
        return value

    @field_validator("language_mode")
    @classmethod
    def language_mode_not_null(cls, value: LanguageMode | None) -> LanguageMode:
        if value is None:
            raise ValueError("This field cannot be cleared to null — pass \"automatic\" or \"ask\".")
        return value

    @field_validator("content_scope")
    @classmethod
    def content_scope_not_null(cls, value: ContentScope | None) -> ContentScope:
        if value is None:
            raise ValueError("This field cannot be cleared to null — pass \"single_business\" or \"aggregator\".")
        return value

    @field_validator("formality")
    @classmethod
    def formality_not_null(cls, value: BusinessFormality | None) -> BusinessFormality:
        if value is None:
            raise ValueError("This field cannot be cleared to null — pass \"casual\", \"neutral\", or \"formal\".")
        return value

    @field_validator("emoji_policy")
    @classmethod
    def emoji_policy_not_null(cls, value: EmojiPolicy | None) -> EmojiPolicy:
        if value is None:
            raise ValueError("This field cannot be cleared to null — pass \"default\" or \"none\".")
        return value

    @field_validator("reminder_minutes_before")
    @classmethod
    def reminder_minutes_before_valid(cls, value: int | None) -> int:
        if value is None:
            raise ValueError("This field cannot be cleared to null.")
        if not (5 <= value <= 1440):
            raise ValueError("Must be an integer from 5 to 1440 (24 hours).")
        return value


# Phase 44 — the two real gateways this codebase has an actual
# PaymentProvider implementation for (app/services/payments/). Both are
# Nepali payment gateways that process NPR only in reality; enabling payment
# collection on a business whose currency isn't NPR is rejected below rather
# than silently generating a nonsensical payment request.
SUPPORTED_PAYMENT_PROVIDERS = frozenset({"esewa", "khalti"})


class PaymentSettingsUpdate(BaseModel):
    """PATCH /business/payment-settings — deliberately separate from
    BusinessUpdate (never the generic PATCH /business/me), since this is the
    one business-level toggle that must be plan-gated: the route itself
    re-checks Premium via require_plan on every call (Phase 34 discipline),
    something a generic PATCH endpoint has no per-field way to do."""

    payment_collection_enabled: bool
    payment_providers: list[str] = []
    # Phase 44's original single-gateway field, still accepted so existing API clients keep working: folded into
    # `payment_providers` below and never returned.
    payment_provider: str | None = None

    @model_validator(mode="after")
    def providers_required_when_enabled(self) -> "PaymentSettingsUpdate":
        if self.payment_provider and not self.payment_providers:
            self.payment_providers = [self.payment_provider]
        self.payment_provider = None
        unknown = set(self.payment_providers) - SUPPORTED_PAYMENT_PROVIDERS
        if unknown:
            raise ValueError(f"payment_providers may only contain: {', '.join(sorted(SUPPORTED_PAYMENT_PROVIDERS))}.")
        # de-duplicated, in a stable order (so "which is the default when a booking can't ask" is deterministic)
        self.payment_providers = sorted(set(self.payment_providers))
        if self.payment_collection_enabled:
            if not self.payment_providers:
                raise ValueError("Enable at least one payment provider (esewa and/or khalti).")
        else:
            self.payment_providers = []
        return self
