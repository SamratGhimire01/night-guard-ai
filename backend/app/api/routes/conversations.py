import uuid

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.api.dependencies import get_current_user, get_db
from app.core.exceptions import NotFoundError
from app.db.models.business import BusinessUser
from app.schemas.conversation import IncomingMessageCreate, OrchestratedMessageResponse
from app.services.conversation import handle_incoming_message

router = APIRouter()


@router.post(
    "/conversations/{conversation_id}/messages",
    response_model=OrchestratedMessageResponse,
    status_code=201,
)
def post_conversation_message(
    conversation_id: uuid.UUID,
    payload: IncomingMessageCreate,
    current_user: BusinessUser = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> OrchestratedMessageResponse:
    """Drives the Phase 8 orchestration end-to-end for a single incoming
    customer message. Not yet wired to any real channel (Phase 22+) — this is
    the internal endpoint for testing the orchestrator. Tenant-scoped via
    current_user.business_id; a conversation_id that doesn't exist or belongs
    to another business is a 404, same IDOR-safe pattern as every other
    resource in this codebase."""
    result = handle_incoming_message(
        db, conversation_id=conversation_id, business_id=current_user.business_id, content=payload.content
    )
    if result is None:
        raise NotFoundError("Conversation not found.")
    return OrchestratedMessageResponse(**result)
