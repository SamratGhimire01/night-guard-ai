"""Real WhatsApp Embedded Signup (Meta's JS-SDK self-serve WABA connect flow) —
a NEW, purely additive way for a business to connect its own WhatsApp Business
Account, alongside (never replacing) Phase 22's manual credential-entry path
(app/services/channels/whatsapp.py, app/services/channels/whatsapp_webhook.py)
and the Dashboard Channel Integration Setup UI phase's hand-typed-config
POST /integrations. None of those three files is touched by this module.

Real, confirmed sequence (Meta's current Embedded Signup docs, checked before
writing this — not assumed from general knowledge) this module implements the
SERVER side of:
  1. The dashboard loads Meta's JS SDK and calls FB.login() with a WhatsApp
     Embedded Signup `config_id`. Meta returns a short-lived (30s)
     authorization `code` to the browser via FB.login's own callback, plus
     the customer's real `waba_id`/`phone_number_id` via a separate
     `window.postMessage` event — neither of those two values is secret.
  2. THIS module exchanges that `code` for a real, permanent business access
     token: GET https://graph.facebook.com/{version}/oauth/access_token
     (client_id/client_secret/code) — Meta's own documented "manually build a
     login flow" contract. No redirect_uri: unlike Phase 40's Google Calendar
     OAuth (a full-page redirect flow), this is the JS SDK's code flow, which
     never leaves the dashboard page.
  3. Subscribes this app to the customer's WABA webhooks so this app's
     existing, UNCHANGED POST /api/v1/webhooks/whatsapp starts receiving
     their messages: POST /{waba_id}/subscribed_apps.
  4. Saves the result through integration_service.save_integration_config —
     the exact same function Phase 40's Google Calendar OAuth callback
     already funnels through, producing the exact same Integration row shape
     (business_id, type="whatsapp", config={phone_number_id, access_token,
     ...}, enabled) that WhatsAppChannelAdapter.send_message and
     whatsapp_webhook.py's _resolve_integration already read. This is the
     literal proof the ticket asked for: a self-serve-connected business's
     credentials work through the existing send/webhook code with zero
     changes to either, because they produce an identical row.

Requires WHATSAPP_EMBEDDED_SIGNUP_APP_ID + WHATSAPP_EMBEDDED_SIGNUP_CONFIG_ID
(new, empty-by-default settings — see app/core/config.py) and reuses the
already-existing WHATSAPP_APP_SECRET (Phase 22) for the token exchange: one
real Meta App, two legitimate uses of its one secret (inbound signature
verification, and this outbound token exchange).
"""

import logging
import uuid

import httpx
from sqlalchemy.orm import Session

from app.core.config import settings
from app.db.models.integration import Integration
from app.services import integration_service

logger = logging.getLogger(__name__)

_OAUTH_TOKEN_URL_TEMPLATE = "https://graph.facebook.com/{api_version}/oauth/access_token"
_SUBSCRIBE_URL_TEMPLATE = "https://graph.facebook.com/{api_version}/{waba_id}/subscribed_apps"
_TIMEOUT_SECONDS = 15
INTEGRATION_TYPE = "whatsapp"


class WhatsAppEmbeddedSignupError(Exception):
    """Raised on any real failure exchanging the signup code or subscribing to
    webhooks. Never includes a raw token/secret in its message — only Meta's
    own error text or an HTTP status, same log-scrubbing discipline as
    GoogleCalendarError (app/services/google_calendar_service.py)."""


def is_configured() -> bool:
    return bool(settings.whatsapp_embedded_signup_app_id and settings.whatsapp_embedded_signup_config_id)


def _extract_meta_error(response: httpx.Response) -> str:
    try:
        body = response.json()
        return (body.get("error") or {}).get("message") or f"HTTP {response.status_code}"
    except ValueError:
        return f"HTTP {response.status_code}"


def _exchange_code_for_token(code: str) -> str:
    try:
        response = httpx.get(
            _OAUTH_TOKEN_URL_TEMPLATE.format(api_version=settings.whatsapp_api_version),
            params={
                "client_id": settings.whatsapp_embedded_signup_app_id,
                "client_secret": settings.whatsapp_app_secret,
                "code": code,
            },
            timeout=_TIMEOUT_SECONDS,
        )
    except httpx.TransportError as exc:
        raise WhatsAppEmbeddedSignupError(f"token exchange transport error: {type(exc).__name__}") from None
    if response.status_code != 200:
        raise WhatsAppEmbeddedSignupError(f"token exchange failed: {_extract_meta_error(response)}")
    access_token = response.json().get("access_token")
    if not access_token:
        raise WhatsAppEmbeddedSignupError("Meta did not return an access token.")
    return access_token


def _subscribe_app_to_waba(waba_id: str, access_token: str) -> None:
    try:
        response = httpx.post(
            _SUBSCRIBE_URL_TEMPLATE.format(api_version=settings.whatsapp_api_version, waba_id=waba_id),
            headers={"Authorization": f"Bearer {access_token}"},
            timeout=_TIMEOUT_SECONDS,
        )
    except httpx.TransportError as exc:
        raise WhatsAppEmbeddedSignupError(f"webhook subscription transport error: {type(exc).__name__}") from None
    if response.status_code != 200:
        raise WhatsAppEmbeddedSignupError(f"webhook subscription failed: {_extract_meta_error(response)}")


def complete_embedded_signup(
    db: Session, *, business_id: uuid.UUID, code: str, waba_id: str, phone_number_id: str
) -> Integration:
    """Real code-for-token exchange + real webhook subscription, then stores
    the result through the SAME shared Integration upsert Phase 40's Google
    Calendar OAuth callback and the manual-entry dashboard form both already
    use. Raises WhatsAppEmbeddedSignupError on any real failure; the route is
    responsible for turning that into a clean 422, never a raw 500."""
    access_token = _exchange_code_for_token(code)
    _subscribe_app_to_waba(waba_id, access_token)

    config = {"phone_number_id": phone_number_id, "access_token": access_token, "waba_id": waba_id}
    return integration_service.save_integration_config(
        db, business_id=business_id, type_=INTEGRATION_TYPE, config=config, enabled=True
    )
