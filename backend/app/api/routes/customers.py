import uuid

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.api.dependencies import get_current_user, get_db, require_role
from app.core.exceptions import NotFoundError
from app.db.models.business import BusinessUser
from app.schemas.customer import CustomerCreate, CustomerRead, CustomerUpdate
from app.services import customer_service

router = APIRouter()


@router.post("/customers", response_model=CustomerRead, status_code=201)
def create_customer(
    payload: CustomerCreate,
    current_user: BusinessUser = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> CustomerRead:
    customer = customer_service.create_customer(db, business_id=current_user.business_id, payload=payload)
    return CustomerRead.model_validate(customer)


@router.get("/customers/{customer_id}", response_model=CustomerRead)
def get_customer(
    customer_id: uuid.UUID,
    current_user: BusinessUser = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> CustomerRead:
    customer = customer_service.get_customer(
        db, business_id=current_user.business_id, customer_id=customer_id
    )
    if customer is None:
        raise NotFoundError("Customer not found.")
    return CustomerRead.model_validate(customer)


@router.patch("/customers/{customer_id}", response_model=CustomerRead)
def update_customer(
    customer_id: uuid.UUID,
    payload: CustomerUpdate,
    current_user: BusinessUser = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> CustomerRead:
    """Same RBAC tier as POST/GET (any authenticated role) — editing a
    customer's own contact details is not a business-config write like
    DELETE, which stays owner/admin-only."""
    customer = customer_service.update_customer(
        db, business_id=current_user.business_id, customer_id=customer_id, payload=payload
    )
    if customer is None:
        raise NotFoundError("Customer not found.")
    return CustomerRead.model_validate(customer)


@router.delete("/customers/{customer_id}", status_code=204)
def delete_customer(
    customer_id: uuid.UUID,
    current_user: BusinessUser = Depends(require_role(["owner", "admin"])),
    db: Session = Depends(get_db),
) -> None:
    """Restricted to owner/admin — proves the require_role mechanism (staff is forbidden)."""
    deleted = customer_service.delete_customer(
        db, business_id=current_user.business_id, customer_id=customer_id
    )
    if not deleted:
        raise NotFoundError("Customer not found.")
