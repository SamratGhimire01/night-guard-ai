import uuid
from decimal import Decimal

from pydantic import BaseModel, ConfigDict, field_validator


def _non_negative_price(value: Decimal | None) -> Decimal | None:
    if value is not None and value < 0:
        raise ValueError("Price must not be negative.")
    return value


def _positive_duration(value: int | None) -> int | None:
    if value is not None and value <= 0:
        raise ValueError("Duration must be a positive number of minutes.")
    return value


class ServiceCreate(BaseModel):
    name: str
    description: str | None = None
    price: Decimal
    duration_minutes: int
    staff_id: uuid.UUID | None = None

    _validate_price = field_validator("price")(_non_negative_price)
    _validate_duration = field_validator("duration_minutes")(_positive_duration)


class ServiceUpdate(BaseModel):
    """PATCH — every field optional, only fields actually sent are changed."""

    name: str | None = None
    description: str | None = None
    price: Decimal | None = None
    duration_minutes: int | None = None
    staff_id: uuid.UUID | None = None

    _validate_price = field_validator("price")(_non_negative_price)
    _validate_duration = field_validator("duration_minutes")(_positive_duration)


class ServiceRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    business_id: uuid.UUID
    name: str
    description: str | None
    price: Decimal
    duration_minutes: int
    staff_id: uuid.UUID | None
