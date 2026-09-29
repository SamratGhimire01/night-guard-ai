"""Casual-companion persona: a standalone chat path that never touches the business orchestrator, KB, bookings or any
other tenant's data. Enabled per Instagram integration with config {"persona": "companion"} — remove that key (or this
package) to disable it. Only reads/writes this one conversation's own messages, for conversational memory."""

import logging
import re
import uuid
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.models.conversation import Message, MessageSenderType
from app.llm import get_chat_provider
from app.services.channels.base import get_or_create_conversation

logger = logging.getLogger(__name__)

SYSTEM_PROMPT = (Path(__file__).parent / "prompt.md").read_text(encoding="utf-8")
# ponytail: plain last-N window, no summarization; add app/memory/summarization if chats outgrow it
_HISTORY_LIMIT = 40
_DISCLOSURE = "heyy 😊 just so you know, I'm an AI companion, but I'm still down to chat haha\n\n"
_FALLBACK = "sorry, my brain lagged for a sec 😅 say that again?"


def reply(
    db: Session, *, business_id: uuid.UUID, channel: str, external_ref: str, content: str,
    external_message_id: str | None, deliver,
) -> str:
    conversation = get_or_create_conversation(
        db, business_id=business_id, channel=channel, external_ref=external_ref,
        default_customer_name="Instagram Contact",
    )
    conversation_id = conversation.id
    history = list(reversed(db.execute(
        select(Message.sender_type, Message.content).where(Message.conversation_id == conversation_id)
        .order_by(Message.created_at.desc()).limit(_HISTORY_LIMIT)
    ).all()))
    first_reply = not any(sender == MessageSenderType.AGENT for sender, _ in history)
    messages = [{"role": "system", "content": SYSTEM_PROMPT}]
    messages += [{"role": "user" if sender == MessageSenderType.CUSTOMER else "assistant", "content": body}
                 for sender, body in history]
    messages.append({"role": "user", "content": content})

    # Stored before the LLM call so a Meta redelivery hits the external_message_id unique constraint. Everything the
    # LLM call needs is plain data by now, so no DB connection is held while waiting on the model.
    db.add(Message(conversation_id=conversation_id, sender_type=MessageSenderType.CUSTOMER, content=content,
                   external_message_id=external_message_id))
    db.commit()

    try:
        text = get_chat_provider().chat(messages).strip() or _FALLBACK
    except Exception:
        logger.exception("companion: LLM call failed for conversation %s", conversation_id)
        text = _FALLBACK

    # Section 29: the first-reply disclosure is enforced in code, so no user instruction can suppress it.
    if first_reply and not re.search(r"\bai\b", text, re.IGNORECASE):
        text = _DISCLOSURE + text

    db.add(Message(conversation_id=conversation_id, sender_type=MessageSenderType.AGENT, content=text))
    db.commit()
    deliver(text)
    return text
