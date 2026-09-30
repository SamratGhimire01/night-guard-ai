"""Startup checks for a production deployment (ENVIRONMENT=production).

Critical problems stop the app from starting, because running with them would be unsafe (anyone could forge a login
token with a weak SECRET_KEY; a wildcard dashboard CORS origin lets any site call the API with a stolen token). Risky
but legitimate choices (still on the eSewa/Khalti sandbox, links pointing at a tunnel) are logged loudly instead, so
the operator sees them in the first lines of the log."""

import logging
from urllib.parse import urlparse

from app.core.config import Settings

logger = logging.getLogger(__name__)

_DEV_HOSTS = ("localhost", "127.0.0.1", "0.0.0.0")
_WEAK_MARKERS = ("change", "secret", "example", "test", "dev")


class UnsafeProductionConfig(RuntimeError):
    pass


def _dev_url(url: str) -> bool:
    host = (urlparse(url).hostname or "").lower()
    return host in _DEV_HOSTS or host.endswith((".ngrok-free.app", ".ngrok-free.dev", ".ngrok.app", ".ngrok.io"))


def problems(settings: Settings) -> tuple[list[str], list[str]]:
    """(critical, warnings) for this configuration. Empty lists outside production."""
    if settings.environment != "production":
        return [], []
    critical, warnings = [], []
    key = settings.secret_key or ""
    if len(key) < 32 or any(m in key.lower() for m in _WEAK_MARKERS):
        critical.append("SECRET_KEY must be a random value of at least 32 characters (e.g. `openssl rand -hex 32`).")
    origins = [o.strip() for o in settings.dashboard_cors_origins.split(",") if o.strip()]
    if not origins or "*" in origins:
        critical.append("DASHBOARD_CORS_ORIGINS must list your dashboard's exact https origin, not '*'.")
    elif any(_dev_url(o) or not o.startswith("https://") for o in origins):
        warnings.append(f"DASHBOARD_CORS_ORIGINS includes a non-https or local origin: {settings.dashboard_cors_origins}")
    for name in ("dashboard_base_url", "backend_base_url"):
        value = getattr(settings, name)
        if _dev_url(value) or not value.startswith("https://"):
            warnings.append(f"{name.upper()} is {value!r}; customer links (emails, QR codes, payments) need a public https domain.")
    if "rc-epay" in settings.esewa_base_url or settings.esewa_product_code == "EPAYTEST":
        warnings.append("eSewa is on its test sandbox (ESEWA_BASE_URL / ESEWA_PRODUCT_CODE); real deposits won't be collected.")
    if "dev.khalti" in settings.khalti_base_url:
        warnings.append("Khalti is on its test sandbox (KHALTI_BASE_URL); real deposits won't be collected.")
    if not settings.gmail_address or not settings.gmail_app_password:
        warnings.append("No platform email (GMAIL_ADDRESS / GMAIL_APP_PASSWORD): password resets and alerts can't be sent.")
    return critical, warnings


def enforce(settings: Settings) -> None:
    critical, warnings = problems(settings)
    for w in warnings:
        logger.warning("production config: %s", w)
    if critical:
        for c in critical:
            logger.critical("production config: %s", c)
        raise UnsafeProductionConfig("Refusing to start: " + " ".join(critical))
