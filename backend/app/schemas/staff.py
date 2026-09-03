import uuid

from pydantic import BaseModel, ConfigDict, field_validator


class StaffCreate(BaseModel):
    name: str
    role: str

    @field_validator("name", "role")
    @classmethod
    def not_blank(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("This field must not be blank.")
        return value


class StaffUpdate(BaseModel):
    """PATCH — every field optional, only fields actually sent are changed."""

    name: str | None = None
    role: str | None = None

    @field_validator("name", "role")
    @classmethod
    def not_blank(cls, value: str | None) -> str | None:
        if value is not None and not value.strip():
            raise ValueError("This field must not be blank.")
        return value


class StaffRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    business_id: uuid.UUID
    name: str
    role: str
