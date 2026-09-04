import base64
import json
import logging
import urllib.error
import urllib.parse
import urllib.request

from app.core.config import settings
from app.services.notifications.base import NotificationDeliveryError, NotificationProvider

logger = logging.getLogger(__name__)


class SMSNotificationProvider(NotificationProvider):
    """Stub — used whenever real Twilio credentials aren't configured (see
    TwilioSMSProvider below), regardless of a business's sms_enabled flag.
    Never contacts a real carrier/gateway. Logs what it would have sent and
    always reports success as *simulated*; the dispatch service marks the
    Notification SIMULATED (never SENT/DELIVERED) for exactly this reason, so
    nothing here can be mistaken for proof a text message actually reached
    anyone."""

    SIMULATED = True

    def send(self, *, to: str, subject: str, body: str) -> str:
        logger.info("SIMULATED SMS to %s: %s", to or "<no phone on file>", subject)
        return "simulated — no real SMS gateway configured"


_API_URL = "https://api.twilio.com/2010-04-01/Accounts/{sid}/Messages.json"
_TIMEOUT_SECONDS = 15
# Twilio HTTP statuses that mean "retrying this exact request won't help"
# (bad/unverified number, bad auth, malformed request) vs anything else
# (5xx, 429 rate limit) treated as transient.
_PERMANENT_HTTP_STATUSES = {400, 401, 403}


def _normalize_phone(phone: str) -> str:
    # ponytail: naive US-only E.164 heuristic (10 digits -> +1########);
    # anything already starting with "+" is trusted as-is. Extend with a real
    # phone-number library (e.g. phonenumbers) if international customers
    # arrive and this stops being good enough.
    digits = "".join(ch for ch in phone if ch.isdigit())
    if phone.strip().startswith("+"):
        return "+" + digits
    if len(digits) == 10:
        return "+1" + digits
    return "+" + digits


class TwilioSMSProvider(NotificationProvider):
    """Real SMS via Twilio's REST API, called directly over HTTPS with
    urllib (stdlib) rather than adding the `twilio` SDK dependency for what's
    a single POST. Only ever constructed by dispatch_service when
    TWILIO_ACCOUNT_SID/TWILIO_AUTH_TOKEN/TWILIO_FROM_NUMBER are all present."""

    def send(self, *, to: str, subject: str, body: str) -> str:
        if not to:
            raise NotificationDeliveryError("No phone number on file.", transient=False)

        url = _API_URL.format(sid=settings.twilio_account_sid)
        data = urllib.parse.urlencode(
            {"To": _normalize_phone(to), "From": settings.twilio_from_number, "Body": body}
        ).encode()
        auth = base64.b64encode(
            f"{settings.twilio_account_sid}:{settings.twilio_auth_token}".encode()
        ).decode()
        request = urllib.request.Request(
            url, data=data, headers={"Authorization": f"Basic {auth}"}, method="POST"
        )
        try:
            with urllib.request.urlopen(request, timeout=_TIMEOUT_SECONDS) as response:
                payload = json.loads(response.read())
                # Twilio's synchronous response only confirms it ACCEPTED the
                # message (status usually "queued"/"accepted") — not that a
                # carrier delivered it. No delivery-status webhook is wired up
                # in this simple setup, so this is the real ceiling of what we
                # can honestly confirm (mirrors the email provider's SMTP "250
                # accepted" ceiling — see dispatch_service's SENT terminal state).
                return f"twilio accepted sid={payload.get('sid')} status={payload.get('status')}"
        except urllib.error.HTTPError as exc:
            # Never log exc's raw response body: Twilio error payloads can echo
            # back request details; only the HTTP status/class is logged, same
            # scrubbing discipline as the Gmail SMTP provider.
            transient = exc.code not in _PERMANENT_HTTP_STATUSES
            raise NotificationDeliveryError(
                f"HTTPError {exc.code}: {'transient' if transient else 'permanent'} Twilio failure",
                transient=transient,
            ) from None
        except urllib.error.URLError as exc:
            raise NotificationDeliveryError(
                f"{type(exc.reason).__name__}: could not reach Twilio", transient=True
            ) from None
