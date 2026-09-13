import uuid
from datetime import date

from fastapi import APIRouter, Depends, Query
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.dependencies import get_current_user, get_db, require_role
from app.core.exceptions import NotFoundError
from app.db.models.appointment import AppointmentStatus
from app.db.models.business import BusinessUser
from app.db.models.customer import Customer
from app.db.models.service import Service
from app.db.models.staff import Staff
from app.schemas.appointment import (
    AppointmentCreate,
    AppointmentListItem,
    AppointmentRead,
    AppointmentReschedule,
    CheckinRequest,
    CheckinResponse,
    PaymentCheckinInfo,
)
from app.services import booking_service, checkin_service, payment_service

router = APIRouter()


@router.post("/appointments", response_model=AppointmentRead, status_code=201)
def create_appointment(
    payload: AppointmentCreate,
    current_user: BusinessUser = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> AppointmentRead:
    """Real booking write path. Also the exact function the booking tool (Phase
    10 orchestrator) calls on the LLM's behalf — see
    app.services.conversation.booking_tool. Every validation (service/staff
    exist and belong to this tenant, slot is really open) and the race-condition
    guarantee live in booking_service.create_appointment, not here or in the
    tool — one implementation, two callers."""
    appointment = booking_service.create_appointment(
        db,
        business_id=current_user.business_id,
        customer_id=payload.customer_id,
        service_id=payload.service_id,
        staff_id=payload.staff_id,
        scheduled_at=payload.scheduled_at,
    )
    return AppointmentRead.model_validate(appointment)


@router.get("/appointments", response_model=list[AppointmentListItem])
def list_appointments(
    customer_id: uuid.UUID | None = Query(default=None),
    status: AppointmentStatus | None = Query(default=None),
    date_from: date | None = Query(default=None),
    date_to: date | None = Query(default=None),
    group_booking_id: uuid.UUID | None = Query(default=None),
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    current_user: BusinessUser = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> list[AppointmentListItem]:
    """`group_booking_id` (Phase 12) filters down to just the appointments
    written together from one group-booking request — every appointment's own
    `group_booking_id` in the response is enough for a client to group them
    itself without a separate lookup.

    `limit`/`offset` (Phase 29 — Phase 28's F3 flagged this as the highest-risk
    unbounded list endpoint): ordered by scheduled_at like before, so paging is
    stable across calls as long as no appointment in the already-returned range
    is rescheduled.

    Response includes denormalized customer/service/staff names (the
    dashboard Appointments page's own real need) — resolved via ONE follow-up
    query per resource type, scoped only to the distinct IDs on this page
    (never more rows than `limit`), not a per-appointment query and not a
    full, separately-unbounded customer list."""
    appointments = booking_service.list_appointments(
        db,
        business_id=current_user.business_id,
        customer_id=customer_id,
        status=status,
        date_from=date_from,
        date_to=date_to,
        group_booking_id=group_booking_id,
        limit=limit,
        offset=offset,
    )
    customer_ids = {a.customer_id for a in appointments}
    service_ids = {a.service_id for a in appointments}
    staff_ids = {a.staff_id for a in appointments if a.staff_id is not None}
    customers = {
        c.id: c.name for c in db.execute(select(Customer).where(Customer.id.in_(customer_ids))).scalars()
    } if customer_ids else {}
    services = {
        s.id: s.name for s in db.execute(select(Service).where(Service.id.in_(service_ids))).scalars()
    } if service_ids else {}
    staff = {
        s.id: s.name for s in db.execute(select(Staff).where(Staff.id.in_(staff_ids))).scalars()
    } if staff_ids else {}
    return [
        AppointmentListItem(
            **AppointmentRead.model_validate(a).model_dump(),
            customer_name=customers.get(a.customer_id, "Unknown customer"),
            service_name=services.get(a.service_id),
            staff_name=staff.get(a.staff_id) if a.staff_id else None,
        )
        for a in appointments
    ]


@router.get("/appointments/{appointment_id}", response_model=AppointmentRead)
def get_appointment(
    appointment_id: uuid.UUID,
    current_user: BusinessUser = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> AppointmentRead:
    appointment = booking_service.get_appointment(
        db, business_id=current_user.business_id, appointment_id=appointment_id
    )
    if appointment is None:
        raise NotFoundError("Appointment not found.")
    return AppointmentRead.model_validate(appointment)


@router.patch("/appointments/{appointment_id}/cancel", response_model=AppointmentRead)
def cancel_appointment(
    appointment_id: uuid.UUID,
    current_user: BusinessUser = Depends(require_role(["owner", "admin"])),
    db: Session = Depends(get_db),
) -> AppointmentRead:
    """Also the exact function the cancellation tool (Phase 11 orchestrator)
    calls on the LLM's behalf — see app.services.conversation.appointment_tools.
    That path calls booking_service.cancel_appointment directly in-process
    (never through this HTTP route), so gating this route to owner/admin
    (Appointments Management page, this phase — every other resource's write
    endpoint already follows this exact rule; this one never had it) doesn't
    touch the LLM's own ability to cancel on a customer's behalf at all. All
    validation (tenant-scoped, must be in a cancellable state) and the
    Notification write live in booking_service.cancel_appointment, not here."""
    appointment = booking_service.cancel_appointment(
        db, business_id=current_user.business_id, appointment_id=appointment_id
    )
    return AppointmentRead.model_validate(appointment)


@router.patch("/appointments/{appointment_id}/reschedule", response_model=AppointmentRead)
def reschedule_appointment(
    appointment_id: uuid.UUID,
    payload: AppointmentReschedule,
    current_user: BusinessUser = Depends(require_role(["owner", "admin"])),
    db: Session = Depends(get_db),
) -> AppointmentRead:
    """Also the exact function the reschedule tool (Phase 11 orchestrator) calls
    on the LLM's behalf. Updates the same appointment row in place — the booking
    ID never changes — and reuses the Phase 10 exclusion constraint (enforced by
    Postgres on UPDATE too) as the real race-condition guarantee."""
    appointment = booking_service.reschedule_appointment(
        db,
        business_id=current_user.business_id,
        appointment_id=appointment_id,
        new_scheduled_at=payload.scheduled_at,
    )
    return AppointmentRead.model_validate(appointment)


@router.post("/appointments/checkin", response_model=CheckinResponse)
def check_in_appointment(
    payload: CheckinRequest,
    current_user: BusinessUser = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> CheckinResponse:
    """Phase 46 — the real QR scan endpoint. Deliberately `get_current_user`
    (any authenticated role, including staff), not `require_role(["owner",
    "admin"])` — the ticket's explicit ask is that front-desk staff can do
    this, unlike cancel/reschedule above. NOT a public endpoint: a bare photo
    of the QR code is useless without also being a real, logged-in staff
    member OF THE SAME BUSINESS — the token lookup itself is scoped to
    `current_user.business_id` inside checkin_service, so a token from
    another business is indistinguishable from one that doesn't exist."""
    appointment = checkin_service.check_in_appointment(
        db, business_id=current_user.business_id, token=payload.token
    )
    customer = db.get(Customer, appointment.customer_id)
    service = db.get(Service, appointment.service_id)
    payment = payment_service.get_payment_for_appointment(
        db, business_id=current_user.business_id, appointment_id=appointment.id
    )
    pending_payment = None
    if payment is not None:
        pending_payment = PaymentCheckinInfo(
            payment_id=payment.id,
            amount=payment.amount,
            currency=payment.currency,
            remaining=(service.price - payment.amount) if service else payment.amount,
            status=payment.status.value,
            collected_in_person_amount=payment.collected_in_person_amount,
            collected_in_person_at=payment.collected_in_person_at,
        )
    return CheckinResponse(
        appointment_id=appointment.id,
        status=appointment.status,
        checked_in_at=appointment.checked_in_at,
        customer_name=customer.name if customer else "Unknown customer",
        service_name=service.name if service else "Unknown service",
        scheduled_at=appointment.scheduled_at,
        pending_payment=pending_payment,
    )


@router.post("/appointments/{appointment_id}/complete", response_model=AppointmentRead)
def complete_appointment(
    appointment_id: uuid.UUID,
    current_user: BusinessUser = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> AppointmentRead:
    """Phase 46 (continued) — the real, separate "mark service complete"
    action. Deliberately `get_current_user` (any authenticated role,
    including staff), same bar as the check-in scan above — reachable from
    both the check-in scanner's result screen and the Appointments dashboard
    page. Only ever moves an ARRIVED appointment to COMPLETED; the atomic
    claim guarantee lives in checkin_service.mark_appointment_completed."""
    appointment = checkin_service.mark_appointment_completed(
        db, business_id=current_user.business_id, appointment_id=appointment_id
    )
    return AppointmentRead.model_validate(appointment)
