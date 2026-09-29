import uuid

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.models.customer import Customer


def get_customer_context(db: Session, *, customer_id: uuid.UUID, business_id: uuid.UUID) -> dict | None:
    """Compact customer profile for prompt injection. Tenant-scoped: None for a
    customer that doesn't exist or belongs to another business."""
    customer = db.execute(
        select(Customer).where(Customer.id == customer_id, Customer.business_id == business_id)
    ).scalar_one_or_none()
    if customer is None:
        return None

    return {
        "id": str(customer.id),
        "name": customer.known_name,
        "phone": customer.phone,
        "email": customer.email,
        "preferred_language": customer.preferred_language,
    }
