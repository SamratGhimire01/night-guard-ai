import uuid
from typing import Literal

from fastapi import APIRouter, Depends, Query
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.dependencies import get_db, require_role
from app.core.exceptions import NotFoundError
from app.db.models.business import BusinessUser
from app.db.models.conversation import Conversation
from app.db.models.customer import Customer
from app.schemas.handoff import HumanHandoffListItem, HumanHandoffRead, HumanHandoffUpdate
from app.services import handoff_service

router = APIRouter()

# Staff need to see and resolve these too — they're the ones actually fielding
# the escalation — unlike reports/followups (owner/admin-only, since those
# reach real customers or expose business performance data).
_HANDOFF_ROLES = ["owner", "admin", "staff"]


@router.get("/handoffs", response_model=list[HumanHandoffListItem])
def list_handoffs(
    status: Literal["open", "resolved", "all"] = Query(default="open"),
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    current_user: BusinessUser = Depends(require_role(_HANDOFF_ROLES)),
    db: Session = Depends(get_db),
) -> list[HumanHandoffListItem]:
    handoffs = handoff_service.list_handoffs(
        db, business_id=current_user.business_id, status_filter=status, limit=limit, offset=offset
    )
    conversation_ids = {h.conversation_id for h in handoffs}
    conversations = {
        c.id: c for c in db.execute(select(Conversation).where(Conversation.id.in_(conversation_ids))).scalars()
    } if conversation_ids else {}
    customer_ids = {c.customer_id for c in conversations.values()}
    customers = {
        c.id: c.name for c in db.execute(select(Customer).where(Customer.id.in_(customer_ids))).scalars()
    } if customer_ids else {}
    return [
        HumanHandoffListItem(
            **HumanHandoffRead.model_validate(h).model_dump(),
            customer_name=(
                customers.get(conversations[h.conversation_id].customer_id, "Unknown customer")
                if h.conversation_id in conversations
                else "Unknown customer"
            ),
            channel=conversations[h.conversation_id].channel if h.conversation_id in conversations else "unknown",
        )
        for h in handoffs
    ]


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
