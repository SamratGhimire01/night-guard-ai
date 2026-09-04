import uuid
from datetime import datetime

from sqlalchemy import Boolean, DateTime, ForeignKey, String, Text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.database import Base
from app.db.models.mixins import CreatedAtMixin, TenantMixin, UUIDPrimaryKeyMixin


class TrainingQuestion(UUIDPrimaryKeyMixin, TenantMixin, CreatedAtMixin, Base):
    """Phase 20: an owner/admin testing the AI in the training room.

    Deliberately NOT wired through the real customer-facing orchestrator /
    Conversation / Message tables (Phase 7/8) — a training question must never
    trigger a real booking/cancel/reschedule side effect, a Phase 18 follow-up,
    or a Phase 19 human handoff the way a genuine customer message would. It
    reuses the exact same Phase 6 knowledge search + Phase 8
    classify_and_respond call, just without persisting through the
    conversation pipeline — see training_service.py.
    """

    __tablename__ = "training_questions"

    question: Mapped[str] = mapped_column(Text, nullable=False)
    answer: Mapped[str] = mapped_column(Text, nullable=False)
    # The real Phase 8 ConversationIntent value, plain string — same "not a
    # Postgres enum" convention as Message.detected_intent (app-side already
    # constrains it via ConversationIntent).
    intent: Mapped[str] = mapped_column(String(50), nullable=False)
    # Plain FK, not a same-tenant composite — same documented, pre-existing
    # convention as KnowledgeDocument.approved_by (Phase 2's gap).
    asked_by: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("business_users.id"), nullable=False)

    # Feedback — all nullable until POST /training/feedback is called.
    is_correct: Mapped[bool | None] = mapped_column(Boolean)
    corrected_answer: Mapped[str | None] = mapped_column(Text)
    # The real KnowledgeDocument this correction produced — only set when
    # is_correct=False AND a corrected_answer was given (see training_service).
    # Plain FK, not a same-tenant composite: this column is always written by
    # that same code path within the same business_id, never client-supplied,
    # so there's no cross-tenant risk despite no composite constraint
    # (knowledge_documents has no UNIQUE(id, business_id) target to composite
    # against today — the identical situation FollowUp.trigger_message_id
    # already documented for Message).
    correction_knowledge_document_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("knowledge_documents.id", ondelete="SET NULL")
    )
    feedback_by: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("business_users.id"))
    feedback_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
