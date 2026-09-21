import logging
import uuid
from datetime import datetime, timezone
from decimal import ROUND_HALF_UP, Decimal
from zoneinfo import ZoneInfo

from sqlalchemy import select, update
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.exceptions import NotFoundError, UnprocessableEntityError
from app.db.models.appointment import Appointment
from app.db.models.business import Business
from app.db.models.customer import Customer
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
    business.payment_providers = payload.payment_providers
    db.commit()
    db.refresh(business)
    return business


def deposit_amount(service: Service) -> Decimal:
    # ROUND_HALF_UP to 2dp — the same precision as Service.price's own
    # Numeric(10, 2) column; this codebase has no per-currency decimal-places
    # table (e.g. treating JPY as 0dp) anywhere else, so introducing one only
    # for this feature would be new, undocumented scope rather than "rounded
    # sensibly" for an existing convention.
    fraction = Decimal(service.deposit_percentage) / Decimal(100)
    return (service.price * fraction).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


def qr_page_url(payment: Payment) -> str:
    """The small public page showing this payment link as a scannable QR (api/routes/qr_view.py) — what chat gets
    alongside the plain link."""
    return f"{settings.backend_base_url.rstrip('/')}/pay-qr/{payment.id}"


def _deposit_due(business: Business | None, service: Service | None) -> bool:
    """True only when payment collection is genuinely real for this booking: Premium, toggled on with at least one
    gateway, and this specific service has a deposit configured."""
    return bool(
        business is not None
        and service is not None
        and business.plan.value == "premium"
        and business.payment_collection_enabled
        and business.payment_providers
        and service.deposit_enabled
    )


def _start_payment(
    db: Session,
    *,
    business: Business,
    service: Service,
    appointment: Appointment,
    provider_name: str,
    conversation_id: uuid.UUID | None = None,
) -> Payment | None:
    """Creates the Payment row, then the real gateway request for it. Never raises; None only if the row itself could
    not be written (a gateway failure still leaves a FAILED row, exactly as before)."""
    payment = Payment(
        business_id=business.id,
        appointment_id=appointment.id,
        provider=provider_name,
        amount=deposit_amount(service),
        currency=business.currency,
        status=PaymentStatus.PENDING,
        payment_url="",
        conversation_id=conversation_id,
    )
    db.add(payment)
    try:
        db.flush()
    except Exception:
        logger.exception("failed to create payment row for appointment_id=%s", appointment.id)
        db.rollback()
        return None

    provider = get_provider(provider_name)
    try:
        initiation = provider.initiate_payment(
            payment_id=payment.id, amount=payment.amount, product_name=f"{service.name} deposit — {business.name}"
        )
    except PaymentGatewayError:
        logger.exception("payment initiation failed for payment_id=%s provider=%s", payment.id, provider.name)
        payment.status = PaymentStatus.FAILED
        db.commit()
        return payment

    payment.payment_url = initiation.payment_url
    payment.gateway_reference = initiation.gateway_reference
    db.commit()
    return payment


def create_payment_for_appointment(db: Session, appointment: Appointment, *, defer_choice: bool = False) -> None:
    """Best-effort payment request, called right after a real booking's own
    commit — same resilience discipline as Phase 40's
    google_calendar_service.sync_appointment_created: NEVER raises. A
    gateway failure must never be reported to the customer as a failed
    booking, since the booking already committed in Postgres before this
    ever runs. A no-op (no Payment row at all) whenever payment collection
    isn't real for this booking — free plan, toggle off, or the specific
    service has no deposit configured — never a stray pending row for a
    booking nobody asked to pay for.

    When the business offers more than one gateway, `defer_choice=True` (the chat booking path) creates nothing yet:
    the customer is asked which they prefer and `choose_provider` creates the request through their pick. Any caller
    that can't ask (dashboard/API bookings) leaves it False and gets the business's first configured gateway."""
    business = db.get(Business, appointment.business_id)
    service = db.get(Service, appointment.service_id)
    if not _deposit_due(business, service):
        return
    if defer_choice and len(business.payment_providers) > 1:
        return
    _start_payment(
        db, business=business, service=service, appointment=appointment, provider_name=business.payment_providers[0]
    )


def awaits_provider_choice(db: Session, appointment: Appointment) -> bool:
    """A confirmed booking that owes a deposit, over more than one gateway, with no request created yet."""
    business = db.get(Business, appointment.business_id)
    service = db.get(Service, appointment.service_id)
    return (
        _deposit_due(business, service)
        and len(business.payment_providers) > 1
        and appointment.status.value == "confirmed"
        and get_payment_for_appointment(db, business_id=business.id, appointment_id=appointment.id) is None
    )


def choose_provider(
    db: Session, *, appointment: Appointment, provider_name: str, conversation_id: uuid.UUID | None
) -> Payment | None:
    """The customer's answer to "eSewa or Khalti?": creates the real payment request through exactly that gateway.
    None if the choice is no longer valid (not one of this business's gateways, or nothing is awaiting one)."""
    business = db.get(Business, appointment.business_id)
    service = db.get(Service, appointment.service_id)
    if business is None or provider_name not in business.payment_providers or not awaits_provider_choice(db, appointment):
        return None
    return _start_payment(
        db,
        business=business,
        service=service,
        appointment=appointment,
        provider_name=provider_name,
        conversation_id=conversation_id,
    )


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
    if payment.status == PaymentStatus.COMPLETED:
        notify_payment_completed(db, payment)
    return payment


def notify_payment_completed(db: Session, payment: Payment) -> None:
    """Proactive "payment received" message into the chat the booking came from — sent only after the gateway's own
    independent verification said COMPLETED (verify_and_update is the only caller), never off a redirect claim.
    Exactly once: a single conditional UPDATE claims `completion_notified_at`, so a redirect hit twice or two racing
    verifications cannot double-send. Claimed BEFORE sending — a crash in between loses one message rather than
    repeating it. No conversation (a dashboard/API booking) means nothing to send. Never raises: a chat-send failure
    must not undo a payment that already verified."""
    if payment.conversation_id is None:
        return
    try:
        # function-level imports: the channel/conversation layer imports this module (booking_tool), so a module-level
        # import here would be a cycle
        from app.db.models.conversation import Conversation
        from app.services.channels.proactive import send_to_conversation
        from app.services.conversation.response_templates import render

        claimed = db.execute(
            update(Payment)
            .where(Payment.id == payment.id, Payment.completion_notified_at.is_(None))
            .values(completion_notified_at=datetime.now(timezone.utc))
        ).rowcount
        db.commit()
        if claimed != 1:
            return
        conversation = db.get(Conversation, payment.conversation_id)
        appointment = db.get(Appointment, payment.appointment_id)
        service = db.get(Service, appointment.service_id) if appointment else None
        if conversation is None or appointment is None or service is None:
            return
        business = db.get(Business, payment.business_id)
        customer = db.get(Customer, appointment.customer_id)
        text = render(
            "payment_received",
            conversation.detected_language,
            who=f", {customer.name}" if customer and customer.name else "",
            when=appointment.scheduled_at.astimezone(ZoneInfo(business.timezone)).strftime("%A, %B %-d at %-I:%M %p"),
            currency=payment.currency,
            amount=str(payment.amount),
            service=service.name,
            id=str(appointment.id),
        )
        logger.info(
            "payment completed, notifying conversation_id=%s payment_id=%s: %s",
            conversation.id,
            payment.id,
            send_to_conversation(db, conversation=conversation, text=text),
        )
    except Exception:
        logger.exception("payment-completed notification failed for payment_id=%s", payment.id)


def get_payment_for_business(db: Session, *, business_id: uuid.UUID, payment_id: uuid.UUID) -> Payment | None:
    """Tenant-scoped lookup for the real, authenticated staff-facing routes
    (unlike get_payment above, which is deliberately unscoped for the public
    gateway callback routes)."""
    return db.execute(
        select(Payment).where(Payment.id == payment_id, Payment.business_id == business_id)
    ).scalar_one_or_none()


def record_in_person_payment(db: Session, *, business_id: uuid.UUID, payment_id: uuid.UUID, amount: Decimal) -> Payment:
    """Phase 46 — the ONE explicit, distinct staff action that records a real
    remaining-balance amount collected in person (e.g. at check-in). Never
    touches `status`/`gateway_reference` — those stay reserved for the
    ONLINE deposit's own gateway-verified outcome (see Payment's own
    docstring for why conflating the two would misrepresent a staff
    attestation as a cryptographically-verified transaction). Deliberately
    NOT wrapped in the same atomic-claim ceremony as the QR check-in or the
    reminder guard: the ticket never asked for one-time-use here, and
    allowing a second call (e.g. staff correcting a typo'd amount) to simply
    overwrite the previous value is the more useful real behavior for a
    manual data-entry action, not an oversight."""
    payment = get_payment_for_business(db, business_id=business_id, payment_id=payment_id)
    if payment is None:
        raise NotFoundError("Payment not found.")
    payment.collected_in_person_amount = amount
    payment.collected_in_person_at = datetime.now(timezone.utc)
    db.commit()
    db.refresh(payment)
    return payment
