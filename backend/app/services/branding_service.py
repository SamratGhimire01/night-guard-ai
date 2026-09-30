"""Business logo upload and website-widget settings.

The logo is stored in the business row (bytes + content type) and served publicly by GET /api/v1/widget/{id}/logo, so
the widget on a customer's website and the dashboard both load it from the same place. Only raster formats are
accepted (PNG, JPEG, WebP), checked by their file signature rather than the name or the browser's claimed type: an SVG
could carry script, and it would be served from our own origin."""

import hashlib
import uuid
from datetime import UTC, datetime
from urllib.parse import urlparse

from sqlalchemy.orm import Session
from sqlalchemy.orm.attributes import flag_modified

from app.core.config import settings
from app.core.exceptions import PayloadTooLargeError, UnsupportedMediaTypeError
from app.db.models.business import Business
from app.schemas.widget import WidgetSettings

MAX_LOGO_BYTES = 1024 * 1024


def _sniff_image_type(raw: bytes) -> str | None:
    if raw.startswith(b"\x89PNG\r\n\x1a\n"):
        return "image/png"
    if raw.startswith(b"\xff\xd8\xff"):
        return "image/jpeg"
    if raw[:4] == b"RIFF" and raw[8:12] == b"WEBP":
        return "image/webp"
    return None


def logo_path(business_id: uuid.UUID) -> str:
    return f"/api/v1/widget/{business_id}/logo"


def set_logo(db: Session, *, business_id: uuid.UUID, raw: bytes) -> Business:
    if len(raw) > MAX_LOGO_BYTES:
        raise PayloadTooLargeError("The logo must be 1 MB or smaller.")
    content_type = _sniff_image_type(raw)
    if content_type is None:
        raise UnsupportedMediaTypeError("Upload a PNG, JPG or WebP image.")
    business = db.get(Business, business_id)
    business.logo_image = raw
    business.logo_content_type = content_type
    # A new version string on every upload, so browsers and the widget never keep showing a cached old logo.
    business.logo_url = f"{logo_path(business_id)}?v={hashlib.sha256(raw).hexdigest()[:12]}"
    db.commit()
    db.refresh(business)
    return business


def clear_logo(db: Session, *, business_id: uuid.UUID) -> Business:
    business = db.get(Business, business_id)
    business.logo_image = None
    business.logo_content_type = None
    business.logo_url = None
    db.commit()
    db.refresh(business)
    return business


def get_widget_settings(business: Business) -> WidgetSettings:
    # Unknown keys (from an older or newer version of the settings) are ignored rather than failing the widget.
    known = {k: v for k, v in (business.widget_settings or {}).items() if k in WidgetSettings.model_fields}
    return WidgetSettings(**known)


def update_widget_settings(db: Session, *, business_id: uuid.UUID, payload: WidgetSettings) -> WidgetSettings:
    business = db.get(Business, business_id)
    business.widget_settings = payload.model_dump()
    flag_modified(business, "widget_settings")
    db.commit()
    db.refresh(business)
    return get_widget_settings(business)


def note_widget_origin(db: Session, *, business: Business, origin: str | None) -> None:
    """Records the first real website the chat loads on. The dashboard preview runs in a sandboxed frame (origin
    "null") and the dashboard itself is excluded, so only a genuine embed counts. Written once, never again."""
    if business.widget_installed_at is not None or not origin or origin == "null":
        return
    dashboard_origins = {o.strip().rstrip("/") for o in settings.dashboard_cors_origins.split(",") if o.strip()}
    dashboard_origins.add(settings.dashboard_base_url.rstrip("/"))
    parsed = urlparse(origin)
    if origin.rstrip("/") in dashboard_origins or parsed.scheme not in ("http", "https") or not parsed.hostname:
        return
    business.widget_installed_at = datetime.now(UTC)
    business.widget_installed_origin = origin[:255]
    db.commit()
