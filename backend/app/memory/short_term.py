import uuid

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.models.conversation import Message
from app.memory.conversations import get_conversation

DEFAULT_RECENT_MESSAGES = 10


def get_recent_messages(
    db: Session, *, conversation_id: uuid.UUID, business_id: uuid.UUID, limit: int = DEFAULT_RECENT_MESSAGES
) -> list[Message]:
    """Last `limit` messages for a conversation, oldest first (natural reading/LLM-
    context order). Tenant-scoped: returns [] for a conversation that doesn't exist
    or belongs to another business — never leaks another tenant's messages even to
    a guessed conversation_id."""
    if get_conversation(db, conversation_id=conversation_id, business_id=business_id) is None:
        return []

    stmt = (
        select(Message)
        .where(Message.conversation_id == conversation_id)
        .order_by(Message.created_at.desc())
        .limit(limit)
    )
    most_recent_first = list(db.execute(stmt).scalars())
    return list(reversed(most_recent_first))
