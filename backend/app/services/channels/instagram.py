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

_SEND_URL_TEMPLATE = "https://graph.facebook.com/{api_version}/{ig_account_id}/messages"
_SEND_TIMEOUT_SECONDS = 15


class InstagramChannelAdapter(ChannelAdapter):
    """The real Instagram Messaging adapter — same architectural pattern as
    Phase 22/26's WhatsApp/Messenger adapters: receive-side logic is pure
    DB/orchestrator plumbing with no external network dependency, so
    app.api.routes.webhooks calls this exact class whether the payload came
    from a real Meta server or a documented, correctly-HMAC-signed curl
    request simulating one (see PHASE_STATUS.md Phase 27).

    send_message is the only part that ever talks to Meta's network, and it
    degrades gracefully to a logged simulation whenever no access token is
    configured for this business — same discipline as WhatsApp/Messenger.
    """

    channel = "instagram"

    def receive_message(
        self,
        db: Session,
        *,
        business_id: uuid.UUID,
        external_customer_ref: str,
        content: str,
        external_message_id: str | None = None,
    ) -> dict | None:
        # external_customer_ref is the real Instagram-scoped id (IGSID) —
        # like WhatsApp's wa_id/Messenger's PSID and unlike the widget's
        # session token, this isn't a secret, so it's used directly as
        # ChannelIdentity.external_ref.
        conversation = get_or_create_conversation(
            db,
            business_id=business_id,
            channel=self.channel,
            external_ref=external_customer_ref,
            default_customer_name="Instagram Contact",
        )
        # The exact same Phase 8 orchestrator every other channel already
        # goes through — no parallel/simplified conversation logic.
        return handle_incoming_message(
            db,
            conversation_id=conversation.id,
            business_id=business_id,
            content=content,
            external_message_id=external_message_id,
        )

    def send_message(self, *, igsid: str, text: str, ig_account_id: str, access_token: str) -> str:
        """Real Instagram Messaging API send request
        (POST https://graph.facebook.com/{version}/{ig_account_id}/messages?access_token=...,
        Meta's current documented request shape:
        {"recipient":{"id":igsid},"message":{"text":text}}), made via stdlib
        urllib — same "no SDK for one POST" precedent as WhatsApp/Messenger.

        Real, deliberate difference from Messenger's send URL despite the
        near-identical request BODY shape (both share {"recipient":{"id":..},
        "message":{"text":..}}): Instagram's Send API is called against
        /{ig_account_id}/messages, a path scoped to the specific Instagram
        professional account, NOT Messenger's Page-scoped /me/messages — Meta
        deliberately disambiguates the two products at this one point even
        though the rest of the wire format is shared. Like Messenger (and
        unlike WhatsApp), there is no platform-wide token: each Instagram
        professional account has its own access token, sourced per-request
        from this business's own Integration.config, not a global setting.

        Graceful fallback, same discipline as WhatsApp/Messenger: an empty/
        missing access_token logs a SIMULATED line and returns immediately,
        never attempting a network call. Never raises on a real failure
        either — only the HTTP status is logged, never the response body.
        """
        if not access_token:
            logger.info("SIMULATED Instagram send to %s: %s", igsid, text)
            return "simulated — no real access token configured for this business"

        url = _SEND_URL_TEMPLATE.format(api_version=settings.instagram_api_version, ig_account_id=ig_account_id)
        body = json.dumps({"recipient": {"id": igsid}, "message": {"text": text}}).encode("utf-8")
        request = urllib.request.Request(
            f"{url}?access_token={access_token}",
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
            logger.warning("Instagram send failed: HTTP %s", exc.code)
            return f"failed: HTTP {exc.code}"
        except urllib.error.URLError as exc:
            logger.warning("Instagram send failed: could not reach Graph API (%s)", type(exc.reason).__name__)
            return "failed: could not reach Graph API"
