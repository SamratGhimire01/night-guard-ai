import uuid

from pydantic import BaseModel, ConfigDict, field_validator


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
    languages: list[str] | None
    tone: str | None
    sms_enabled: bool


class BusinessUpdate(BaseModel):
    """PATCH — a field omitted entirely is left unchanged; a field sent as an
    explicit null clears it (only valid for the nullable ones below). name/timezone
    are NOT NULL in the DB, so an explicit null on either is rejected with a 422
    rather than reaching the DB as an IntegrityError."""

    name: str | None = None
    description: str | None = None
    address: str | None = None
    phone: str | None = None
    email: str | None = None
    website: str | None = None
    timezone: str | None = None
    languages: list[str] | None = None
    tone: str | None = None
    sms_enabled: bool | None = None

    @field_validator("name", "timezone")
    @classmethod
    def required_field_not_null(cls, value: str | None) -> str:
        if value is None:
            raise ValueError("This field is required and cannot be cleared to null.")
        return value

    @field_validator("sms_enabled")
    @classmethod
    def sms_enabled_not_null(cls, value: bool | None) -> bool:
        if value is None:
            raise ValueError("sms_enabled cannot be cleared to null — pass true or false.")
        return value
