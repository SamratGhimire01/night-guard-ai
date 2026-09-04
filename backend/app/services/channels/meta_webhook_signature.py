import hashlib
import hmac

_SIGNATURE_PREFIX = "sha256="


def verify_signature(*, app_secret: str, raw_body: bytes, signature_header: str | None) -> bool:
    """Real Meta webhook verification: X-Hub-Signature-256 is
    `"sha256=" + hex(HMAC-SHA256(app_secret, raw_request_body))`. This exact
    mechanism is genuinely shared across every Meta Graph API webhook product
    (WhatsApp Cloud API, Messenger Platform, Instagram) — all signed with the
    consuming Meta App's own App Secret — so it lives here once and is reused
    by whatsapp_webhook.py and messenger_webhook.py rather than being
    duplicated per channel (Phase 22 originally defined this inside
    whatsapp_webhook.py; Phase 26 extracted it here since Messenger needs the
    identical check against its own app secret).

    Verified against the RAW bytes (never a re-serialized/re-parsed JSON body
    — key ordering/whitespace could differ from what Meta actually signed)
    using a constant-time comparison. An empty app_secret or missing/malformed
    header always fails closed — never "no secret configured, so skip
    verification."
    """
    if not app_secret or not signature_header or not signature_header.startswith(_SIGNATURE_PREFIX):
        return False
    expected = hmac.new(app_secret.encode("utf-8"), raw_body, hashlib.sha256).hexdigest()
    provided = signature_header[len(_SIGNATURE_PREFIX) :]
    return hmac.compare_digest(expected, provided)
