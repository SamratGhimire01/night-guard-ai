import uuid

from sqlalchemy import ForeignKeyConstraint, UniqueConstraint
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.database import Base
from app.db.models.mixins import CreatedAtMixin, TenantMixin, UUIDPrimaryKeyMixin


class ServiceKnowledgeDocument(UUIDPrimaryKeyMixin, TenantMixin, CreatedAtMixin, Base):
    """Phase 36 — a dashboard-only organizational link ("this knowledge document is
    about this service") between one Service and one KnowledgeDocument. This is
    purely a UI convenience for the business owner to group related documents next
    to a service; it does NOT change Phase 6's RAG search, which still searches
    every approved document for the business regardless of any attachment here.
    A plain many-to-many join table, not a new field on either side, since a
    document can reasonably describe more than one service (and vice versa)."""

    __tablename__ = "service_knowledge_documents"
    __table_args__ = (
        UniqueConstraint(
            "service_id", "knowledge_document_id", name="uq_service_knowledge_document"
        ),
        # Same composite-FK-to-a-same-tenant-unique-constraint pattern Service already
        # uses for staff_id (fk_services_staff_same_tenant) — the DB itself rejects
        # attaching a service to another business's knowledge document, or vice versa,
        # not just the application layer.
        ForeignKeyConstraint(
            ["service_id", "business_id"],
            ["services.id", "services.business_id"],
            name="fk_skd_service_same_tenant",
            ondelete="CASCADE",
        ),
        ForeignKeyConstraint(
            ["knowledge_document_id", "business_id"],
            ["knowledge_documents.id", "knowledge_documents.business_id"],
            name="fk_skd_knowledge_document_same_tenant",
            ondelete="CASCADE",
        ),
    )

    service_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False, index=True)
    knowledge_document_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), nullable=False, index=True
    )
