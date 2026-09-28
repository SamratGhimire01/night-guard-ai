import uuid

from pgvector.sqlalchemy import Vector
from sqlalchemy import ForeignKey, String, Text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.database import Base
from app.db.models.knowledge import EMBEDDING_DIMENSIONS
from app.db.models.mixins import CreatedAtMixin, UUIDPrimaryKeyMixin


class StyleExemplar(UUIDPrimaryKeyMixin, CreatedAtMixin, Base):
    """Fact-free, human-written example replies used to nudge tone/register in
    intent.py's LLM-draft prompt step ONLY -- never a source of facts, never
    seen by any template-dispatch branch (booking_success, cancellation, hours,
    resend, ...), which always render from response_templates.py instead. See
    style_exemplar_service.retrieve and intent.py's "Example replies" prompt
    section for the isolation this depends on.

    `intent`/`language` mirror Conversation.detected_intent/detected_language's
    own convention: plain strings, not Postgres enums -- ConversationIntent/
    ConversationLanguage already constrain them app-side, so a new intent never
    needs a migration here.
    """

    __tablename__ = "style_exemplars"

    # Nullable, unlike TenantMixin's business_id: null = shared/global (usable by
    # any tenant, further narrowed by business_type below); non-null = a real
    # tenant-specific override exemplar.
    business_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("businesses.id", ondelete="CASCADE"), index=True
    )
    # A shared exemplar's category flavor (e.g. "dental", "trekking"), matched
    # against the retrieving tenant's own Business.business_type. Null means
    # truly universal -- eligible for every tenant regardless of type.
    business_type: Mapped[str | None] = mapped_column(String(50))
    intent: Mapped[str] = mapped_column(String(50), nullable=False)
    language: Mapped[str] = mapped_column(String(20), nullable=False, index=True)
    register: Mapped[str] = mapped_column(String(20), nullable=False)
    # The example reply itself, with any real fact already replaced by a
    # placeholder token ({PRICE}, {TIME}, {NAME}, ...) -- never a real price,
    # time, or name. See fact_validator.check_unfilled_slots for the guard
    # that catches one of these leaking through unfilled into a real reply.
    text: Mapped[str] = mapped_column(Text, nullable=False)
    embedding: Mapped[list[float] | None] = mapped_column(Vector(EMBEDDING_DIMENSIONS))
