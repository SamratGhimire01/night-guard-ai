import uuid

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.api.dependencies import get_db, require_superadmin
from app.core.entitlements import PLAN_FEATURES
from app.core.exceptions import NotFoundError
from app.db.models.business import BusinessUser
from app.schemas.plan import AdminBusinessRead, AdminPlanUpdate, PlanRead
from app.services import plan_service

router = APIRouter()

# Phase 34, requirement #4 — platform-admin-only endpoints to view/change any
# business's plan. Gated by require_superadmin (Business.is_superadmin),
# which is completely independent of a business's own owner/admin/staff
# roles — a business's own admin must never be able to reach these, or they
# could upgrade themselves to premium for free. There is deliberately no API
# anywhere to grant is_superadmin — see that column's docstring.


@router.get("/admin/businesses", response_model=list[AdminBusinessRead])
def list_businesses(
    current_user: BusinessUser = Depends(require_superadmin), db: Session = Depends(get_db)
) -> list[AdminBusinessRead]:
    businesses = plan_service.list_businesses(db)
    return [AdminBusinessRead.model_validate(b) for b in businesses]


@router.get("/admin/businesses/{business_id}/plan", response_model=PlanRead)
def get_business_plan(
    business_id: uuid.UUID,
    current_user: BusinessUser = Depends(require_superadmin),
    db: Session = Depends(get_db),
) -> PlanRead:
    business = plan_service.get_business(db, business_id=business_id)
    if business is None:
        raise NotFoundError("Business not found.")
    return PlanRead(business_id=business.id, plan=business.plan, features=PLAN_FEATURES[business.plan])


@router.patch("/admin/businesses/{business_id}/plan", response_model=PlanRead)
def update_business_plan(
    business_id: uuid.UUID,
    payload: AdminPlanUpdate,
    current_user: BusinessUser = Depends(require_superadmin),
    db: Session = Depends(get_db),
) -> PlanRead:
    business = plan_service.change_plan(
        db, business_id=business_id, new_plan=payload.plan, actor=current_user.email
    )
    if business is None:
        raise NotFoundError("Business not found.")
    return PlanRead(business_id=business.id, plan=business.plan, features=PLAN_FEATURES[business.plan])
