import uuid

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.models.staff import Staff
from app.schemas.staff import StaffCreate, StaffUpdate


def list_staff(db: Session, *, business_id: uuid.UUID) -> list[Staff]:
    return list(db.execute(select(Staff).where(Staff.business_id == business_id)).scalars())


def create_staff(db: Session, *, business_id: uuid.UUID, payload: StaffCreate) -> Staff:
    staff = Staff(business_id=business_id, **payload.model_dump())
    db.add(staff)
    db.commit()
    db.refresh(staff)
    return staff


def get_staff(db: Session, *, business_id: uuid.UUID, staff_id: uuid.UUID) -> Staff | None:
    return db.execute(
        select(Staff).where(Staff.id == staff_id, Staff.business_id == business_id)
    ).scalar_one_or_none()


def update_staff(
    db: Session, *, business_id: uuid.UUID, staff_id: uuid.UUID, payload: StaffUpdate
) -> Staff | None:
    staff = get_staff(db, business_id=business_id, staff_id=staff_id)
    if staff is None:
        return None
    for field, value in payload.model_dump(exclude_unset=True, exclude_none=True).items():
        setattr(staff, field, value)
    db.commit()
    db.refresh(staff)
    return staff


def delete_staff(db: Session, *, business_id: uuid.UUID, staff_id: uuid.UUID) -> bool:
    staff = get_staff(db, business_id=business_id, staff_id=staff_id)
    if staff is None:
        return False
    db.delete(staff)
    db.commit()
    return True
