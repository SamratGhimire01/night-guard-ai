import uuid

from pydantic import BaseModel, ConfigDict, field_validator

from app.db.models.business import BusinessPlan
from app.schemas.common import safe_str

# description is a Text column (unbounded in the DB) — a DoS/sanity ceiling,
# not a real business-description-length constraint (Phase 29).
_MAX_DESCRIPTION_CHARS = 10_000


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
    follow_ups_enabled: bool
    # Phase 34 — read-only here on purpose: intentionally absent from
    # BusinessUpdate below. The only writer is app.services.plan_service.
    # change_plan, reached only through the superadmin-gated admin endpoints
    # — a business must never be able to upgrade itself via its own PATCH.
    plan: BusinessPlan


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
    languages: list[safe_str(16)] | None = None
    tone: safe_str(100) | None = None
    sms_enabled: bool | None = None
    follow_ups_enabled: bool | None = None

    @field_validator("name", "timezone")
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
