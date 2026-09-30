from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.exceptions import ConflictError, UnauthorizedError
from app.core.security import hash_password, verify_password
from app.db.models.business import Business, BusinessUser, BusinessUserRole
from app.schemas.auth import RegisterRequest


# The currency a new business most likely charges in, from the time zone its browser reported at sign-up. Only exact
# zones and region prefixes we are sure of; everything else keeps the USD default and the owner can change it.
_CURRENCY_BY_ZONE = {
    "Asia/Kathmandu": "NPR", "Asia/Katmandu": "NPR",
    "Asia/Kolkata": "INR", "Asia/Calcutta": "INR",
    "Europe/London": "GBP",
    "Asia/Tokyo": "JPY",
    "Asia/Shanghai": "CNY", "Asia/Chongqing": "CNY", "Asia/Harbin": "CNY", "Asia/Urumqi": "CNY",
    "Asia/Singapore": "SGD",
    "America/Toronto": "CAD", "America/Vancouver": "CAD", "America/Edmonton": "CAD", "America/Winnipeg": "CAD",
    "America/Halifax": "CAD", "America/St_Johns": "CAD", "America/Regina": "CAD",
}
_EURO_ZONES = {
    "Europe/Amsterdam", "Europe/Athens", "Europe/Berlin", "Europe/Brussels", "Europe/Dublin", "Europe/Helsinki",
    "Europe/Lisbon", "Europe/Luxembourg", "Europe/Madrid", "Europe/Paris", "Europe/Rome", "Europe/Vienna",
    "Europe/Bratislava", "Europe/Ljubljana", "Europe/Tallinn", "Europe/Riga", "Europe/Vilnius", "Europe/Zagreb",
    "Europe/Malta", "Asia/Nicosia", "Europe/Monaco",
}


def currency_for_timezone(timezone: str) -> str:
    if timezone in _CURRENCY_BY_ZONE:
        return _CURRENCY_BY_ZONE[timezone]
    if timezone in _EURO_ZONES:
        return "EUR"
    if timezone.startswith("Australia/"):
        return "AUD"
    return "USD"


def register_business(db: Session, payload: RegisterRequest) -> BusinessUser:
    """Creates a Business + its first BusinessUser (role=owner) in one transaction."""
    existing = db.execute(
        select(BusinessUser).where(func.lower(BusinessUser.email) == payload.email.strip().lower())
    ).scalar_one_or_none()
    if existing is not None:
        raise ConflictError("This email is already registered.")

    business = Business(
        name=payload.business_name, timezone=payload.timezone, currency=currency_for_timezone(payload.timezone)
    )
    db.add(business)
    db.flush()  # assigns business.id without ending the transaction

    user = BusinessUser(
        business_id=business.id,
        email=payload.email.strip().lower(),
        hashed_password=hash_password(payload.password),
        role=BusinessUserRole.OWNER,
    )
    db.add(user)
    db.commit()
    db.refresh(user)
    return user


def authenticate(db: Session, email: str, password: str) -> BusinessUser:
    user = db.execute(
        select(BusinessUser).where(func.lower(BusinessUser.email) == email.strip().lower())
    ).scalar_one_or_none()
    if user is None or not verify_password(password, user.hashed_password):
        raise UnauthorizedError("Invalid email or password.")
    return user
