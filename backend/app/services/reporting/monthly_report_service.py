import calendar
import uuid
from collections import Counter
from datetime import datetime
from zoneinfo import ZoneInfo

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.exceptions import NotFoundError
from app.db.models.appointment import Appointment, AppointmentStatus
from app.db.models.audit_log import AuditLog
from app.db.models.business import Business
from app.db.models.conversation import Conversation
from app.db.models.customer import Customer
from app.services.notifications.base import NotificationDeliveryError
from app.services.notifications.email_provider import EmailNotificationProvider
from app.services.notifications.templates.render import render_monthly_report_email
from app.services.reporting.excel_export import monthly_report_to_xlsx_bytes
from app.services.reporting.report_service import _name_maps

_RESCHEDULE_ACTION = "appointment_rescheduled"
_WEEKDAY_NAMES = list(calendar.day_name)  # ["Monday", ..., "Sunday"]


def _month_bounds(business: Business, year: int, month: int) -> tuple[datetime, datetime]:
    """Same local-calendar-boundary discipline as the daily report's
    _day_bounds — a business's "month" is its own timezone's month, not
    UTC's. `month` is validated 1-12 at the route layer (FastAPI Query
    constraint); an out-of-range value here would raise from `datetime()`
    itself, which is an acceptable, honest 500 for a value the route already
    guards against reaching this function in practice."""
    tz = ZoneInfo(business.timezone)
    start = datetime(year, month, 1, tzinfo=tz)
    end = datetime(year + 1, 1, 1, tzinfo=tz) if month == 12 else datetime(year, month + 1, 1, tzinfo=tz)
    return start, end


def _count(db: Session, *filters) -> int:
    return db.execute(select(func.count()).select_from(Appointment).where(*filters)).scalar_one()


def generate_monthly_report(db: Session, *, business_id: uuid.UUID, year: int, month: int) -> dict:
    """Real DB-derived monthly aggregates only — no LLM commentary, per the
    master plan's explicit warning against fabricated analytics. Every number
    here is a real query result; where a concept has no real producer in this
    codebase (appointments_completed — see below), that is reported honestly
    (0 + implemented=False) rather than guessed, the same discipline Phase 16
    established for HumanHandoff.

    METHODOLOGY (stated explicitly, since several of these terms are
    genuinely ambiguous and the ticket asked for an explicit definition):
    - "requested" appointments = Appointment.created_at falls in the month —
      booking demand that ARRIVED this month, regardless of what date the
      appointment itself is/was for.
    - "scheduled for the month" = Appointment.scheduled_at falls in the month
      (any current status) — the real calendar volume for the month. This is
      the single row-set busiest_days/busiest_hours, cancellation_rate, and
      appointments_completed are all derived from, so they share one
      consistent axis (schedule date, current status) rather than mixing a
      schedule-date population with an event-date numerator, which could
      otherwise silently disagree across a month boundary (e.g. an
      appointment scheduled for this month but cancelled next month).
    - cancellation_rate = (of that same scheduled-for-month population) the
      fraction whose CURRENT status is CANCELLED. Deliberately NOT paired
      with "cancellation events that happened during the month" (a different,
      event-dated axis, reported separately below as
      `appointments.cancellation_events_this_month`) — see above.
    - busiest_days/busiest_hours/most_requested_services all EXCLUDE
      currently-cancelled appointments from the scheduled-for-month
      population: a cancelled appointment never actually occupied staff time
      or reflected fulfilled demand, so counting it would overstate real
      workload/popularity.
    - booking_conversion = appointments requested this month ÷ total
      conversations this month. This is an honest proxy, not precise
      per-conversation attribution: this codebase does not persist
      per-conversation/message intent classification anywhere (verified —
      no `intent` column exists on Message or Conversation; Phase 8's
      classification happens in memory, per turn, and is never stored), so
      "conversations that had real booking intent" cannot be queried
      directly. A future phase persisting intent per turn would let this
      become a precise "true booking-intent conversion" metric instead of
      this proxy.
    """
    business = db.get(Business, business_id)
    if business is None:
        raise NotFoundError("Business not found.")

    start, end = _month_bounds(business, year, month)
    tz = ZoneInfo(business.timezone)

    conversations_total = db.execute(
        select(func.count())
        .select_from(Conversation)
        .where(Conversation.business_id == business_id, Conversation.created_at >= start, Conversation.created_at < end)
    ).scalar_one()

    new_customers = db.execute(
        select(func.count())
        .select_from(Customer)
        .where(Customer.business_id == business_id, Customer.created_at >= start, Customer.created_at < end)
    ).scalar_one()
    total_customers_at_month_end = db.execute(
        select(func.count())
        .select_from(Customer)
        .where(Customer.business_id == business_id, Customer.created_at < end)
    ).scalar_one()

    appointments_requested = _count(
        db, Appointment.business_id == business_id, Appointment.created_at >= start, Appointment.created_at < end
    )
    cancellation_events = _count(
        db,
        Appointment.business_id == business_id,
        Appointment.status == AppointmentStatus.CANCELLED,
        Appointment.updated_at >= start,
        Appointment.updated_at < end,
    )

    reschedule_resource_ids = list(
        db.execute(
            select(AuditLog.resource_id).where(
                AuditLog.business_id == business_id,
                AuditLog.action == _RESCHEDULE_ACTION,
                AuditLog.created_at >= start,
                AuditLog.created_at < end,
            )
        ).scalars()
    )

    # The single scheduled-for-month row set (any status) — cancellation_rate,
    # appointments_completed, busiest_days/hours, and most_requested_services
    # are all derived from this one query, see METHODOLOGY above.
    scheduled_rows = list(
        db.execute(
            select(Appointment).where(
                Appointment.business_id == business_id,
                Appointment.scheduled_at >= start,
                Appointment.scheduled_at < end,
            )
        ).scalars()
    )
    scheduled_for_month = len(scheduled_rows)
    cancelled_of_scheduled = sum(1 for a in scheduled_rows if a.status == AppointmentStatus.CANCELLED)
    completed_of_scheduled = sum(1 for a in scheduled_rows if a.status == AppointmentStatus.COMPLETED)
    active_rows = [a for a in scheduled_rows if a.status != AppointmentStatus.CANCELLED]

    day_counts = Counter(_WEEKDAY_NAMES[a.scheduled_at.astimezone(tz).weekday()] for a in active_rows)
    hour_counts = Counter(a.scheduled_at.astimezone(tz).hour for a in active_rows)
    service_counts = Counter(a.service_id for a in active_rows)
    _customers, services, _staff = _name_maps(
        db, business_id=business_id, customer_ids=set(), service_ids=set(service_counts), staff_ids=set()
    )

    busiest_days = [
        {"day": day, "count": day_counts.get(day, 0)}
        for day in sorted(_WEEKDAY_NAMES, key=lambda d: (-day_counts.get(d, 0), _WEEKDAY_NAMES.index(d)))
    ]
    busiest_hours = [
        {"hour": hour, "count": count}
        for hour, count in sorted(hour_counts.items(), key=lambda item: (-item[1], item[0]))
    ]
    most_requested_services = [
        {
            "service_id": str(service_id),
            "service_name": services[service_id].name if service_id in services else None,
            "count": count,
        }
        for service_id, count in sorted(service_counts.items(), key=lambda item: -item[1])
    ]

    cancellation_rate_value = (cancelled_of_scheduled / scheduled_for_month) if scheduled_for_month else None
    booking_conversion_value = (appointments_requested / conversations_total) if conversations_total else None

    return {
        "business_id": str(business_id),
        "business_name": business.name,
        "timezone": business.timezone,
        "year": year,
        "month": month,
        "period_label": f"{calendar.month_name[month]} {year}",
        "conversations": {"total": conversations_total},
        "customers": {"new": new_customers, "total_at_month_end": total_customers_at_month_end},
        "appointments": {
            "requested": appointments_requested,
            "scheduled_for_month": scheduled_for_month,
            "cancellation_events_this_month": cancellation_events,
            "cancelled_of_scheduled": cancelled_of_scheduled,
            "completed": {
                "count": completed_of_scheduled,
                "implemented": False,
                "note": (
                    "AppointmentStatus.COMPLETED has no real producer anywhere in this codebase "
                    "(verified by grep) — nothing ever marks an appointment completed, so this is "
                    "honestly always 0 today, not fabricated."
                ),
            },
            "rescheduled": {
                "events": len(reschedule_resource_ids),
                "distinct_appointments": len(set(reschedule_resource_ids)),
            },
        },
        "cancellation_rate": {
            "value": cancellation_rate_value,
            "numerator": cancelled_of_scheduled,
            "denominator": scheduled_for_month,
            "definition": (
                "Of appointments SCHEDULED for this month (any current status), the fraction whose "
                "current status is CANCELLED."
            ),
        },
        "booking_conversion": {
            "value": booking_conversion_value,
            "numerator": appointments_requested,
            "denominator": conversations_total,
            "definition": (
                "Appointments requested (created) this month ÷ total conversations this month. "
                "An honest proxy, not precise per-conversation attribution — this codebase does not "
                "persist per-conversation intent classification (no `intent` column exists on "
                "Message/Conversation), so true 'booking-intent conversations' can't be queried directly."
            ),
        },
        "busiest_days": busiest_days,
        "busiest_hours": busiest_hours,
        "most_requested_services": most_requested_services,
        "methodology_note": (
            "busiest_days/busiest_hours/most_requested_services exclude currently-cancelled "
            "appointments from the scheduled-for-month population (a cancelled appointment never "
            "occupied real staff time)."
        ),
    }


def _monthly_report_rows(report: dict) -> list[tuple[str, object]]:
    """Shared between the plain-text body and the HTML summary table (same
    single-source-of-truth discipline as the daily report's _daily_report_rows)."""
    a = report["appointments"]
    cr = report["cancellation_rate"]
    bc = report["booking_conversion"]
    return [
        ("Conversations", report["conversations"]["total"]),
        ("New Customers", report["customers"]["new"]),
        ("Total Customers (month end)", report["customers"]["total_at_month_end"]),
        ("Appointments Requested", a["requested"]),
        ("Appointments Scheduled This Month", a["scheduled_for_month"]),
        ("Cancellation Events This Month", a["cancellation_events_this_month"]),
        ("Cancellation Rate", f"{cr['value']:.1%}" if cr["value"] is not None else "N/A"),
        ("Booking Conversion", f"{bc['value']:.1%}" if bc["value"] is not None else "N/A"),
        ("Reschedule Events", a["rescheduled"]["events"]),
    ]


def _compose_monthly_report_email_body(report: dict) -> str:
    lines = "\n".join(f"{label}: {value}" for label, value in _monthly_report_rows(report))
    top_days = ", ".join(f"{d['day']} ({d['count']})" for d in report["busiest_days"][:3] if d["count"])
    top_services = ", ".join(f"{s['service_name']} ({s['count']})" for s in report["most_requested_services"][:3])
    return (
        f"Hi,\n\nHere is the monthly report for {report['business_name']} — {report['period_label']}.\n\n"
        f"{lines}\n\n"
        f"Busiest days: {top_days or 'no activity'}\n"
        f"Most-requested services: {top_services or 'no activity'}\n\n"
        f"Full detail is attached as an Excel file.\n"
    )


def send_monthly_report_email(db: Session, *, business_id: uuid.UUID, year: int, month: int) -> dict:
    """Same real, callable-action (not a cron), same never-crash discipline as
    send_daily_report_email — see that function's docstring."""
    report = generate_monthly_report(db, business_id=business_id, year=year, month=month)
    business = db.get(Business, business_id)
    recipient = business.email if business else None
    if not recipient:
        return {
            "sent": False,
            "recipient": None,
            "reason": "Business has no report email on file (Business.email is empty) — set one via PATCH /business/me.",
        }

    xlsx_bytes = monthly_report_to_xlsx_bytes(report)
    filename = f"monthly_report_{year:04d}-{month:02d}.xlsx"
    subject = f"{business.name} — Monthly Report for {report['period_label']}"
    body = _compose_monthly_report_email_body(report)
    top_days = ", ".join(f"{d['day']} ({d['count']})" for d in report["busiest_days"][:3] if d["count"])
    top_services = ", ".join(f"{s['service_name']} ({s['count']})" for s in report["most_requested_services"][:3])
    html_body = render_monthly_report_email(
        business_name=business.name,
        period_label=report["period_label"],
        rows=_monthly_report_rows(report),
        busiest_days=top_days,
        most_requested_services=top_services,
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
