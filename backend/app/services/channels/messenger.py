import json
import logging
import urllib.error
import urllib.request
import uuid

from sqlalchemy.orm import Session

from app.core.config import settings
from app.services.channels.base import ChannelAdapter, get_or_create_conversation
from app.services.conversation.orchestrator import handle_incoming_message

logger = logging.getLogger(__name__)

_SEND_URL_TEMPLATE = "https://graph.facebook.com/{api_version}/me/messages"
_SEND_TIMEOUT_SECONDS = 15


class MessengerChannelAdapter(ChannelAdapter):
    """The real Messenger Platform adapter — same architectural pattern as
    Phase 22's WhatsAppChannelAdapter: receive-side logic is pure DB/
    orchestrator plumbing with no external network dependency, so
    app.api.routes.webhooks calls this exact class whether the payload came
    from a real Meta Page or a documented, correctly-HMAC-signed curl request
    simulating one (see PHASE_STATUS.md Phase 26).

    send_message is the only part that ever talks to Meta's network, and it
    degrades gracefully to a logged simulation whenever no Page access token
    is configured for this business — same discipline as WhatsApp's
    WHATSAPP_ACCESS_TOKEN fallback.
    """

    channel = "messenger"

    def receive_message(
        self,
        db: Session,
        *,
        business_id: uuid.UUID,
        external_customer_ref: str,
        content: str,
        external_message_id: str | None = None,
        deliver=None,
    ) -> dict | None:
        # external_customer_ref is the real Messenger PSID (page-scoped id) —
        # like WhatsApp's wa_id and unlike the widget's session token, this
        # isn't a secret, so it's used directly as ChannelIdentity.external_ref.
        conversation = get_or_create_conversation(
            db,
            business_id=business_id,
            channel=self.channel,
            external_ref=external_customer_ref,
            default_customer_name="Messenger Contact",
        )
        # The exact same Phase 8 orchestrator every other channel already
        # goes through — no parallel/simplified conversation logic.
        return handle_incoming_message(
            db,
            conversation_id=conversation.id,
            business_id=business_id,
            content=content,
            external_message_id=external_message_id,
            deliver=deliver,
        )

    def send_message(self, *, psid: str, text: str, page_access_token: str) -> str:
        """Real Messenger Send API request
        (POST https://graph.facebook.com/{version}/me/messages?access_token=...,
        Meta's actual documented request shape:
        {"recipient":{"id":psid},"message":{"text":text}}), made via stdlib
        urllib — same "no SDK for one POST" precedent as WhatsAppChannelAdapter.

        Real, deliberate difference from WhatsApp's send_message: WhatsApp
        uses one platform-wide WHATSAPP_ACCESS_TOKEN because a single Meta
        App/WABA sends on behalf of many registered phone numbers. Messenger's
        Send API is authenticated per-PAGE (a Page Access Token minted via
        OAuth for that one specific Facebook Page) — there is no such thing as
        one token valid across multiple Pages/businesses. So
        page_access_token is a real, required argument here, sourced from
        THIS business's own Integration.config["page_access_token"]
        (messenger_webhook.py), not a global setting.

        Graceful fallback, same discipline as WhatsApp: an empty/missing
        page_access_token logs a SIMULATED line and returns immediately,
        never attempting a network call. Never raises on a real failure
        either — a send failure must never break the webhook's own ack to
        Meta; only the HTTP status is logged, never the response body (same
        scrubbing discipline as WhatsApp/Gmail/Twilio).
        """
        if not page_access_token:
            logger.info("SIMULATED Messenger send to %s: %s", psid, text)
            return "simulated — no real page access token configured for this business"

        url = _SEND_URL_TEMPLATE.format(api_version=settings.messenger_api_version)
        body = json.dumps({"recipient": {"id": psid}, "message": {"text": text}}).encode("utf-8")
        request = urllib.request.Request(
            f"{url}?access_token={page_access_token}",
            data=body,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        try:
            with urllib.request.urlopen(request, timeout=_SEND_TIMEOUT_SECONDS) as response:
                payload = json.loads(response.read())
                message_id = payload.get("message_id")
                return f"sent mid={message_id}"
        except urllib.error.HTTPError as exc:
            logger.warning("Messenger send failed: HTTP %s", exc.code)
            return f"failed: HTTP {exc.code}"
        except urllib.error.URLError as exc:
            logger.warning("Messenger send failed: could not reach Graph API (%s)", type(exc.reason).__name__)
            return "failed: could not reach Graph API"
