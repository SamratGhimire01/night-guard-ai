import uuid
from datetime import UTC, datetime

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from app.db.models.knowledge import KnowledgeChunk, KnowledgeDocument, KnowledgeDocumentStatus
from app.llm import get_embedding_provider
from app.rag.chunking import chunk_text
from app.schemas.knowledge import KnowledgeDocumentUpdate


def list_documents(
    db: Session, *, business_id: uuid.UUID, status: KnowledgeDocumentStatus | None = None
) -> list[KnowledgeDocument]:
    stmt = select(KnowledgeDocument).where(KnowledgeDocument.business_id == business_id)
    if status is not None:
        stmt = stmt.where(KnowledgeDocument.status == status)
    stmt = stmt.order_by(KnowledgeDocument.created_at.desc())
    return list(db.execute(stmt).scalars())


def create_document(
    db: Session,
    *,
    business_id: uuid.UUID,
    title: str,
    content: str,
    source: str,
    status: KnowledgeDocumentStatus = KnowledgeDocumentStatus.DRAFT,
    approved_by: uuid.UUID | None = None,
) -> KnowledgeDocument:
    """`status`/`approved_by` default to the original Phase 5 behavior (always
    draft, never approved) — every pre-Phase-20 caller (manual entry, upload)
    is unaffected. Phase 20's training-room correction is the first caller to
    pass status=APPROVED directly (see training_service.py for why), which
    also triggers real chunking/embedding immediately, same as going through
    the existing PATCH .../knowledge/{id} {"status":"approved"} approval path."""
    document = KnowledgeDocument(
        business_id=business_id,
        title=title,
        content=content,
        source=source,
        status=status,
    )
    if status == KnowledgeDocumentStatus.APPROVED:
        document.approved_by = approved_by
        document.approved_at = datetime.now(UTC)
    db.add(document)
    db.commit()
    db.refresh(document)
    if status == KnowledgeDocumentStatus.APPROVED:
        _regenerate_chunks(db, document)
        db.refresh(document)
    return document


def get_document(
    db: Session, *, business_id: uuid.UUID, document_id: uuid.UUID
) -> KnowledgeDocument | None:
    return db.execute(
        select(KnowledgeDocument).where(
            KnowledgeDocument.id == document_id, KnowledgeDocument.business_id == business_id
        )
    ).scalar_one_or_none()


def _regenerate_chunks(db: Session, document: KnowledgeDocument) -> None:
    """Invalidates any existing chunks and, only if the document is currently
    approved, re-chunks + re-embeds its content. Only approved documents may
    ever have retrievable chunks — this is what enforces that at write time,
    rather than relying solely on a status filter at query time."""
    db.execute(delete(KnowledgeChunk).where(KnowledgeChunk.knowledge_document_id == document.id))

    if document.status == KnowledgeDocumentStatus.APPROVED:
        pieces = chunk_text(document.content)
        if pieces:
            vectors = get_embedding_provider().embed(pieces)
            for piece, vector in zip(pieces, vectors, strict=True):
                db.add(KnowledgeChunk(knowledge_document_id=document.id, content=piece, embedding=vector))

    db.commit()


def update_document(
    db: Session,
    *,
    business_id: uuid.UUID,
    document_id: uuid.UUID,
    payload: KnowledgeDocumentUpdate,
    current_user_id: uuid.UUID,
) -> KnowledgeDocument | None:
    document = get_document(db, business_id=business_id, document_id=document_id)
    if document is None:
        return None

    data = payload.model_dump(exclude_unset=True)
    new_status = data.pop("status", None)
    content_changed = "content" in data

    if content_changed:
        # Lightweight versioning: bump the counter on every content edit. No separate
        # history/snapshot table — Phase 5 scope is "structured, versioned, gated by
        # approval," not full revision history.
        document.version += 1

    for field, value in data.items():
        setattr(document, field, value)

    if new_status is not None:
        document.status = new_status
        if new_status == KnowledgeDocumentStatus.APPROVED:
            document.approved_by = current_user_id
            document.approved_at = datetime.now(UTC)

    db.commit()
    db.refresh(document)

    # Re-chunk on approval, on re-approval-after-edit, on any content edit to an
    # already-approved doc, and on leaving approved (archive) — skipped entirely
    # for a no-op status/title-only edit, so we don't burn an embedding call for
    # nothing.
    if content_changed or new_status is not None:
        _regenerate_chunks(db, document)
        db.refresh(document)

    return document


def search_chunks(
    db: Session, *, business_id: uuid.UUID, query_vector: list[float], top_k: int
) -> list[tuple[KnowledgeChunk, KnowledgeDocument, float]]:
    """Tenant-scoped similarity search over approved-document chunks only.
    Returns (chunk, parent document, similarity) tuples, best match first."""
    distance = KnowledgeChunk.embedding.cosine_distance(query_vector)
    stmt = (
        select(KnowledgeChunk, KnowledgeDocument, (1 - distance).label("similarity"))
        .join(KnowledgeDocument, KnowledgeChunk.knowledge_document_id == KnowledgeDocument.id)
        .where(
            KnowledgeDocument.business_id == business_id,
            KnowledgeDocument.status == KnowledgeDocumentStatus.APPROVED,
        )
        .order_by(distance)
        .limit(top_k)
    )
    return [(chunk, doc, similarity) for chunk, doc, similarity in db.execute(stmt).all()]


# Real conversation-quality fix (PHASE_STATUS.md): `search_chunks` always
# returns its top_k results with no relevance floor, by design — the
# admin-facing raw knowledge-search endpoint (app/api/routes/knowledge.py)
# genuinely wants to see everything, unfiltered, for debugging what does and
# doesn't match. But every caller that hands these results to the LLM
# (orchestrator.handle_incoming_message, training_service.ask) was showing it
# real noise on top of real matches — live-measured on this project's own
# real business ("Samaj Dental Clinic") knowledge base: genuinely relevant
# top-1 matches scored 0.379-0.645 (parking, cancellation policy, braces
# timeline, payment methods, cleaning pricing); a bare greeting, "thank you,"
# and an unrelated question scored 0.080-0.207 top-1 — a real, clean gap
# between the two clusters. 0.25 sits in that gap, closer to the irrelevant
# side (comfortably above the highest irrelevant score seen, 0.207) so a
# genuinely relevant but weaker match is never wrongly hidden — showing one
# extra borderline chunk is a much smaller real harm than hiding real,
# correct information (rule 1 in intent.py's accuracy floor). Filters
# per-chunk, not all-or-nothing: a query whose #1 result is relevant but
# whose #2/#3 are noise (real example: "can I pay by card?" -> 0.400, 0.192,
# 0.156) correctly keeps only the real match.
LLM_RELEVANCE_FLOOR = 0.25


def filter_for_llm(
    results: list[tuple[KnowledgeChunk, KnowledgeDocument, float]],
) -> list[tuple[KnowledgeChunk, KnowledgeDocument, float]]:
    """Drops chunks below LLM_RELEVANCE_FLOOR — the ONLY place this floor is
    applied, so every caller that feeds the LLM shares one real, evidenced
    cutoff. Never applied to `search_chunks` itself or to the raw admin
    search endpoint, which intentionally shows unfiltered results."""
    return [r for r in results if r[2] >= LLM_RELEVANCE_FLOOR]


def delete_document(db: Session, *, business_id: uuid.UUID, document_id: uuid.UUID) -> bool:
    document = get_document(db, business_id=business_id, document_id=document_id)
    if document is None:
        return False
    db.delete(document)
    db.commit()
    return True
