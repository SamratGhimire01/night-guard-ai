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
    """PATCH — a field omitted entirely is left unchanged. Both fields are NOT NULL
    in the DB (Staff has no nullable field to clear), so an explicit null is rejected
    with a 422 rather than reaching the DB as an IntegrityError."""

    name: str | None = None
    role: str | None = None

    @field_validator("name", "role")
    @classmethod
    def not_blank(cls, value: str | None) -> str:
        if value is None:
            raise ValueError("This field is required and cannot be cleared to null.")
        if not value.strip():
            raise ValueError("This field must not be blank.")
        return value


class StaffRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    business_id: uuid.UUID
    name: str
    role: str
