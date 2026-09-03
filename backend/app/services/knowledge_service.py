import uuid
from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.models.knowledge import KnowledgeDocument, KnowledgeDocumentStatus
from app.schemas.knowledge import KnowledgeDocumentUpdate


def list_documents(
    db: Session, *, business_id: uuid.UUID, status: KnowledgeDocumentStatus | None = None
) -> list[KnowledgeDocument]:
    stmt = select(KnowledgeDocument).where(KnowledgeDocument.business_id == business_id)
    if status is not None:
        stmt = stmt.where(KnowledgeDocument.status == status)
    stmt = stmt.order_by(KnowledgeDocument.created_at.desc())
    return list(db.execute(stmt).scalars())


def create_document(
    db: Session, *, business_id: uuid.UUID, title: str, content: str, source: str
) -> KnowledgeDocument:
    document = KnowledgeDocument(
        business_id=business_id,
        title=title,
        content=content,
        source=source,
        status=KnowledgeDocumentStatus.DRAFT,
    )
    db.add(document)
    db.commit()
    db.refresh(document)
    return document


def get_document(
    db: Session, *, business_id: uuid.UUID, document_id: uuid.UUID
) -> KnowledgeDocument | None:
    return db.execute(
        select(KnowledgeDocument).where(
            KnowledgeDocument.id == document_id, KnowledgeDocument.business_id == business_id
        )
    ).scalar_one_or_none()


def update_document(
    db: Session,
    *,
    business_id: uuid.UUID,
    document_id: uuid.UUID,
    payload: KnowledgeDocumentUpdate,
    current_user_id: uuid.UUID,
) -> KnowledgeDocument | None:
    document = get_document(db, business_id=business_id, document_id=document_id)
    if document is None:
        return None

    data = payload.model_dump(exclude_unset=True)
    new_status = data.pop("status", None)

    if "content" in data:
        # Lightweight versioning: bump the counter on every content edit. No separate
        # history/snapshot table — Phase 5 scope is "structured, versioned, gated by
        # approval," not full revision history.
        document.version += 1

    for field, value in data.items():
        setattr(document, field, value)

    if new_status is not None:
        document.status = new_status
        if new_status == KnowledgeDocumentStatus.APPROVED:
            document.approved_by = current_user_id
            document.approved_at = datetime.now(UTC)

    db.commit()
    db.refresh(document)
    return document


def delete_document(db: Session, *, business_id: uuid.UUID, document_id: uuid.UUID) -> bool:
    document = get_document(db, business_id=business_id, document_id=document_id)
    if document is None:
        return False
    db.delete(document)
    db.commit()
    return True
