import base64
import html
import json
import logging
import uuid

from fastapi import APIRouter, Depends
from fastapi.responses import HTMLResponse
from sqlalchemy.orm import Session

from app.api.dependencies import get_current_user, get_db, require_plan, require_role
from app.core.config import settings
from app.core.exceptions import NotFoundError
from app.db.models.business import BusinessPlan, BusinessUser
from app.db.models.payment import PaymentStatus
from app.schemas.business import BusinessRead, PaymentSettingsUpdate
from app.schemas.payment import PaymentRead, RecordInPersonPaymentRequest
from app.services import payment_service
from app.services.payments.esewa import signed_form_fields

logger = logging.getLogger(__name__)

router = APIRouter()

_RESULT_PAGE = """<!doctype html><html><head><meta charset="utf-8">
<title>{title}</title></head>
<body style="font-family:Arial,Helvetica,sans-serif;text-align:center;padding:48px 16px;">
<h2>{heading}</h2><p>{message}</p></body></html>"""


def _result_page(*, title: str, heading: str, message: str) -> HTMLResponse:
    return HTMLResponse(_RESULT_PAGE.format(title=html.escape(title), heading=html.escape(heading), message=html.escape(message)))


@router.patch("/business/payment-settings", response_model=BusinessRead)
def update_payment_settings(
    payload: PaymentSettingsUpdate,
    current_user: BusinessUser = Depends(require_role(["owner", "admin"])),
    _plan_gate: BusinessUser = Depends(require_plan(BusinessPlan.PREMIUM)),
    db: Session = Depends(get_db),
) -> BusinessRead:
    business = payment_service.update_payment_settings(db, business_id=current_user.business_id, payload=payload)
    return BusinessRead.model_validate(business)


@router.get("/payments", response_model=list[PaymentRead])
def list_payments(
    current_user: BusinessUser = Depends(get_current_user), db: Session = Depends(get_db)
) -> list[PaymentRead]:
    """The real "pending payments" dashboard view (Phase 44 requirement #5) —
    every Payment row for this business, tenant-scoped like everything else.
    Any authenticated role can read (the ticket's own explicit ask: "so
    staff can see payment status per appointment, even though confirmation
    itself is automatic") — only the payment-settings toggle above is
    owner/admin-gated, same read/write split as GET /business/plan vs the
    superadmin-only plan-change endpoints. Not plan-gated on read either: a
    business that was Premium when a payment was created (and then
    downgraded) must still be able to see its own history."""
    payments = payment_service.list_payments(db, business_id=current_user.business_id)
    return [PaymentRead.model_validate(p) for p in payments]


@router.post("/payments/{payment_id}/collect-in-person", response_model=PaymentRead)
def collect_in_person(
    payment_id: uuid.UUID,
    payload: RecordInPersonPaymentRequest,
    current_user: BusinessUser = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> PaymentRead:
    """Phase 46 — the one explicit, distinct action for staff to record a
    real remaining-balance amount collected in person (shown alongside the
    check-in confirmation, but never fired by the scan itself — see
    payment_service.record_in_person_payment's own docstring for why this is
    never conflated with the online deposit's gateway-verified `status`).
    Any authenticated role, same bar as GET /payments and the checkin route
    — a front-desk staff member is exactly who does this in practice."""
    payment = payment_service.record_in_person_payment(
        db, business_id=current_user.business_id, payment_id=payment_id, amount=payload.amount
    )
    return PaymentRead.model_validate(payment)


@router.get("/payments/esewa/redirect/{payment_id}", response_class=HTMLResponse)
def esewa_redirect(payment_id: uuid.UUID, db: Session = Depends(get_db)) -> HTMLResponse:
    """The real link handed to the customer. Public/unauthenticated — a
    customer clicking this from chat/email has no bearer token. eSewa's own
    real ePay v2 API has no server-to-server "create payment" call (see
    EsewaPaymentProvider's docstring); this IS the initiation, an
    auto-submitting HTML form POSTing real signed fields straight to eSewa,
    the same mechanism every real eSewa merchant integration uses."""
    payment = payment_service.get_payment(db, payment_id=payment_id)
    if payment is None or payment.provider != "esewa" or payment.status != PaymentStatus.PENDING:
        raise NotFoundError("Payment not found or no longer payable.")

    fields = signed_form_fields(payment_id=payment.id, amount=payment.amount)
    inputs = "\n".join(f'<input type="hidden" name="{html.escape(k)}" value="{html.escape(v)}">' for k, v in fields.items())
    form_html = f"""<!doctype html><html><head><meta charset="utf-8"><title>Redirecting to eSewa…</title></head>
<body onload="document.forms[0].submit()">
<p>Redirecting you to eSewa to complete payment…</p>
<form method="POST" action="{settings.esewa_base_url}/api/epay/main/v2/form">
{inputs}
</form>
</body></html>"""
    return HTMLResponse(form_html)


def _handle_esewa_return(payment_id_param: str | None, data: str | None, db: Session) -> HTMLResponse:
    """Shared by both success_url and failure_url — eSewa's own docs say the
    redirect payload alone is never sufficient confirmation (a status-check
    call is required regardless), so both land here and both trigger the
    exact same real, independent verification rather than trusting which URL
    was hit.

    `payment_id_param` (our own query param, see signed_form_fields) is the
    primary way this payment is identified — real, live testing found
    eSewa's "Cancel Payment" button redirects to failure_url with NO `data`
    param at all, unlike a real declined payment attempt. `data` (eSewa's
    own base64 payload) is decoded only as a secondary source when
    payment_id_param is somehow missing; either way, nothing from either is
    ever trusted as the actual payment outcome — only verify_and_update's
    real status-check call decides that."""
    payment_id: uuid.UUID | None = None
    if payment_id_param:
        try:
            payment_id = uuid.UUID(payment_id_param)
        except ValueError:
            pass
    if payment_id is None and data:
        try:
            decoded = json.loads(base64.b64decode(data))
            payment_id = uuid.UUID(decoded["transaction_uuid"])
        except Exception:
            logger.warning("esewa return: could not decode/parse redirect payload")
    if payment_id is None:
        return _result_page(title="Payment", heading="Something went wrong", message="No payment reference received from eSewa.")

    payment = payment_service.get_payment(db, payment_id=payment_id)
    if payment is None:
        return _result_page(title="Payment", heading="Not found", message="This payment could not be found.")

    payment = payment_service.verify_and_update(db, payment)
    if payment.status == PaymentStatus.COMPLETED:
        return _result_page(
            title="Payment received", heading="Payment received", message="Thank you — your deposit was received. Your appointment is confirmed."
        )
    return _result_page(
        title="Payment not completed",
        heading="Payment not completed",
        message="Your deposit was not completed, but your appointment is still confirmed — you can pay at the clinic instead, or try the payment link again.",
    )


@router.get("/payments/esewa/success", response_class=HTMLResponse)
def esewa_success(payment_id: str | None = None, data: str | None = None, db: Session = Depends(get_db)) -> HTMLResponse:
    return _handle_esewa_return(payment_id, data, db)


@router.get("/payments/esewa/failure", response_class=HTMLResponse)
def esewa_failure(payment_id: str | None = None, data: str | None = None, db: Session = Depends(get_db)) -> HTMLResponse:
    return _handle_esewa_return(payment_id, data, db)


@router.get("/payments/khalti/callback", response_class=HTMLResponse)
def khalti_callback(
    pidx: str | None = None,
    status: str | None = None,
    purchase_order_id: str | None = None,
    db: Session = Depends(get_db),
) -> HTMLResponse:
    """Khalti's real return_url redirect — same discipline as eSewa's: the
    query-string `status` here is NEVER trusted by itself (Khalti's own docs
    say only the real lookup API's `Completed` status counts). Looked up by
    `purchase_order_id` (this Payment row's own id, exactly what was sent as
    that field at initiate time), not `pidx`, in case pidx itself is somehow
    malformed on the redirect — purchase_order_id is our own value."""
    if not purchase_order_id:
        return _result_page(title="Payment", heading="Something went wrong", message="No payment reference received from Khalti.")
    try:
        payment_id = uuid.UUID(purchase_order_id)
    except ValueError:
        return _result_page(title="Payment", heading="Something went wrong", message="Malformed payment reference from Khalti.")

    payment = payment_service.get_payment(db, payment_id=payment_id)
    if payment is None:
        return _result_page(title="Payment", heading="Not found", message="This payment could not be found.")

    payment = payment_service.verify_and_update(db, payment)
    if payment.status == PaymentStatus.COMPLETED:
        return _result_page(
            title="Payment received", heading="Payment received", message="Thank you — your deposit was received. Your appointment is confirmed."
        )
    return _result_page(
        title="Payment not completed",
        heading="Payment not completed",
        message="Your deposit was not completed, but your appointment is still confirmed — you can pay at the clinic instead, or try the payment link again.",
    )
