from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.api.dependencies import get_current_user, get_db, require_role
from app.db.models.business import BusinessUser
from app.schemas.integration import IntegrationRead, IntegrationUpsert
from app.services import integration_service

router = APIRouter()


@router.get("/integrations", response_model=list[IntegrationRead])
def list_integrations(
    current_user: BusinessUser = Depends(get_current_user), db: Session = Depends(get_db)
) -> list[IntegrationRead]:
    rows = integration_service.list_integrations(db, business_id=current_user.business_id)
    return [IntegrationRead.model_validate(row) for row in rows]


@router.post("/integrations", response_model=IntegrationRead, status_code=201)
def upsert_integration(
    payload: IntegrationUpsert,
    current_user: BusinessUser = Depends(require_role(["owner", "admin"])),
    db: Session = Depends(get_db),
) -> IntegrationRead:
    integration = integration_service.upsert_integration(
        db, business_id=current_user.business_id, payload=payload
    )
    return IntegrationRead.model_validate(integration)
