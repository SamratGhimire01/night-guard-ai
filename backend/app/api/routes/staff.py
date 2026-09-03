import uuid

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.api.dependencies import get_current_user, get_db, require_role
from app.core.exceptions import NotFoundError
from app.db.models.business import BusinessUser
from app.schemas.staff import StaffCreate, StaffRead, StaffUpdate
from app.services import staff_service

router = APIRouter()


@router.get("/staff", response_model=list[StaffRead])
def list_staff(
    current_user: BusinessUser = Depends(get_current_user), db: Session = Depends(get_db)
) -> list[StaffRead]:
    staff = staff_service.list_staff(db, business_id=current_user.business_id)
    return [StaffRead.model_validate(s) for s in staff]


@router.post("/staff", response_model=StaffRead, status_code=201)
def create_staff(
    payload: StaffCreate,
    current_user: BusinessUser = Depends(require_role(["owner", "admin"])),
    db: Session = Depends(get_db),
) -> StaffRead:
    staff = staff_service.create_staff(db, business_id=current_user.business_id, payload=payload)
    return StaffRead.model_validate(staff)


@router.patch("/staff/{staff_id}", response_model=StaffRead)
def update_staff(
    staff_id: uuid.UUID,
    payload: StaffUpdate,
    current_user: BusinessUser = Depends(require_role(["owner", "admin"])),
    db: Session = Depends(get_db),
) -> StaffRead:
    staff = staff_service.update_staff(
        db, business_id=current_user.business_id, staff_id=staff_id, payload=payload
    )
    if staff is None:
        raise NotFoundError("Staff member not found.")
    return StaffRead.model_validate(staff)


@router.delete("/staff/{staff_id}", status_code=204)
def delete_staff(
    staff_id: uuid.UUID,
    current_user: BusinessUser = Depends(require_role(["owner", "admin"])),
    db: Session = Depends(get_db),
) -> None:
    deleted = staff_service.delete_staff(db, business_id=current_user.business_id, staff_id=staff_id)
    if not deleted:
        raise NotFoundError("Staff member not found.")
