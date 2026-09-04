import uuid
from typing import Literal

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.api.dependencies import get_db, require_role
from app.core.exceptions import NotFoundError
from app.db.models.business import BusinessUser
from app.schemas.handoff import HumanHandoffRead, HumanHandoffUpdate
from app.services import handoff_service

router = APIRouter()

# Staff need to see and resolve these too — they're the ones actually fielding
# the escalation — unlike reports/followups (owner/admin-only, since those
# reach real customers or expose business performance data).
_HANDOFF_ROLES = ["owner", "admin", "staff"]


@router.get("/handoffs", response_model=list[HumanHandoffRead])
def list_handoffs(
    status: Literal["open", "resolved", "all"] = Query(default="open"),
    current_user: BusinessUser = Depends(require_role(_HANDOFF_ROLES)),
    db: Session = Depends(get_db),
) -> list[HumanHandoffRead]:
    handoffs = handoff_service.list_handoffs(db, business_id=current_user.business_id, status_filter=status)
    return [HumanHandoffRead.model_validate(h) for h in handoffs]


@router.patch("/handoffs/{handoff_id}", response_model=HumanHandoffRead)
def update_handoff(
    handoff_id: uuid.UUID,
    payload: HumanHandoffUpdate,  # noqa: ARG001  only "resolved" is a valid value, enforced by the schema itself
    current_user: BusinessUser = Depends(require_role(_HANDOFF_ROLES)),
    db: Session = Depends(get_db),
) -> HumanHandoffRead:
    handoff = handoff_service.resolve_handoff(db, business_id=current_user.business_id, handoff_id=handoff_id)
    if handoff is None:
        raise NotFoundError("Handoff not found.")
    return HumanHandoffRead.model_validate(handoff)
