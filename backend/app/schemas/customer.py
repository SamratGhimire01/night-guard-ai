import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict, EmailStr, field_validator

from app.schemas.common import safe_str


class CustomerCreate(BaseModel):
    # max_length values match customers.name/phone/preferred_language's real
    # VARCHAR(255)/VARCHAR(50)/VARCHAR(32) column widths (Phase 29 — see
    # app/schemas/common.py's docstring for the real bug this closes).
    name: safe_str(255)
    phone: safe_str(50) | None = None
    email: safe_str(255) | None = None
    preferred_language: safe_str(32) | None = None
    # Phase 15: explicit SMS consent, settable at creation. Also settable
    # later now via CustomerUpdate (this gap closed for real, see below).
    sms_opt_in: bool = False


class CustomerUpdate(BaseModel):
    """PATCH — a field omitted entirely is left unchanged; a field sent as an
    explicit null clears it (only valid for the nullable ones: phone, email,
    preferred_language). `name`/`sms_opt_in` are NOT NULL in the DB, so an
    explicit null on either is rejected with a 422 rather than reaching the DB
    as an IntegrityError — same pattern as BusinessUpdate/ServiceUpdate.
    `business_id` is deliberately not a field here at all: a customer can
    never be reassigned to another tenant through this endpoint.

    Closes the real gap Phase 15 flagged: no customer-update endpoint existed
    anywhere in this codebase, so neither contact info nor sms_opt_in could
    ever be changed after a Customer row was created (e.g. an anonymous
    widget visitor who later volunteers their real name/email mid-
    conversation — see the Phase 23 urgent-fix entry in PHASE_STATUS.md)."""

    name: safe_str(255) | None = None
    phone: safe_str(50) | None = None
    email: EmailStr | None = None
    preferred_language: safe_str(32) | None = None
    sms_opt_in: bool | None = None

    @field_validator("name")
    @classmethod
    def name_not_null(cls, value: str | None) -> str:
        if value is None:
            raise ValueError("This field is required and cannot be cleared to null.")
        return value

    @field_validator("sms_opt_in")
    @classmethod
    def sms_opt_in_not_null(cls, value: bool | None) -> bool:
        if value is None:
            raise ValueError("This field cannot be cleared to null — pass true or false.")
        return value


class CustomerRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    business_id: uuid.UUID
    name: str
    phone: str | None
    email: str | None
    preferred_language: str | None
    sms_opt_in: bool


class CustomerListItem(BaseModel):
    id: uuid.UUID
    name: str | None  # None until the customer has told us their name
    phone: str | None
    email: str | None
    channel: str | None
    conversations: int
    appointments: int
    first_seen_at: datetime
    last_contact_at: datetime
