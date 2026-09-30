import logging
import uuid
from datetime import datetime, timezone
from typing import Literal

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.db.models.conversation import Conversation
from app.db.models.customer import Customer
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


def is_ungrounded_info_question(
    *,
    intent: ConversationIntent,
    best_similarity: float | None,
    llm_confirmed_answered: bool | None,
) -> bool:
    """True for a genuine info-question intent with no sufficiently relevant
    knowledge and no independent confirmation the LLM answered from elsewhere
    (e.g. the services list) -- the exact predicate `_handoff_reason` already
    uses to decide whether a low-similarity answer deserves a HumanHandoff.
    Exposed separately so a caller can also force the RESPONSE itself honest
    (orchestrator._handle_turn's grounding guard) instead of just silently
    flagging staff while an ungrounded guess still reaches the customer."""
    return intent in _INFO_INTENTS and (
        best_similarity is None or best_similarity < KNOWLEDGE_RELEVANCE_THRESHOLD
    ) and llm_confirmed_answered is not True


def _handoff_reason(
    *,
    intent: ConversationIntent,
    best_similarity: float | None,
    llm_confirmed_answered: bool | None,
    is_language_switch_request: bool = False,
    is_provider_failure: bool = False,
    front_desk_reason: str | None = None,
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
    if front_desk_reason:
        # Phase 14: the reply already told the customer "let me connect you with our front desk" (resend limit reached /
        # send failed) — the caller states the real reason so that promise is backed by a real HumanHandoff row.
        return front_desk_reason
    if intent == ConversationIntent.COMPLAINT:
        return "Customer message was classified as a complaint."
    if intent == ConversationIntent.HUMAN_HANDOFF:
        return "Customer explicitly asked to speak with a human/staff member."
    if is_ungrounded_info_question(
        intent=intent, best_similarity=best_similarity, llm_confirmed_answered=llm_confirmed_answered
    ):
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
    front_desk_reason: str | None = None,
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
        front_desk_reason=front_desk_reason,
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
    _alert_owner(db, handoff)
    return handoff


def _alert_owner(db: Session, handoff: HumanHandoff) -> None:
    """Emails the owner/admins about a NEW handoff (never blocks or breaks the customer's turn)."""
    from app.services import owner_alert_service

    conversation = db.get(Conversation, handoff.conversation_id)
    customer = db.get(Customer, conversation.customer_id) if conversation else None
    owner_alert_service.notify_handoff(
        db,
        business_id=handoff.business_id,
        conversation_id=handoff.conversation_id,
        reason=handoff.reason,
        customer_name=(customer.known_name if customer else None) or "A customer",
    )


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
    # Phase 52: resolving the escalation also hands the conversation back to the AI (same commit).
    conversation = db.execute(
        select(Conversation).where(Conversation.id == handoff.conversation_id, Conversation.business_id == business_id)
    ).scalar_one_or_none()
    if conversation is not None:
        conversation.human_takeover_until = None
        conversation.human_takeover_by = None
    db.commit()
    db.refresh(handoff)
    return handoff


def _demo() -> None:
    # A genuine info-question with nothing relevant retrieved -- the exact
    # "below-threshold retrieval" case the orchestrator's grounding guard
    # replaces with a fixed honest fallback instead of trusting the LLM.
    assert is_ungrounded_info_question(
        intent=ConversationIntent.SERVICE_QUESTION, best_similarity=0.2, llm_confirmed_answered=None
    )
    # No knowledge results at all (best_similarity=None) is the same case.
    assert is_ungrounded_info_question(
        intent=ConversationIntent.GENERAL_QUESTION, best_similarity=None, llm_confirmed_answered=None
    )
    # A genuinely relevant match must not be flagged.
    assert not is_ungrounded_info_question(
        intent=ConversationIntent.SERVICE_QUESTION, best_similarity=0.8, llm_confirmed_answered=None
    )
    # Phase 23's real fix: a pricing/service question fully answered from the
    # services list (not the knowledge base) is confirmed answered by the LLM
    # itself -- low knowledge-chunk similarity must not override that.
    assert not is_ungrounded_info_question(
        intent=ConversationIntent.PRICING_QUESTION, best_similarity=0.1, llm_confirmed_answered=True
    )
    # BOOKING/CANCELLATION/etc. have their own tool paths -- knowledge
    # similarity is meaningless for them and must never flag anything.
    assert not is_ungrounded_info_question(
        intent=ConversationIntent.BOOKING, best_similarity=None, llm_confirmed_answered=None
    )
    print("handoff_service self-check: all assertions passed")


if __name__ == "__main__":
    _demo()
