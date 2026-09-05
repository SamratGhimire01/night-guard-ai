import uuid
from datetime import date

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.api.dependencies import get_current_user, get_db
from app.core.exceptions import NotFoundError
from app.db.models.appointment import AppointmentStatus
from app.db.models.business import BusinessUser
from app.schemas.appointment import AppointmentCreate, AppointmentRead, AppointmentReschedule
from app.services import booking_service

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


@router.get("/appointments", response_model=list[AppointmentRead])
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
) -> list[AppointmentRead]:
    """`group_booking_id` (Phase 12) filters down to just the appointments
    written together from one group-booking request — every appointment's own
    `group_booking_id` in the response is enough for a client to group them
    itself without a separate lookup.

    `limit`/`offset` (Phase 29 — Phase 28's F3 flagged this as the highest-risk
    unbounded list endpoint): ordered by scheduled_at like before, so paging is
    stable across calls as long as no appointment in the already-returned range
    is rescheduled. Response shape is unchanged (still a bare list) — a
    business with fewer than `limit` appointments sees no difference at all."""
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
    return [AppointmentRead.model_validate(a) for a in appointments]


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
    current_user: BusinessUser = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> AppointmentRead:
    """Also the exact function the cancellation tool (Phase 11 orchestrator)
    calls on the LLM's behalf — see app.services.conversation.appointment_tools.
    All validation (tenant-scoped, must be in a cancellable state) and the
    Notification write live in booking_service.cancel_appointment, not here."""
    appointment = booking_service.cancel_appointment(
        db, business_id=current_user.business_id, appointment_id=appointment_id
    )
    return AppointmentRead.model_validate(appointment)


@router.patch("/appointments/{appointment_id}/reschedule", response_model=AppointmentRead)
def reschedule_appointment(
    appointment_id: uuid.UUID,
    payload: AppointmentReschedule,
    current_user: BusinessUser = Depends(get_current_user),
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
