import re
import uuid
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, EmailStr, field_validator

from app.schemas.common import safe_str

_PASSWORD_MIN_LENGTH = 8
# bcrypt's real hard limit is 72 BYTES — anything past that is silently
# ignored by the algorithm itself, not a crash, but capping the accepted
# input here (Phase 29) means the truncation is visible/rejected up front
# rather than a footgun where two different long passwords quietly hash
# identically. Also closes the same unbounded-string shape as
# business_name below (a 200,000-char business_name crashed with a raw 500
# — see app/schemas/common.py's docstring).
_PASSWORD_MAX_LENGTH = 72


def _validate_password_strength(password: str) -> str:
    if len(password) < _PASSWORD_MIN_LENGTH:
        raise ValueError(f"Password must be at least {_PASSWORD_MIN_LENGTH} characters long.")
    if not re.search(r"[A-Za-z]", password):
        raise ValueError("Password must contain at least one letter.")
    if not re.search(r"[0-9]", password):
        raise ValueError("Password must contain at least one digit.")
    return password


class RegisterRequest(BaseModel):
    business_name: safe_str(255)
    timezone: safe_str(64)
    email: EmailStr
    password: safe_str(_PASSWORD_MAX_LENGTH)

    @field_validator("password")
    @classmethod
    def password_strength(cls, value: str) -> str:
        return _validate_password_strength(value)


class RegisterResponse(BaseModel):
    business_id: uuid.UUID
    user_id: uuid.UUID
    email: EmailStr
    role: str


class LoginRequest(BaseModel):
    email: EmailStr
    password: safe_str(_PASSWORD_MAX_LENGTH)


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    expires_in: int


class CurrentUserResponse(BaseModel):
    user_id: uuid.UUID
    business_id: uuid.UUID
    email: EmailStr
    role: str


class ForgotPasswordRequest(BaseModel):
    email: EmailStr


class ResetPasswordRequest(BaseModel):
    token: safe_str(2000)
    new_password: safe_str(_PASSWORD_MAX_LENGTH)

    @field_validator("new_password")
    @classmethod
    def password_strength(cls, value: str) -> str:
        return _validate_password_strength(value)


class ChangePasswordRequest(BaseModel):
    current_password: safe_str(_PASSWORD_MAX_LENGTH)
    new_password: safe_str(_PASSWORD_MAX_LENGTH)

    @field_validator("new_password")
    @classmethod
    def password_strength(cls, value: str) -> str:
        return _validate_password_strength(value)


class TeamMemberRead(BaseModel):
    model_config = {"from_attributes": True}

    id: uuid.UUID
    email: str
    role: str
    created_at: datetime

    @field_validator("role", mode="before")
    @classmethod
    def role_value(cls, value) -> str:
        return getattr(value, "value", value)


class TeamInviteRequest(BaseModel):
    email: EmailStr
    role: Literal["admin", "staff"]


class TeamInviteResult(BaseModel):
    member: TeamMemberRead
    invite_link: str  # also emailed; shown to the owner so they can pass it on if email isn't set up


class TeamRoleUpdate(BaseModel):
    role: Literal["admin", "staff"]
