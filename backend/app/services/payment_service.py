import logging
import uuid
from decimal import ROUND_HALF_UP, Decimal

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.exceptions import UnprocessableEntityError
from app.db.models.appointment import Appointment
from app.db.models.business import Business
from app.db.models.payment import Payment, PaymentStatus
from app.db.models.service import Service
from app.schemas.business import PaymentSettingsUpdate
from app.services.payments.base import PaymentGatewayError, PaymentProvider
from app.services.payments.esewa import EsewaPaymentProvider
from app.services.payments.khalti import KhaltiPaymentProvider

logger = logging.getLogger(__name__)

_PROVIDERS: dict[str, PaymentProvider] = {"esewa": EsewaPaymentProvider(), "khalti": KhaltiPaymentProvider()}

# Real-world fact, not a guess: both eSewa and Khalti are Nepali payment
# gateways that only ever process NPR. Enabling payment collection for a
# business priced in any other currency would silently generate a real
# payment request in the wrong denomination, so it's rejected outright here
# rather than built and left to surprise someone later.
_GATEWAY_CURRENCY = "NPR"


def get_provider(name: str) -> PaymentProvider:
    return _PROVIDERS[name]


def update_payment_settings(db: Session, *, business_id: uuid.UUID, payload: PaymentSettingsUpdate) -> Business:
    business = db.get(Business, business_id)
    if payload.payment_collection_enabled and business.currency != _GATEWAY_CURRENCY:
        raise UnprocessableEntityError(
            f"Payment collection requires the business currency to be {_GATEWAY_CURRENCY} "
            f"(eSewa/Khalti only process {_GATEWAY_CURRENCY}) — this business is priced in "
            f"{business.currency}."
        )
    business.payment_collection_enabled = payload.payment_collection_enabled
    business.payment_provider = payload.payment_provider
    db.commit()
    db.refresh(business)
    return business


def _deposit_amount(service: Service) -> Decimal:
    # ROUND_HALF_UP to 2dp — the same precision as Service.price's own
    # Numeric(10, 2) column; this codebase has no per-currency decimal-places
    # table (e.g. treating JPY as 0dp) anywhere else, so introducing one only
    # for this feature would be new, undocumented scope rather than "rounded
    # sensibly" for an existing convention.
    fraction = Decimal(service.deposit_percentage) / Decimal(100)
    return (service.price * fraction).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


def create_payment_for_appointment(db: Session, appointment: Appointment) -> None:
    """Best-effort payment request, called right after a real booking's own
    commit — same resilience discipline as Phase 40's
    google_calendar_service.sync_appointment_created: NEVER raises. A
    gateway failure must never be reported to the customer as a failed
    booking, since the booking already committed in Postgres before this
    ever runs. A no-op (no Payment row at all) whenever payment collection
    isn't real for this booking — free plan, toggle off, or the specific
    service has no deposit configured — never a stray pending row for a
    booking nobody asked to pay for."""
    business = db.get(Business, appointment.business_id)
    service = db.get(Service, appointment.service_id)
    if business is None or service is None:
        return
    if business.plan.value != "premium" or not business.payment_collection_enabled or not business.payment_provider:
        return
    if not service.deposit_enabled:
        return

    payment = Payment(
        business_id=business.id,
        appointment_id=appointment.id,
        provider=business.payment_provider,
        amount=_deposit_amount(service),
        currency=business.currency,
        status=PaymentStatus.PENDING,
        payment_url="",
    )
    db.add(payment)
    try:
        db.flush()
    except Exception:
        logger.exception("failed to create payment row for appointment_id=%s", appointment.id)
        db.rollback()
        return

    provider = get_provider(business.payment_provider)
    try:
        initiation = provider.initiate_payment(
            payment_id=payment.id, amount=payment.amount, product_name=f"{service.name} deposit — {business.name}"
        )
    except PaymentGatewayError:
        logger.exception("payment initiation failed for payment_id=%s provider=%s", payment.id, provider.name)
        payment.status = PaymentStatus.FAILED
        db.commit()
        return

    payment.payment_url = initiation.payment_url
    payment.gateway_reference = initiation.gateway_reference
    db.commit()


def get_payment_for_appointment(db: Session, *, business_id: uuid.UUID, appointment_id: uuid.UUID) -> Payment | None:
    return db.execute(
        select(Payment).where(Payment.business_id == business_id, Payment.appointment_id == appointment_id)
    ).scalar_one_or_none()


def get_payment(db: Session, *, payment_id: uuid.UUID) -> Payment | None:
    """Unscoped by business_id on purpose — this is the lookup used by the
    real, unauthenticated eSewa/Khalti redirect and callback routes, which
    have no bearer token and identify the payment only by the id the gateway
    itself echoes back (transaction_uuid / purchase_order_id)."""
    return db.get(Payment, payment_id)


def list_payments(db: Session, *, business_id: uuid.UUID) -> list[Payment]:
    return list(
        db.execute(select(Payment).where(Payment.business_id == business_id).order_by(Payment.created_at.desc())).scalars()
    )


def verify_and_update(db: Session, payment: Payment) -> Payment:
    """Real, independent confirmation via the gateway's own server-side API —
    called by the redirect/callback routes, never trusting whatever the
    redirect query string itself claimed. Never touches Appointment —
    Payment.status is purely informational (see Payment's own docstring)."""
    if payment.status != PaymentStatus.PENDING:
        return payment
    provider = get_provider(payment.provider)
    try:
        result = provider.verify_payment(
            payment_id=payment.id, amount=payment.amount, gateway_reference=payment.gateway_reference
        )
    except PaymentGatewayError:
        logger.exception("payment verification failed for payment_id=%s provider=%s", payment.id, provider.name)
        return payment

    payment.status = PaymentStatus.COMPLETED if result.completed else PaymentStatus.FAILED
    if result.gateway_reference:
        payment.gateway_reference = result.gateway_reference
    db.commit()
    db.refresh(payment)
    return payment
