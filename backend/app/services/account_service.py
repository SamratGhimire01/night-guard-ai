"""Passwords and team logins: forgot/reset/change password, and owners adding, re-roling and removing team members.

Emails (reset links, invites) go out on a background thread from the platform email account, so a slow mail server
never holds up the request, and "forgot password" answers the same way whether or not the address has an account."""

import logging
import secrets
import threading
import uuid

import jwt
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.exceptions import ConflictError, ForbiddenError, NotFoundError, UnauthorizedError, UnprocessableEntityError
from app.core.security import (
    INVITE_PURPOSE,
    PASSWORD_RESET_PURPOSE,
    create_password_token,
    decode_password_token,
    hash_password,
    password_fingerprint,
    verify_password,
)
from app.db.models.business import Business, BusinessUser, BusinessUserRole
from app.services.notifications.email_provider import EmailNotificationProvider

logger = logging.getLogger(__name__)

RESET_LINK_MINUTES = 60
INVITE_LINK_MINUTES = 7 * 24 * 60


def _link(token: str) -> str:
    return f"{settings.dashboard_base_url.rstrip('/')}/reset-password?token={token}"


def _email_in_background(*, to: str, subject: str, body: str) -> None:
    def send():
        try:
            EmailNotificationProvider().send(to=to, subject=subject, body=body)
        except Exception:
            logger.warning("account email to %s failed", to, exc_info=True)

    threading.Thread(target=send, daemon=True).start()


def request_password_reset(db: Session, *, email: str) -> None:
    """Emails a reset link if the address has an account. Silent either way, so the endpoint can't be used to find out
    which emails are registered."""
    user = db.execute(
        select(BusinessUser).where(func.lower(BusinessUser.email) == email.strip().lower())
    ).scalar_one_or_none()
    if user is None:
        return
    token = create_password_token(
        user_id=user.id, password_hash=user.hashed_password, purpose=PASSWORD_RESET_PURPOSE, expires_minutes=RESET_LINK_MINUTES
    )
    _email_in_background(
        to=user.email,
        subject="Reset your Night Guard AI password",
        body=(
            "Someone (hopefully you) asked to reset the password for your Night Guard AI dashboard.\n\n"
            f"Choose a new password here (the link works once, for the next hour):\n{_link(token)}\n\n"
            "If you didn't ask for this, you can ignore this email. Your password stays the same."
        ),
    )


def set_password_from_link(db: Session, *, token: str, new_password: str) -> BusinessUser:
    try:
        user_id, _purpose, fingerprint = decode_password_token(token)
    except jwt.ExpiredSignatureError as exc:
        raise UnauthorizedError("This link has expired. Ask for a new one from the login page.") from exc
    except jwt.PyJWTError as exc:
        raise UnauthorizedError("This link isn't valid. Ask for a new one from the login page.") from exc
    user = db.get(BusinessUser, user_id)
    if user is None or password_fingerprint(user.hashed_password) != fingerprint:
        raise UnauthorizedError("This link has already been used. Ask for a new one from the login page.")
    user.hashed_password = hash_password(new_password)
    db.commit()
    db.refresh(user)
    return user


def change_password(db: Session, *, user: BusinessUser, current_password: str, new_password: str) -> BusinessUser:
    if not verify_password(current_password, user.hashed_password):
        raise UnprocessableEntityError("Your current password isn't right.")
    if current_password == new_password:
        raise UnprocessableEntityError("Choose a password different from your current one.")
    user.hashed_password = hash_password(new_password)
    db.commit()
    db.refresh(user)
    return user


# ---- team ----

def list_team(db: Session, *, business_id: uuid.UUID) -> list[BusinessUser]:
    return list(
        db.execute(
            select(BusinessUser).where(BusinessUser.business_id == business_id).order_by(BusinessUser.created_at)
        ).scalars()
    )


def _can_manage(actor: BusinessUser, role: BusinessUserRole) -> bool:
    """Owners manage everyone except other owners; admins manage staff only."""
    if role == BusinessUserRole.OWNER:
        return False
    if actor.role == BusinessUserRole.OWNER:
        return True
    return actor.role == BusinessUserRole.ADMIN and role == BusinessUserRole.STAFF


def invite_member(db: Session, *, actor: BusinessUser, email: str, role: BusinessUserRole) -> tuple[BusinessUser, str]:
    """Creates the login with an unusable random password and returns (user, set-password link). The link is also
    emailed; returning it lets the owner pass it on themselves when email isn't set up."""
    if not _can_manage(actor, role):
        raise ForbiddenError("You can't add someone with that role.")
    email = email.strip().lower()
    if db.execute(select(BusinessUser.id).where(func.lower(BusinessUser.email) == email)).scalar_one_or_none() is not None:
        raise ConflictError("This email already has a Night Guard AI login.")
    user = BusinessUser(
        business_id=actor.business_id, email=email, role=role, hashed_password=hash_password(secrets.token_urlsafe(32))
    )
    db.add(user)
    db.commit()
    db.refresh(user)
    business = db.get(Business, actor.business_id)
    token = create_password_token(
        user_id=user.id, password_hash=user.hashed_password, purpose=INVITE_PURPOSE, expires_minutes=INVITE_LINK_MINUTES
    )
    link = _link(token)
    _email_in_background(
        to=email,
        subject=f"You've been added to {business.name} on Night Guard AI",
        body=(
            f"{actor.email} added you to the {business.name} dashboard on Night Guard AI as {role.value}.\n\n"
            f"Choose your password to get started (the link works for 7 days):\n{link}\n"
        ),
    )
    return user, link


def _member(db: Session, *, actor: BusinessUser, user_id: uuid.UUID) -> BusinessUser:
    user = db.get(BusinessUser, user_id)
    if user is None or user.business_id != actor.business_id:
        raise NotFoundError("Team member not found.")
    if user.id == actor.id:
        raise ForbiddenError("You can't change your own access here.")
    return user


def change_role(db: Session, *, actor: BusinessUser, user_id: uuid.UUID, role: BusinessUserRole) -> BusinessUser:
    user = _member(db, actor=actor, user_id=user_id)
    if not (_can_manage(actor, user.role) and _can_manage(actor, role)):
        raise ForbiddenError("You can't give or change that role.")
    user.role = role
    db.commit()
    db.refresh(user)
    return user


def remove_member(db: Session, *, actor: BusinessUser, user_id: uuid.UUID) -> None:
    user = _member(db, actor=actor, user_id=user_id)
    if not _can_manage(actor, user.role):
        raise ForbiddenError("You can't remove this person.")
    db.delete(user)
    db.commit()
