import json
import logging
import urllib.error
import urllib.request
import uuid
from decimal import Decimal

from app.core.config import settings
from app.core.public_url import UnsafePublicURLError, public_backend_base_url
from app.services.payments.base import PaymentGatewayError, PaymentInitiation, PaymentProvider, PaymentVerification

logger = logging.getLogger(__name__)

_TIMEOUT_SECONDS = 15
# Khalti's real ePayment API (KPG-2) enforces a minimum of NPR 10 (1000 paisa)
# per their documented `amount` field.
_MIN_AMOUNT_PAISA = 1000


def _post_json(path: str, body: dict, *, recover_status_on_http_error: bool = False) -> dict:
    """`recover_status_on_http_error` exists because of a real, live-tested
    quirk found in Khalti's own lookup API: for a non-success terminal
    outcome (e.g. "User canceled") it returns HTTP 400, not 200 — but the
    body is still a complete, real, parseable status payload (with an extra
    `error_key` field), not a genuine request error. Without this, every
    cancelled/failed Khalti payment would raise PaymentGatewayError and the
    Payment row would be stuck at PENDING forever, never reaching the honest
    FAILED state. initiate_payment never sets this — a 400 there really is a
    bad request (e.g. malformed payload), with no status payload to recover."""
    url = f"{settings.khalti_base_url}{path}"
    request = urllib.request.Request(
        url,
        data=json.dumps(body).encode(),
        headers={
            "Authorization": f"Key {settings.khalti_secret_key}",
            "Content-Type": "application/json",
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=_TIMEOUT_SECONDS) as response:
            return json.loads(response.read())
    except urllib.error.HTTPError as exc:
        raw = exc.read()
        if recover_status_on_http_error:
            try:
                payload = json.loads(raw)
            except json.JSONDecodeError:
                payload = None
            if payload is not None and "status" in payload:
                return payload
        # Never log the raw response body otherwise: it can echo back request
        # fields — same scrubbing discipline as the Twilio/Gmail providers.
        raise PaymentGatewayError(f"Khalti HTTP {exc.code}: {raw.decode(errors='replace')[:200]}") from None
    except urllib.error.URLError as exc:
        raise PaymentGatewayError(f"Khalti request failed: {exc}") from None


class KhaltiPaymentProvider(PaymentProvider):
    """Real Khalti ePayment (KPG-2) integration (docs.khalti.com). Unlike
    eSewa, Khalti's real API IS a server-to-server call: initiate_payment
    actually POSTs to Khalti and gets back a real `pidx` + `payment_url`."""

    name = "khalti"

    def initiate_payment(self, *, payment_id: uuid.UUID, amount: Decimal, product_name: str) -> PaymentInitiation:
        amount_paisa = int((amount * 100).to_integral_value())
        if amount_paisa < _MIN_AMOUNT_PAISA:
            raise PaymentGatewayError(
                f"Amount {amount} is below Khalti's real minimum of NPR {_MIN_AMOUNT_PAISA / 100:.2f}."
            )
        # Checked before the real network call below: a dev/tunnel return_url would have
        # Khalti try to redirect the customer's browser back to a dead address the
        # moment their payment completes.
        try:
            base_url = public_backend_base_url()
        except UnsafePublicURLError as exc:
            raise PaymentGatewayError("backend base URL is not a real public domain") from exc
        response = _post_json(
            "/api/v2/epayment/initiate/",
            {
                "return_url": f"{base_url}/api/v1/payments/khalti/callback",
                "website_url": base_url,
                "amount": amount_paisa,
                "purchase_order_id": str(payment_id),
                "purchase_order_name": product_name,
            },
        )
        return PaymentInitiation(payment_url=response["payment_url"], gateway_reference=response["pidx"])

    def verify_payment(
        self, *, payment_id: uuid.UUID, amount: Decimal, gateway_reference: str | None
    ) -> PaymentVerification:
        """Real, independent call to Khalti's lookup API — never trusts the
        `status`/`transaction_id` query params on the return_url redirect by
        itself. Requires gateway_reference (Khalti's `pidx`, stored at
        initiate time) since Khalti's lookup is keyed by pidx, not our own
        purchase_order_id."""
        if not gateway_reference:
            raise PaymentGatewayError("No pidx on file for this payment — cannot verify with Khalti.")
        response = _post_json(
            "/api/v2/epayment/lookup/", {"pidx": gateway_reference}, recover_status_on_http_error=True
        )
        status = response.get("status", "")
        return PaymentVerification(completed=status == "Completed", raw_status=status, gateway_reference=gateway_reference)
