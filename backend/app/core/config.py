from pydantic import field_validator
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
    # Reasoning effort sent with every chat completion (gpt-5-family reasoning models). "low" roughly halves reply latency with
    # no measurable quality loss (PHASE_STATUS.md, Phase 17). "default" (or empty) sends nothing = the deployment's own default
    # (medium): the one-env-var rollback, AZURE_OPENAI_REASONING_EFFORT=default.
    azure_openai_reasoning_effort: str = "low"

    @field_validator("azure_openai_reasoning_effort")
    @classmethod
    def _valid_reasoning_effort(cls, value: str) -> str:
        # An unsupported value makes Azure answer HTTP 400 on EVERY chat call, so a typo here must fail at startup, not at the
        # first customer message.
        if value.strip().lower() not in {"", "default", "minimal", "low", "medium", "high", "xhigh"}:
            raise ValueError("AZURE_OPENAI_REASONING_EFFORT must be one of: default, minimal, low, medium, high, xhigh")
        return value

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

    # WhatsApp Embedded Signup (app/services/channels/whatsapp_embedded_signup.py).
    # A NEW, purely additive self-serve connect option alongside the manual
    # phone_number_id/access_token entry above — neither this nor the manual
    # path is removed; a business owner picks whichever applies to them. Empty
    # by default, same honest "no production Meta Tech Provider approval yet"
    # gap as every other Meta credential in this file: the dashboard hides the
    # "Connect WhatsApp (self-serve)" button until both are set.
    # whatsapp_embedded_signup_app_id: the Meta App ID — public by nature (it's
    #   passed to the client-side JS SDK's FB.init(), never a secret).
    # whatsapp_embedded_signup_config_id: the Facebook Login for Business
    #   configuration ID (create one from the "WhatsApp Embedded Signup
    #   Configuration" template in the Meta App Dashboard) — also passed
    #   client-side, also not a secret.
    # The actual secret this flow needs server-side for the code-for-token
    # exchange is whatsapp_app_secret above — already exists (Phase 22), reused
    # here rather than duplicated, since it's the same Meta App's one secret.
    whatsapp_embedded_signup_app_id: str = ""
    whatsapp_embedded_signup_config_id: str = ""

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

    # eSewa ePay v2 + Khalti ePayment (Phase 44, Premium payment collection).
    # Platform-wide credentials, same pattern as Twilio above — Night Guard AI
    # itself is the merchant of record for every business's payment
    # collection (a business picks WHICH of these two gateways to use via
    # Business.payment_provider, not its own separate merchant account).
    # esewa_* defaults are eSewa's own publicly documented UAT sandbox
    # credentials (developer.esewa.com.np) — safe to commit, not a real
    # secret. khalti_secret_key has no safe public default (Khalti requires a
    # real sandbox signup at test-admin.khalti.com even for testing) so it's
    # empty until a real key is provided.
    esewa_product_code: str = "EPAYTEST"
    esewa_secret_key: str = "8gBm/:&EnhH.1/q"
    esewa_base_url: str = "https://rc-epay.esewa.com.np"
    esewa_status_check_base_url: str = "https://rc.esewa.com.np"
    khalti_secret_key: str = ""
    khalti_base_url: str = "https://dev.khalti.com"

    # This backend's own public base URL — where eSewa/Khalti redirect the
    # customer's browser back to after payment, and where a real payment link
    # sent to a customer points. Unlike dashboard_base_url (the SPA), this is
    # never used for an authenticated dashboard redirect.
    backend_base_url: str = "http://localhost:8010"

    # Phase 45: how often the in-process reminder scheduler (app/services/
    # scheduler.py) polls for due reminders. 60s in production; override to
    # a short value only for a real, timed live-verification run (never left
    # short in committed config).
    reminder_poll_interval_seconds: int = 60

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
