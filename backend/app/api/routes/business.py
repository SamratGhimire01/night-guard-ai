import uuid

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.api.dependencies import get_current_user, get_db, require_role
from app.core.entitlements import PLAN_FEATURES
from app.core.exceptions import NotFoundError
from app.db.models.business import BusinessUser
from app.schemas.business import BusinessRead, BusinessUpdate
from app.schemas.business_hours import (
    BusinessHoursUpdate,
    BusinessHourRead,
    HolidayExceptionCreate,
    HolidayExceptionRead,
)
from app.schemas.plan import PlanRead
from app.services import business_hours_service, business_service

router = APIRouter()


@router.get("/business/me", response_model=BusinessRead)
def get_my_business(
    current_user: BusinessUser = Depends(get_current_user), db: Session = Depends(get_db)
) -> BusinessRead:
    business = business_service.get_business(db, business_id=current_user.business_id)
    return BusinessRead.model_validate(business)


@router.get("/business/plan", response_model=PlanRead)
def get_my_plan(
    current_user: BusinessUser = Depends(get_current_user), db: Session = Depends(get_db)
) -> PlanRead:
    """Phase 34, requirement #5 — any authenticated business user (not just
    owner/admin, same read-access bar as GET /business/me) can see their own
    real plan and what it includes. This is the real data endpoint a future
    dashboard "billing" screen will read from — no dashboard exists yet
    (frontend/ is still a placeholder, per Phase 28), so this is the whole
    deliverable for now."""
    business = business_service.get_business(db, business_id=current_user.business_id)
    return PlanRead(business_id=business.id, plan=business.plan, features=PLAN_FEATURES[business.plan])


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
