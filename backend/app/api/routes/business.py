import uuid

from datetime import UTC, datetime

from fastapi import APIRouter, Depends, File, UploadFile
from sqlalchemy.orm import Session

from app.api.dependencies import get_current_user, get_db, require_role
from app.core.entitlements import PLAN_FEATURES
from app.core.exceptions import ConflictError, NotFoundError
from app.db.models.business import BusinessPlan, BusinessUser
from app.schemas.business import _AVAILABLE_TIMEZONES, SUPPORTED_CURRENCIES, BusinessRead, BusinessUpdate
from app.schemas.business_hours import (
    BusinessHoursUpdate,
    BusinessHourRead,
    HolidayExceptionCreate,
    HolidayExceptionRead,
)
from app.schemas.plan import PlanRead, UpgradeRequestResult
from app.schemas.widget import WidgetSettings
from app.services import branding_service, business_hours_service, business_service, owner_alert_service, setup_service

router = APIRouter()


@router.get("/business/me", response_model=BusinessRead)
def get_my_business(
    current_user: BusinessUser = Depends(get_current_user), db: Session = Depends(get_db)
) -> BusinessRead:
    business = business_service.get_business(db, business_id=current_user.business_id)
    return BusinessRead.model_validate(business)


@router.get("/business/reference-data")
def get_business_reference_data(current_user: BusinessUser = Depends(get_current_user)) -> dict:
    """Timezone/currency option lists for the Business Profile Settings page's
    dropdowns — served from the exact same sets `BusinessUpdate` validates
    against (app/schemas/business.py), not re-derived client-side from the
    browser's own Intl API. Real, live-found bug this avoids: Chromium's
    `Intl.supportedValuesOf('timeZone')` returns the OLD IANA alias
    "Asia/Katmandu", while Python's `zoneinfo.available_timezones()` (what
    the backend actually validates against) only recognizes the canonical
    "Asia/Kathmandu" — dozens of such aliases genuinely diverge between a
    browser's ICU data and the server's tzdata. Serving the backend's own
    validated set as the dropdown's data guarantees the two can never
    disagree, no matter how either side's timezone database drifts."""
    return {"timezones": sorted(_AVAILABLE_TIMEZONES), "currencies": sorted(SUPPORTED_CURRENCIES)}


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


@router.get("/business/setup-status")
def get_setup_status(current_user: BusinessUser = Depends(get_current_user), db: Session = Depends(get_db)) -> dict:
    """The Overview's "Get set up" checklist, worked out from the business's real data."""
    return setup_service.setup_status(db, business_id=current_user.business_id)


@router.post("/business/plan/upgrade-request", response_model=UpgradeRequestResult)
def request_plan_upgrade(
    current_user: BusinessUser = Depends(require_role(["owner", "admin"])),
    db: Session = Depends(get_db),
) -> UpgradeRequestResult:
    """An owner asks to move to Premium. Recorded on the business (so the platform team sees it in the admin list) and
    emailed to the platform's support address in the background. The email is best effort: the request stands even if
    it can't be sent."""
    business = business_service.get_business(db, business_id=current_user.business_id)
    if business.plan == BusinessPlan.PREMIUM:
        raise ConflictError("This business is already on Premium.")
    business.upgrade_requested_at = datetime.now(UTC)
    db.commit()
    notified = owner_alert_service.send_upgrade_request(
        business_name=business.name, business_id=business.id, requested_by=current_user.email,
        contact_email=business.email,
    )
    return UpgradeRequestResult(requested_at=business.upgrade_requested_at, team_notified=notified)


@router.patch("/business/me", response_model=BusinessRead)
def update_my_business(
    payload: BusinessUpdate,
    current_user: BusinessUser = Depends(require_role(["owner", "admin"])),
    db: Session = Depends(get_db),
) -> BusinessRead:
    business = business_service.update_business(db, business_id=current_user.business_id, payload=payload)
    return BusinessRead.model_validate(business)


@router.post("/business/logo", response_model=BusinessRead)
async def upload_my_logo(
    file: UploadFile = File(...),
    current_user: BusinessUser = Depends(require_role(["owner", "admin"])),
    db: Session = Depends(get_db),
) -> BusinessRead:
    """Upload the business logo (PNG, JPG or WebP, up to 1 MB). It replaces any logo URL typed in earlier and is shown
    in the website chat widget and the dashboard."""
    raw = await file.read(branding_service.MAX_LOGO_BYTES + 1)
    business = branding_service.set_logo(db, business_id=current_user.business_id, raw=raw)
    return BusinessRead.model_validate(business)


@router.delete("/business/logo", response_model=BusinessRead)
def delete_my_logo(
    current_user: BusinessUser = Depends(require_role(["owner", "admin"])),
    db: Session = Depends(get_db),
) -> BusinessRead:
    business = branding_service.clear_logo(db, business_id=current_user.business_id)
    return BusinessRead.model_validate(business)


@router.get("/business/widget-settings", response_model=WidgetSettings)
def get_my_widget_settings(
    current_user: BusinessUser = Depends(get_current_user), db: Session = Depends(get_db)
) -> WidgetSettings:
    business = business_service.get_business(db, business_id=current_user.business_id)
    return branding_service.get_widget_settings(business)


@router.put("/business/widget-settings", response_model=WidgetSettings)
def update_my_widget_settings(
    payload: WidgetSettings,
    current_user: BusinessUser = Depends(require_role(["owner", "admin"])),
    db: Session = Depends(get_db),
) -> WidgetSettings:
    return branding_service.update_widget_settings(db, business_id=current_user.business_id, payload=payload)


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
