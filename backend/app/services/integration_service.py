import uuid

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.db.models.integration import Integration
from app.schemas.integration import IntegrationUpsert


def list_integrations(db: Session, *, business_id: uuid.UUID) -> list[Integration]:
    return list(db.execute(select(Integration).where(Integration.business_id == business_id)).scalars())


def _get(db: Session, *, business_id: uuid.UUID, type_: str) -> Integration | None:
    return db.execute(
        select(Integration).where(Integration.business_id == business_id, Integration.type == type_)
    ).scalar_one_or_none()


def upsert_integration(db: Session, *, business_id: uuid.UUID, payload: IntegrationUpsert) -> Integration:
    """Create-or-replace the one integration row this business has for
    payload.type — a real alternative to hand-editing the DB to go live with
    a Meta Page/App. The (business_id, type) unique constraint is the real
    guard against a concurrent double-create race; caught here the same
    "IntegrityError means someone else already won" way the inbound webhook
    processors treat a duplicate delivery (see
    messenger_webhook.process_webhook_payload)."""
    existing = _get(db, business_id=business_id, type_=payload.type)
    if existing is not None:
        existing.config = payload.config
        existing.enabled = payload.enabled
        db.commit()
        db.refresh(existing)
        return existing

    integration = Integration(
        business_id=business_id, type=payload.type, config=payload.config, enabled=payload.enabled
    )
    db.add(integration)
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        existing = _get(db, business_id=business_id, type_=payload.type)
        existing.config = payload.config
        existing.enabled = payload.enabled
        db.commit()
        db.refresh(existing)
        return existing
    db.refresh(integration)
    return integration
