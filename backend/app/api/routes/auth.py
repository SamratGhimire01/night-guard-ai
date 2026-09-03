from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.api.dependencies import get_current_user, get_db
from app.core.config import settings
from app.core.exceptions import TooManyRequestsError
from app.core.rate_limit import login_rate_limiter
from app.core.security import create_access_token
from app.db.models.business import BusinessUser
from app.schemas.auth import (
    CurrentUserResponse,
    LoginRequest,
    RegisterRequest,
    RegisterResponse,
    TokenResponse,
)
from app.services import auth_service

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
    token = create_access_token(user_id=user.id, business_id=user.business_id, role=user.role.value)
    return TokenResponse(access_token=token, expires_in=settings.access_token_expire_minutes * 60)


@router.get("/me", response_model=CurrentUserResponse)
def me(current_user: BusinessUser = Depends(get_current_user)) -> CurrentUserResponse:
    return CurrentUserResponse(
        user_id=current_user.id,
        business_id=current_user.business_id,
        email=current_user.email,
        role=current_user.role.value,
    )
