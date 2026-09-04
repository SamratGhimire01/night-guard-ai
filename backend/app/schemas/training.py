import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict, field_validator, model_validator


class TrainingAskRequest(BaseModel):
    question: str

    @field_validator("question")
    @classmethod
    def not_blank(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("This field must not be blank.")
        return value


class TrainingKnowledgeChunkUsed(BaseModel):
    chunk_id: uuid.UUID
    document_id: uuid.UUID
    document_title: str
    content: str
    similarity: float


class TrainingAskResponse(BaseModel):
    training_question_id: uuid.UUID
    question: str
    answer: str
    intent: str
    knowledge_chunks_used: list[TrainingKnowledgeChunkUsed]


class TrainingFeedbackRequest(BaseModel):
    training_question_id: uuid.UUID
    is_correct: bool
    corrected_answer: str | None = None

    @model_validator(mode="after")
    def corrected_answer_matches_is_correct(self) -> "TrainingFeedbackRequest":
        if self.is_correct and self.corrected_answer is not None:
            raise ValueError("corrected_answer must not be set when is_correct is true.")
        if not self.is_correct and not (self.corrected_answer and self.corrected_answer.strip()):
            raise ValueError("corrected_answer is required and must not be blank when is_correct is false.")
        return self


class TrainingQuestionRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    question: str
    answer: str
    intent: str
    is_correct: bool | None
    corrected_answer: str | None
    correction_knowledge_document_id: uuid.UUID | None
    feedback_at: datetime | None
    created_at: datetime
