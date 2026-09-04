import logging

from app.services.notifications.base import NotificationProvider

logger = logging.getLogger(__name__)


class SMSNotificationProvider(NotificationProvider):
    """Stub only. Per the master plan, SMS is a premium feature for a later
    phase — this never contacts a real carrier/gateway. It logs what it would
    have sent and always reports success as *simulated*; the dispatch service
    marks the Notification SIMULATED (never SENT/DELIVERED) for exactly this
    reason, so nothing here can be mistaken for proof a text message actually
    reached anyone."""

    def send(self, *, to: str, subject: str, body: str) -> str:
        logger.info("SIMULATED SMS to %s: %s", to or "<no phone on file>", subject)
        return "simulated — no real SMS gateway configured"
