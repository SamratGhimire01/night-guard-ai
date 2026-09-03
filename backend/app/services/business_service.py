import uuid

from sqlalchemy.orm import Session

from app.db.models.business import Business
from app.schemas.business import BusinessUpdate


def get_business(db: Session, *, business_id: uuid.UUID) -> Business:
    return db.get(Business, business_id)


def update_business(db: Session, *, business_id: uuid.UUID, payload: BusinessUpdate) -> Business:
    business = db.get(Business, business_id)
    # exclude_none: a PATCH sending an explicit null for a required field (name,
    # timezone) would otherwise hit the DB's NOT NULL constraint as a 500 instead
    # of a clean no-op; nullable fields are simply cleared with "" instead of null.
    for field, value in payload.model_dump(exclude_unset=True, exclude_none=True).items():
        setattr(business, field, value)
    db.commit()
    db.refresh(business)
    return business
