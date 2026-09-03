import uuid

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.models.customer import Customer
from app.schemas.customer import CustomerCreate


def create_customer(db: Session, *, business_id: uuid.UUID, payload: CustomerCreate) -> Customer:
    customer = Customer(business_id=business_id, **payload.model_dump())
    db.add(customer)
    db.commit()
    db.refresh(customer)
    return customer


def get_customer(db: Session, *, business_id: uuid.UUID, customer_id: uuid.UUID) -> Customer | None:
    """Scoped to business_id: a customer belonging to another tenant is indistinguishable
    from one that doesn't exist at all — this is what makes cross-tenant IDOR impossible."""
    return db.execute(
        select(Customer).where(Customer.id == customer_id, Customer.business_id == business_id)
    ).scalar_one_or_none()


def delete_customer(db: Session, *, business_id: uuid.UUID, customer_id: uuid.UUID) -> bool:
    customer = get_customer(db, business_id=business_id, customer_id=customer_id)
    if customer is None:
        return False
    db.delete(customer)
    db.commit()
    return True
