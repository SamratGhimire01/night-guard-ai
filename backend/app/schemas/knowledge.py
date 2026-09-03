import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict, field_validator

from app.db.models.knowledge import KnowledgeDocumentStatus


def _not_blank(value: str) -> str:
    if not value.strip():
        raise ValueError("This field must not be blank.")
    return value


class KnowledgeDocumentCreate(BaseModel):
    title: str
    content: str

    @field_validator("title", "content")
    @classmethod
    def not_blank(cls, value: str) -> str:
        return _not_blank(value)


class KnowledgeDocumentUpdate(BaseModel):
    """PATCH — a field omitted entirely is left unchanged. title/content/status are
    NOT NULL in the DB, so an explicit null on any of them is rejected with a 422
    rather than reaching the DB as an IntegrityError."""

    title: str | None = None
    content: str | None = None
    status: KnowledgeDocumentStatus | None = None

    @field_validator("title", "content")
    @classmethod
    def not_null_or_blank(cls, value: str | None) -> str:
        if value is None:
            raise ValueError("This field is required and cannot be cleared to null.")
        return _not_blank(value)

    @field_validator("status")
    @classmethod
    def status_not_null(cls, value: KnowledgeDocumentStatus | None) -> KnowledgeDocumentStatus:
        if value is None:
            raise ValueError("This field is required and cannot be cleared to null.")
        return value


class KnowledgeDocumentRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    business_id: uuid.UUID
    title: str
    content: str
    source: str
    status: KnowledgeDocumentStatus
    version: int
    approved_by: uuid.UUID | None
    approved_at: datetime | None
    created_at: datetime
    updated_at: datetime
