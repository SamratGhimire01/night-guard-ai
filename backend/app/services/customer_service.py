import uuid

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.models.customer import Customer
from app.schemas.customer import CustomerCreate, CustomerUpdate


def create_customer(db: Session, *, business_id: uuid.UUID, payload: CustomerCreate) -> Customer:
    customer = Customer(business_id=business_id, **payload.model_dump())
    db.add(customer)
    db.commit()
    db.refresh(customer)
    return customer


def update_customer(
    db: Session, *, business_id: uuid.UUID, customer_id: uuid.UUID, payload: CustomerUpdate
) -> Customer | None:
    """Tenant-scoped partial update. None for a customer that doesn't exist or
    belongs to another business — same IDOR-safe pattern as every other
    resource in this codebase. `exclude_unset`: a field the client never sent
    is left alone; a field sent as an explicit null DOES come through (and
    clears a nullable column) — CustomerUpdate's validators reject an
    explicit null on name/sms_opt_in before this ever runs."""
    customer = get_customer(db, business_id=business_id, customer_id=customer_id)
    if customer is None:
        return None
    for field, value in payload.model_dump(exclude_unset=True).items():
        setattr(customer, field, value)
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
