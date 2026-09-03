from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.exceptions import ConflictError, UnauthorizedError
from app.core.security import hash_password, verify_password
from app.db.models.business import Business, BusinessUser, BusinessUserRole
from app.schemas.auth import RegisterRequest


def register_business(db: Session, payload: RegisterRequest) -> BusinessUser:
    """Creates a Business + its first BusinessUser (role=owner) in one transaction."""
    existing = db.execute(
        select(BusinessUser).where(BusinessUser.email == payload.email)
    ).scalar_one_or_none()
    if existing is not None:
        raise ConflictError("This email is already registered.")

    business = Business(name=payload.business_name, timezone=payload.timezone)
    db.add(business)
    db.flush()  # assigns business.id without ending the transaction

    user = BusinessUser(
        business_id=business.id,
        email=payload.email,
        hashed_password=hash_password(payload.password),
        role=BusinessUserRole.OWNER,
    )
    db.add(user)
    db.commit()
    db.refresh(user)
    return user


def authenticate(db: Session, email: str, password: str) -> BusinessUser:
    user = db.execute(select(BusinessUser).where(BusinessUser.email == email)).scalar_one_or_none()
    if user is None or not verify_password(password, user.hashed_password):
        raise UnauthorizedError("Invalid email or password.")
    return user
