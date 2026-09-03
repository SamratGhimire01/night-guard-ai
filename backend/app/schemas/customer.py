import uuid

from pydantic import BaseModel, ConfigDict


class CustomerCreate(BaseModel):
    name: str
    phone: str | None = None
    email: str | None = None
    preferred_language: str | None = None


class CustomerRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    business_id: uuid.UUID
    name: str
    phone: str | None
    email: str | None
    preferred_language: str | None
