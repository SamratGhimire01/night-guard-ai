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

    # Phase 35 — the business dashboard SPA runs on its own origin (Vite dev
    # server) and calls this API with a bearer token, not cookies, so this is
    # ordinary CORS (not the widget's separate wildcard policy in
    # widget_cors.py, which serves arbitrary third-party embed sites).
    # Comma-separated; kept narrow (dashboard dev origins only) rather than "*".
    dashboard_cors_origins: str = "http://localhost:5173,http://localhost:4173"

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

    # Instagram Messaging (app/services/channels/instagram.py). Empty by default —
    # no production Meta Instagram professional account exists yet (Phase 27), same
    # honest gap as WhatsApp/Messenger. instagram_app_secret/instagram_verify_token
    # play the identical role as their WhatsApp/Messenger counterparts (the webhook
    # signature/handshake mechanism is genuinely the same across all three products —
    # see meta_webhook_signature.py). Like Messenger, there is no
    # instagram_access_token setting: each Instagram professional account has its
    # own access token, obtained per-account — that lives in each business's own
    # Integration.config["access_token"], not here.
    instagram_app_secret: str = ""
    instagram_verify_token: str = ""
    instagram_api_version: str = "v20.0"

    # Google Calendar OAuth (app/services/google_calendar_service.py, Phase 40).
    # Empty by default — no real Google Cloud OAuth client exists until configured.
    # google_redirect_uri must be registered VERBATIM (exact string match) as an
    # Authorized redirect URI on that OAuth client, and must equal wherever
    # app/api/routes/google_calendar.py's callback route is actually reachable —
    # see PHASE_STATUS.md Phase 40 for the exact Cloud Console steps.
    google_client_id: str = ""
    google_client_secret: str = ""
    google_redirect_uri: str = ""

    # Phase 40: the callback redirects the user's browser back to the dashboard
    # SPA (not this API) after a real Google consent flow completes.
    dashboard_base_url: str = "http://localhost:5173"

    # Phase 39: real multi-LLM provider selection. USING_LLM picks which
    # ChatProvider app/llm/__init__.py's get_chat_provider() returns -- "azure"
    # (default), "grok"/"xai", or "groq". Embeddings stay on Azure regardless
    # of this setting -- neither xAI nor Groq offers an embeddings API this
    # phase (see app/llm/__init__.py).
    using_llm: str = "azure"
    xai_api_key: str = ""
    xai_endpoint: str = "https://api.x.ai/v1"
    xai_chat_model: str = "grok-4"
    # Groq (api.groq.com, fast inference for open-weight models) -- a
    # DIFFERENT company/product from xAI's "Grok" above despite the
    # near-identical name; real model catalog confirmed via GET
    # {groq_endpoint}/models (see PHASE_STATUS.md Phase 39).
    groq_api_key: str = ""
    groq_endpoint: str = "https://api.groq.com/openai/v1"
    groq_chat_model: str = "openai/gpt-oss-120b"

    # Deepgram (pre-recorded/batch speech-to-text for the widget's
    # push-to-talk voice input, app/voice/deepgram.py, Phase 43h). Empty by
    # default: app/voice/deepgram.py raises a clear, caught error (never a
    # crash) if a voice message is sent with no key configured.
    deepgram_api_key: str = ""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )


settings = Settings()
