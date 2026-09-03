import uuid

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.api.dependencies import get_current_user, get_db, require_role
from app.core.exceptions import NotFoundError
from app.db.models.business import BusinessUser
from app.schemas.business import BusinessRead, BusinessUpdate
from app.schemas.business_hours import (
    BusinessHoursUpdate,
    BusinessHourRead,
    HolidayExceptionCreate,
    HolidayExceptionRead,
)
from app.services import business_hours_service, business_service

router = APIRouter()


@router.get("/business/me", response_model=BusinessRead)
def get_my_business(
    current_user: BusinessUser = Depends(get_current_user), db: Session = Depends(get_db)
) -> BusinessRead:
    business = business_service.get_business(db, business_id=current_user.business_id)
    return BusinessRead.model_validate(business)


@router.patch("/business/me", response_model=BusinessRead)
def update_my_business(
    payload: BusinessUpdate,
    current_user: BusinessUser = Depends(require_role(["owner", "admin"])),
    db: Session = Depends(get_db),
) -> BusinessRead:
    business = business_service.update_business(db, business_id=current_user.business_id, payload=payload)
    return BusinessRead.model_validate(business)


@router.get("/business/hours")
def get_business_hours(
    current_user: BusinessUser = Depends(get_current_user), db: Session = Depends(get_db)
) -> dict:
    weekly = business_hours_service.list_hours(db, business_id=current_user.business_id)
    exceptions = business_hours_service.list_exceptions(db, business_id=current_user.business_id)
    return {
        "weekly": [BusinessHourRead.model_validate(day).model_dump(mode="json") for day in weekly],
        "exceptions": [
            HolidayExceptionRead.model_validate(exc).model_dump(mode="json") for exc in exceptions
        ],
    }


@router.put("/business/hours", response_model=list[BusinessHourRead])
def put_business_hours(
    payload: BusinessHoursUpdate,
    current_user: BusinessUser = Depends(require_role(["owner", "admin"])),
    db: Session = Depends(get_db),
) -> list[BusinessHourRead]:
    rows = business_hours_service.replace_hours(db, business_id=current_user.business_id, payload=payload)
    return [BusinessHourRead.model_validate(row) for row in rows]


@router.post("/business/hours/exceptions", response_model=HolidayExceptionRead, status_code=201)
def create_business_hours_exception(
    payload: HolidayExceptionCreate,
    current_user: BusinessUser = Depends(require_role(["owner", "admin"])),
    db: Session = Depends(get_db),
) -> HolidayExceptionRead:
    exception = business_hours_service.create_exception(
        db, business_id=current_user.business_id, payload=payload
    )
    return HolidayExceptionRead.model_validate(exception)


@router.delete("/business/hours/exceptions/{exception_id}", status_code=204)
def delete_business_hours_exception(
    exception_id: uuid.UUID,
    current_user: BusinessUser = Depends(require_role(["owner", "admin"])),
    db: Session = Depends(get_db),
) -> None:
    deleted = business_hours_service.delete_exception(
        db, business_id=current_user.business_id, exception_id=exception_id
    )
    if not deleted:
        raise NotFoundError("Hours exception not found.")
