import uuid

import jwt
from fastapi import Depends
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.orm import Session

from app.core.exceptions import ForbiddenError, UnauthorizedError
from app.core.security import decode_access_token
from app.db.database import get_db
from app.db.models.business import BusinessUser

__all__ = ["get_db", "get_current_user", "require_role"]

_bearer_scheme = HTTPBearer()


def get_current_user(
    credentials: HTTPAuthorizationCredentials = Depends(_bearer_scheme),
    db: Session = Depends(get_db),
) -> BusinessUser:
    """Validates the JWT and loads the BusinessUser it names.

    business_id and role for the rest of this request come ONLY from the
    validated token (current_user.business_id / current_user.role) — every
    business-data endpoint must scope its queries using current_user.business_id
    from this dependency, never a business_id read from the request body/query.
    """
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
