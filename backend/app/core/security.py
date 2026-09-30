"""Password hashing and JWT issuance/verification.

No authorization logic lives here (see app/api/dependencies.py for
get_current_user / require_role) — this module only deals with proving who
someone is and producing/reading the token that says so.
"""

import hashlib
import uuid
from datetime import datetime, timedelta, timezone

import bcrypt
import jwt

from app.core.config import settings


def hash_password(password: str) -> str:
    return bcrypt.hashpw(password.encode("utf-8"), bcrypt.gensalt()).decode("utf-8")


def verify_password(password: str, hashed_password: str) -> bool:
    return bcrypt.checkpw(password.encode("utf-8"), hashed_password.encode("utf-8"))


def password_fingerprint(hashed_password: str) -> str:
    """Short digest of the stored password hash. Carried in access and password-reset tokens, so changing the password
    invalidates every token issued before (other sessions are signed out, a reset link works only once)."""
    return hashlib.sha256(hashed_password.encode("utf-8")).hexdigest()[:16]


def create_access_token(
    *,
    user_id: uuid.UUID,
    business_id: uuid.UUID,
    role: str,
    expires_minutes: int | None = None,
    password_hash: str | None = None,
) -> str:
    """Issues a JWT whose payload carries business_id and role.

    business_id/role are read from this token by get_current_user on every
    subsequent request — they are never taken from client-supplied request
    data for any authenticated endpoint.
    """
    if expires_minutes is None:
        expires_minutes = settings.access_token_expire_minutes

    now = datetime.now(timezone.utc)
    payload = {
        "sub": str(user_id),
        "business_id": str(business_id),
        "role": role,
        "iat": now,
        "exp": now + timedelta(minutes=expires_minutes),
    }
    if password_hash is not None:
        payload["pv"] = password_fingerprint(password_hash)
    return jwt.encode(payload, settings.secret_key, algorithm=settings.jwt_algorithm)


PASSWORD_RESET_PURPOSE = "password_reset"
INVITE_PURPOSE = "invite"


def create_password_token(*, user_id: uuid.UUID, password_hash: str, purpose: str, expires_minutes: int) -> str:
    """A link token that lets someone set a new password: a forgotten-password reset or a team invite. Never accepted
    as an access token (get_current_user rejects any token with a purpose), and dead once the password changes."""
    now = datetime.now(timezone.utc)
    payload = {
        "sub": str(user_id),
        "purpose": purpose,
        "pv": password_fingerprint(password_hash),
        "iat": now,
        "exp": now + timedelta(minutes=expires_minutes),
    }
    return jwt.encode(payload, settings.secret_key, algorithm=settings.jwt_algorithm)


def decode_password_token(token: str) -> tuple[uuid.UUID, str, str]:
    """(user_id, purpose, password fingerprint). Raises jwt.PyJWTError for anything invalid, expired or not a
    password token."""
    payload = jwt.decode(token, settings.secret_key, algorithms=[settings.jwt_algorithm])
    if payload.get("purpose") not in (PASSWORD_RESET_PURPOSE, INVITE_PURPOSE):
        raise jwt.InvalidTokenError("Not a password token.")
    try:
        return uuid.UUID(payload["sub"]), payload["purpose"], payload["pv"]
    except (KeyError, ValueError) as exc:
        raise jwt.InvalidTokenError("Malformed password token.") from exc


def decode_access_token(token: str) -> dict:
    """Raises jwt.PyJWTError (or a subclass) if the token is invalid/expired/tampered."""
    return jwt.decode(token, settings.secret_key, algorithms=[settings.jwt_algorithm])


_OAUTH_STATE_PURPOSE = "google_oauth_state"


def create_oauth_state_token(business_id: uuid.UUID) -> str:
    """Signs a short-lived, single-purpose token carrying business_id through
    Google's real OAuth redirect round-trip (Phase 40) — Google's callback
    request carries no Authorization header, so this (not a normal access
    token, which would otherwise double as live API credentials if it ever
    leaked via a referrer header) is how the callback learns which business
    initiated the connection. A distinct `purpose` claim keeps this from ever
    being accepted by decode_access_token's callers or vice versa."""
    now = datetime.now(timezone.utc)
    payload = {
        "business_id": str(business_id),
        "purpose": _OAUTH_STATE_PURPOSE,
        "iat": now,
        "exp": now + timedelta(minutes=10),
    }
    return jwt.encode(payload, settings.secret_key, algorithm=settings.jwt_algorithm)


def decode_oauth_state_token(token: str) -> uuid.UUID:
    """Raises jwt.PyJWTError (or a subclass) if invalid/expired/tampered/wrong-purpose."""
    payload = jwt.decode(token, settings.secret_key, algorithms=[settings.jwt_algorithm])
    if payload.get("purpose") != _OAUTH_STATE_PURPOSE:
        raise jwt.InvalidTokenError("Token is not a valid OAuth state token.")
    return uuid.UUID(payload["business_id"])
