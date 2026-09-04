from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.api.dependencies import get_db, require_role
from app.core.exceptions import NotFoundError
from app.db.models.business import BusinessUser
from app.schemas.training import (
    TrainingAskRequest,
    TrainingAskResponse,
    TrainingFeedbackRequest,
    TrainingKnowledgeChunkUsed,
    TrainingQuestionRead,
)
from app.services import training_service

router = APIRouter()

# The training room exposes real (would-be) customer-facing answers and lets
# someone reshape real knowledge — same owner/admin bar as Phase 5's
# approve/edit actions, which this ultimately triggers.
_TRAINING_ROLES = ["owner", "admin"]


@router.post("/training/ask", response_model=TrainingAskResponse)
def ask_training_question(
    payload: TrainingAskRequest,
    current_user: BusinessUser = Depends(require_role(_TRAINING_ROLES)),
    db: Session = Depends(get_db),
) -> TrainingAskResponse:
    training_question, knowledge_results = training_service.ask(
        db, business_id=current_user.business_id, question=payload.question, asked_by=current_user.id
    )
    return TrainingAskResponse(
        training_question_id=training_question.id,
        question=training_question.question,
        answer=training_question.answer,
        intent=training_question.intent,
        knowledge_chunks_used=[
            TrainingKnowledgeChunkUsed(
                chunk_id=chunk.id,
                document_id=doc.id,
                document_title=doc.title,
                content=chunk.content,
                similarity=similarity,
            )
            for chunk, doc, similarity in knowledge_results
        ],
    )


@router.post("/training/feedback", response_model=TrainingQuestionRead)
def submit_training_feedback(
    payload: TrainingFeedbackRequest,
    current_user: BusinessUser = Depends(require_role(_TRAINING_ROLES)),
    db: Session = Depends(get_db),
) -> TrainingQuestionRead:
    training_question = training_service.submit_feedback(
        db,
        business_id=current_user.business_id,
        training_question_id=payload.training_question_id,
        is_correct=payload.is_correct,
        corrected_answer=payload.corrected_answer,
        feedback_by=current_user.id,
    )
    if training_question is None:
        raise NotFoundError("Training question not found.")
    return TrainingQuestionRead.model_validate(training_question)


@router.get("/training/history", response_model=list[TrainingQuestionRead])
def list_training_history(
    current_user: BusinessUser = Depends(require_role(_TRAINING_ROLES)),
    db: Session = Depends(get_db),
) -> list[TrainingQuestionRead]:
    history = training_service.list_history(db, business_id=current_user.business_id)
    return [TrainingQuestionRead.model_validate(h) for h in history]
