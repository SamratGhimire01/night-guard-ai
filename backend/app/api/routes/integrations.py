from typing import Literal

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.api.dependencies import get_db, require_role
from app.core.config import settings
from app.core.exceptions import UnprocessableEntityError
from app.db.models.business import BusinessUser
from app.schemas.integration import (
    IntegrationRead,
    IntegrationTestResult,
    IntegrationUpsert,
    WhatsAppEmbeddedSignupComplete,
    WhatsAppEmbeddedSignupConfig,
)
from app.services import integration_service
from app.services.channels import whatsapp_embedded_signup

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
    type: Literal["whatsapp", "messenger", "instagram", "email"],
    current_user: BusinessUser = Depends(require_role(["owner", "admin"])),
    db: Session = Depends(get_db),
) -> IntegrationTestResult:
    ok, detail = integration_service.test_connection(db, business_id=current_user.business_id, type_=type)
    return IntegrationTestResult(ok=ok, detail=detail)


@router.get("/integrations/whatsapp/embedded-signup/config", response_model=WhatsAppEmbeddedSignupConfig)
def whatsapp_embedded_signup_config(
    _current_user: BusinessUser = Depends(require_role(["owner", "admin"])),
) -> WhatsAppEmbeddedSignupConfig:
    """NEW, separate from everything above — lets the dashboard decide whether
    to render the self-serve "Connect WhatsApp" button at all. Same RBAC gate
    as the rest of this router (owner/admin only), even though app_id/
    config_id aren't secrets, for consistency with the rest of this page."""
    return WhatsAppEmbeddedSignupConfig(
        configured=whatsapp_embedded_signup.is_configured(),
        app_id=settings.whatsapp_embedded_signup_app_id,
        config_id=settings.whatsapp_embedded_signup_config_id,
        api_version=settings.whatsapp_api_version,
    )


@router.post("/integrations/whatsapp/embedded-signup", response_model=IntegrationRead, status_code=201)
def complete_whatsapp_embedded_signup(
    payload: WhatsAppEmbeddedSignupComplete,
    current_user: BusinessUser = Depends(require_role(["owner", "admin"])),
    db: Session = Depends(get_db),
) -> IntegrationRead:
    """NEW, separate entry point for the real Meta Embedded Signup flow —
    distinct from POST /integrations above (which saves a business owner's
    hand-typed credentials) and untouched by anything
    app/api/routes/webhooks.py or app/services/channels/whatsapp.py already
    relies on. Reuses integration_service's underlying save logic (via
    whatsapp_embedded_signup.complete_embedded_signup ->
    integration_service.save_integration_config) so the resulting Integration
    row is identical in shape to one saved through the manual path — proving
    the existing send/webhook code needs zero changes to work with either."""
    try:
        integration = whatsapp_embedded_signup.complete_embedded_signup(
            db,
            business_id=current_user.business_id,
            code=payload.code,
            waba_id=payload.waba_id,
            phone_number_id=payload.phone_number_id,
        )
    except whatsapp_embedded_signup.WhatsAppEmbeddedSignupError as exc:
        raise UnprocessableEntityError(str(exc)) from None
    return IntegrationRead.model_validate(integration)
