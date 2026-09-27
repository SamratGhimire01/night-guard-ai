import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.db.models.knowledge import KnowledgeDocumentStatus
from app.schemas.common import safe_str

# Matches routes/knowledge.py's own _MAX_UPLOAD_BYTES cap for the file-upload
# path — this manual-entry path (a plain JSON `content` field, not a file)
# had no size cap at all before Phase 29, which would otherwise let it bypass
# that same limit trivially. `content` is a Text column (genuinely unbounded
# in the DB, unlike title's VARCHAR(255)), so this is a DoS/sanity ceiling,
# not a real-document-size constraint — no legitimate knowledge article gets
# near 10 million characters.
_MAX_CONTENT_CHARS = 10 * 1024 * 1024


def _not_blank(value: str) -> str:
    if not value.strip():
        raise ValueError("This field must not be blank.")
    return value


class KnowledgeDocumentCreate(BaseModel):
    title: safe_str(255)
    content: safe_str(_MAX_CONTENT_CHARS)

    @field_validator("title", "content")
    @classmethod
    def not_blank(cls, value: str) -> str:
        return _not_blank(value)


class KnowledgeDocumentUpdate(BaseModel):
    """PATCH — a field omitted entirely is left unchanged. title/content/status are
    NOT NULL in the DB, so an explicit null on any of them is rejected with a 422
    rather than reaching the DB as an IntegrityError."""

    title: safe_str(255) | None = None
    content: safe_str(_MAX_CONTENT_CHARS) | None = None
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


class KnowledgeURLIngestRequest(BaseModel):
    """Part 2B: a single page by default; `crawl=true` also follows same-domain links
    found ON that page (depth 1, robots.txt-respecting, capped), one KnowledgeDocument
    per page. Every resulting document lands as draft, same as upload/manual entry."""

    url: safe_str(2048)
    crawl: bool = False
    max_pages: int = Field(default=1, ge=1, le=8)

    @field_validator("url")
    @classmethod
    def url_not_blank(cls, value: str) -> str:
        return _not_blank(value)


class KnowledgeSearchRequest(BaseModel):
    query: str
    top_k: int = Field(default=5, ge=1, le=20)

    @field_validator("query")
    @classmethod
    def query_not_blank(cls, value: str) -> str:
        return _not_blank(value)


class KnowledgeSearchResult(BaseModel):
    chunk_id: uuid.UUID
    document_id: uuid.UUID
    document_title: str
    content: str
    similarity: float


class KnowledgeSearchResponse(BaseModel):
    results: list[KnowledgeSearchResult]
