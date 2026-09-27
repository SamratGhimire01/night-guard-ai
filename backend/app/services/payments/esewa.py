import base64
import hashlib
import hmac
import json
import logging
import urllib.error
import urllib.parse
import urllib.request
import uuid
from decimal import Decimal

from app.core.config import settings
from app.core.public_url import UnsafePublicURLError, public_backend_base_url
from app.services.payments.base import PaymentGatewayError, PaymentInitiation, PaymentProvider, PaymentVerification

logger = logging.getLogger(__name__)

_TIMEOUT_SECONDS = 15
# eSewa's real ePay v2 signature covers exactly these three fields, in this
# exact order (developer.esewa.com.np) — this is `signed_field_names`, sent
# verbatim alongside the signature itself.
_SIGNED_FIELD_NAMES = "total_amount,transaction_uuid,product_code"


def _format_amount(amount: Decimal) -> str:
    # eSewa expects a plain decimal string in the form field, byte-identical
    # to what's fed into the signature below — quantized to 2dp to match this
    # codebase's own Numeric(10, 2) precision (see Service.price).
    return str(amount.quantize(Decimal("0.01")))


def _sign(total_amount: str, transaction_uuid: str, product_code: str) -> str:
    message = f"total_amount={total_amount},transaction_uuid={transaction_uuid},product_code={product_code}"
    digest = hmac.new(settings.esewa_secret_key.encode(), message.encode(), hashlib.sha256).digest()
    return base64.b64encode(digest).decode()


def signed_form_fields(*, payment_id: uuid.UUID, amount: Decimal) -> dict[str, str]:
    """Real eSewa ePay v2 form fields, computed fresh every time (no state to
    persist — see EsewaPaymentProvider.initiate_payment's docstring for why
    eSewa has no separate server-side initiate call). Used both by
    initiate_payment (irrelevant here, since eSewa needs no pre-call) and by
    the `/payments/esewa/redirect/{payment_id}` route that actually renders
    the auto-submit form the customer's browser POSTs to eSewa. total_amount
    equals amount (tax/service/delivery charges all zero — this is a
    booking deposit, not a itemized cart)."""
    total_amount = _format_amount(amount)
    transaction_uuid = str(payment_id)
    # `payment_id` is carried in the URL PATH of both URLs, never as a query param. eSewa appends its own payload to
    # these URLs as a literal "?data=<base64>" WITHOUT checking whether the URL already has a query string — so a
    # success_url of ".../success?payment_id=X" came back as ".../success?payment_id=X?data=..." (two "?"), which parsed
    # as a single payment_id value of "X?data=..." and stranded a real, completed payment at PENDING (found live in
    # Phase 47's real sandbox run). A path segment survives that append intact. The id itself is needed because eSewa's
    # "Cancel Payment" button redirects to failure_url with NO `data` at all, so `data` alone can't identify the
    # payment. Verification itself still never trusts anything from the URL except this id — only the real,
    # independent status-check API decides "completed" (see _handle_esewa_return).
    success_url = f"{settings.backend_base_url}/api/v1/payments/esewa/success/{transaction_uuid}"
    failure_url = f"{settings.backend_base_url}/api/v1/payments/esewa/failure/{transaction_uuid}"
    return {
        "amount": total_amount,
        "tax_amount": "0",
        "total_amount": total_amount,
        "transaction_uuid": transaction_uuid,
        "product_code": settings.esewa_product_code,
        "product_service_charge": "0",
        "product_delivery_charge": "0",
        "success_url": success_url,
        "failure_url": failure_url,
        "signed_field_names": _SIGNED_FIELD_NAMES,
        "signature": _sign(total_amount, transaction_uuid, settings.esewa_product_code),
    }


class EsewaPaymentProvider(PaymentProvider):
    """Real eSewa ePay v2 integration (developer.esewa.com.np). eSewa's real
    API has no server-to-server "create payment" call at all — a merchant
    initiates a payment purely by having the customer's own browser POST a
    signed HTML form directly to eSewa's endpoint. So `initiate_payment`
    makes no network call; it just returns the URL of this backend's own
    redirect page (app/api/routes/payments.py), which renders that real
    signed form at the moment the customer actually opens the link — the
    honest reflection of how eSewa's real integration works, not a
    simplification."""

    name = "esewa"

    def initiate_payment(self, *, payment_id: uuid.UUID, amount: Decimal, product_name: str) -> PaymentInitiation:
        # The ONLY guard needed on this gateway's use of backend_base_url: everything
        # else it builds (signed_form_fields' success_url/failure_url) is only ever
        # reached by a customer who already opened THIS payment_url, so if that check
        # passed here, backend_base_url was already proven safe by the time those run.
        try:
            base_url = public_backend_base_url()
        except UnsafePublicURLError as exc:
            raise PaymentGatewayError("backend base URL is not a real public domain") from exc
        return PaymentInitiation(
            payment_url=f"{base_url}/api/v1/payments/esewa/redirect/{payment_id}",
            gateway_reference=None,
        )

    def verify_payment(
        self, *, payment_id: uuid.UUID, amount: Decimal, gateway_reference: str | None
    ) -> PaymentVerification:
        """Real, independent call to eSewa's Status Check API — never trusts
        whatever the success/failure redirect claimed. `transaction_uuid` is
        this Payment row's own id (what was sent as the form field above)."""
        params = urllib.parse.urlencode(
            {
                "product_code": settings.esewa_product_code,
                "total_amount": _format_amount(amount),
                "transaction_uuid": str(payment_id),
            }
        )
        url = f"{settings.esewa_status_check_base_url}/api/epay/transaction/status/?{params}"
        try:
            with urllib.request.urlopen(url, timeout=_TIMEOUT_SECONDS) as response:
                payload = json.loads(response.read())
        except (urllib.error.HTTPError, urllib.error.URLError) as exc:
            raise PaymentGatewayError(f"eSewa status check failed: {exc}") from None

        status = payload.get("status", "")
        return PaymentVerification(
            completed=status == "COMPLETE",
            raw_status=status,
            gateway_reference=payload.get("ref_id"),
        )
