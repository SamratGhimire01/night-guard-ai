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

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )


settings = Settings()
