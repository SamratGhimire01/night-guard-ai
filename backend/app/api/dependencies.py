import uuid

import jwt
from fastapi import Depends
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.orm import Session

from app.core.entitlements import ensure_plan
from app.core.exceptions import ForbiddenError, UnauthorizedError
from app.core.security import decode_access_token
from app.db.database import get_db
from app.db.models.business import Business, BusinessPlan, BusinessUser

__all__ = ["get_db", "get_current_user", "require_role", "require_plan", "require_superadmin"]

_bearer_scheme = HTTPBearer(auto_error=False)


def get_current_user(
    credentials: HTTPAuthorizationCredentials | None = Depends(_bearer_scheme),
    db: Session = Depends(get_db),
) -> BusinessUser:
    """Validates the JWT and loads the BusinessUser it names.

    business_id and role for the rest of this request come ONLY from the
    validated token (current_user.business_id / current_user.role) — every
    business-data endpoint must scope its queries using current_user.business_id
    from this dependency, never a business_id read from the request body/query.
    """
    if credentials is None:
        # auto_error=False above so a missing header lands here instead of
        # HTTPBearer's own auto_error=True path — which raises a raw 403
        # {"detail": "Not authenticated"} that bypasses the app's uniform
        # error envelope and picks the wrong status code (401 is correct for
        # "no/invalid credentials"; 403 is for "authenticated but not allowed").
        raise UnauthorizedError("Not authenticated.")
    try:
        payload = decode_access_token(credentials.credentials)
    except jwt.ExpiredSignatureError:
        raise UnauthorizedError("Token has expired.")
    except jwt.PyJWTError:
        raise UnauthorizedError("Invalid token.")

    try:
        user_id = uuid.UUID(payload["sub"])
    except (KeyError, ValueError):
        raise UnauthorizedError("Invalid token.")

    user = db.get(BusinessUser, user_id)
    if user is None:
        raise UnauthorizedError("User for this token no longer exists.")
    return user


def require_role(allowed_roles: list[str]):
    """Dependency factory gating a route to specific BusinessUser roles.

    Usage: Depends(require_role(["owner", "admin"]))
    """

    def _check_role(current_user: BusinessUser = Depends(get_current_user)) -> BusinessUser:
        if current_user.role.value not in allowed_roles:
            raise ForbiddenError("You do not have permission to perform this action.")
        return current_user

    return _check_role


def require_plan(minimum: BusinessPlan):
    """Dependency factory gating a route to businesses whose plan meets
    `minimum` (Phase 34). Always re-checks the REAL, current
    `current_user.business_id`'s own Business row on every request — never
    cached, never trusted from the JWT (the token carries no plan claim at
    all), so a downgrade takes effect on the very next request. Raises
    `PlanRequiredError` (402) via the same `ensure_plan` the conversation
    orchestrator's test hook also calls — one real gating function, two
    callers.

    Usage: Depends(require_plan(BusinessPlan.PREMIUM))
    """

    def _check_plan(
        current_user: BusinessUser = Depends(get_current_user), db: Session = Depends(get_db)
    ) -> BusinessUser:
        business = db.get(Business, current_user.business_id)
        ensure_plan(business, minimum)
        return current_user

    return _check_plan


def require_superadmin(current_user: BusinessUser = Depends(get_current_user)) -> BusinessUser:
    """Gates a route to a PLATFORM-level admin (Business.is_superadmin),
    completely independent of `role`/`business_id` — see BusinessUser.
    is_superadmin's docstring. Used only by the admin plan-management
    endpoints (app/api/routes/admin.py); nothing else in this codebase should
    ever need it."""
    if not current_user.is_superadmin:
        raise ForbiddenError("You do not have permission to perform this action.")
    return current_user
