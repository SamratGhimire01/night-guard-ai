import uuid

from pydantic import BaseModel, ConfigDict


class CustomerCreate(BaseModel):
    name: str
    phone: str | None = None
    email: str | None = None
    preferred_language: str | None = None
    # Phase 15: explicit SMS consent, settable at creation. No customer-update
    # endpoint exists yet in this codebase to flip it later — see Customer
    # model's comment and PHASE_STATUS.md Phase 15 for the "why default False,
    # why creation-only for now" reasoning.
    sms_opt_in: bool = False


class CustomerRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    business_id: uuid.UUID
    name: str
    phone: str | None
    email: str | None
    preferred_language: str | None
    sms_opt_in: bool
