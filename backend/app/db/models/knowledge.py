import enum
import uuid
from datetime import datetime

from pgvector.sqlalchemy import Vector
from sqlalchemy import DateTime, Enum, ForeignKey, String, Text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.database import Base
from app.db.models.mixins import CreatedAtMixin, TenantMixin, UpdatedAtMixin, UUIDPrimaryKeyMixin

# Placeholder dimension matching common embedding models (e.g. OpenAI text-embedding-3-small).
# Revisit once the actual embedding model is chosen (Phase 5/6).
EMBEDDING_DIMENSIONS = 1536


class KnowledgeDocumentStatus(str, enum.Enum):
    DRAFT = "draft"
    APPROVED = "approved"
    ARCHIVED = "archived"


class KnowledgeDocument(UUIDPrimaryKeyMixin, TenantMixin, CreatedAtMixin, UpdatedAtMixin, Base):
    __tablename__ = "knowledge_documents"

    title: Mapped[str] = mapped_column(String(255), nullable=False)
    # Phase 5: the raw ingested text (typed manually or extracted from an uploaded
    # file). Phase 6 will chunk this into KnowledgeChunk rows for embedding/retrieval;
    # this column stays the source of truth for "what was actually submitted."
    content: Mapped[str] = mapped_column(Text, nullable=False, server_default="")
    source: Mapped[str] = mapped_column(String(500), nullable=False)
    status: Mapped[KnowledgeDocumentStatus] = mapped_column(
        Enum(KnowledgeDocumentStatus, name="knowledge_document_status"), nullable=False
    )
    version: Mapped[int] = mapped_column(nullable=False, server_default="1")
    # Not tenant-cross-checked at the DB level: approved_by references business_users.id
    # directly, without verifying it belongs to the same business_id as this document.
    # Known gap, see PHASE_STATUS.md.
    approved_by: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("business_users.id")
    )
    approved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class KnowledgeChunk(UUIDPrimaryKeyMixin, CreatedAtMixin, Base):
    """No business_id: tenant context is inherited via knowledge_document_id."""

    __tablename__ = "knowledge_chunks"

    knowledge_document_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("knowledge_documents.id", ondelete="CASCADE"), index=True, nullable=False
    )
    content: Mapped[str] = mapped_column(Text, nullable=False)
    embedding: Mapped[list[float] | None] = mapped_column(Vector(EMBEDDING_DIMENSIONS))
