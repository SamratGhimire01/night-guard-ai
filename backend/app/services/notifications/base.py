from abc import ABC, abstractmethod


class NotificationDeliveryError(Exception):
    """Raised by a NotificationProvider when one send attempt fails.

    `transient=True` means the failure is the kind retrying might fix (a
    network blip, a temporary SMTP error) — the dispatch service retries a
    bounded number of times. `transient=False` means retrying is pointless
    (bad/missing recipient, rejected credentials) — it fails immediately.
    """

    def __init__(self, message: str, *, transient: bool):
        self.transient = transient
        super().__init__(message)


class NotificationProvider(ABC):
    """Sends one notification. Implementations wrap a specific channel/backend
    (Gmail SMTP, a future SMS gateway, ...) so the dispatch service — and the
    rest of the codebase — never knows or cares which one is behind a given
    Notification.channel. Mirrors the ChatProvider/EmbeddingProvider seam from
    app/llm/base.py."""

    @abstractmethod
    def send(self, *, to: str, subject: str, body: str) -> str:
        """Sends the message. Returns a short human-readable success detail
        (e.g. the real SMTP server response) for logging. Raises
        NotificationDeliveryError on any failure — never returns a falsy value
        to signal failure."""
