import smtplib
from email.message import EmailMessage

from app.core.config import settings
from app.services.notifications.base import NotificationDeliveryError, NotificationProvider

_SMTP_HOST = "smtp.gmail.com"
_SMTP_PORT = 587

# Retrying these never helps: the server rejected who/what we sent, not a
# transient network condition.
_PERMANENT_SMTP_ERRORS = (
    smtplib.SMTPAuthenticationError,
    smtplib.SMTPRecipientsRefused,
    smtplib.SMTPSenderRefused,
)


class EmailNotificationProvider(NotificationProvider):
    """Real email via Gmail SMTP — smtplib (stdlib, no new dependency),
    authenticating as GMAIL_ADDRESS with GMAIL_APP_PASSWORD from settings."""

    def send(
        self,
        *,
        to: str,
        subject: str,
        body: str,
        html_body: str | None = None,
        attachments: list[tuple[str, bytes, str]] | None = None,
        inline_images: list[tuple[str, bytes, str]] | None = None,
    ) -> str:
        """`html_body` (Phase 17, email-only — same status as `attachments`
        below, not part of the shared NotificationProvider interface): when
        given, the message becomes a real multipart/alternative — `body`
        (plain text) stays the primary part via set_content, `html_body` is
        added via add_alternative, so every client that can't/won't render
        HTML still gets the plain-text version. `attachments` (Phase 16,
        email-only — not part of the shared NotificationProvider interface
        other channels implement, and never passed by dispatch_service's
        generic per-channel retry loop for ordinary appointment
        notifications): a list of (filename, content_bytes, mime_type), e.g.
        for the daily report's .xlsx.

        `inline_images` (Phase 46, email-only, same status as `attachments`):
        a list of (content_id, content_bytes, mime_type) — real images
        referenced by the HTML body as `cid:<content_id>` (RFC 2392), e.g.
        the check-in QR code. Real bug this replaces (see PHASE_STATUS.md):
        a base64 `data:` URI image never actually renders in a real Gmail
        inbox, even though the raw HTML contains a genuinely valid,
        independently-decodable image — Gmail simply refuses to display
        `data:` URIs at all. CID embedding is the correct, standard,
        universally-supported fix. Requires `html_body` to mean anything —
        attached to THAT part specifically (via `add_related`, which
        promotes it to `multipart/related`), not to the top-level message,
        which is what makes `cid:` resolution work in every real mail
        client. EmailMessage's high-level API handles the real resulting
        `multipart/mixed(multipart/alternative(text, multipart/related(html,
        image)), attachment)` nesting automatically."""
        if not settings.gmail_address or not settings.gmail_app_password:
            raise NotificationDeliveryError(
                "GMAIL_ADDRESS/GMAIL_APP_PASSWORD are not configured.", transient=False
            )
        if not to:
            raise NotificationDeliveryError("No recipient email address on file.", transient=False)

        message = EmailMessage()
        message["From"] = settings.gmail_address
        message["To"] = to
        message["Subject"] = subject
        message.set_content(body)
        if html_body:
            message.add_alternative(html_body, subtype="html")
            if inline_images:
                html_part = message.get_payload()[-1]
                for content_id, content, mime_type in inline_images:
                    maintype, _, subtype = mime_type.partition("/")
                    html_part.add_related(
                        content, maintype=maintype, subtype=subtype or "octet-stream", cid=f"<{content_id}>"
                    )
        for filename, content, mime_type in attachments or []:
            maintype, _, subtype = mime_type.partition("/")
            message.add_attachment(content, maintype=maintype, subtype=subtype or "octet-stream", filename=filename)

        try:
            with smtplib.SMTP(_SMTP_HOST, _SMTP_PORT, timeout=15) as smtp:
                smtp.starttls()
                smtp.login(settings.gmail_address, settings.gmail_app_password)
                refused = smtp.send_message(message)
                if refused:
                    # send_message only returns non-empty here on a *partial*
                    # refusal across multiple recipients; this provider always
                    # sends to exactly one, so this path is defensive, not expected.
                    raise NotificationDeliveryError(f"Recipient refused: {refused}", transient=False)
                return "250 message accepted for delivery"
        except _PERMANENT_SMTP_ERRORS as exc:
            # Never log/store exc's raw args here: extend the same scrubbing
            # discipline as the Azure endpoint leak (app/core/logging.py) to SMTP
            # auth — log only the exception class, never the server's raw
            # response text from the AUTH exchange.
            raise NotificationDeliveryError(
                f"{type(exc).__name__}: permanent SMTP failure", transient=False
            ) from None
        except smtplib.SMTPException as exc:
            # Unlike _PERMANENT_SMTP_ERRORS above, this isn't the AUTH
            # exchange -- exc's args are the server's real DATA/response text
            # (e.g. "550 5.4.5 Daily user sending limit exceeded"), not
            # credential material, so it's safe and genuinely useful to keep.
            raise NotificationDeliveryError(
                f"{type(exc).__name__}: transient SMTP failure ({exc})", transient=True
            ) from None
        except OSError as exc:
            # Connection refused / timeout / DNS failure reaching smtp.gmail.com.
            raise NotificationDeliveryError(
                f"{type(exc).__name__}: could not reach SMTP host", transient=True
            ) from None
