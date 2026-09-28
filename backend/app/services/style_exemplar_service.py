import uuid

from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from app.db.models.style_exemplar import StyleExemplar
from app.llm import get_embedding_provider


def create_exemplar(
    db: Session,
    *,
    business_id: uuid.UUID | None,
    business_type: str | None,
    intent: str,
    language: str,
    register: str,
    text: str,
) -> StyleExemplar:
    """Embeds `text` and inserts one exemplar row. `text` must already have every
    real fact (price/time/name/...) replaced by a {PLACEHOLDER} token -- see
    StyleExemplar's docstring."""
    vector = get_embedding_provider().embed([text])[0]
    exemplar = StyleExemplar(
        business_id=business_id,
        business_type=business_type,
        intent=intent,
        language=language,
        register=register,
        text=text,
        embedding=vector,
    )
    db.add(exemplar)
    db.commit()
    db.refresh(exemplar)
    return exemplar


def retrieve(
    db: Session,
    *,
    business_id: uuid.UUID,
    business_type: str | None,
    language: str,
    query_vector: list[float],
    top_k: int = 6,
) -> list[StyleExemplar]:
    """Semantic retrieval only -- see intent.py/orchestrator.py for why this
    can't filter by the turn's `intent` (unknown until the SAME LLM call that
    would receive this prompt section returns it). Eligible rows are:
      - business_id == this tenant (a real tenant-specific override), OR
      - business_id IS NULL AND (business_type IS NULL, i.e. truly universal,
        OR business_type == this tenant's own business_type)
    Ranked purely by cosine distance to `query_vector` (the customer message's
    own embedding, reused from the knowledge-search call this same turn -- no
    extra embedding call). `language` is a hard filter, same as `business_id`/
    `business_type` scoping -- never returns an exemplar in the wrong script."""
    scope = or_(
        StyleExemplar.business_id == business_id,
        StyleExemplar.business_id.is_(None) & (
            StyleExemplar.business_type.is_(None)
            if business_type is None
            else or_(StyleExemplar.business_type.is_(None), StyleExemplar.business_type == business_type)
        ),
    )
    distance = StyleExemplar.embedding.cosine_distance(query_vector)
    stmt = (
        select(StyleExemplar)
        .where(scope, StyleExemplar.language == language, StyleExemplar.embedding.is_not(None))
        .order_by(distance)
        .limit(top_k)
    )
    return list(db.execute(stmt).scalars())
