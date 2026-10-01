import uuid
from decimal import Decimal

from pydantic import BaseModel, ConfigDict, field_validator, model_validator

from app.schemas.common import safe_str


# services.price is NUMERIC(10, 2); anything larger crashed the insert with a 500 instead of a clear message.
_MAX_PRICE = Decimal("99999999.99")
# A service is something booked into one day.
_MAX_DURATION_MINUTES = 24 * 60


def _non_negative_price(value: Decimal) -> Decimal:
    if not value.is_finite():
        raise ValueError("Price must be a number.")
    if value < 0:
        raise ValueError("Price must not be negative.")
    if value > _MAX_PRICE:
        raise ValueError("Price is too large.")
    return value


def _positive_duration(value: int) -> int:
    if value <= 0:
        raise ValueError("Duration must be a positive number of minutes.")
    if value > _MAX_DURATION_MINUTES:
        raise ValueError("Duration can be at most 24 hours (1440 minutes).")
    return value


def _not_blank(value: str) -> str:
    if not value.strip():
        raise ValueError("This field must not be blank.")
    return value


def _validate_deposit_pair(deposit_enabled: bool, deposit_percentage: int | None) -> int | None:
    """Phase 44: deposit_percentage is only meaningful when deposit_enabled is
    true — enforced here (schema layer), not a DB CHECK constraint, matching
    this codebase's existing convention (e.g. BusinessHours' closed/open_time
    pair). 100 is a legitimate value (full payment upfront), not a special
    case — only the 1-100 range is checked. Disabling deposit always clears
    the percentage rather than leaving a stale value silently ignored."""
    if not deposit_enabled:
        return None
    if deposit_percentage is None or not (1 <= deposit_percentage <= 100):
        raise ValueError("deposit_percentage must be an integer from 1 to 100 when deposit_enabled is true.")
    return deposit_percentage


class ServiceCreate(BaseModel):
    # max_length matches services.name/description's real VARCHAR(255)/
    # VARCHAR(2000) column widths (Phase 29 — see app/schemas/common.py).
    name: safe_str(255)
    description: safe_str(2000) | None = None
    price: Decimal
    duration_minutes: int
    staff_id: uuid.UUID | None = None
    deposit_enabled: bool = False
    deposit_percentage: int | None = None

    _validate_name = field_validator("name")(_not_blank)
    _validate_price = field_validator("price")(_non_negative_price)
    _validate_duration = field_validator("duration_minutes")(_positive_duration)

    @model_validator(mode="after")
    def deposit_pair_consistent(self) -> "ServiceCreate":
        # model_validator(mode="after"), not field_validator: a
        # field_validator never runs on an omitted field using its default
        # value (pydantic v2 only validates defaults with validate_default=
        # True), so deposit_percentage=None being the default for an omitted
        # field would silently skip this check entirely — real bug found via
        # this phase's own test suite (test_service_create_rejects_deposit_
        # enabled_without_percentage returned 201, not 422, before this fix).
        self.deposit_percentage = _validate_deposit_pair(self.deposit_enabled, self.deposit_percentage)
        return self


class ServiceUpdate(BaseModel):
    """PATCH — a field omitted entirely is left unchanged; a field sent as an
    explicit null clears it (only valid for the nullable ones: description,
    staff_id, deposit_percentage). name/price/duration_minutes are NOT NULL in the
    DB, so an explicit null on any of those is rejected with a 422 rather than
    reaching the DB as an IntegrityError."""

    name: safe_str(255) | None = None
    description: safe_str(2000) | None = None
    price: Decimal | None = None
    duration_minutes: int | None = None
    staff_id: uuid.UUID | None = None
    deposit_enabled: bool | None = None
    deposit_percentage: int | None = None

    @field_validator("name")
    @classmethod
    def name_not_null(cls, value: str | None) -> str:
        if value is None:
            raise ValueError("This field is required and cannot be cleared to null.")
        return _not_blank(value)

    @field_validator("price")
    @classmethod
    def price_valid(cls, value: Decimal | None) -> Decimal:
        if value is None:
            raise ValueError("This field is required and cannot be cleared to null.")
        return _non_negative_price(value)

    @field_validator("duration_minutes")
    @classmethod
    def duration_valid(cls, value: int | None) -> int:
        if value is None:
            raise ValueError("This field is required and cannot be cleared to null.")
        return _positive_duration(value)

    @model_validator(mode="after")
    def deposit_pair_consistent(self) -> "ServiceUpdate":
        # Only re-validated when deposit_enabled is actually part of this PATCH —
        # a PATCH touching unrelated fields must not require re-sending deposit
        # fields (exclude_unset semantics, same as every other field here).
        if "deposit_enabled" in self.model_fields_set:
            self.deposit_percentage = _validate_deposit_pair(bool(self.deposit_enabled), self.deposit_percentage)
        elif "deposit_percentage" in self.model_fields_set and self.deposit_percentage is not None:
            if not (1 <= self.deposit_percentage <= 100):
                raise ValueError("deposit_percentage must be an integer from 1 to 100.")
        return self


class ServiceRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    business_id: uuid.UUID
    name: str
    description: str | None
    price: Decimal
    duration_minutes: int
    staff_id: uuid.UUID | None
    deposit_enabled: bool
    deposit_percentage: int | None
