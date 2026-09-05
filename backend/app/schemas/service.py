import uuid
from decimal import Decimal

from pydantic import BaseModel, ConfigDict, field_validator

from app.schemas.common import safe_str


def _non_negative_price(value: Decimal) -> Decimal:
    if value < 0:
        raise ValueError("Price must not be negative.")
    return value


def _positive_duration(value: int) -> int:
    if value <= 0:
        raise ValueError("Duration must be a positive number of minutes.")
    return value


class ServiceCreate(BaseModel):
    # max_length matches services.name/description's real VARCHAR(255)/
    # VARCHAR(2000) column widths (Phase 29 — see app/schemas/common.py).
    name: safe_str(255)
    description: safe_str(2000) | None = None
    price: Decimal
    duration_minutes: int
    staff_id: uuid.UUID | None = None

    _validate_price = field_validator("price")(_non_negative_price)
    _validate_duration = field_validator("duration_minutes")(_positive_duration)


class ServiceUpdate(BaseModel):
    """PATCH — a field omitted entirely is left unchanged; a field sent as an
    explicit null clears it (only valid for the nullable ones: description,
    staff_id). name/price/duration_minutes are NOT NULL in the DB, so an explicit
    null on any of those is rejected with a 422 rather than reaching the DB as an
    IntegrityError."""

    name: safe_str(255) | None = None
    description: safe_str(2000) | None = None
    price: Decimal | None = None
    duration_minutes: int | None = None
    staff_id: uuid.UUID | None = None

    @field_validator("name")
    @classmethod
    def name_not_null(cls, value: str | None) -> str:
        if value is None:
            raise ValueError("This field is required and cannot be cleared to null.")
        return value

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


class ServiceRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    business_id: uuid.UUID
    name: str
    description: str | None
    price: Decimal
    duration_minutes: int
    staff_id: uuid.UUID | None
