import json
import logging

from fastapi import APIRouter, Depends, Query, Request
from fastapi.responses import PlainTextResponse
from sqlalchemy.orm import Session

from app.api.dependencies import get_db
from app.core.config import settings
from app.core.exceptions import ForbiddenError, UnauthorizedError
from app.services.channels.instagram_webhook import process_webhook_payload as process_instagram_webhook_payload
from app.services.channels.messenger_webhook import process_webhook_payload as process_messenger_webhook_payload
from app.services.channels.whatsapp_webhook import process_webhook_payload, verify_signature

logger = logging.getLogger(__name__)

router = APIRouter()


@router.get("/api/v1/webhooks/whatsapp", response_class=PlainTextResponse)
def verify_whatsapp_webhook(
    hub_mode: str = Query(alias="hub.mode", default=""),
    hub_verify_token: str = Query(alias="hub.verify_token", default=""),
    hub_challenge: str = Query(alias="hub.challenge", default=""),
) -> str:
    """Meta's real, one-time webhook subscription handshake (documented
    contract): Meta calls this with hub.mode=subscribe and a hub.verify_token
    it expects to match what you registered in the Meta App Dashboard. A
    match must echo back hub.challenge as a PLAIN TEXT body (not JSON) with a
    real 200; anything else must be a real 403 — never a fabricated "looks
    right" 200 regardless of the token."""
    token_configured = bool(settings.whatsapp_verify_token)
    if hub_mode == "subscribe" and token_configured and hub_verify_token == settings.whatsapp_verify_token:
        return hub_challenge
    raise ForbiddenError("Webhook verification failed.")


@router.post("/api/v1/webhooks/whatsapp")
async def receive_whatsapp_webhook(request: Request, db: Session = Depends(get_db)) -> dict:
    """Real inbound webhook receiver. Signature verification happens against
    the RAW body bytes, before any JSON parsing (see verify_signature's
    docstring for why) — a real X-Hub-Signature-256 HMAC check, real even
    without a live Meta account, per the ticket's explicit ask.

    Always acks quickly: per Meta's own documented behavior, a non-2xx or
    slow response causes webhook retries/backoff, so a business_id we don't
    recognize or a duplicate message_id is logged and skipped, never turned
    into an error response here (see process_webhook_payload)."""
    raw_body = await request.body()
    signature = request.headers.get("x-hub-signature-256")
    if not verify_signature(app_secret=settings.whatsapp_app_secret, raw_body=raw_body, signature_header=signature):
        raise UnauthorizedError("Invalid webhook signature.")

    payload = json.loads(raw_body)
    outcomes = process_webhook_payload(db, payload)
    logger.info("whatsapp webhook processed: %d message(s), outcomes=%s", len(outcomes), [o["status"] for o in outcomes])
    return {"status": "ok"}


@router.get("/api/v1/webhooks/messenger", response_class=PlainTextResponse)
def verify_messenger_webhook(
    hub_mode: str = Query(alias="hub.mode", default=""),
    hub_verify_token: str = Query(alias="hub.verify_token", default=""),
    hub_challenge: str = Query(alias="hub.challenge", default=""),
) -> str:
    """Meta's real webhook subscription handshake — the identical mechanism
    as WhatsApp's (same Meta Graph API webhooks platform under both
    products): hub.mode=subscribe + a matching hub.verify_token echoes
    hub.challenge back as plain text with a real 200; anything else is a
    real 403."""
    token_configured = bool(settings.messenger_verify_token)
    if hub_mode == "subscribe" and token_configured and hub_verify_token == settings.messenger_verify_token:
        return hub_challenge
    raise ForbiddenError("Webhook verification failed.")


@router.post("/api/v1/webhooks/messenger")
async def receive_messenger_webhook(request: Request, db: Session = Depends(get_db)) -> dict:
    """Real inbound Messenger webhook receiver — same signature-then-parse
    discipline as WhatsApp's receiver, reusing the identical
    verify_signature (Meta's X-Hub-Signature-256 mechanism is genuinely the
    same across both products, just keyed by this app's own
    MESSENGER_APP_SECRET). Always acks fast: an unrecognized page_id or a
    duplicate message_id is logged and skipped, never turned into an error
    response (see messenger_webhook.process_webhook_payload)."""
    raw_body = await request.body()
    signature = request.headers.get("x-hub-signature-256")
    if not verify_signature(app_secret=settings.messenger_app_secret, raw_body=raw_body, signature_header=signature):
        raise UnauthorizedError("Invalid webhook signature.")

    payload = json.loads(raw_body)
    outcomes = process_messenger_webhook_payload(db, payload)
    logger.info("messenger webhook processed: %d message(s), outcomes=%s", len(outcomes), [o["status"] for o in outcomes])
    return {"status": "ok"}


@router.get("/api/v1/webhooks/instagram", response_class=PlainTextResponse)
def verify_instagram_webhook(
    hub_mode: str = Query(alias="hub.mode", default=""),
    hub_verify_token: str = Query(alias="hub.verify_token", default=""),
    hub_challenge: str = Query(alias="hub.challenge", default=""),
) -> str:
    """Meta's real webhook subscription handshake — the identical mechanism
    as WhatsApp's/Messenger's (same Meta Graph API webhooks platform under
    all three products): hub.mode=subscribe + a matching hub.verify_token
    echoes hub.challenge back as plain text with a real 200; anything else is
    a real 403."""
    token_configured = bool(settings.instagram_verify_token)
    if hub_mode == "subscribe" and token_configured and hub_verify_token == settings.instagram_verify_token:
        return hub_challenge
    raise ForbiddenError("Webhook verification failed.")


@router.post("/api/v1/webhooks/instagram")
async def receive_instagram_webhook(request: Request, db: Session = Depends(get_db)) -> dict:
    """Real inbound Instagram webhook receiver — same signature-then-parse
    discipline as WhatsApp's/Messenger's receiver, reusing the identical
    verify_signature (Meta's X-Hub-Signature-256 mechanism is genuinely the
    same across all three products, just keyed by this app's own
    INSTAGRAM_APP_SECRET). Always acks fast: an unrecognized ig_account_id or
    a duplicate message_id is logged and skipped, never turned into an error
    response (see instagram_webhook.process_webhook_payload)."""
    raw_body = await request.body()
    signature = request.headers.get("x-hub-signature-256")
    if not verify_signature(app_secret=settings.instagram_app_secret, raw_body=raw_body, signature_header=signature):
        raise UnauthorizedError("Invalid webhook signature.")

    payload = json.loads(raw_body)
    outcomes = process_instagram_webhook_payload(db, payload)
    logger.info("instagram webhook processed: %d message(s), outcomes=%s", len(outcomes), [o["status"] for o in outcomes])
    return {"status": "ok"}
