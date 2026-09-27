"""Automatic buying-intent triage for the inbox's "Leads" tab: which open conversations
look like a real potential customer, plus a short staff-facing summary of what they want.

Scored in the background by the scheduler (app/services/scheduler.py), never on the
customer-facing message path -- a second LLM call on every incoming message would double
the latency/cost of every single conversation for something only staff, not customers,
ever see (the same mistake app/memory/summarization.py's own perf note already found and
fixed for a different call)."""

import json
import logging
import uuid

from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from app.db.models.conversation import Conversation, Message, MessageSenderType
from app.llm import get_chat_provider

logger = logging.getLogger(__name__)

_VALID_SIGNALS = {"high", "medium", "low"}
# A single "hi" isn't enough signal to judge buying intent either way -- skip scoring
# (and re-scoring) until there's a real exchange.
_MIN_CUSTOMER_MESSAGES = 2

_SYSTEM_PROMPT = (
    "You read a customer-service conversation for a business and judge how likely this "
    "customer is to actually buy/book, so staff can triage their inbox. Output ONLY JSON, "
    'no other text: {"buy_intent": "high"|"medium"|"low", "summary": "..."}.\n'
    '"high": clear purchase/booking intent -- asked price, availability, how to pay/proceed, '
    "compared real options, or said they want to book/sign up.\n"
    '"medium": genuine interest but no concrete next step yet (general questions about the '
    "service, no price/availability/booking question).\n"
    '"low": idle browsing, a one-off question unrelated to buying, or a complaint with no '
    "purchase signal.\n"
    'summary: 2-3 factual sentences for a staff member who has NOT read the conversation -- '
    "what the customer wants, any specifics they mentioned (dates, budget, programs/services "
    "named, deadlines), and what they're currently waiting on. No filler, no preamble."
)


def _parse(raw: str) -> tuple[str | None, str | None]:
    text = raw.strip()
    if text.startswith("```"):
        text = text.strip("`").strip()
        if text.lower().startswith("json"):
            text = text[4:].strip()
    try:
        data = json.loads(text)
        signal = data.get("buy_intent")
        summary = (data.get("summary") or "").strip() or None
        return (signal if signal in _VALID_SIGNALS else None), summary
    except (json.JSONDecodeError, AttributeError) as exc:
        logger.warning("lead_service: could not parse LLM response as JSON: %s", exc)
        return None, None


def score_conversation(db: Session, conversation: Conversation) -> None:
    """Scores ONE conversation and persists lead_signal/lead_summary/lead_scored_at.
    Customer + AI messages only (a staff reply is the business's own words, not a signal
    about the customer). Raises on a real LLM/DB failure -- callers (score_stale_conversations)
    catch per-conversation so one bad call never blocks the rest of the batch."""
    messages = list(
        db.execute(
            select(Message)
            .where(Message.conversation_id == conversation.id, Message.sender_type != MessageSenderType.STAFF)
            .order_by(Message.created_at)
        ).scalars()
    )
    transcript = "\n".join(f"{m.sender_type.value}: {m.content}" for m in messages)
    if not transcript.strip():
        return

    raw = get_chat_provider().chat(
        [{"role": "system", "content": _SYSTEM_PROMPT}, {"role": "user", "content": transcript}]
    )
    signal, summary = _parse(raw)
    conversation.lead_signal = signal
    conversation.lead_summary = summary
    conversation.lead_scored_at = func.localtimestamp()
    db.commit()


def score_stale_conversations(db: Session, *, limit: int = 20, business_id: uuid.UUID | None = None) -> int:
    """Scores up to `limit` conversations whose lead signal is missing or stale (a new
    customer message arrived since the last score), oldest-stale-first. Returns how many
    were attempted. Called from the scheduler tick with no `business_id` (a real global
    scan, same as reminder_service/no_show_service) -- see score_conversation for why this
    never runs on the live message path. `business_id` exists so a test can assert on its
    own tenant's conversations without depending on how much unrelated backlog exists
    elsewhere in the database."""
    last_cust = (
        select(
            Message.conversation_id,
            func.max(Message.created_at).label("at"),
            func.count().label("n"),
        )
        .where(Message.sender_type == MessageSenderType.CUSTOMER)
        .group_by(Message.conversation_id)
        .subquery()
    )
    stmt = (
        select(Conversation)
        .join(last_cust, last_cust.c.conversation_id == Conversation.id)
        .where(
            last_cust.c.n >= _MIN_CUSTOMER_MESSAGES,
            or_(Conversation.lead_scored_at.is_(None), Conversation.lead_scored_at < last_cust.c.at),
        )
        .order_by(last_cust.c.at.asc())
        .limit(limit)
    )
    if business_id is not None:
        stmt = stmt.where(Conversation.business_id == business_id)
    conversations = list(db.execute(stmt).scalars())
    for conversation in conversations:
        try:
            score_conversation(db, conversation)
        except Exception:
            logger.exception("lead_service: failed to score conversation %s", conversation.id)
            db.rollback()
    return len(conversations)
