import re
import uuid

from pydantic import BaseModel, EmailStr, field_validator

_PASSWORD_MIN_LENGTH = 8


def _validate_password_strength(password: str) -> str:
    if len(password) < _PASSWORD_MIN_LENGTH:
        raise ValueError(f"Password must be at least {_PASSWORD_MIN_LENGTH} characters long.")
    if not re.search(r"[A-Za-z]", password):
        raise ValueError("Password must contain at least one letter.")
    if not re.search(r"[0-9]", password):
        raise ValueError("Password must contain at least one digit.")
    return password


class RegisterRequest(BaseModel):
    business_name: str
    timezone: str
    email: EmailStr
    password: str

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
    password: str


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    expires_in: int


class CurrentUserResponse(BaseModel):
    user_id: uuid.UUID
    business_id: uuid.UUID
    email: EmailStr
    role: str
