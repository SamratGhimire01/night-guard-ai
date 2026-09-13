import uuid
from typing import Callable

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.config import settings
from app.db.models.integration import Integration
from app.schemas.integration import IntegrationUpsert
from app.services.channels.graph_api import test_graph_credentials

# Per-type mapping of a saved Integration.config -> the (object_id,
# access_token, api_version) test_graph_credentials needs — the one place
# that knows which config keys each channel's real credential lives under.
# WhatsApp falls back to the platform-wide WHATSAPP_ACCESS_TOKEN for rows
# saved before per-business WhatsApp tokens existed (see
# WhatsAppChannelAdapter.send_message).
_TEST_CONNECTION_SPECS: dict[str, Callable[[dict], tuple[str | None, str | None, str]]] = {
    "whatsapp": lambda config: (
        config.get("phone_number_id"),
        config.get("access_token") or settings.whatsapp_access_token,
        settings.whatsapp_api_version,
    ),
    "messenger": lambda config: (config.get("page_id"), config.get("page_access_token"), settings.messenger_api_version),
    "instagram": lambda config: (config.get("ig_account_id"), config.get("access_token"), settings.instagram_api_version),
}


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


def test_connection(db: Session, *, business_id: uuid.UUID, type_: str) -> tuple[bool, str]:
    """Real "Test connection" button support — loads THIS business's own
    saved Integration row (never credentials passed in the request; only
    what was already saved via upsert_integration) and makes one real,
    lightweight GET against Meta's Graph API to confirm they're valid. Never
    sends a message to a real customer."""
    spec = _TEST_CONNECTION_SPECS.get(type_)
    if spec is None:
        return False, f"Test connection is not supported for type={type_!r}."

    integration = get_integration(db, business_id=business_id, type_=type_)
    if integration is None or not integration.enabled:
        return False, "Not connected yet — save your credentials first."

    object_id, access_token, api_version = spec(integration.config or {})
    if not object_id or not access_token:
        return False, "Saved configuration is missing a required value."
    return test_graph_credentials(object_id=object_id, access_token=access_token, api_version=api_version)


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
