import uuid
from datetime import datetime
from decimal import Decimal

from pydantic import BaseModel, ConfigDict, field_validator

from app.db.models.payment import PaymentStatus


class PaymentRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    business_id: uuid.UUID
    appointment_id: uuid.UUID
    provider: str
    amount: Decimal
    currency: str
    status: PaymentStatus
    gateway_reference: str | None
    payment_url: str
    # Phase 46 — a real, distinct staff action; never set by anything else.
    collected_in_person_amount: Decimal | None
    collected_in_person_at: datetime | None
    # Phase 49 — when a completed deposit was kept because the appointment became a no-show; None otherwise.
    forfeited_due_to_no_show_at: datetime | None


class RecordInPersonPaymentRequest(BaseModel):
    """Phase 46 — the explicit, separate action recording a real amount
    collected in person (e.g. the remaining balance at check-in). Never
    inferred from a QR scan alone."""

    amount: Decimal

    @field_validator("amount")
    @classmethod
    def non_negative(cls, value: Decimal) -> Decimal:
        if value < 0:
            raise ValueError("amount must not be negative.")
        return value
