import uuid
from abc import ABC, abstractmethod
from dataclasses import dataclass
from decimal import Decimal


class PaymentGatewayError(Exception):
    """Raised when a real call to a gateway's API fails (network error, or a
    real error response from eSewa/Khalti's own servers). Mirrors
    NotificationDeliveryError's role (app/services/notifications/base.py):
    the caller (payment_service) decides what "failed" means for the
    Payment row — this never corrupts or blocks the appointment itself, see
    booking_service.create_appointment's docstring."""


@dataclass
class PaymentInitiation:
    """What starting a real payment produced. `payment_url` is always a real
    link the customer's browser can open to actually pay — for eSewa (no
    server-to-server "create payment" call exists in their real API) this is
    this backend's own redirect page that renders a real signed auto-submit
    form; for Khalti it's the real `payment_url` returned by their real
    `/epayment/initiate/` call. `gateway_reference` is whatever the gateway
    itself hands back at this point to identify the payment later (Khalti's
    `pidx`) — None when nothing is issued yet (eSewa)."""

    payment_url: str
    gateway_reference: str | None


@dataclass
class PaymentVerification:
    """The result of an independent, server-side confirmation call — never
    built from a client-supplied/redirect-supplied claim. `raw_status` is
    the gateway's own real status string, kept for the Payment row's
    diagnostic trail even though only `completed` drives any real logic."""

    completed: bool
    raw_status: str
    gateway_reference: str | None = None


class PaymentProvider(ABC):
    """Real eSewa/Khalti gateway integration, one implementation per gateway.
    Mirrors the ChatProvider/NotificationProvider seam elsewhere in this
    codebase (app/llm/base.py, app/services/notifications/base.py): the rest
    of the codebase never knows or cares which real gateway is behind a given
    Payment, only that these two methods exist."""

    name: str

    @abstractmethod
    def initiate_payment(self, *, payment_id: uuid.UUID, amount: Decimal, product_name: str) -> PaymentInitiation:
        """Starts a real payment request for `amount` (already the final
        deposit amount — currency conversion/rounding happens before this is
        called, see payment_service). Raises PaymentGatewayError on a real
        failure; never fabricates a payment_url."""

    @abstractmethod
    def verify_payment(
        self, *, payment_id: uuid.UUID, amount: Decimal, gateway_reference: str | None
    ) -> PaymentVerification:
        """Independently confirms this payment's real status via the
        gateway's own server-side verification API (eSewa's status-check
        endpoint / Khalti's lookup endpoint) — NEVER trusts a redirect
        query-string claim by itself. Raises PaymentGatewayError on a real
        failure to even reach the gateway (network error, malformed
        response) — that is distinct from a real "not completed" result,
        which is a normal PaymentVerification(completed=False, ...)."""
