import enum
import uuid
from datetime import datetime
from decimal import Decimal

from sqlalchemy import DateTime, Enum, ForeignKeyConstraint, Numeric, String, UniqueConstraint
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.database import Base
from app.db.models.mixins import CreatedAtMixin, TenantMixin, UpdatedAtMixin, UUIDPrimaryKeyMixin


class PaymentStatus(str, enum.Enum):
    PENDING = "pending"
    COMPLETED = "completed"
    FAILED = "failed"


class Payment(UUIDPrimaryKeyMixin, TenantMixin, CreatedAtMixin, UpdatedAtMixin, Base):
    """A real payment request against one appointment (Phase 44, Premium).

    One row per appointment, created only when the business has payment
    collection enabled AND the booked service has a real deposit configured
    — see app.services.payment_service.create_payment_for_appointment. This
    row's own `id` IS the transaction reference sent to the gateway
    (eSewa's `transaction_uuid` / Khalti's `purchase_order_id`) — reused
    rather than minting a second unique identifier, since the gateway
    redirect/callback routes need a single, unauthenticated, globally-unique
    lookup key and this primary key already is one.

    A payment failure/delay must NEVER affect the appointment it belongs to
    — status here is purely informational, never a write path back onto
    Appointment. See booking_service.create_appointment's docstring and
    PHASE_STATUS.md Phase 44 for the full architectural rule.
    """

    __tablename__ = "payments"
    __table_args__ = (
        # One payment request per appointment — create_payment_for_appointment
        # is only ever called once, right after the appointment's own commit.
        UniqueConstraint("appointment_id", name="uq_payments_appointment_id"),
        ForeignKeyConstraint(
            ["appointment_id", "business_id"],
            ["appointments.id", "appointments.business_id"],
            name="fk_payments_appointment_same_tenant",
        ),
    )

    appointment_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), index=True, nullable=False)
    # "esewa" | "khalti" — whichever provider was configured on the business
    # at the moment this payment was created (Business.payment_providers may
    # change later; this row keeps the one it was actually created against).
    provider: Mapped[str] = mapped_column(String(20), nullable=False)
    amount: Mapped[Decimal] = mapped_column(Numeric(10, 2), nullable=False)
    currency: Mapped[str] = mapped_column(String(10), nullable=False)
    status: Mapped[PaymentStatus] = mapped_column(
        Enum(PaymentStatus, name="payment_status"), nullable=False, default=PaymentStatus.PENDING, server_default="PENDING"
    )
    # Khalti's `pidx` (needed by the lookup verification API) is stored the
    # moment initiate_payment returns it. eSewa has no equivalent at
    # initiate time (its "initiation" is just a signed browser form, not a
    # server call) — this is filled in with eSewa's real `transaction_code`
    # only once verify_payment's real status-check API confirms one exists.
    gateway_reference: Mapped[str | None] = mapped_column(String(255))
    # The real link handed to the customer in chat/email.
    payment_url: Mapped[str] = mapped_column(String(1000), nullable=False)
    # Phase 46: a real, EXPLICIT staff action recording a remaining-balance
    # amount collected in person at check-in — deliberately separate columns
    # from `status`/`gateway_reference` above, never conflated with them.
    # `status` stays reserved for what it always meant: the ONLINE deposit's
    # own gateway-verified outcome. An in-person cash/card payment is
    # fundamentally different — staff's own attestation, not a
    # cryptographically/API-verified transaction — so it gets its own
    # honestly-named fields rather than silently flipping `status` to
    # something that would misrepresent it as gateway-confirmed. NULL until
    # a staff member explicitly records it (see
    # app.services.payment_service.record_in_person_payment) — never
    # inferred from a check-in scan alone, per the ticket's explicit ask.
    collected_in_person_amount: Mapped[Decimal | None] = mapped_column(Numeric(10, 2))
    collected_in_person_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    # The chat conversation this booking/payment came from (NULL for a dashboard/API-made booking) — the address the
    # proactive "payment received" message goes back to (payment_service.notify_payment_completed). No FK: a deleted
    # conversation must never block anything here, and the send path re-checks the conversation exists.
    conversation_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))
    # Atomic once-only claim for that message (same shape as Appointment.reminder_sent_at): a single conditional UPDATE
    # sets it, so a gateway redirect hit twice, or the redirect racing a repeat, can never send it twice.
    completion_notified_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
