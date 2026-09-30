import uuid

from fastapi import APIRouter, Depends, Query
from fastapi.responses import Response
from sqlalchemy.orm import Session

from app.api.dependencies import get_current_user, get_db, require_role
from app.core.exceptions import NotFoundError
from app.db.models.business import BusinessUser
from app.schemas.customer import CustomerCreate, CustomerListItem, CustomerRead, CustomerUpdate
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


@router.get("/customers", response_model=list[CustomerListItem])
def list_customers(
    q: str | None = Query(default=None, max_length=100),
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    current_user: BusinessUser = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> list[CustomerListItem]:
    rows = customer_service.list_customers(db, business_id=current_user.business_id, q=q, limit=limit, offset=offset)
    return [CustomerListItem(**r) for r in rows]


@router.get("/customers/export.csv")
def export_customers(
    current_user: BusinessUser = Depends(require_role(["owner", "admin"])),
    db: Session = Depends(get_db),
) -> Response:
    return Response(
        content=customer_service.customers_csv(db, business_id=current_user.business_id),
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": 'attachment; filename="customers.csv"'},
    )


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
