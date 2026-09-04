import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict, field_validator

from app.db.models.appointment import AppointmentStatus


def _require_tz_aware(value: datetime) -> datetime:
    if value.tzinfo is None:
        raise ValueError("scheduled_at must include a timezone offset.")
    return value


class AppointmentCreate(BaseModel):
    customer_id: uuid.UUID
    service_id: uuid.UUID
    staff_id: uuid.UUID | None = None
    # duration_minutes is NOT accepted here: Python derives it from the service,
    # never from the caller — the same rule that keeps the LLM from inventing a
    # booking applies just as much to a client-supplied duration.
    scheduled_at: datetime

    @field_validator("scheduled_at")
    @classmethod
    def must_be_timezone_aware(cls, value: datetime) -> datetime:
        return _require_tz_aware(value)


class AppointmentReschedule(BaseModel):
    scheduled_at: datetime

    @field_validator("scheduled_at")
    @classmethod
    def must_be_timezone_aware(cls, value: datetime) -> datetime:
        return _require_tz_aware(value)


class AppointmentRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    business_id: uuid.UUID
    customer_id: uuid.UUID
    service_id: uuid.UUID
    staff_id: uuid.UUID | None
    scheduled_at: datetime
    duration_minutes: int
    status: AppointmentStatus
    created_at: datetime
    group_booking_id: uuid.UUID | None
