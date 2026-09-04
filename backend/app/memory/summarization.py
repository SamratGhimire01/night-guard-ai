import uuid

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.db.models.conversation import Conversation, Message
from app.llm import get_chat_provider
from app.memory.conversations import get_conversation

DEFAULT_THRESHOLD = 20
DEFAULT_KEEP_RECENT = 10

_SUMMARY_SYSTEM_PROMPT = (
    "You summarize customer service conversations for a business assistant's memory. "
    "Produce a compact, factual summary (a few sentences) capturing what the customer "
    "wants, decisions made, and any commitments. No filler, no preamble. "
    "If you are given an existing summary plus new messages: MERGE them — every "
    "specific fact, detail, or commitment already in the existing summary (names, "
    "symptoms, dates/times, allergies, complaints, decisions, etc.) MUST still appear "
    "in your output, even if the new messages don't repeat it. Never let new content "
    "push out old facts; only add to them or update something that was explicitly "
    "changed or resolved."
)


def _build_summary_prompt(previous_summary: str | None, messages: list[Message]) -> list[dict[str, str]]:
    transcript = "\n".join(f"{m.sender_type.value}: {m.content}" for m in messages)
    user_content = (
        (
            f"Existing summary of earlier parts of this conversation (preserve every fact "
            f"in it):\n{previous_summary}\n\n"
            if previous_summary
            else ""
        )
        + f"New messages to fold into the summary:\n{transcript}"
    )
    return [
        {"role": "system", "content": _SUMMARY_SYSTEM_PROMPT},
        {"role": "user", "content": user_content},
    ]


def maybe_summarize_conversation(
    db: Session,
    *,
    conversation_id: uuid.UUID,
    business_id: uuid.UUID,
    threshold: int = DEFAULT_THRESHOLD,
    keep_recent: int = DEFAULT_KEEP_RECENT,
) -> Conversation | None:
    """If the conversation has grown past `threshold` messages, folds every message
    older than the most recent `keep_recent` into conversation.summary via the chat
    LLM (Phase 6's ChatProvider — never a hardcoded Azure call), and advances
    summarized_message_count so those messages are never re-summarized on a later
    call. No-op if not yet due, or if nothing new needs summarizing. None if the
    conversation doesn't exist / isn't this business's."""
    conversation = get_conversation(db, conversation_id=conversation_id, business_id=business_id)
    if conversation is None:
        return None

    total = db.execute(
        select(func.count()).select_from(Message).where(Message.conversation_id == conversation_id)
    ).scalar_one()
    if total <= threshold:
        return conversation

    boundary = total - keep_recent
    if boundary <= conversation.summarized_message_count:
        return conversation

    newly_old = list(
        db.execute(
            select(Message)
            .where(Message.conversation_id == conversation_id)
            .order_by(Message.created_at.asc())
            .offset(conversation.summarized_message_count)
            .limit(boundary - conversation.summarized_message_count)
        ).scalars()
    )
    if not newly_old:
        return conversation

    prompt = _build_summary_prompt(conversation.summary, newly_old)
    conversation.summary = get_chat_provider().chat(prompt)
    conversation.summarized_message_count = boundary

    db.commit()
    db.refresh(conversation)
    return conversation
