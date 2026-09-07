import logging

import jwt
from fastapi import APIRouter, Depends
from fastapi.responses import RedirectResponse
from sqlalchemy.orm import Session

from app.api.dependencies import get_current_user, get_db, require_plan, require_role
from app.core.config import settings
from app.core.security import create_oauth_state_token, decode_oauth_state_token
from app.db.models.business import Business, BusinessPlan, BusinessUser
from app.schemas.google_calendar import GoogleCalendarAuthorizationURL, GoogleCalendarStatus
from app.services import google_calendar_service

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/integrations/google-calendar")

_FRONTEND_PAGE = "/dashboard/google-calendar"


@router.get("/connect", response_model=GoogleCalendarAuthorizationURL)
def connect(
    current_user: BusinessUser = Depends(require_role(["owner", "admin"])),
    _plan_gate: BusinessUser = Depends(require_plan(BusinessPlan.PREMIUM)),
) -> GoogleCalendarAuthorizationURL:
    """Returns the real Google consent URL rather than redirecting directly:
    a plain browser navigation can't carry an Authorization header, so the
    dashboard calls this via its normal authenticated apiFetch and THEN
    navigates the whole page to the URL in the response — that's what lets
    this stay gated behind require_role/require_plan like every other
    business-data endpoint. require_plan raises a real 402 for a Free-plan
    business before this ever returns a URL."""
    state = create_oauth_state_token(current_user.business_id)
    return GoogleCalendarAuthorizationURL(authorization_url=google_calendar_service.build_authorization_url(state))


@router.get("/callback")
def callback(
    code: str | None = None,
    state: str | None = None,
    error: str | None = None,
    db: Session = Depends(get_db),
) -> RedirectResponse:
    """Google redirects the user's real browser here directly — no
    Authorization header, no bearer token. `state` (minted by /connect) is
    the only thing identifying which business this is; every failure honestly
    redirects back to the dashboard with a query param instead of a raw 500,
    since a real user's browser lands here, not an API client."""
    target = f"{settings.dashboard_base_url}{_FRONTEND_PAGE}"
    if error:
        return RedirectResponse(f"{target}?gcal_error={error}", status_code=302)
    if not code or not state:
        return RedirectResponse(f"{target}?gcal_error=missing_code_or_state", status_code=302)

    try:
        business_id = decode_oauth_state_token(state)
    except jwt.PyJWTError:
        return RedirectResponse(f"{target}?gcal_error=invalid_or_expired_state", status_code=302)

    business = db.get(Business, business_id)
    if business is None or business.plan != BusinessPlan.PREMIUM:
        # Re-checked here, not just at /connect — a real, if narrow, race: the
        # business could have been downgraded during the real consent
        # round-trip with Google.
        return RedirectResponse(f"{target}?gcal_error=plan_required", status_code=302)

    try:
        google_calendar_service.complete_oauth_connection(db, business_id=business_id, code=code)
    except google_calendar_service.GoogleCalendarError:
        logger.warning(
            "google calendar oauth connection failed for business_id=%s", business_id, exc_info=True
        )
        return RedirectResponse(f"{target}?gcal_error=connection_failed", status_code=302)

    return RedirectResponse(f"{target}?gcal_connected=1", status_code=302)


@router.get("/status", response_model=GoogleCalendarStatus)
def status(
    current_user: BusinessUser = Depends(get_current_user), db: Session = Depends(get_db)
) -> GoogleCalendarStatus:
    """Any authenticated role can read (same bar as GET /business/plan) —
    reading connection state is never itself a premium action; only /connect
    is gated. Honest for a downgraded business: still shows the real stored
    state rather than pretending it's disconnected."""
    return GoogleCalendarStatus(**google_calendar_service.get_status(db, business_id=current_user.business_id))


@router.post("/disconnect", response_model=GoogleCalendarStatus)
def disconnect(
    current_user: BusinessUser = Depends(require_role(["owner", "admin"])), db: Session = Depends(get_db)
) -> GoogleCalendarStatus:
    """Deliberately not plan-gated: a business must always be able to
    disconnect (e.g. right after a downgrade), never blocked from removing
    its own stored tokens."""
    google_calendar_service.disconnect(db, business_id=current_user.business_id)
    return GoogleCalendarStatus(connected=False, calendar_name=None)
