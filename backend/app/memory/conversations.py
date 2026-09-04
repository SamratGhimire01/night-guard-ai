import uuid

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.models.conversation import Conversation


def get_conversation(db: Session, *, conversation_id: uuid.UUID, business_id: uuid.UUID) -> Conversation | None:
    """Tenant-scoped lookup shared by every memory module — returns None for a
    conversation that doesn't exist OR belongs to another business, so callers
    never need to special-case "not found" vs. "not yours"."""
    return db.execute(
        select(Conversation).where(
            Conversation.id == conversation_id, Conversation.business_id == business_id
        )
    ).scalar_one_or_none()
