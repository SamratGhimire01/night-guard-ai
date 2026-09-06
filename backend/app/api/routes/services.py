import uuid

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.api.dependencies import get_current_user, get_db, require_role
from app.core.exceptions import NotFoundError
from app.db.models.business import BusinessUser
from app.schemas.knowledge import KnowledgeDocumentRead
from app.schemas.service import ServiceCreate, ServiceRead, ServiceUpdate
from app.schemas.service_knowledge import ServiceKnowledgeDocumentAttach
from app.services import service_knowledge_service, service_service

router = APIRouter()


@router.get("/services", response_model=list[ServiceRead])
def list_services(
    current_user: BusinessUser = Depends(get_current_user), db: Session = Depends(get_db)
) -> list[ServiceRead]:
    services = service_service.list_services(db, business_id=current_user.business_id)
    return [ServiceRead.model_validate(s) for s in services]


@router.post("/services", response_model=ServiceRead, status_code=201)
def create_service(
    payload: ServiceCreate,
    current_user: BusinessUser = Depends(require_role(["owner", "admin"])),
    db: Session = Depends(get_db),
) -> ServiceRead:
    service = service_service.create_service(db, business_id=current_user.business_id, payload=payload)
    return ServiceRead.model_validate(service)


@router.patch("/services/{service_id}", response_model=ServiceRead)
def update_service(
    service_id: uuid.UUID,
    payload: ServiceUpdate,
    current_user: BusinessUser = Depends(require_role(["owner", "admin"])),
    db: Session = Depends(get_db),
) -> ServiceRead:
    service = service_service.update_service(
        db, business_id=current_user.business_id, service_id=service_id, payload=payload
    )
    if service is None:
        raise NotFoundError("Service not found.")
    return ServiceRead.model_validate(service)


@router.delete("/services/{service_id}", status_code=204)
def delete_service(
    service_id: uuid.UUID,
    current_user: BusinessUser = Depends(require_role(["owner", "admin"])),
    db: Session = Depends(get_db),
) -> None:
    deleted = service_service.delete_service(
        db, business_id=current_user.business_id, service_id=service_id
    )
    if not deleted:
        raise NotFoundError("Service not found.")


# --- Phase 36: dashboard-only service <-> knowledge-document attachment. -----------
# Purely an organizational convenience for the business owner's UI (e.g. "Root Canal
# — What to Expect" attached to the "Root Canal Treatment" service) — it does NOT
# change Phase 6's RAG search, which still searches every approved document for the
# business regardless of any attachment made here. Same read-any/write-owner-admin
# RBAC split as every other Phase 4 resource.


@router.get("/services/{service_id}/knowledge-documents", response_model=list[KnowledgeDocumentRead])
def list_service_knowledge_documents(
    service_id: uuid.UUID,
    current_user: BusinessUser = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> list[KnowledgeDocumentRead]:
    documents = service_knowledge_service.list_attached_documents(
        db, business_id=current_user.business_id, service_id=service_id
    )
    return [KnowledgeDocumentRead.model_validate(d) for d in documents]


@router.post(
    "/services/{service_id}/knowledge-documents",
    response_model=KnowledgeDocumentRead,
    status_code=201,
)
def attach_service_knowledge_document(
    service_id: uuid.UUID,
    payload: ServiceKnowledgeDocumentAttach,
    current_user: BusinessUser = Depends(require_role(["owner", "admin"])),
    db: Session = Depends(get_db),
) -> KnowledgeDocumentRead:
    document = service_knowledge_service.attach_document(
        db,
        business_id=current_user.business_id,
        service_id=service_id,
        knowledge_document_id=payload.knowledge_document_id,
    )
    return KnowledgeDocumentRead.model_validate(document)


@router.delete("/services/{service_id}/knowledge-documents/{knowledge_document_id}", status_code=204)
def detach_service_knowledge_document(
    service_id: uuid.UUID,
    knowledge_document_id: uuid.UUID,
    current_user: BusinessUser = Depends(require_role(["owner", "admin"])),
    db: Session = Depends(get_db),
) -> None:
    detached = service_knowledge_service.detach_document(
        db,
        business_id=current_user.business_id,
        service_id=service_id,
        knowledge_document_id=knowledge_document_id,
    )
    if not detached:
        raise NotFoundError("This document is not attached to this service.")
