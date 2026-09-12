import re
import uuid
from zoneinfo import available_timezones

from pydantic import BaseModel, ConfigDict, field_validator

from app.db.models.business import BusinessPlan
from app.schemas.common import safe_str

# description is a Text column (unbounded in the DB) — a DoS/sanity ceiling,
# not a real business-description-length constraint (Phase 29).
_MAX_DESCRIPTION_CHARS = 10_000

_HEX_COLOR_RE = re.compile(r"^#[0-9A-Fa-f]{6}$")
_EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
_AVAILABLE_TIMEZONES = available_timezones()

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
        if value is not None and value not in _AVAILABLE_TIMEZONES:
            raise ValueError("Must be a real IANA timezone, e.g. America/New_York.")
        return value

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

    @field_validator("sms_enabled", "follow_ups_enabled")
    @classmethod
    def bool_toggle_not_null(cls, value: bool | None) -> bool:
        if value is None:
            raise ValueError("This field cannot be cleared to null — pass true or false.")
        return value
