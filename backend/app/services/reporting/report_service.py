import uuid
from collections import defaultdict
from datetime import date, datetime, time, timedelta
from decimal import Decimal
from zoneinfo import ZoneInfo

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.exceptions import NotFoundError
from app.db.models.appointment import Appointment, AppointmentStatus
from app.db.models.audit_log import AuditLog
from app.db.models.business import Business
from app.db.models.customer import Customer
from app.db.models.handoff import HumanHandoff
from app.db.models.service import Service
from app.db.models.staff import Staff
from app.services.notifications.base import NotificationDeliveryError
from app.services.notifications.email_provider import EmailNotificationProvider
from app.services.notifications.templates.render import render_daily_report_email
from app.services.reporting.excel_export import report_to_xlsx_bytes

_RESCHEDULE_ACTION = "appointment_rescheduled"

# Shared wording (daily/monthly/yearly all use this exact text) — deliberately
# still not called "revenue" even after Phase 44 (real eSewa/Khalti deposit
# tracking) and Phase 46 (real AppointmentStatus.COMPLETED via QR check-in):
# both are REAL now, but neither makes this figure exact. Payment tracking
# only exists for services with deposit_enabled=true (most services have no
# Payment row at all — pay-in-person, untracked by design, see Phase 44), and
# even a completed appointment's in-person remainder is only recorded when a
# staff member explicitly does so (Payment.collected_in_person_amount, Phase
# 46) — never guaranteed to be filled in. So this stays an ESTIMATE of billed
# value at list price, never presented as confirmed collected revenue.
REVENUE_ESTIMATE_DEFINITION = (
    "Estimated billed value of non-cancelled appointments (any status except CANCELLED) at each "
    "appointment's service list price (Service.price, Phase 4). This is an ESTIMATE of billed "
    "value, not confirmed collected revenue — real payment tracking (Phase 44 online deposits, "
    "Phase 46 in-person collection at check-in) only covers services with a deposit configured "
    "and only when a real payment/collection actually happened, not every appointment's full "
    "price. Not reduced for discounts, taxes, or no-shows."
)


def _sum_service_prices(rows, services: dict) -> Decimal:
    """rows: an iterable of Appointment-like objects with .service_id. Caller
    decides which population to pass in (e.g. already excluding cancelled) —
    this just sums real Service.price values, never fabricates one for a
    service_id it can't resolve."""
    return sum((services[r.service_id].price for r in rows if r.service_id in services), Decimal("0.00"))


def _day_bounds(business: Business, report_date: date) -> tuple[datetime, datetime]:
    """Same local-calendar-day-to-UTC-range resolution booking_service already
    uses for date_from/date_to filters — a business's "day" is its own
    timezone's day, not UTC's."""
    tz = ZoneInfo(business.timezone)
    start = datetime.combine(report_date, time.min, tzinfo=tz)
    return start, start + timedelta(days=1)


def _name_maps(db: Session, *, business_id: uuid.UUID, customer_ids: set, service_ids: set, staff_ids: set) -> tuple[dict, dict, dict]:
    customers = {
        c.id: c
        for c in db.execute(
            select(Customer).where(Customer.business_id == business_id, Customer.id.in_(customer_ids))
        ).scalars()
    } if customer_ids else {}
    services = {
        s.id: s
        for s in db.execute(
            select(Service).where(Service.business_id == business_id, Service.id.in_(service_ids))
        ).scalars()
    } if service_ids else {}
    staff = {
        s.id: s
        for s in db.execute(
            select(Staff).where(Staff.business_id == business_id, Staff.id.in_(staff_ids))
        ).scalars()
    } if staff_ids else {}
    return customers, services, staff


def _appointments_scheduled(
    db: Session, *, business_id: uuid.UUID, start: datetime, end: datetime
) -> tuple[list[dict], Decimal]:
    appointments = list(
        db.execute(
            select(Appointment)
            .where(
                Appointment.business_id == business_id,
                Appointment.scheduled_at >= start,
                Appointment.scheduled_at < end,
            )
            .order_by(Appointment.scheduled_at)
        ).scalars()
    )
    customers, services, staff = _name_maps(
        db,
        business_id=business_id,
        customer_ids={a.customer_id for a in appointments},
        service_ids={a.service_id for a in appointments},
        staff_ids={a.staff_id for a in appointments if a.staff_id},
    )
    rows = [
        {
            "id": str(a.id),
            "scheduled_at": a.scheduled_at.isoformat(),
            "status": a.status.value,
            "customer_name": customers[a.customer_id].name if a.customer_id in customers else None,
            "service_name": services[a.service_id].name if a.service_id in services else None,
            "staff_name": staff[a.staff_id].name if a.staff_id in staff else None,
            "group_booking_id": str(a.group_booking_id) if a.group_booking_id else None,
        }
        for a in appointments
    ]
    revenue_estimate = _sum_service_prices(
        (a for a in appointments if a.status != AppointmentStatus.CANCELLED), services
    )
    return rows, revenue_estimate


def _appointments_cancelled(db: Session, *, business_id: uuid.UUID, start: datetime, end: datetime) -> list[dict]:
    """Cancelled THAT DAY, regardless of original scheduled_at. cancel_appointment
    (Phase 11) is the only code path that ever sets status=CANCELLED, and once
    CANCELLED an appointment is never touched again (_CANCELLABLE_STATUSES gates
    both cancel and reschedule) — so updated_at is a real, reliable proxy for
    "when this cancellation happened," not a guess."""
    cancelled = list(
        db.execute(
            select(Appointment).where(
                Appointment.business_id == business_id,
                Appointment.status == AppointmentStatus.CANCELLED,
                Appointment.updated_at >= start,
                Appointment.updated_at < end,
            )
        ).scalars()
    )
    customers, services, _staff = _name_maps(
        db,
        business_id=business_id,
        customer_ids={a.customer_id for a in cancelled},
        service_ids={a.service_id for a in cancelled},
        staff_ids=set(),
    )
    return [
        {
            "id": str(a.id),
            "originally_scheduled_at": a.scheduled_at.isoformat(),
            "cancelled_at": a.updated_at.isoformat(),
            "customer_name": customers[a.customer_id].name if a.customer_id in customers else None,
            "service_name": services[a.service_id].name if a.service_id in services else None,
        }
        for a in cancelled
    ]


def _appointments_rescheduled(db: Session, *, business_id: uuid.UUID, start: datetime, end: datetime) -> list[dict]:
    """Old -> new time, reconstructed from the real AuditLog trail (Phase 11
    writes one row per reschedule: result="moved_from=<old scheduled_at>").
    reschedule_appointment is the ONLY path that ever changes
    Appointment.scheduled_at, so for a given reschedule event, "new time" is
    exactly the next reschedule event's "moved_from" for the same appointment
    (if the appointment was moved again after), or — if this was the most
    recent reschedule ever recorded for it — the appointment's real current
    scheduled_at. Neither branch is a guess; both follow directly from that
    single-writer guarantee."""
    todays_logs = list(
        db.execute(
            select(AuditLog)
            .where(
                AuditLog.business_id == business_id,
                AuditLog.action == _RESCHEDULE_ACTION,
                AuditLog.created_at >= start,
                AuditLog.created_at < end,
            )
            .order_by(AuditLog.created_at)
        ).scalars()
    )
    if not todays_logs:
        return []

    appointment_ids = {uuid.UUID(log.resource_id) for log in todays_logs}
    all_logs = list(
        db.execute(
            select(AuditLog)
            .where(
                AuditLog.business_id == business_id,
                AuditLog.action == _RESCHEDULE_ACTION,
                AuditLog.resource_id.in_([str(i) for i in appointment_ids]),
            )
            .order_by(AuditLog.resource_id, AuditLog.created_at)
        ).scalars()
    )
    chains: dict[str, list[AuditLog]] = defaultdict(list)
    for log in all_logs:
        chains[log.resource_id].append(log)
    position_by_log_id = {log.id: i for chain in chains.values() for i, log in enumerate(chain)}

    appointments = {
        a.id: a
        for a in db.execute(select(Appointment).where(Appointment.id.in_(appointment_ids))).scalars()
    }
    customers, services, _staff = _name_maps(
        db,
        business_id=business_id,
        customer_ids={a.customer_id for a in appointments.values()},
        service_ids={a.service_id for a in appointments.values()},
        staff_ids=set(),
    )

    def _parse_moved_from(log: AuditLog) -> datetime:
        return datetime.fromisoformat(log.result.removeprefix("moved_from="))

    rows = []
    for log in todays_logs:
        appointment_id = uuid.UUID(log.resource_id)
        chain = chains[log.resource_id]
        idx = position_by_log_id[log.id]
        old_time = _parse_moved_from(log)
        if idx + 1 < len(chain):
            new_time = _parse_moved_from(chain[idx + 1])
        else:
            appt = appointments.get(appointment_id)
            new_time = appt.scheduled_at if appt is not None else None
        appt = appointments.get(appointment_id)
        rows.append(
            {
                "id": str(appointment_id),
                "old_scheduled_at": old_time.isoformat(),
                "new_scheduled_at": new_time.isoformat() if new_time else None,
                "changed_at": log.created_at.isoformat(),
                "customer_name": customers[appt.customer_id].name if appt and appt.customer_id in customers else None,
                "service_name": services[appt.service_id].name if appt and appt.service_id in services else None,
            }
        )
    return rows


def _new_leads(db: Session, *, business_id: uuid.UUID, start: datetime, end: datetime) -> list[dict]:
    customers = list(
        db.execute(
            select(Customer)
            .where(Customer.business_id == business_id, Customer.created_at >= start, Customer.created_at < end)
            .order_by(Customer.created_at)
        ).scalars()
    )
    return [
        {
            "id": str(c.id),
            "name": c.name,
            "phone": c.phone,
            "email": c.email,
            "created_at": c.created_at.isoformat(),
        }
        for c in customers
    ]


def _human_review(db: Session, *, business_id: uuid.UUID) -> dict:
    """Phase 16 flagged this as always-zero (HumanHandoff had no real
    producer). Phase 19 added the real producer (app.services.handoff_service,
    called from the conversation orchestrator), so this is now a real,
    currently-open-handoff count — no code here changed except the flag/note
    reflecting that, exactly as Phase 16 anticipated."""
    open_count = db.execute(
        select(HumanHandoff).where(HumanHandoff.business_id == business_id, HumanHandoff.resolved_at.is_(None))
    ).scalars().all()
    return {
        "count": len(open_count),
        "implemented": True,
        "note": "Real count of currently-open human handoffs for this business.",
    }


def generate_daily_report(db: Session, *, business_id: uuid.UUID, report_date: date) -> dict:
    """The single source of truth for a business's daily report — real queries
    against real current data only, no LLM, no estimation. Both the JSON
    endpoint and the Excel export call this exact function so they can never
    disagree with each other."""
    business = db.get(Business, business_id)
    if business is None:
        raise NotFoundError("Business not found.")

    start, end = _day_bounds(business, report_date)
    appointments, revenue_estimate = _appointments_scheduled(db, business_id=business_id, start=start, end=end)
    cancellations = _appointments_cancelled(db, business_id=business_id, start=start, end=end)
    reschedules = _appointments_rescheduled(db, business_id=business_id, start=start, end=end)
    new_leads = _new_leads(db, business_id=business_id, start=start, end=end)
    human_review = _human_review(db, business_id=business_id)

    status_counts: dict[str, int] = defaultdict(int)
    for a in appointments:
        status_counts[a["status"]] += 1

    return {
        "business_id": str(business_id),
        "business_name": business.name,
        "timezone": business.timezone,
        "report_date": report_date.isoformat(),
        "appointments": appointments,
        "cancellations": cancellations,
        "reschedules": reschedules,
        "new_leads": new_leads,
        "human_review": human_review,
        "revenue_estimate": {
            "value": str(revenue_estimate),
            "appointment_count": sum(1 for a in appointments if a["status"] != "cancelled"),
            "definition": REVENUE_ESTIMATE_DEFINITION,
        },
        "summary": {
            "appointments_scheduled": len(appointments),
            "appointments_by_status": dict(status_counts),
            "cancellations": len(cancellations),
            "reschedules": len(reschedules),
            "new_leads": len(new_leads),
            "human_review_open_count": human_review["count"],
        },
    }


def _daily_report_rows(report: dict) -> list[tuple[str, int]]:
    """Shared between the plain-text body and the HTML summary table (Phase
    17) so the two can never show different numbers — both read this exact
    list, which itself just echoes report["summary"]."""
    s = report["summary"]
    human_review_label = "Conversations needing human review"
    if not report["human_review"]["implemented"]:
        human_review_label += " (feature not yet implemented — always 0 today)"
    return [
        ("Appointments Scheduled", s["appointments_scheduled"]),
        ("Cancellations", s["cancellations"]),
        ("Reschedules", s["reschedules"]),
        ("New Leads", s["new_leads"]),
        (human_review_label, s["human_review_open_count"]),
    ]


def _compose_report_email_body(report: dict) -> str:
    """Deterministic Python text, no LLM — same discipline as
    app.services.notifications.content.compose_email."""
    lines = "\n".join(f"{label}: {value}" for label, value in _daily_report_rows(report))
    return (
        f"Hi,\n\nHere is the daily operations report for {report['business_name']} on {report['report_date']}.\n\n"
        f"{lines}\n\n"
        f"Full detail is attached as an Excel file.\n"
    )


def send_daily_report_email(db: Session, *, business_id: uuid.UUID, report_date: date) -> dict:
    """Real, callable admin action — not a cron job. No scheduler/worker
    infrastructure exists in this codebase yet (Phase 13 already flagged this
    same gap for dispatch_queued_notifications), so real automatic 6am
    delivery is an honest, explicitly deferred later-infrastructure phase, not
    something faked here. Recipient is business.email (Phase 4's existing
    field) — a dedicated, separately-configurable "report email"/report time
    per the master plan is a real nice-to-have, deferred (see
    PHASE_STATUS.md); business.email is the documented default this ticket
    itself named.

    Never raises: a send failure is reported back as data (sent=False +
    reason), the same "don't crash the caller" discipline as
    dispatch_service.dispatch_notification, just returned synchronously since
    this is a direct admin-triggered action rather than an inline
    booking-flow side effect."""
    report = generate_daily_report(db, business_id=business_id, report_date=report_date)
    business = db.get(Business, business_id)
    recipient = business.email if business else None
    if not recipient:
        return {
            "sent": False,
            "recipient": None,
            "reason": "Business has no report email on file (Business.email is empty) — set one via PATCH /business/me.",
        }

    xlsx_bytes = report_to_xlsx_bytes(report)
    filename = f"daily_report_{report_date.isoformat()}.xlsx"
    subject = f"{business.name} — Daily Report for {report_date.isoformat()}"
    body = _compose_report_email_body(report)
    html_body = render_daily_report_email(
        business_name=business.name,
        business_address=business.address,
        business_phone=business.phone,
        business_email=business.email,
        period_label=f"Report for {report_date.isoformat()}",
        rows=_daily_report_rows(report),
    )

    try:
        detail = EmailNotificationProvider().send(
            to=recipient,
            subject=subject,
            body=body,
            html_body=html_body,
            attachments=[
                (filename, xlsx_bytes, "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")
            ],
        )
    except NotificationDeliveryError as exc:
        return {"sent": False, "recipient": recipient, "reason": str(exc), "transient": exc.transient}

    return {
        "sent": True,
        "recipient": recipient,
        "detail": detail,
        "attachment_filename": filename,
        "attachment_size_bytes": len(xlsx_bytes),
    }
