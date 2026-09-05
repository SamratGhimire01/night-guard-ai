import uuid

from pydantic import BaseModel, ConfigDict, field_validator

from app.schemas.common import safe_str


class StaffCreate(BaseModel):
    # max_length matches staff.name/role's real VARCHAR(255)/VARCHAR(100)
    # column widths (Phase 29 — see app/schemas/common.py).
    name: safe_str(255)
    role: safe_str(100)

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

    name: safe_str(255) | None = None
    role: safe_str(100) | None = None

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
