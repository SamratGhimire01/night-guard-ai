import uuid

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.db.models.integration import Integration
from app.schemas.integration import IntegrationUpsert


def list_integrations(db: Session, *, business_id: uuid.UUID) -> list[Integration]:
    return list(db.execute(select(Integration).where(Integration.business_id == business_id)).scalars())


def get_integration(db: Session, *, business_id: uuid.UUID, type_: str) -> Integration | None:
    return db.execute(
        select(Integration).where(Integration.business_id == business_id, Integration.type == type_)
    ).scalar_one_or_none()


# Kept as a "private" alias for existing callers/tests written against the old
# name — same function, not a second implementation.
_get = get_integration


def save_integration_config(
    db: Session, *, business_id: uuid.UUID, type_: str, config: dict, enabled: bool
) -> Integration:
    """Create-or-replace the one integration row this business has for
    `type_` — the single writer both the self-serve IntegrationUpsert route
    (via upsert_integration below) and Phase 40's Google Calendar OAuth
    callback (which never goes through that public, hand-typed-config schema)
    funnel through. The (business_id, type) unique constraint is the real
    guard against a concurrent double-create race; caught here the same
    "IntegrityError means someone else already won" way the inbound webhook
    processors treat a duplicate delivery (see
    messenger_webhook.process_webhook_payload)."""
    existing = get_integration(db, business_id=business_id, type_=type_)
    if existing is not None:
        existing.config = config
        existing.enabled = enabled
        db.commit()
        db.refresh(existing)
        return existing

    integration = Integration(business_id=business_id, type=type_, config=config, enabled=enabled)
    db.add(integration)
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        existing = get_integration(db, business_id=business_id, type_=type_)
        existing.config = config
        existing.enabled = enabled
        db.commit()
        db.refresh(existing)
        return existing
    db.refresh(integration)
    return integration


def upsert_integration(db: Session, *, business_id: uuid.UUID, payload: IntegrationUpsert) -> Integration:
    """POST /integrations — a real alternative to hand-editing the DB to go
    live with a Meta Page/App (Messenger/WhatsApp/Instagram only; Google
    Calendar's tokens are never hand-typed through this endpoint, see
    save_integration_config's docstring)."""
    return save_integration_config(
        db, business_id=business_id, type_=payload.type, config=payload.config, enabled=payload.enabled
    )


def delete_integration(db: Session, *, business_id: uuid.UUID, type_: str) -> bool:
    """Real disconnect — removes the row entirely (not just enabled=False), so
    a re-connect starts clean and no stale token is ever left sitting in the
    DB. Returns False if there was nothing to delete (idempotent)."""
    existing = get_integration(db, business_id=business_id, type_=type_)
    if existing is None:
        return False
    db.delete(existing)
    db.commit()
    return True
