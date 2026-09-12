import logging
import uuid
from datetime import datetime, timezone
from typing import Literal

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.db.models.handoff import HumanHandoff
from app.schemas.conversation import ConversationIntent

logger = logging.getLogger(__name__)

# Genuine information-question intents — the only ones a knowledge-relevance
# gap is a meaningful signal for. BOOKING/CANCELLATION/RESCHEDULING/
# APPOINTMENT_STATUS have their own dedicated tool paths (Phase 10/11/14) and
# a low similarity score there means nothing (no knowledge chunk is expected
# to answer "book me Tuesday at 2pm").
_INFO_INTENTS = frozenset(
    {
        ConversationIntent.GENERAL_QUESTION,
        ConversationIntent.SERVICE_QUESTION,
        ConversationIntent.PRICING_QUESTION,
        ConversationIntent.BUSINESS_HOURS,
        ConversationIntent.LOCATION,
    }
)

# Phase 8 flagged this exact gap: "no hard similarity-score cutoff... a
# minimum-similarity filter would be a cheap, real hardening if this ever
# fails in practice." This is that cutoff — but only for deciding whether to
# create a real handoff record, not for the LLM's own response text (Phase
# 8/9's guardrail+tone already handle that conversationally on their own).
# 0.289 (an irrelevant match, Phase 8's own real test) is well below this;
# not independently tuned against a large real corpus, a reasonable starting
# point.
KNOWLEDGE_RELEVANCE_THRESHOLD = 0.5


def _handoff_reason(
    *,
    intent: ConversationIntent,
    best_similarity: float | None,
    llm_confirmed_answered: bool | None,
    is_language_switch_request: bool = False,
    is_provider_failure: bool = False,
) -> str | None:
    """None means this turn doesn't qualify for a handoff. Otherwise the real
    reason to record on the row — never a generic string reused for every
    trigger.

    `is_provider_failure` (urgent fix, real 500 found live — PHASE_STATUS.md):
    orchestrator sets this when the LLM/embedding provider call itself failed
    after its own internal retries (app/llm/azure_openai.py's `_post`) —
    there was never a real classification this turn, so `intent`/
    `best_similarity` are meaningless placeholders the caller couldn't avoid
    passing. Checked FIRST, unconditionally, same as `is_language_switch_request`
    below: a genuine outage is never something ANY other signal should be able
    to suppress or reclassify away.

    `is_language_switch_request` (Phase 25b urgent fix): real bug found live —
    the LLM told a customer switching languages "I can connect you with a
    Nepali-speaking team member" and this created a real HumanHandoff, even
    though this system is natively fluent in every locked-language option
    (see intent.py rule 7). A language switch is never, by itself, a reason a
    human needs to follow up, so this is checked FIRST and unconditionally —
    structurally excluded regardless of intent, similarity, or what the LLM's
    own `needs_human_handoff` self-report said, the same hard guarantee
    OFF_TOPIC already gets from simply not being in `_INFO_INTENTS`.

    `llm_confirmed_answered` (Phase 23 urgent fix): real bug found in live
    testing — the knowledge-similarity threshold below was originally the
    ONLY signal for _INFO_INTENTS, but PRICING_QUESTION/SERVICE_QUESTION have
    a second real, always-available data source the knowledge base search
    never sees: the business's own `Available services` list, which is
    handed to the LLM directly in every prompt (see intent.py's
    `_format_services`). A customer asking "how much is a Root Canal" gets a
    fully correct answer straight from that list, yet the knowledge-chunk
    search (searching unrelated documents) can easily score low similarity —
    the OLD code then created a handoff and appended "I've also let our team
    know" onto an already-fully-answered response: a real false-positive,
    live-verified (best similarity 0.26 on a correctly-answered $450/60min
    pricing question — see PHASE_STATUS.md). `llm_confirmed_answered=True`
    (the LLM's own `needs_human_handoff: false` self-report, rule 15 in
    intent.py's system prompt) suppresses ONLY the low-similarity path for
    _INFO_INTENTS; COMPLAINT/HUMAN_HANDOFF are never affected, and `None`
    (the field wasn't in this response — e.g. an older stubbed test) falls
    back to the original, unchanged similarity-only behavior. This can never
    newly CREATE a handoff the old logic wouldn't have — it can only suppress
    a false positive the LLM itself confirms it didn't need."""
    if is_provider_failure:
        return "The AI provider was unreachable after retries and could not process this message."
    if is_language_switch_request:
        return None
    if intent == ConversationIntent.COMPLAINT:
        return "Customer message was classified as a complaint."
    if intent == ConversationIntent.HUMAN_HANDOFF:
        return "Customer explicitly asked to speak with a human/staff member."
    if intent in _INFO_INTENTS and (best_similarity is None or best_similarity < KNOWLEDGE_RELEVANCE_THRESHOLD):
        if llm_confirmed_answered is True:
            return None
        found = f"{best_similarity:.2f}" if best_similarity is not None else "no knowledge base results"
        return f"No sufficiently relevant knowledge found for a {intent.value} (best similarity: {found})."
    return None


def maybe_create_handoff(
    db: Session,
    *,
    business_id: uuid.UUID,
    conversation_id: uuid.UUID,
    intent: ConversationIntent,
    best_similarity: float | None,
    llm_confirmed_answered: bool | None = None,
    is_language_switch_request: bool = False,
    is_provider_failure: bool = False,
) -> HumanHandoff | None:
    """The real HumanHandoff producer — the gap Phase 16 flagged (the model
    has existed since Phase 2; nothing ever constructed a row). Returns the
    open handoff for this conversation (existing or newly created) if this
    turn qualifies, else None — the caller uses a non-None return to decide
    whether to tell the customer a human will follow up.

    Anti-duplicate: an application-level check below skips the insert when an
    open handoff already exists for this conversation (the fast path — avoids
    a wasted round trip on every message of an already-escalated
    conversation). The REAL backstop is the partial unique index on
    (conversation_id) WHERE resolved_at IS NULL (see the model) — a race
    between two concurrent requests still can't ever leave two open rows for
    the same conversation.
    """
    reason = _handoff_reason(
        intent=intent,
        best_similarity=best_similarity,
        llm_confirmed_answered=llm_confirmed_answered,
        is_language_switch_request=is_language_switch_request,
        is_provider_failure=is_provider_failure,
    )
    if reason is None:
        return None

    existing = db.execute(
        select(HumanHandoff).where(
            HumanHandoff.business_id == business_id,
            HumanHandoff.conversation_id == conversation_id,
            HumanHandoff.resolved_at.is_(None),
        )
    ).scalar_one_or_none()
    if existing is not None:
        return existing

    handoff = HumanHandoff(business_id=business_id, conversation_id=conversation_id, reason=reason, status="open")
    db.add(handoff)
    try:
        db.commit()
    except IntegrityError:
        # Real race: another concurrent request for the same conversation
        # committed its own open handoff between our existence check and our
        # insert. The partial unique index rejected ours — that's success,
        # not failure: reuse the one that won.
        db.rollback()
        return db.execute(
            select(HumanHandoff).where(
                HumanHandoff.business_id == business_id,
                HumanHandoff.conversation_id == conversation_id,
                HumanHandoff.resolved_at.is_(None),
            )
        ).scalar_one_or_none()

    db.refresh(handoff)
    logger.info("human_handoff created: conversation_id=%s reason=%s", conversation_id, reason)
    return handoff


def list_handoffs(
    db: Session,
    *,
    business_id: uuid.UUID,
    status_filter: Literal["open", "resolved", "all"] = "open",
    limit: int = 50,
    offset: int = 0,
) -> list[HumanHandoff]:
    """limit/offset — this endpoint had none at all (genuinely unbounded,
    unlike every other list endpoint since Phase 29's audit); added while
    building the real Human Handoffs dashboard page rather than shipping a
    second unbounded list."""
    stmt = select(HumanHandoff).where(HumanHandoff.business_id == business_id)
    if status_filter == "open":
        stmt = stmt.where(HumanHandoff.resolved_at.is_(None))
    elif status_filter == "resolved":
        stmt = stmt.where(HumanHandoff.resolved_at.is_not(None))
    stmt = stmt.order_by(HumanHandoff.created_at.desc()).limit(limit).offset(offset)
    return list(db.execute(stmt).scalars())


def resolve_handoff(db: Session, *, business_id: uuid.UUID, handoff_id: uuid.UUID) -> HumanHandoff | None:
    handoff = db.execute(
        select(HumanHandoff).where(HumanHandoff.id == handoff_id, HumanHandoff.business_id == business_id)
    ).scalar_one_or_none()
    if handoff is None:
        return None
    handoff.status = "resolved"
    handoff.resolved_at = datetime.now(timezone.utc)
    db.commit()
    db.refresh(handoff)
    return handoff
