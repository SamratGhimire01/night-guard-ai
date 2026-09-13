from typing import Literal

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.api.dependencies import get_db, require_role
from app.db.models.business import BusinessUser
from app.schemas.integration import IntegrationRead, IntegrationTestResult, IntegrationUpsert
from app.services import integration_service

router = APIRouter()


@router.get("/integrations", response_model=list[IntegrationRead])
def list_integrations(
    current_user: BusinessUser = Depends(require_role(["owner", "admin"])), db: Session = Depends(get_db)
) -> list[IntegrationRead]:
    """Owner/admin only — unlike GET /business/plan-style "any role can read"
    endpoints, a channel's connection state/config lives right next to where
    credentials get saved on the dashboard, so this stays behind the same
    gate as the write side (POST below) rather than the more permissive
    pattern GET /integrations/google-calendar/status uses."""
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


@router.post("/integrations/{type}/test-connection", response_model=IntegrationTestResult)
def test_connection(
    type: Literal["whatsapp", "messenger", "instagram"],
    current_user: BusinessUser = Depends(require_role(["owner", "admin"])),
    db: Session = Depends(get_db),
) -> IntegrationTestResult:
    ok, detail = integration_service.test_connection(db, business_id=current_user.business_id, type_=type)
    return IntegrationTestResult(ok=ok, detail=detail)
