import uuid
from datetime import datetime
from decimal import Decimal

from pydantic import BaseModel, ConfigDict, field_validator

from app.db.models.appointment import AppointmentStatus


def _require_tz_aware(value: datetime) -> datetime:
    if value.tzinfo is None:
        raise ValueError("scheduled_at must include a timezone offset.")
    return value


class AppointmentCreate(BaseModel):
    customer_id: uuid.UUID
    service_id: uuid.UUID
    staff_id: uuid.UUID | None = None
    # duration_minutes is NOT accepted here: Python derives it from the service,
    # never from the caller — the same rule that keeps the LLM from inventing a
    # booking applies just as much to a client-supplied duration.
    scheduled_at: datetime

    @field_validator("scheduled_at")
    @classmethod
    def must_be_timezone_aware(cls, value: datetime) -> datetime:
        return _require_tz_aware(value)


class AppointmentReschedule(BaseModel):
    scheduled_at: datetime

    @field_validator("scheduled_at")
    @classmethod
    def must_be_timezone_aware(cls, value: datetime) -> datetime:
        return _require_tz_aware(value)


class AppointmentRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    # Phase 55: the short, customer-facing reference (the ONLY one a customer is ever
    # shown) -- included here too so staff can look an appointment up by the same code a
    # customer might quote back to them.
    confirmation_code: str
    business_id: uuid.UUID
    customer_id: uuid.UUID
    service_id: uuid.UUID
    staff_id: uuid.UUID | None
    scheduled_at: datetime
    duration_minutes: int
    status: AppointmentStatus
    created_at: datetime
    group_booking_id: uuid.UUID | None
    # Phase 46 — deliberately NOT `checkin_token` here: the token's only real
    # consumers are the email QR image and the checkin POST body, so it's
    # never returned by the general appointment read/list endpoints.
    checked_in_at: datetime | None
    completed_at: datetime | None


class CheckinRequest(BaseModel):
    # The exact real value decoded from the QR by the dashboard scanner
    # (Phase 46) — the raw checkin_token, never the appointment_id.
    token: uuid.UUID


class CheckinResponse(BaseModel):
    appointment_id: uuid.UUID
    status: AppointmentStatus
    checked_in_at: datetime
    customer_name: str
    service_name: str
    scheduled_at: datetime
    # None whenever no real Phase 44 Payment row exists for this appointment
    # (no deposit was ever configured) — there is nothing to record. Never
    # auto-populated as "paid"; see PaymentRead's own `collected_in_person_*`
    # fields for why check-in itself never assumes a payment was received.
    pending_payment: "PaymentCheckinInfo | None" = None


class PaymentCheckinInfo(BaseModel):
    payment_id: uuid.UUID
    amount: Decimal
    currency: str
    remaining: Decimal
    status: str
    collected_in_person_amount: Decimal | None
    collected_in_person_at: datetime | None


CheckinResponse.model_rebuild()


class AppointmentListItem(AppointmentRead):
    """GET /appointments only — same fields as AppointmentRead plus the
    denormalized names the dashboard's Appointments page needs to render a
    table (customer/service/staff) without the client fetching a full,
    separately-unbounded customer list just to build a name lookup (there is
    no GET /customers list endpoint at all, deliberately not added for this —
    see the route). Resolved via a single follow-up query scoped to just the
    IDs present on this one page (bounded by the same limit as the page
    itself), not a per-row query."""

    customer_name: str
    service_name: str | None
    staff_name: str | None
