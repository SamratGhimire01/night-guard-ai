import json
import logging

from fastapi import APIRouter, Depends, Query, Request
from fastapi.responses import PlainTextResponse
from sqlalchemy.orm import Session

from app.api.dependencies import get_db
from app.core.config import settings
from app.core.exceptions import ForbiddenError, UnauthorizedError
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
