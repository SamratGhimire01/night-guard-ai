import uuid

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.models.service import Service
from app.schemas.service import ServiceCreate, ServiceUpdate


def list_services(db: Session, *, business_id: uuid.UUID) -> list[Service]:
    return list(db.execute(select(Service).where(Service.business_id == business_id)).scalars())


def create_service(db: Session, *, business_id: uuid.UUID, payload: ServiceCreate) -> Service:
    service = Service(business_id=business_id, **payload.model_dump())
    db.add(service)
    db.commit()
    db.refresh(service)
    return service


def get_service(db: Session, *, business_id: uuid.UUID, service_id: uuid.UUID) -> Service | None:
    return db.execute(
        select(Service).where(Service.id == service_id, Service.business_id == business_id)
    ).scalar_one_or_none()


def update_service(
    db: Session, *, business_id: uuid.UUID, service_id: uuid.UUID, payload: ServiceUpdate
) -> Service | None:
    service = get_service(db, business_id=business_id, service_id=service_id)
    if service is None:
        return None
    # exclude_unset: an omitted field is left alone. An explicit null (only ever
    # possible for description/staff_id — ServiceUpdate's validators reject it for
    # name/price/duration_minutes) clears that nullable column.
    for field, value in payload.model_dump(exclude_unset=True).items():
        setattr(service, field, value)
    db.commit()
    db.refresh(service)
    return service


def delete_service(db: Session, *, business_id: uuid.UUID, service_id: uuid.UUID) -> bool:
    service = get_service(db, business_id=business_id, service_id=service_id)
    if service is None:
        return False
    db.delete(service)
    db.commit()
    return True
