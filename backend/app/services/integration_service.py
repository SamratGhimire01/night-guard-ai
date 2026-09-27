import uuid
from typing import Callable

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.config import settings
from app.db.models.integration import Integration
from app.schemas.integration import IntegrationUpsert
from app.services.notifications.email_provider import test_smtp_credentials
from app.services.channels.graph_api import (
    fetch_instagram_user_id,
    instagram_graph_host,
    test_graph_credentials,
    test_messenger_credentials,
)


def _check_whatsapp(config: dict) -> tuple[bool, str]:
    # Falls back to the platform-wide WHATSAPP_ACCESS_TOKEN for rows saved
    # before per-business WhatsApp tokens existed (see
    # WhatsAppChannelAdapter.send_message) — unchanged by this fix.
    object_id = config.get("phone_number_id")
    access_token = config.get("access_token") or settings.whatsapp_access_token
    if not object_id or not access_token:
        return False, "Saved configuration is missing a required value."
    return test_graph_credentials(object_id=object_id, access_token=access_token, api_version=settings.whatsapp_api_version)


def _check_messenger(config: dict) -> tuple[bool, str]:
    # Real fix (see graph_api.test_messenger_credentials docstring): a plain
    # object-read false-negatived a fully valid, never-expiring token that
    # genuinely can send — this checks the actual pages_messaging-gated
    # capability instead.
    access_token = config.get("page_access_token")
    if not access_token:
        return False, "Saved configuration is missing a required value."
    return test_messenger_credentials(access_token=access_token, api_version=settings.messenger_api_version)


def _check_instagram(config: dict) -> tuple[bool, str]:
    # Real fix: route to the correct Graph API host for this token's real
    # connection product (see graph_api.instagram_graph_host) instead of
    # always assuming graph.facebook.com. "me" resolves the current token's
    # own identity on either host — no dependency on ig_account_id being
    # correct for the check to at least prove the token itself is valid.
    access_token = config.get("access_token")
    if not access_token:
        return False, "Saved configuration is missing a required value."
    return test_graph_credentials(
        object_id="me",
        access_token=access_token,
        api_version=settings.instagram_api_version,
        host=instagram_graph_host(access_token),
    )


def _check_email(config: dict) -> tuple[bool, str]:
    return test_smtp_credentials(config.get("gmail_address", ""), config.get("app_password", ""))


# Per-type real connection check — each channel now genuinely reflects its
# own real send capability (see the three functions above), not one generic
# mechanism applied uniformly regardless of whether it fits.
_TEST_CONNECTION_CHECKS: dict[str, Callable[[dict], tuple[bool, str]]] = {
    "whatsapp": _check_whatsapp,
    "messenger": _check_messenger,
    "instagram": _check_instagram,
    "email": _check_email,
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
    config = dict(payload.config)
    if payload.type == "instagram":
        # Webhooks address the account by its professional id, which is not the id people usually paste as "Instagram
        # Account ID" — look it up from the token so inbound DMs are matched either way (see fetch_instagram_user_id).
        user_id = fetch_instagram_user_id(access_token=config.get("access_token", ""), api_version=settings.instagram_api_version)
        if user_id:
            config["ig_user_id"] = user_id
    return save_integration_config(db, business_id=business_id, type_=payload.type, config=config, enabled=payload.enabled)


def test_connection(db: Session, *, business_id: uuid.UUID, type_: str) -> tuple[bool, str]:
    """Real "Test connection" button support — loads THIS business's own
    saved Integration row (never credentials passed in the request; only
    what was already saved via upsert_integration) and makes one real,
    lightweight Meta API call, chosen per-type to actually reflect that
    channel's real send capability (see _TEST_CONNECTION_CHECKS above).
    Never sends a message to a real customer."""
    check = _TEST_CONNECTION_CHECKS.get(type_)
    if check is None:
        return False, f"Test connection is not supported for type={type_!r}."

    integration = get_integration(db, business_id=business_id, type_=type_)
    if integration is None or not integration.enabled:
        return False, "Not connected yet — save your credentials first."

    return check(integration.config or {})


def email_credentials(db: Session, *, business_id: uuid.UUID) -> tuple[str, str] | None:
    """This business's own Gmail (address, app_password) if it has saved an
    enabled one, else None -> EmailNotificationProvider falls back to the
    platform-wide account. Never falls back once a business HAS saved its own:
    a broken login must surface as a failed send, not silently go out from a
    different sender."""
    integration = get_integration(db, business_id=business_id, type_="email")
    if integration is None or not integration.enabled:
        return None
    config = integration.config or {}
    address, password = config.get("gmail_address"), config.get("app_password")
    return (address, password) if address and password else None


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
