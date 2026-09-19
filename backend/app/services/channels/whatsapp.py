import json
import logging
import urllib.error
import urllib.request
import uuid

import httpx
from sqlalchemy.orm import Session

from app.core.config import settings
from app.services.channels.base import ChannelAdapter, get_or_create_conversation
from app.services.conversation.orchestrator import handle_incoming_message

logger = logging.getLogger(__name__)

_SEND_URL_TEMPLATE = "https://graph.facebook.com/{api_version}/{phone_number_id}/messages"
_SEND_TIMEOUT_SECONDS = 15


class WhatsAppChannelAdapter(ChannelAdapter):
    """The real WhatsApp Cloud API adapter — receive-side logic is pure DB/
    orchestrator plumbing with no dependency on any external network call, so
    it needs no mock/real split at all: app.api.routes.webhooks calls this
    exact class whether the payload came from a real Meta server or a
    documented, correctly-HMAC-signed curl request simulating one (see
    PHASE_STATUS.md Phase 22).

    The send side (send_message) is the only part that ever talks to Meta's
    network, and it degrades gracefully to a logged simulation whenever
    WHATSAPP_ACCESS_TOKEN isn't configured — the exact same class, unchanged,
    becomes a real integration the moment real credentials are set. This is
    the literal "MockWhatsAppAdapter -> MetaWhatsAppAdapter without changing
    the conversation engine" swap the master plan (Phase 49) describes: there
    is only ever one adapter class, and "mock" vs "real" is just which
    settings are populated, not a different code path.
    """

    channel = "whatsapp"

    def receive_message(
        self,
        db: Session,
        *,
        business_id: uuid.UUID,
        external_customer_ref: str,
        content: str,
        external_message_id: str | None = None,
    ) -> dict | None:
        # external_customer_ref is the real WhatsApp wa_id (a phone number) —
        # unlike the widget's session token, this is not a secret, so it's
        # used directly as ChannelIdentity.external_ref, no hashing needed
        # (see widget_service.py's docstring for why THAT case is different).
        conversation = get_or_create_conversation(
            db,
            business_id=business_id,
            channel=self.channel,
            external_ref=external_customer_ref,
            default_customer_name="WhatsApp Contact",
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

    def send_message(self, *, to: str, text: str, phone_number_id: str, access_token: str = "") -> str:
        """Real Meta Cloud API send call
        (POST https://graph.facebook.com/{version}/{phone_number_id}/messages,
        Meta's actual documented request shape) — made directly via urllib
        (stdlib), same "no SDK for one POST" precedent as
        TwilioSMSProvider. Never raises: a send failure here must never break
        the webhook's own 200 ack to Meta (same "notification failure can't
        break the flow" discipline as Phase 13's dispatch_service) — the
        caller only ever sees a descriptive string back, success or not.

        `access_token`: this business's own token from
        Integration.config["access_token"] (the dashboard channel-connect
        phase added real per-business WhatsApp tokens, matching how
        Messenger/Instagram already worked). Falls back to the platform-wide
        WHATSAPP_ACCESS_TOKEN when empty, so rows saved before that phase (or
        a shared platform token) keep working unchanged.

        Graceful fallback when no token is available either way (no
        production Meta Business account exists yet — Phase 22): logs a
        SIMULATED line and returns immediately, the identical fallback
        pattern Phase 15's SMSNotificationProvider stub uses for Twilio.
        """
        token = access_token or settings.whatsapp_access_token
        if not token:
            logger.info("SIMULATED WhatsApp send to %s: %s", to, text)
            return "simulated — no real WhatsApp access token configured"

        url = _SEND_URL_TEMPLATE.format(api_version=settings.whatsapp_api_version, phone_number_id=phone_number_id)
        body = json.dumps(
            {
                "messaging_product": "whatsapp",
                "recipient_type": "individual",
                "to": to,
                "type": "text",
                "text": {"preview_url": False, "body": text},
            }
        ).encode("utf-8")
        request = urllib.request.Request(
            url,
            data=body,
            headers={
                "Authorization": f"Bearer {token}",
                "Content-Type": "application/json",
            },
            method="POST",
        )
        try:
            with urllib.request.urlopen(request, timeout=_SEND_TIMEOUT_SECONDS) as response:
                payload = json.loads(response.read())
                message_id = (payload.get("messages") or [{}])[0].get("id")
                return f"sent wamid={message_id}"
        except urllib.error.HTTPError as exc:
            # Never log exc's raw response body: Meta error payloads can echo
            # back request details — only the HTTP status is logged, same
            # scrubbing discipline as every other real provider in this
            # codebase (Gmail SMTP, Twilio).
            logger.warning("WhatsApp send failed: HTTP %s", exc.code)
            return f"failed: HTTP {exc.code}"
        except urllib.error.URLError as exc:
            logger.warning("WhatsApp send failed: could not reach Graph API (%s)", type(exc.reason).__name__)
            return "failed: could not reach Graph API"

    def send_image_message(
        self,
        *,
        to: str,
        image_bytes: bytes,
        mime_type: str,
        caption: str,
        phone_number_id: str,
        access_token: str = "",
    ) -> str:
        """Real Meta Cloud API image send (Phase 9/resend-QR research,
        confirmed live against Meta's current docs, not assumed): unlike
        email's CID embedding, WhatsApp has no "attach bytes to this
        message" mechanism at all — an image message can only ever reference
        an already-uploaded media id. Two real calls, in order:
        1. `POST /{phone_number_id}/media` (multipart/form-data: `file`,
           `type`, `messaging_product=whatsapp`) -> `{"id": "<media_id>"}`.
        2. `POST /{phone_number_id}/messages` (JSON: `type="image"`,
           `image={"id": "<media_id>", "caption": "..."}`) -- the same send
           endpoint send_message uses, just a different `type`/body shape.
        httpx (already a real dependency, used identically in
        whatsapp_embedded_signup.py) instead of urllib here specifically
        because step 1 needs real multipart/form-data, which urllib has no
        built-in support for. Same graceful-simulation, never-raises, and
        never-log-the-raw-response-body discipline as send_message."""
        token = access_token or settings.whatsapp_access_token
        if not token:
            logger.info("SIMULATED WhatsApp image send to %s (%d bytes, %s)", to, len(image_bytes), mime_type)
            return "simulated — no real WhatsApp access token configured"

        media_url = f"https://graph.facebook.com/{settings.whatsapp_api_version}/{phone_number_id}/media"
        try:
            upload_response = httpx.post(
                media_url,
                headers={"Authorization": f"Bearer {token}"},
                data={"messaging_product": "whatsapp", "type": mime_type},
                files={"file": ("qr.png", image_bytes, mime_type)},
                timeout=_SEND_TIMEOUT_SECONDS,
            )
        except httpx.TransportError as exc:
            logger.warning("WhatsApp media upload failed: could not reach Graph API (%s)", type(exc).__name__)
            return "failed: could not reach Graph API"
        if upload_response.status_code != 200:
            logger.warning("WhatsApp media upload failed: HTTP %s", upload_response.status_code)
            return f"failed: HTTP {upload_response.status_code} on media upload"
        media_id = upload_response.json().get("id")
        if not media_id:
            logger.warning("WhatsApp media upload returned no media id")
            return "failed: media upload returned no id"

        send_url = _SEND_URL_TEMPLATE.format(api_version=settings.whatsapp_api_version, phone_number_id=phone_number_id)
        body = {
            "messaging_product": "whatsapp",
            "recipient_type": "individual",
            "to": to,
            "type": "image",
            "image": {"id": media_id, "caption": caption},
        }
        try:
            send_response = httpx.post(
                send_url,
                headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
                json=body,
                timeout=_SEND_TIMEOUT_SECONDS,
            )
        except httpx.TransportError as exc:
            logger.warning("WhatsApp image send failed: could not reach Graph API (%s)", type(exc).__name__)
            return "failed: could not reach Graph API"
        if send_response.status_code != 200:
            logger.warning("WhatsApp image send failed: HTTP %s", send_response.status_code)
            return f"failed: HTTP {send_response.status_code}"
        message_id = (send_response.json().get("messages") or [{}])[0].get("id")
        return f"sent wamid={message_id}"
