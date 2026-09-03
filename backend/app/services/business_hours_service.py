import uuid

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from app.core.exceptions import ConflictError
from app.db.models.business import BusinessHours, BusinessHoursException
from app.schemas.business_hours import BusinessHoursUpdate, HolidayExceptionCreate


def list_hours(db: Session, *, business_id: uuid.UUID) -> list[BusinessHours]:
    return list(
        db.execute(
            select(BusinessHours)
            .where(BusinessHours.business_id == business_id)
            .order_by(BusinessHours.day_of_week)
        ).scalars()
    )


def replace_hours(
    db: Session, *, business_id: uuid.UUID, payload: BusinessHoursUpdate
) -> list[BusinessHours]:
    """Full-week replace: delete whatever exists for this business, insert the new set."""
    db.execute(delete(BusinessHours).where(BusinessHours.business_id == business_id))
    rows = [
        BusinessHours(
            business_id=business_id,
            day_of_week=day.day_of_week,
            closed=day.closed,
            open_time=day.open_time,
            close_time=day.close_time,
        )
        for day in payload.days
    ]
    db.add_all(rows)
    db.commit()
    return list_hours(db, business_id=business_id)


def list_exceptions(db: Session, *, business_id: uuid.UUID) -> list[BusinessHoursException]:
    return list(
        db.execute(
            select(BusinessHoursException)
            .where(BusinessHoursException.business_id == business_id)
            .order_by(BusinessHoursException.date)
        ).scalars()
    )


def create_exception(
    db: Session, *, business_id: uuid.UUID, payload: HolidayExceptionCreate
) -> BusinessHoursException:
    existing = db.execute(
        select(BusinessHoursException).where(
            BusinessHoursException.business_id == business_id,
            BusinessHoursException.date == payload.date,
        )
    ).scalar_one_or_none()
    if existing is not None:
        raise ConflictError("An hours exception for this date already exists.")

    exception = BusinessHoursException(business_id=business_id, **payload.model_dump())
    db.add(exception)
    db.commit()
    db.refresh(exception)
    return exception


def delete_exception(db: Session, *, business_id: uuid.UUID, exception_id: uuid.UUID) -> bool:
    exception = db.execute(
        select(BusinessHoursException).where(
            BusinessHoursException.id == exception_id,
            BusinessHoursException.business_id == business_id,
        )
    ).scalar_one_or_none()
    if exception is None:
        return False
    db.delete(exception)
    db.commit()
    return True
