from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.api.dependencies import get_current_user, get_db
from app.core.config import settings
from app.core.exceptions import TooManyRequestsError
from app.core.rate_limit import login_rate_limiter, password_reset_rate_limiter
from app.core.security import create_access_token
from app.db.models.business import BusinessUser
from app.schemas.auth import (
    ChangePasswordRequest,
    CurrentUserResponse,
    ForgotPasswordRequest,
    ResetPasswordRequest,
    LoginRequest,
    RegisterRequest,
    RegisterResponse,
    TokenResponse,
)
from app.services import account_service, auth_service

router = APIRouter()


@router.post("/register", response_model=RegisterResponse, status_code=201)
def register(payload: RegisterRequest, db: Session = Depends(get_db)) -> RegisterResponse:
    user = auth_service.register_business(db, payload)
    return RegisterResponse(
        business_id=user.business_id, user_id=user.id, email=user.email, role=user.role.value
    )


@router.post("/login", response_model=TokenResponse)
def login(payload: LoginRequest, db: Session = Depends(get_db)) -> TokenResponse:
    rate_limit_key = payload.email.lower()
    if login_rate_limiter.is_blocked(rate_limit_key):
        raise TooManyRequestsError("Too many login attempts. Try again later.")
    login_rate_limiter.record_attempt(rate_limit_key)

    user = auth_service.authenticate(db, payload.email, payload.password)
    return _token_for(user)


def _token_for(user: BusinessUser) -> TokenResponse:
    token = create_access_token(
        user_id=user.id, business_id=user.business_id, role=user.role.value, password_hash=user.hashed_password
    )
    return TokenResponse(access_token=token, expires_in=settings.access_token_expire_minutes * 60)


@router.get("/me", response_model=CurrentUserResponse)
def me(current_user: BusinessUser = Depends(get_current_user)) -> CurrentUserResponse:
    return CurrentUserResponse(
        user_id=current_user.id,
        business_id=current_user.business_id,
        email=current_user.email,
        role=current_user.role.value,
    )


@router.post("/forgot-password", status_code=202)
def forgot_password(payload: ForgotPasswordRequest, db: Session = Depends(get_db)) -> dict:
    """Emails a reset link if the address has a login. Same answer either way (no way to probe which emails exist)."""
    key = payload.email.lower()
    if not password_reset_rate_limiter.is_blocked(key):
        password_reset_rate_limiter.record_attempt(key)
        account_service.request_password_reset(db, email=payload.email)
    return {"message": "If that email has an account, we've sent a link to reset the password."}


@router.post("/reset-password", response_model=TokenResponse)
def reset_password(payload: ResetPasswordRequest, db: Session = Depends(get_db)) -> TokenResponse:
    """Sets a new password from an emailed reset or invite link, and logs the person straight in."""
    user = account_service.set_password_from_link(db, token=payload.token, new_password=payload.new_password)
    return _token_for(user)


@router.post("/change-password", response_model=TokenResponse)
def change_password(
    payload: ChangePasswordRequest,
    current_user: BusinessUser = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> TokenResponse:
    """Changes the password and returns a fresh token for this session; every other session is signed out."""
    user = account_service.change_password(
        db, user=current_user, current_password=payload.current_password, new_password=payload.new_password
    )
    return _token_for(user)
