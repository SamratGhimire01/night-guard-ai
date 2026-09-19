import uuid
from typing import Literal

from pydantic import BaseModel, ConfigDict, model_validator

from app.schemas.common import safe_str

# Which config keys each channel's webhook resolver/sender actually reads —
# see messenger_webhook.py/instagram_webhook.py/whatsapp_webhook.py's
# _resolve_integration and the adapters' send_message docstrings. Keeping
# this here (not in the DB) since config is a free-form JSONB column and this
# is the one place validating what a given `type` requires before it's saved.
_REQUIRED_CONFIG_KEYS: dict[str, set[str]] = {
    "whatsapp": {"phone_number_id", "access_token"},
    "messenger": {"page_id", "page_access_token"},
    "instagram": {"ig_account_id", "access_token"},
}

# Which of the required keys above are secrets that must never be echoed back
# in an API response once saved — same write-only posture as a password
# field. IntegrationRead.redact_secrets strips these before serializing.
_SECRET_CONFIG_KEYS: dict[str, set[str]] = {
    "whatsapp": {"access_token"},
    "messenger": {"page_access_token"},
    "instagram": {"access_token"},
}


class IntegrationUpsert(BaseModel):
    """POST body — creates this business's integration for `type` if none
    exists yet, otherwise replaces its config/enabled (see
    integration_service.upsert_integration)."""

    type: Literal["whatsapp", "messenger", "instagram"]
    config: dict[str, safe_str(500)]
    enabled: bool = True

    @model_validator(mode="after")
    def config_has_required_keys(self) -> "IntegrationUpsert":
        required = _REQUIRED_CONFIG_KEYS[self.type]
        missing = [key for key in sorted(required) if not self.config.get(key)]
        if missing:
            raise ValueError(f"config for type={self.type!r} is missing required key(s): {missing}")
        return self


class IntegrationRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    type: str
    config: dict
    enabled: bool

    @model_validator(mode="after")
    def redact_secrets(self) -> "IntegrationRead":
        """No integration's real secret ever comes back out of this API,
        write-only like a password field. Phase 40: google_calendar's config
        holds real OAuth access/refresh tokens, handled as a special case
        (only calendar_id is non-secret). Dashboard channel-connect phase:
        whatsapp/messenger/instagram each hold one real bearer token in
        `config` (see _SECRET_CONFIG_KEYS) — stripped the same way, whatever
        route returns an IntegrationRead (this generic list/upsert response
        included)."""
        if self.type == "google_calendar":
            self.config = {"calendar_id": self.config.get("calendar_id")}
            return self
        secret_keys = _SECRET_CONFIG_KEYS.get(self.type)
        if secret_keys:
            self.config = {k: v for k, v in self.config.items() if k not in secret_keys}
        return self


class IntegrationTestResult(BaseModel):
    """POST /integrations/{type}/test-connection response — a real, lightweight
    Meta Graph API GET using this business's own saved credentials (see
    integration_service.test_connection). `detail` is safe to show a user:
    it's either Meta's own error message or a short success summary, never
    the access token itself."""

    ok: bool
    detail: str


class WhatsAppEmbeddedSignupConfig(BaseModel):
    """GET /integrations/whatsapp/embedded-signup/config response — lets the
    dashboard decide whether to show the self-serve "Connect WhatsApp" button
    at all. `app_id`/`config_id` are not secrets (both are passed to the
    client-side Meta JS SDK by design); `configured=False` means the platform
    hasn't set WHATSAPP_EMBEDDED_SIGNUP_APP_ID/_CONFIG_ID yet, in which case
    the dashboard should hide the button and fall back to the manual fields."""

    configured: bool
    app_id: str
    config_id: str
    api_version: str


class WhatsAppEmbeddedSignupComplete(BaseModel):
    """POST /integrations/whatsapp/embedded-signup body — the three real
    values Meta's Embedded Signup hands back to the browser (see
    app/services/channels/whatsapp_embedded_signup.py's module docstring for
    the full flow). `code` is a real, short-lived (30s) authorization code,
    never a long-lived credential itself."""

    code: safe_str(2000)
    waba_id: safe_str(64)
    phone_number_id: safe_str(64)
