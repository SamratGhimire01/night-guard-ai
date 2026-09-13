import io

import qrcode

# A fixed Content-ID for the check-in QR image in any one email — safe to
# reuse across different emails since a Content-ID only needs to be unique
# WITHIN a single MIME message, never globally.
QR_CONTENT_ID = "checkin-qrcode"


def generate_qr_png(data: str) -> bytes:
    """A real QR code encoding `data`, as raw PNG bytes — meant to be
    embedded as a real inline (Content-ID) MIME part, NOT a base64 `data:`
    URI. Real bug found via live Gmail testing (see PHASE_STATUS.md): Gmail
    does not render `data:` URI images in HTML mail at all — this is
    longstanding, well-documented Gmail behavior, not an edge case; the
    earlier `data:` URI approach LOOKED correct (the raw HTML genuinely
    contained a valid, decodable image) but never actually displayed to a
    real recipient. CID embedding (RFC 2392) is the standard, universally-
    supported mechanism used here instead — see
    EmailNotificationProvider.send's `inline_images` parameter. `qrcode`
    (pure Python, Pillow for the actual PNG render) — no external
    QR-generation service."""
    image = qrcode.make(data)
    buffer = io.BytesIO()
    image.save(buffer, format="PNG")
    return buffer.getvalue()
