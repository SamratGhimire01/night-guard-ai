import uuid
from datetime import date as date_
from datetime import time

from pydantic import BaseModel, ConfigDict, field_validator, model_validator


def _check_hours_range(closed: bool, open_time: time | None, close_time: time | None) -> None:
    if closed:
        return
    if open_time is None or close_time is None:
        raise ValueError("open_time and close_time are required unless the day is closed.")
    if close_time <= open_time:
        raise ValueError("close_time must be after open_time.")


class BusinessHourDay(BaseModel):
    day_of_week: int
    closed: bool = False
    open_time: time | None = None
    close_time: time | None = None

    @field_validator("day_of_week")
    @classmethod
    def day_in_range(cls, value: int) -> int:
        if not 0 <= value <= 6:
            raise ValueError("day_of_week must be between 0 (Monday) and 6 (Sunday).")
        return value

    @model_validator(mode="after")
    def valid_range(self) -> "BusinessHourDay":
        _check_hours_range(self.closed, self.open_time, self.close_time)
        return self


class BusinessHoursUpdate(BaseModel):
    """PUT — replaces the entire week's schedule in one call."""

    days: list[BusinessHourDay]

    @field_validator("days")
    @classmethod
    def unique_days(cls, value: list[BusinessHourDay]) -> list[BusinessHourDay]:
        seen = {d.day_of_week for d in value}
        if len(seen) != len(value):
            raise ValueError("Duplicate day_of_week in schedule.")
        return value


class BusinessHourRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    day_of_week: int
    closed: bool
    open_time: time | None
    close_time: time | None


class HolidayExceptionCreate(BaseModel):
    date: date_
    closed: bool = True
    open_time: time | None = None
    close_time: time | None = None

    @model_validator(mode="after")
    def valid_range(self) -> "HolidayExceptionCreate":
        _check_hours_range(self.closed, self.open_time, self.close_time)
        return self


class HolidayExceptionRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    date: date_
    closed: bool
    open_time: time | None
    close_time: time | None
