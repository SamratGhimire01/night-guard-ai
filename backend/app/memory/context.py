import logging
import uuid

from sqlalchemy.orm import Session

from app.memory.appointment_context import get_appointment_context
from app.memory.conversations import get_conversation
from app.memory.customer_context import get_customer_context
from app.memory.short_term import DEFAULT_RECENT_MESSAGES, get_recent_messages

logger = logging.getLogger(__name__)

# ponytail: words/1.3 as a token-count proxy, same tradeoff as app/rag/chunking.py —
# good enough to catch unbounded growth, not exact.
_WORDS_PER_TOKEN = 0.75


def _word_count(value: object) -> int:
    if value is None:
        return 0
    return len(str(value).split())


def assemble_context(
    db: Session, *, conversation_id: uuid.UUID, business_id: uuid.UUID, recent_limit: int = DEFAULT_RECENT_MESSAGES
) -> dict | None:
    """Combines conversation summary + recent raw messages + customer profile +
    appointment context into one bounded structure for a future orchestrator to
    hand to the LLM. Deliberately does NOT include knowledge-base search results —
    that's Phase 8's job, combining this with Phase 6's retrieval separately.
    Tenant-scoped throughout via business_id. None if the conversation isn't this
    business's."""
    conversation = get_conversation(db, conversation_id=conversation_id, business_id=business_id)
    if conversation is None:
        return None

    recent_messages = get_recent_messages(
        db, conversation_id=conversation_id, business_id=business_id, limit=recent_limit
    )
    customer = get_customer_context(db, customer_id=conversation.customer_id, business_id=business_id)
    appointments = get_appointment_context(db, customer_id=conversation.customer_id, business_id=business_id)

    context = {
        "conversation_id": str(conversation_id),
        "summary": conversation.summary,
        "recent_messages": [
            {
                "sender_type": message.sender_type.value,
                "content": message.content,
                "detected_intent": message.detected_intent,
                "created_at": message.created_at.isoformat(),
            }
            for message in recent_messages
        ],
        "customer": customer,
        "appointments": appointments,
    }

    words = _word_count(context["summary"])
    words += sum(_word_count(m["content"]) for m in context["recent_messages"])
    if customer:
        words += sum(_word_count(v) for v in customer.values())
    for bucket in appointments.values():
        for appointment in bucket:
            words += sum(_word_count(v) for v in appointment.values())

    context["_approx_size"] = {"words": words, "tokens_estimate": round(words / _WORDS_PER_TOKEN)}
    logger.info(
        "assembled conversation context: conversation_id=%s approx_words=%d approx_tokens=%d "
        "recent_messages=%d has_summary=%s",
        conversation_id,
        words,
        context["_approx_size"]["tokens_estimate"],
        len(context["recent_messages"]),
        conversation.summary is not None,
    )
    return context
