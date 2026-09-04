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

    def send(self, *, to: str, subject: str, body: str) -> str:
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
            raise NotificationDeliveryError(
                f"{type(exc).__name__}: transient SMTP failure", transient=True
            ) from None
        except OSError as exc:
            # Connection refused / timeout / DNS failure reaching smtp.gmail.com.
            raise NotificationDeliveryError(
                f"{type(exc).__name__}: could not reach SMTP host", transient=True
            ) from None
