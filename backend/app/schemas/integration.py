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
    "whatsapp": {"phone_number_id"},
    "messenger": {"page_id", "page_access_token"},
    "instagram": {"ig_account_id", "access_token"},
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
