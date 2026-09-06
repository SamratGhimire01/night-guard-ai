import uuid

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.exceptions import ConflictError, NotFoundError
from app.db.models.knowledge import KnowledgeDocument
from app.db.models.service import Service
from app.db.models.service_knowledge import ServiceKnowledgeDocument


def _get_service_or_404(db: Session, *, business_id: uuid.UUID, service_id: uuid.UUID) -> Service:
    service = db.execute(
        select(Service).where(Service.id == service_id, Service.business_id == business_id)
    ).scalar_one_or_none()
    if service is None:
        raise NotFoundError("Service not found.")
    return service


def list_attached_documents(
    db: Session, *, business_id: uuid.UUID, service_id: uuid.UUID
) -> list[KnowledgeDocument]:
    _get_service_or_404(db, business_id=business_id, service_id=service_id)
    return list(
        db.execute(
            select(KnowledgeDocument)
            .join(
                ServiceKnowledgeDocument,
                ServiceKnowledgeDocument.knowledge_document_id == KnowledgeDocument.id,
            )
            .where(
                ServiceKnowledgeDocument.service_id == service_id,
                ServiceKnowledgeDocument.business_id == business_id,
            )
            .order_by(KnowledgeDocument.title)
        ).scalars()
    )


def attach_document(
    db: Session, *, business_id: uuid.UUID, service_id: uuid.UUID, knowledge_document_id: uuid.UUID
) -> KnowledgeDocument:
    _get_service_or_404(db, business_id=business_id, service_id=service_id)
    document = db.execute(
        select(KnowledgeDocument).where(
            KnowledgeDocument.id == knowledge_document_id, KnowledgeDocument.business_id == business_id
        )
    ).scalar_one_or_none()
    if document is None:
        raise NotFoundError("Knowledge document not found.")

    existing = db.execute(
        select(ServiceKnowledgeDocument).where(
            ServiceKnowledgeDocument.service_id == service_id,
            ServiceKnowledgeDocument.knowledge_document_id == knowledge_document_id,
        )
    ).scalar_one_or_none()
    if existing is not None:
        raise ConflictError("This document is already attached to this service.")

    link = ServiceKnowledgeDocument(
        business_id=business_id, service_id=service_id, knowledge_document_id=knowledge_document_id
    )
    db.add(link)
    db.commit()
    db.refresh(document)
    return document


def detach_document(
    db: Session, *, business_id: uuid.UUID, service_id: uuid.UUID, knowledge_document_id: uuid.UUID
) -> bool:
    _get_service_or_404(db, business_id=business_id, service_id=service_id)
    link = db.execute(
        select(ServiceKnowledgeDocument).where(
            ServiceKnowledgeDocument.business_id == business_id,
            ServiceKnowledgeDocument.service_id == service_id,
            ServiceKnowledgeDocument.knowledge_document_id == knowledge_document_id,
        )
    ).scalar_one_or_none()
    if link is None:
        return False
    db.delete(link)
    db.commit()
    return True
