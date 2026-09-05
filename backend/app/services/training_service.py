import uuid
from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.models.business import Business
from app.db.models.knowledge import KnowledgeChunk, KnowledgeDocument, KnowledgeDocumentStatus
from app.db.models.training import TrainingQuestion
from app.llm import get_embedding_provider
from app.services import knowledge_service, service_service
from app.services.conversation.intent import classify_and_respond
from app.services.conversation.orchestrator import KNOWLEDGE_TOP_K

_TITLE_MAX_LEN = 200


def ask(
    db: Session, *, business_id: uuid.UUID, question: str, asked_by: uuid.UUID
) -> tuple[TrainingQuestion, list[tuple[KnowledgeChunk, KnowledgeDocument, float]]]:
    """The real "test the AI" mechanic. Reuses the exact Phase 6 knowledge
    search (knowledge_service.search_chunks, same top_k as the real customer
    orchestrator) and the exact Phase 8 classify_and_respond call — never a
    parallel/simplified copy of that logic.

    Deliberately does NOT call app.services.conversation.orchestrator.
    handle_incoming_message: that function persists real Message rows against
    a real Conversation, dispatches real booking/cancel/reschedule tools
    against real data, and (Phase 18/19) can trigger a real follow-up or human
    handoff. None of that is appropriate for an owner testing the AI with a
    made-up question — a training question is not a real customer message, so
    it intentionally never touches conversations, messages, appointments,
    follow-ups, or handoffs. Only the pure retrieval + drafting steps are
    reused; the classification's booking/cancellation/reschedule extractions
    are ignored (never executed) since no tool is ever dispatched here.
    """
    business = db.get(Business, business_id)
    services = service_service.list_services(db, business_id=business_id)

    query_vector = get_embedding_provider().embed([question])[0]
    knowledge_results = knowledge_service.search_chunks(
        db, business_id=business_id, query_vector=query_vector, top_k=KNOWLEDGE_TOP_K
    )

    classification = classify_and_respond(
        business=business,
        context={},
        knowledge_results=knowledge_results,
        customer_message=question,
        services=services,
    )

    training_question = TrainingQuestion(
        business_id=business_id,
        question=question,
        answer=classification.response,
        intent=classification.intent.value,
        asked_by=asked_by,
    )
    db.add(training_question)
    db.commit()
    db.refresh(training_question)

    return training_question, knowledge_results


def submit_feedback(
    db: Session,
    *,
    business_id: uuid.UUID,
    training_question_id: uuid.UUID,
    is_correct: bool,
    corrected_answer: str | None,
    feedback_by: uuid.UUID,
) -> TrainingQuestion | None:
    """Records the owner/admin's judgment. When the answer was marked
    incorrect with a real correction, this is the actual "closes the loop"
    mechanic: a new, real KnowledgeDocument is created FROM the correction —
    source="training_room" — chunked and embedded immediately (see the
    APPROVED-at-creation design decision below), so a re-ask of the same
    question can immediately reflect it. A "correct" mark never creates any
    KnowledgeDocument — there's nothing to correct.

    DESIGN DECISION — approved immediately, not left in "draft" (the ticket
    asked this be made explicit and justified):
    1. This endpoint is already owner/admin-gated — the same authorization
       bar Phase 5 already requires for the manual "approve" action itself.
    2. The submitting user IS a real authorizing human exercising real
       judgment (marking an answer wrong and supplying the correct one) —
       functionally identical to Phase 5's "approve" action, just triggered
       from a different UI.
    3. The single most important acceptance check for this phase is that
       RE-ASKING THE SAME QUESTION immediately reflects the correction. A
       "draft" correction is invisible to search_chunks (Phase 6 only
       retrieves approved chunks) until a SEPARATE approval step — which
       would mean the training room only ever half-closes the loop and silently
       depends on the owner remembering to go approve it elsewhere. That
       directly contradicts the phase's own stated purpose.
    4. Nothing about this is a one-way door: the resulting document is a real,
       ordinary KnowledgeDocument, fully visible/editable/archivable/deletable
       through the existing Phase 5 endpoints exactly like any other approved
       document, if a bad correction ever needs walking back.
    """
    training_question = db.execute(
        select(TrainingQuestion).where(
            TrainingQuestion.id == training_question_id, TrainingQuestion.business_id == business_id
        )
    ).scalar_one_or_none()
    if training_question is None:
        return None

    training_question.is_correct = is_correct
    training_question.corrected_answer = corrected_answer
    training_question.feedback_by = feedback_by
    training_question.feedback_at = datetime.now(UTC)

    if not is_correct and corrected_answer:
        title = f"Training correction: {training_question.question}"[:_TITLE_MAX_LEN]
        document = knowledge_service.create_document(
            db,
            business_id=business_id,
            title=title,
            content=corrected_answer,
            source="training_room",
            status=KnowledgeDocumentStatus.APPROVED,
            approved_by=feedback_by,
        )
        training_question.correction_knowledge_document_id = document.id

    db.commit()
    db.refresh(training_question)
    return training_question


def list_history(
    db: Session, *, business_id: uuid.UUID, limit: int = 50, offset: int = 0
) -> list[TrainingQuestion]:
    stmt = (
        select(TrainingQuestion)
        .where(TrainingQuestion.business_id == business_id)
        .order_by(TrainingQuestion.created_at.desc())
        .limit(limit)
        .offset(offset)
    )
    return list(db.execute(stmt).scalars())
