import uuid

from pydantic import BaseModel, ConfigDict


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


class BusinessUpdate(BaseModel):
    """PATCH — every field optional, only fields actually sent are changed."""

    name: str | None = None
    description: str | None = None
    address: str | None = None
    phone: str | None = None
    email: str | None = None
    website: str | None = None
    timezone: str | None = None
    languages: list[str] | None = None
    tone: str | None = None
