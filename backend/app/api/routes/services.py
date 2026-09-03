import uuid

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.api.dependencies import get_current_user, get_db, require_role
from app.core.exceptions import NotFoundError
from app.db.models.business import BusinessUser
from app.schemas.service import ServiceCreate, ServiceRead, ServiceUpdate
from app.services import service_service

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
