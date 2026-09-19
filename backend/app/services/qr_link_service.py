"""Signed, expiring links to the QR page (`GET /qr/{token}`, app/api/routes/qr_view.py) — the "QR in chat" delivery for
a resend request. A plain https link works identically on WhatsApp, Messenger, Instagram and the website widget (each
just carries the same text; the Meta Media API image-upload flow is deliberately NOT used).

Why a signed token instead of putting the check-in token in the URL: the check-in token is the secret the QR itself
encodes (Phase 46). This link names only the appointment id, an expiry, and an HMAC over both (keyed by the app's
SECRET_KEY, domain-separated with a "qr-view:" prefix so a signature can never be replayed as anything else), so:
  * the link cannot be forged or edited to point at another appointment (a tampered id fails the HMAC),
  * it expires (scheduled time + 24h, never sooner than an hour from issue),
  * the URL never contains the check-in secret; the page only reveals the QR while the link is valid and the
    appointment is still CONFIRMED/ARRIVED.
Stateless on purpose: no new column/migration, and rotating SECRET_KEY revokes every outstanding link."""
import base64
import hashlib
import hmac
import time
import uuid
from datetime import datetime, timedelta

from app.core.config import settings

_LINK_GRACE_AFTER_APPOINTMENT = timedelta(hours=24)
_MIN_LINK_LIFETIME_SECONDS = 3600
_SIGNATURE_BYTES = 16  # 128-bit truncated HMAC-SHA256


def _sign(payload: str) -> str:
    digest = hmac.new(settings.secret_key.encode(), f"qr-view:{payload}".encode(), hashlib.sha256).digest()
    return base64.urlsafe_b64encode(digest[:_SIGNATURE_BYTES]).decode().rstrip("=")


def make_token(appointment_id: uuid.UUID, scheduled_at: datetime, *, now: float | None = None) -> str:
    now = time.time() if now is None else now
    expires = int(max((scheduled_at + _LINK_GRACE_AFTER_APPOINTMENT).timestamp(), now + _MIN_LINK_LIFETIME_SECONDS))
    payload = f"{appointment_id.hex}.{expires}"
    return f"{payload}.{_sign(payload)}"


def verify_token(token: str, *, now: float | None = None) -> uuid.UUID | None:
    """The appointment id if `token` is authentic and unexpired; None for anything else (malformed, forged, expired) —
    callers must treat all of those identically so the response is never an oracle."""
    now = time.time() if now is None else now
    parts = token.split(".")
    if len(parts) != 3 or len(parts[0]) != 32 or not parts[1].isdigit():
        return None
    payload = f"{parts[0]}.{parts[1]}"
    if not hmac.compare_digest(_sign(payload), parts[2]):
        return None
    if int(parts[1]) <= now:
        return None
    try:
        return uuid.UUID(hex=parts[0])
    except ValueError:
        return None


def build_url(appointment_id: uuid.UUID, scheduled_at: datetime) -> str:
    return f"{settings.backend_base_url.rstrip('/')}/qr/{make_token(appointment_id, scheduled_at)}"


def mask_email(email: str) -> str:
    """"jordan@example.com" -> "j***@example.com": confirms WHICH on-file address a resend went to without echoing it."""
    local, _, domain = email.partition("@")
    return f"{local[:1]}***@{domain}" if domain else "***"

