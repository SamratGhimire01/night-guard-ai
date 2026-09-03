import uuid

from sqlalchemy.orm import Session

from app.db.models.business import Business
from app.schemas.business import BusinessUpdate


def get_business(db: Session, *, business_id: uuid.UUID) -> Business:
    return db.get(Business, business_id)


def update_business(db: Session, *, business_id: uuid.UUID, payload: BusinessUpdate) -> Business:
    business = db.get(Business, business_id)
    # exclude_unset: a field the client never sent is left alone. A field sent as an
    # explicit null DOES come through (and clears a nullable column) — BusinessUpdate's
    # validators reject an explicit null on name/timezone before this ever runs, so a
    # NOT NULL violation can't reach the DB from here.
    for field, value in payload.model_dump(exclude_unset=True).items():
        setattr(business, field, value)
    db.commit()
    db.refresh(business)
    return business
