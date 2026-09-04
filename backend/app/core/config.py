from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Application settings, loaded from environment variables / .env file."""

    app_name: str = "Night Guard AI"
    environment: str = "development"
    log_level: str = "INFO"

    database_url: str
    secret_key: str
    jwt_algorithm: str = "HS256"
    access_token_expire_minutes: int = 30

    azure_openai_api_key: str = ""
    azure_openai_endpoint: str = ""
    azure_openai_deployment: str = ""
    azure_openai_embedding_deployment: str = ""
    azure_openai_api_version: str = "2024-05-01-preview"

    # Gmail SMTP — the real EmailNotificationProvider (app/services/notifications/).
    # Empty by default: the provider treats missing credentials as a real,
    # non-retryable send failure rather than crashing at import time.
    gmail_address: str = ""
    gmail_app_password: str = ""

    # Twilio SMS (app/services/notifications/sms_provider.py). Empty by default:
    # the dispatch service falls back to the safe Phase 13 stub (SIMULATED,
    # never a real send) whenever any of these three is missing, regardless of
    # a business's sms_enabled flag.
    twilio_account_sid: str = ""
    twilio_auth_token: str = ""
    twilio_from_number: str = ""

    # WhatsApp Cloud API (app/services/channels/whatsapp.py). Empty by default —
    # no production Meta Business account/credentials exist yet (Phase 22).
    # whatsapp_app_secret: verifies X-Hub-Signature-256 on every inbound webhook —
    #   an empty value makes verification always fail closed (never "no secret
    #   configured, so skip verification").
    # whatsapp_verify_token: our own arbitrary string, compared against Meta's
    #   hub.verify_token on the GET handshake — this is a value WE choose and
    #   register in the Meta App Dashboard, not one Meta issues to us.
    # whatsapp_access_token: the real Send API bearer token. Empty by default:
    #   WhatsAppChannelAdapter.send_message falls back to a safe, logged
    #   simulation whenever this is missing — same graceful-fallback discipline
    #   as Phase 15's SMSNotificationProvider stub.
    whatsapp_app_secret: str = ""
    whatsapp_verify_token: str = ""
    whatsapp_access_token: str = ""
    whatsapp_api_version: str = "v20.0"

    # Messenger Platform (app/services/channels/messenger.py). Empty by default —
    # no production Meta Page/App exists yet (Phase 26), same honest gap as
    # WhatsApp. messenger_app_secret/messenger_verify_token play the identical
    # role as their WhatsApp counterparts (Meta's webhook signature/handshake
    # mechanism is genuinely the same across both products — see
    # meta_webhook_signature.py). UNLIKE WhatsApp there is no
    # messenger_access_token setting: Messenger's Send API is authenticated
    # per-Page (a Page Access Token from OAuth), not one platform-wide token —
    # that lives in each business's own Integration.config["page_access_token"].
    messenger_app_secret: str = ""
    messenger_verify_token: str = ""
    messenger_api_version: str = "v20.0"

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )


settings = Settings()
