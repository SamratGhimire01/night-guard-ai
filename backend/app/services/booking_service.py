import logging
import uuid
from datetime import date, datetime, time, timedelta
from zoneinfo import ZoneInfo

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.exceptions import ConflictError, NotFoundError, UnprocessableEntityError
from app.db.models.appointment import Appointment, AppointmentParticipant, AppointmentStatus
from app.db.models.audit_log import AuditLog
from app.db.models.business import Business, BusinessHours, BusinessHoursException
from app.db.models.customer import Customer
from app.db.models.notification import Notification, NotificationStatus
from app.services import customer_service, service_service, staff_service
from app.services.notifications import dispatch_notification

logger = logging.getLogger(__name__)

_CANCELLABLE_STATUSES = (AppointmentStatus.PENDING, AppointmentStatus.CONFIRMED)

# ponytail: fixed 15-minute grid for every business/service rather than a
# per-business configurable granularity. Real receptionists usually work off
# one shared grid; add a per-business setting if a service ever genuinely
# needs a finer/coarser one than 15 minutes.
SLOT_GRANULARITY_MINUTES = 15


def _notification_channel(business: Business, customer: Customer) -> str:
    """SMS (Phase 15) is used only as a fallback for a customer with no email
    on file — email stays the unconditional default for every customer who has
    one, exactly matching pre-Phase-15 behavior. It's only even eligible when
    the business has explicitly turned SMS on AND the customer explicitly
    opted in (never spam customers who didn't ask for texts — see
    Customer.sms_opt_in's comment and PHASE_STATUS.md Phase 15 for the
    consent design)."""
    if business.sms_enabled and customer.sms_opt_in and customer.phone and not customer.email:
        return "sms"
    return "email"


def _resolve_effective_staff_id(service, staff_id: uuid.UUID | None) -> uuid.UUID | None:
    """The staff member whose calendar this booking actually occupies: the caller's
    explicit choice, else the service's own fixed staff member, else None (meaning
    "no specific staff tracked" — see the module docstring below on what that means
    for availability)."""
    return staff_id if staff_id is not None else service.staff_id


def get_available_slots(
    db: Session,
    *,
    business_id: uuid.UUID,
    service_id: uuid.UUID,
    staff_id: uuid.UUID | None = None,
    date_from: date,
    date_to: date,
    _ignore_conflicts: bool = False,
) -> list[datetime]:
    """Real open start-times for `service_id` between `date_from` and `date_to`
    (inclusive), on a `SLOT_GRANULARITY_MINUTES` grid, honoring weekly
    BusinessHours, per-date BusinessHoursException overrides/holidays, and every
    existing non-cancelled Appointment for the resolved staff resource. Never
    returns a slot outside business hours, on a closed day, already booked, or in
    the past.

    Concurrency note: this is a read — it tells the truth about the DB *at the
    moment of the call*, not a lock. `create_appointment` re-derives availability
    at insert time and the DB's own exclusion constraint is the actual race-proof
    guarantee (see the migration and `create_appointment` below).

    `_ignore_conflicts` is an internal knob (not exposed on any route): it skips
    the existing-appointment overlap filter entirely, leaving only the
    structural open-hours/closed-day/past-time checks. `reschedule_appointment`
    uses this to separate two genuinely different failure reasons that a single
    "is scheduled_at in available slots" check used to conflate into the same
    422 — see reschedule_appointment's docstring for why that conflation was a
    real, observed bug under concurrency.

    Staff resolution: if `staff_id` is given (or the service has a fixed
    `staff_id`), conflicts are checked against that specific staff member's
    calendar. If no staff is resolved at all, this business is treated as a single
    shared resource for that slot (a second staff-less booking at the same exact
    time is refused) — a deliberately conservative default given this schema has
    no notion of "any of N interchangeable staff"; a real staff/service capacity
    model would relax this for multi-staff businesses that don't pin services to
    a specific person.
    """
    business = db.get(Business, business_id)
    if business is None:
        raise NotFoundError("Business not found.")
    service = service_service.get_service(db, business_id=business_id, service_id=service_id)
    if service is None:
        raise NotFoundError("Service not found.")
    if staff_id is not None and staff_service.get_staff(db, business_id=business_id, staff_id=staff_id) is None:
        raise NotFoundError("Staff member not found.")
    if date_to < date_from:
        return []

    effective_staff_id = _resolve_effective_staff_id(service, staff_id)
    tz = ZoneInfo(business.timezone)
    duration = timedelta(minutes=service.duration_minutes)
    now = datetime.now(tz)

    weekly_hours = {
        h.day_of_week: h
        for h in db.execute(select(BusinessHours).where(BusinessHours.business_id == business_id)).scalars()
    }
    exceptions = {
        e.date: e
        for e in db.execute(
            select(BusinessHoursException).where(
                BusinessHoursException.business_id == business_id,
                BusinessHoursException.date >= date_from,
                BusinessHoursException.date <= date_to,
            )
        ).scalars()
    }

    existing: list[Appointment] = []
    if not _ignore_conflicts:
        conflict_filters = [
            Appointment.business_id == business_id,
            Appointment.status != AppointmentStatus.CANCELLED,
            Appointment.scheduled_at >= datetime.combine(date_from, time.min, tzinfo=tz),
            Appointment.scheduled_at < datetime.combine(date_to + timedelta(days=1), time.min, tzinfo=tz),
        ]
        conflict_filters.append(
            Appointment.staff_id == effective_staff_id if effective_staff_id is not None else Appointment.staff_id.is_(None)
        )
        existing = list(db.execute(select(Appointment).where(*conflict_filters)).scalars())

    slots: list[datetime] = []
    current_date = date_from
    while current_date <= date_to:
        exception = exceptions.get(current_date)
        if exception is not None:
            open_t, close_t = (None, None) if exception.closed else (exception.open_time, exception.close_time)
        else:
            hours = weekly_hours.get(current_date.weekday())
            open_t, close_t = (None, None) if hours is None or hours.closed else (hours.open_time, hours.close_time)

        if open_t is not None and close_t is not None:
            slot_start = datetime.combine(current_date, open_t, tzinfo=tz)
            day_end = datetime.combine(current_date, close_t, tzinfo=tz)
            while slot_start + duration <= day_end:
                slot_end = slot_start + duration
                if slot_start > now and not any(
                    slot_start < a.scheduled_at + timedelta(minutes=a.duration_minutes) and a.scheduled_at < slot_end
                    for a in existing
                ):
                    slots.append(slot_start)
                slot_start += timedelta(minutes=SLOT_GRANULARITY_MINUTES)

        current_date += timedelta(days=1)

    return slots


def create_appointment(
    db: Session,
    *,
    business_id: uuid.UUID,
    customer_id: uuid.UUID,
    service_id: uuid.UUID,
    staff_id: uuid.UUID | None,
    scheduled_at: datetime,
    group_booking_id: uuid.UUID | None = None,
    _commit: bool = True,
) -> Appointment:
    """The ONLY path that writes an Appointment row. Re-derives availability for
    real (never trusts a caller's — including the LLM's — claim that a slot is
    free), then relies on the DB's exclusion constraint as the actual race-proof
    guarantee: two concurrent calls for the same slot both pass the checks below,
    but only one write succeeds — the loser gets ConflictError.

    `group_booking_id` (Phase 12) is opaque here — just stamped onto the row so a
    batch of appointments created together (see `create_group_appointments`) can
    be found/filtered as one group later. `_commit=False` (internal, not exposed
    on any route) flushes instead of committing, so `create_group_appointments`
    can write several appointments in one transaction for real all-or-nothing
    semantics — the exclusion constraint still fires on flush (Postgres checks it
    per-statement, not just at commit), so the race guarantee is unchanged.

    A `Notification` (channel=email, event_type=booking_confirmed) is queued
    for every successful booking — this is the ONLY place a booking-confirmation
    Notification is created, so the route, the conversational booking tool, and
    every group-booking cluster all get one for free with no duplicated logic
    (Phase 13). When `_commit=True` it is dispatched for real immediately after
    commit; when `_commit=False` (an all-or-nothing group write), the caller
    dispatches it after the whole group's own outer commit succeeds — see
    `_create_group_all_or_nothing`.

    Phase 31: every real outcome (success, or a caught NotFoundError/
    UnprocessableEntityError/ConflictError) is also recorded as a real
    AuditLog row (action="booking_attempt") — the metrics endpoint's real,
    tenant-scoped source for booking success/failure rate, distinguishing a
    ConflictError ("customer lost a real race for a slot" — expected, not a
    system failure) from the others. Only recorded when `_commit=True`
    (every single-booking and partial-mode-group caller): the all-or-nothing
    group write path (`_commit=False`) records its own metric once for the
    whole batch instead — see `_create_group_all_or_nothing` — so a metric
    row is never committed ahead of the batch's own atomic commit/rollback."""
    try:
        service = service_service.get_service(db, business_id=business_id, service_id=service_id)
        if service is None:
            raise NotFoundError("Service not found.")
        if staff_id is not None and staff_service.get_staff(db, business_id=business_id, staff_id=staff_id) is None:
            raise NotFoundError("Staff member not found.")
        customer = customer_service.get_customer(db, business_id=business_id, customer_id=customer_id)
        if customer is None:
            raise NotFoundError("Customer not found.")

        available = get_available_slots(
            db,
            business_id=business_id,
            service_id=service_id,
            staff_id=staff_id,
            date_from=scheduled_at.date(),
            date_to=scheduled_at.date(),
        )
        if scheduled_at not in available:
            raise UnprocessableEntityError(
                "Requested time is not available (outside business hours, on a closed date, in the "
                "past, or already booked)."
            )

        appointment = Appointment(
            business_id=business_id,
            customer_id=customer_id,
            service_id=service_id,
            staff_id=_resolve_effective_staff_id(service, staff_id),
            scheduled_at=scheduled_at,
            duration_minutes=service.duration_minutes,
            status=AppointmentStatus.CONFIRMED,
            group_booking_id=group_booking_id,
        )
        db.add(appointment)
        try:
            db.flush()
        except IntegrityError:
            db.rollback()
            raise ConflictError("This slot was just booked by someone else — please choose another time.")

        business = db.get(Business, business_id)
        notification = Notification(
            business_id=business_id,
            appointment_id=appointment.id,
            channel=_notification_channel(business, customer),
            event_type="booking_confirmed",
            status=NotificationStatus.QUEUED,
        )
        db.add(notification)

        if _commit:
            db.commit()
            db.refresh(appointment)
            db.refresh(notification)
            dispatch_notification(db, notification)
        else:
            db.flush()
    except (NotFoundError, UnprocessableEntityError, ConflictError) as exc:
        if _commit:
            _record_booking_metric(db, business_id=business_id, result=_booking_metric_result(exc))
        raise
    else:
        if _commit:
            _record_booking_metric(db, business_id=business_id, result="success")
        return appointment


_BOOKING_METRIC_RESULTS = {
    NotFoundError: "not_found",
    UnprocessableEntityError: "unavailable",
    ConflictError: "conflict_race_lost",
}


def _booking_metric_result(exc: Exception) -> str:
    return _BOOKING_METRIC_RESULTS.get(type(exc), "unknown_error")


def _record_booking_metric(db: Session, *, business_id: uuid.UUID, result: str) -> None:
    """Reuses the existing, general-purpose AuditLog model (Phase 3) rather than
    a new table — a real, DB-queryable, tenant-scoped record of every booking
    attempt's outcome, including the ones that never write an Appointment row
    at all (a race loss creates no Appointment, so without this there'd be no
    trace one ever happened). A self-contained commit: this never touches the
    caller's own transaction state, and a failure to record it must never
    break the booking attempt it's describing (never raises)."""
    try:
        db.add(
            AuditLog(
                business_id=business_id,
                actor="system",
                action="booking_attempt",
                resource_type="appointment",
                resource_id="n/a",
                result=result,
            )
        )
        db.commit()
    except Exception:
        db.rollback()
        logger.exception("failed to record booking_attempt metric for business_id=%s (non-fatal)", business_id)


def _cluster_group_people(people: list[dict]) -> list[dict]:
    """Groups people who asked for the identical (service, staff, time) into one
    shared Appointment — see the Phase 12 design decision in PHASE_STATUS.md:
    this schema's EXCLUDE constraint treats a staff-less service as occupying a
    single shared per-business resource, so booking the SAME slot as two
    separate Appointment rows would make the second one lose to the first as a
    false double-booking. People who want a different service and/or time each
    get their own Appointment. Order-preserving on first occurrence."""
    clusters: dict[tuple, dict] = {}
    order: list[tuple] = []
    for person in people:
        key = (person["service_id"], person.get("staff_id"), person["scheduled_at"])
        if key not in clusters:
            clusters[key] = {
                "labels": [],
                "service_id": person["service_id"],
                "staff_id": person.get("staff_id"),
                "scheduled_at": person["scheduled_at"],
            }
            order.append(key)
        clusters[key]["labels"].append(person["label"])
    return [clusters[key] for key in order]


def _serialize_appointment(appointment: Appointment) -> dict:
    return {
        "id": str(appointment.id),
        "service_id": str(appointment.service_id),
        "staff_id": str(appointment.staff_id) if appointment.staff_id else None,
        "scheduled_at": appointment.scheduled_at,
        "duration_minutes": appointment.duration_minutes,
    }


def _fresh_alternatives(
    db: Session, *, business_id: uuid.UUID, service_id: uuid.UUID, staff_id: uuid.UUID | None, around: datetime
) -> list[datetime]:
    """A fresh, real get_available_slots call — never a guess — for a failure
    response to honestly offer real alternatives. Same shape as
    BookAppointmentTool._alternatives, duplicated here (not imported) because it
    is service-layer logic and this module doesn't depend on the conversation
    package."""
    try:
        slots = get_available_slots(
            db,
            business_id=business_id,
            service_id=service_id,
            staff_id=staff_id,
            date_from=around.date(),
            date_to=around.date() + timedelta(days=7),
        )
    except NotFoundError:
        return []
    return slots[:5]


def create_group_appointments(
    db: Session,
    *,
    business_id: uuid.UUID,
    customer_id: uuid.UUID,
    people: list[dict],
    all_or_nothing: bool = False,
) -> dict:
    """Books one Appointment per distinct (service, staff, time) requested across
    `people` (each `{"label", "service_id", "staff_id", "scheduled_at"}`),
    attaching an AppointmentParticipant per person to whichever Appointment their
    slot resolved to. Every booking goes through the exact same
    `create_appointment` validation as a single booking — no shortcuts, and no
    partial trust of the caller's (or LLM's) claim that a slot is free.

    Default (`all_or_nothing=False`): each distinct slot is booked independently
    — a failure on one never blocks or rolls back another, and the result
    honestly reports every slot's real outcome.

    `all_or_nothing=True`: nothing is written until every requested slot is
    first confirmed available by a real, fresh `get_available_slots` check; if
    any one isn't, NONE are booked (matches the ticket's "validate all requested
    slots exist before writing any of them, then commit all-or-nothing"). The
    write pass then re-validates for real via `create_appointment` (never trusts
    the pre-check alone) inside one transaction — if a genuine race steals a slot
    between the two passes, the whole transaction rolls back and every person is
    honestly reported as not booked, rather than leaving a partial write behind.
    """
    if customer_service.get_customer(db, business_id=business_id, customer_id=customer_id) is None:
        raise NotFoundError("Customer not found.")

    group_booking_id = uuid.uuid4()
    clusters = _cluster_group_people(people)

    if all_or_nothing:
        return _create_group_all_or_nothing(
            db, business_id=business_id, customer_id=customer_id, clusters=clusters, group_booking_id=group_booking_id
        )
    return _create_group_partial(
        db, business_id=business_id, customer_id=customer_id, clusters=clusters, group_booking_id=group_booking_id
    )


def _create_group_partial(
    db: Session, *, business_id: uuid.UUID, customer_id: uuid.UUID, clusters: list[dict], group_booking_id: uuid.UUID
) -> dict:
    bookings = []
    for cluster in clusters:
        try:
            appointment = create_appointment(
                db,
                business_id=business_id,
                customer_id=customer_id,
                service_id=cluster["service_id"],
                staff_id=cluster["staff_id"],
                scheduled_at=cluster["scheduled_at"],
                group_booking_id=group_booking_id,
                _commit=False,
            )
        except (NotFoundError, UnprocessableEntityError, ConflictError) as exc:
            bookings.append(
                {
                    "labels": cluster["labels"],
                    "success": False,
                    "appointment": None,
                    "message": exc.message,
                    "alternative_slots": _fresh_alternatives(
                        db,
                        business_id=business_id,
                        service_id=cluster["service_id"],
                        staff_id=cluster["staff_id"],
                        around=cluster["scheduled_at"],
                    ),
                }
            )
            # Recorded here, not inside create_appointment itself: this call used
            # _commit=False, so create_appointment's own metric recording (gated
            # on _commit=True) was skipped — each cluster in partial mode is its
            # own independent commit/failure, safe to record immediately (unlike
            # the all-or-nothing batch, no cross-cluster dangling write risk here).
            _record_booking_metric(db, business_id=business_id, result=_booking_metric_result(exc))
            continue
        # Phase 30 fix: the appointment (+ its queued Notification, both written by
        # create_appointment(_commit=False) above) and its AppointmentParticipant
        # rows must land in ONE commit, not two — otherwise a real process crash in
        # the gap between them leaves a confirmed Appointment with no participant
        # attribution (proven live: a real SIGKILL mid-gap left exactly this state).
        # Each cluster is still its own independent commit, so partial-mode's
        # per-person independence is unchanged.
        for label in cluster["labels"]:
            db.add(AppointmentParticipant(appointment_id=appointment.id, name=label))
        db.commit()
        db.refresh(appointment)
        notification = db.execute(
            select(Notification).where(Notification.appointment_id == appointment.id)
        ).scalar_one()
        dispatch_notification(db, notification)
        _record_booking_metric(db, business_id=business_id, result="success")
        bookings.append(
            {
                "labels": cluster["labels"],
                "success": True,
                "appointment": _serialize_appointment(appointment),
                "message": None,
                "alternative_slots": [],
            }
        )
    return {
        "group_booking_id": str(group_booking_id),
        "all_or_nothing": False,
        "success": all(b["success"] for b in bookings),
        "bookings": bookings,
    }


def _create_group_all_or_nothing(
    db: Session, *, business_id: uuid.UUID, customer_id: uuid.UUID, clusters: list[dict], group_booking_id: uuid.UUID
) -> dict:
    failures: dict[int, str] = {}
    for i, cluster in enumerate(clusters):
        try:
            available = get_available_slots(
                db,
                business_id=business_id,
                service_id=cluster["service_id"],
                staff_id=cluster["staff_id"],
                date_from=cluster["scheduled_at"].date(),
                date_to=cluster["scheduled_at"].date(),
            )
        except NotFoundError as exc:
            failures[i] = exc.message
            continue
        if cluster["scheduled_at"] not in available:
            failures[i] = (
                "Requested time is not available (outside business hours, on a closed date, in "
                "the past, or already booked)."
            )

    if failures:
        bookings = [
            {
                "labels": cluster["labels"],
                "success": False,
                "appointment": None,
                "message": failures.get(
                    i, "you asked to book everyone together, and not every slot was available."
                ),
                "alternative_slots": (
                    _fresh_alternatives(
                        db,
                        business_id=business_id,
                        service_id=cluster["service_id"],
                        staff_id=cluster["staff_id"],
                        around=cluster["scheduled_at"],
                    )
                    if i in failures
                    else []
                ),
            }
            for i, cluster in enumerate(clusters)
        ]
        _record_booking_metric(db, business_id=business_id, result="unavailable")
        return {"group_booking_id": str(group_booking_id), "all_or_nothing": True, "success": False, "bookings": bookings}

    try:
        appointments = [
            create_appointment(
                db,
                business_id=business_id,
                customer_id=customer_id,
                service_id=cluster["service_id"],
                staff_id=cluster["staff_id"],
                scheduled_at=cluster["scheduled_at"],
                group_booking_id=group_booking_id,
                _commit=False,
            )
            for cluster in clusters
        ]
    except (NotFoundError, UnprocessableEntityError, ConflictError) as exc:
        # A genuine race: something changed between the pre-check above and this
        # write pass. A ConflictError means create_appointment's own IntegrityError
        # handler already rolled back the whole transaction; a NotFoundError/
        # UnprocessableEntityError from a LATER cluster (a service/staff deleted
        # mid-batch — narrow, pre-existing edge case) would NOT have — this
        # explicit rollback (a safe no-op in the already-rolled-back case) is what
        # makes it safe for _record_booking_metric below to commit: without it,
        # that commit could accidentally durable-write an earlier cluster's
        # dangling flushed-but-never-meant-to-be-committed Appointment row.
        # Nothing has been committed either way — honestly report every requested
        # slot as not booked, never a partial write.
        db.rollback()
        bookings = [
            {
                "labels": cluster["labels"],
                "success": False,
                "appointment": None,
                "message": exc.message,
                "alternative_slots": [],
            }
            for cluster in clusters
        ]
        _record_booking_metric(db, business_id=business_id, result=_booking_metric_result(exc))
        return {"group_booking_id": str(group_booking_id), "all_or_nothing": True, "success": False, "bookings": bookings}

    for cluster, appointment in zip(clusters, appointments):
        for label in cluster["labels"]:
            db.add(AppointmentParticipant(appointment_id=appointment.id, name=label))
    db.commit()
    for appointment in appointments:
        db.refresh(appointment)
    _record_booking_metric(db, business_id=business_id, result="success")

    # Each create_appointment(..., _commit=False) call above already queued a
    # booking-confirmation Notification but deliberately didn't dispatch it —
    # nothing was committed yet at that point. Dispatch now, scoped to exactly
    # these appointments (not "every queued notification for the business")
    # so a concurrent, unrelated booking's own notification is never touched.
    appointment_ids = [appointment.id for appointment in appointments]
    notifications = db.execute(
        select(Notification).where(Notification.appointment_id.in_(appointment_ids))
    ).scalars()
    for notification in notifications:
        dispatch_notification(db, notification)

    bookings = [
        {
            "labels": cluster["labels"],
            "success": True,
            "appointment": _serialize_appointment(appointment),
            "message": None,
            "alternative_slots": [],
        }
        for cluster, appointment in zip(clusters, appointments)
    ]
    return {"group_booking_id": str(group_booking_id), "all_or_nothing": True, "success": True, "bookings": bookings}


def cancel_appointment(db: Session, *, business_id: uuid.UUID, appointment_id: uuid.UUID) -> Appointment:
    """The ONLY path that cancels an Appointment. Releases the slot immediately —
    the Phase 10 exclusion constraint's WHERE clause already excludes CANCELLED
    rows, so a fresh get_available_slots call reflects this the instant it
    commits, no separate "free the slot" step needed. Also queues a Notification
    (real send is Phase 15/18) so the data model is exercised now."""
    appointment = get_appointment(db, business_id=business_id, appointment_id=appointment_id)
    if appointment is None:
        raise NotFoundError("Appointment not found.")
    if appointment.status not in _CANCELLABLE_STATUSES:
        raise UnprocessableEntityError(
            f"This appointment is already {appointment.status.value} and cannot be cancelled."
        )

    appointment.status = AppointmentStatus.CANCELLED
    business = db.get(Business, business_id)
    customer = db.get(Customer, appointment.customer_id)
    notification = Notification(
        business_id=business_id,
        appointment_id=appointment.id,
        channel=_notification_channel(business, customer),
        event_type="appointment_cancelled",
        status=NotificationStatus.QUEUED,
    )
    db.add(notification)
    db.commit()
    db.refresh(appointment)
    db.refresh(notification)
    dispatch_notification(db, notification)
    return appointment


def reschedule_appointment(
    db: Session, *, business_id: uuid.UUID, appointment_id: uuid.UUID, new_scheduled_at: datetime
) -> Appointment:
    """The ONLY path that reschedules an Appointment. Updates the same row in
    place (not cancel-old/create-new) so the booking ID never changes — the
    Phase 10 exclusion constraint is enforced by Postgres on UPDATE exactly like
    it is on INSERT, so this reuses the identical race-proof guarantee with no
    new DB object needed. An AuditLog row records the appointment moved (with the
    time it moved FROM — the row itself already shows what it moved TO), so this
    is never a silent mutation with no trace.

    The pre-check below deliberately checks ONLY structural validity (business
    hours, closed days, past times) via `_ignore_conflicts=True` — it does NOT
    check for an existing overlapping appointment. A prior version checked both
    in one `scheduled_at not in available` test, which meant "genuinely invalid
    slot" and "someone already holds this slot" both surfaced as the same 422.
    Under concurrency this was worse than cosmetic: two requests racing for the
    same slot would inconsistently get [200, 422] or [200, 409] depending purely
    on whether the loser's SELECT happened to run before or after the winner's
    COMMIT — the same underlying conflict, surfacing two different HTTP status
    codes and error shapes for no semantic reason. Every "already booked" case —
    racy or not — is now left entirely to the DB exclusion constraint, so the
    loser always gets a clean 409 Conflict, never a validation-shaped 422."""
    appointment = get_appointment(db, business_id=business_id, appointment_id=appointment_id)
    if appointment is None:
        raise NotFoundError("Appointment not found.")
    if appointment.status not in _CANCELLABLE_STATUSES:
        raise UnprocessableEntityError(
            f"This appointment is already {appointment.status.value} and cannot be rescheduled."
        )

    structurally_open = get_available_slots(
        db,
        business_id=business_id,
        service_id=appointment.service_id,
        staff_id=appointment.staff_id,
        date_from=new_scheduled_at.date(),
        date_to=new_scheduled_at.date(),
        _ignore_conflicts=True,
    )
    if new_scheduled_at not in structurally_open:
        raise UnprocessableEntityError(
            "Requested time is not available (outside business hours, on a closed date, or in the past)."
        )

    previous_scheduled_at = appointment.scheduled_at
    appointment.scheduled_at = new_scheduled_at
    db.add(
        AuditLog(
            business_id=business_id,
            actor="system",
            action="appointment_rescheduled",
            resource_type="appointment",
            resource_id=str(appointment.id),
            result=f"moved_from={previous_scheduled_at.isoformat()}",
        )
    )
    business = db.get(Business, business_id)
    customer = db.get(Customer, appointment.customer_id)
    notification = Notification(
        business_id=business_id,
        appointment_id=appointment.id,
        channel=_notification_channel(business, customer),
        event_type="appointment_rescheduled",
        status=NotificationStatus.QUEUED,
    )
    db.add(notification)
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        raise ConflictError("This slot was just booked by someone else — please choose another time.")
    db.refresh(appointment)
    db.refresh(notification)
    dispatch_notification(db, notification)
    return appointment


def get_appointment(db: Session, *, business_id: uuid.UUID, appointment_id: uuid.UUID) -> Appointment | None:
    return db.execute(
        select(Appointment).where(Appointment.id == appointment_id, Appointment.business_id == business_id)
    ).scalar_one_or_none()


def list_appointments(
    db: Session,
    *,
    business_id: uuid.UUID,
    customer_id: uuid.UUID | None = None,
    status: AppointmentStatus | None = None,
    date_from: date | None = None,
    date_to: date | None = None,
    group_booking_id: uuid.UUID | None = None,
    limit: int = 50,
    offset: int = 0,
) -> list[Appointment]:
    filters = [Appointment.business_id == business_id]
    if customer_id is not None:
        filters.append(Appointment.customer_id == customer_id)
    if status is not None:
        filters.append(Appointment.status == status)
    if group_booking_id is not None:
        filters.append(Appointment.group_booking_id == group_booking_id)
    if date_from is not None or date_to is not None:
        # date_from/date_to are calendar dates in the business's own timezone, not
        # UTC — resolve against the real Business row rather than assuming UTC.
        business = db.get(Business, business_id)
        tz = ZoneInfo(business.timezone) if business is not None else ZoneInfo("UTC")
        if date_from is not None:
            filters.append(Appointment.scheduled_at >= datetime.combine(date_from, time.min, tzinfo=tz))
        if date_to is not None:
            filters.append(Appointment.scheduled_at < datetime.combine(date_to + timedelta(days=1), time.min, tzinfo=tz))
    return list(
        db.execute(
            select(Appointment).where(*filters).order_by(Appointment.scheduled_at).limit(limit).offset(offset)
        ).scalars()
    )
