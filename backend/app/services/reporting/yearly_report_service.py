import calendar
import uuid
from collections import Counter
from decimal import Decimal

from sqlalchemy.orm import Session

from app.core.exceptions import NotFoundError
from app.db.models.business import Business
from app.services.reporting.monthly_report_service import generate_monthly_report

# Phase 37 — the real yearly report. Deliberately built by calling
# generate_monthly_report (Phase 17) 12 times and aggregating its real
# output, per this ticket's own "Phase 17's monthly logic is the template —
# reuse its patterns, don't reinvent" instruction. This also means every
# number here can never disagree with what GET /reports/monthly already
# shows for any given month of the year — there is exactly one place each
# underlying query lives.


def _aggregate_year(db: Session, *, business_id: uuid.UUID, year: int) -> tuple[dict, bool]:
    """Returns (report_dict, has_real_activity). has_real_activity is used by
    generate_yearly_report to decide whether a prior year is a real baseline
    or an empty one that would fabricate a comparison if used."""
    business = db.get(Business, business_id)
    if business is None:
        raise NotFoundError("Business not found.")

    # ponytail: 12 real monthly aggregations per year (24 when year-over-year
    # pulls in the prior year too) — fine at this app's real data volume;
    # collapse into dedicated year-range queries if a business's appointment
    # count ever makes this measurably slow.
    months = [generate_monthly_report(db, business_id=business_id, year=year, month=m) for m in range(1, 13)]

    total_conversations = sum(m["conversations"]["total"] for m in months)
    total_new_customers = sum(m["customers"]["new"] for m in months)
    total_requested = sum(m["appointments"]["requested"] for m in months)
    total_scheduled = sum(m["appointments"]["scheduled_for_month"] for m in months)
    total_cancelled = sum(m["appointments"]["cancelled_of_scheduled"] for m in months)
    total_completed = sum(m["appointments"]["completed"]["count"] for m in months)
    total_reschedule_events = sum(m["appointments"]["rescheduled"]["events"] for m in months)
    total_revenue = sum((Decimal(m["revenue_estimate"]["value"]) for m in months), Decimal("0.00"))
    total_revenue_appointment_count = sum(m["revenue_estimate"]["appointment_count"] for m in months)

    month_by_month = [
        {
            "month": m["month"],
            "month_name": calendar.month_name[m["month"]],
            "appointments_requested": m["appointments"]["requested"],
            "appointments_scheduled": m["appointments"]["scheduled_for_month"],
            "cancelled": m["appointments"]["cancelled_of_scheduled"],
            "revenue_estimate": m["revenue_estimate"]["value"],
        }
        for m in months
    ]

    # Re-aggregate most_requested_services across all 12 months' already-real
    # per-month counts — same "exclude cancelled" population each monthly
    # report already applied, just summed here rather than re-queried.
    service_totals: Counter = Counter()
    service_names: dict[str, str | None] = {}
    for m in months:
        for s in m["most_requested_services"]:
            if s["service_id"] is None:
                continue
            service_totals[s["service_id"]] += s["count"]
            service_names[s["service_id"]] = s["service_name"]
    most_requested_services = [
        {"service_id": sid, "service_name": service_names.get(sid), "count": count}
        for sid, count in sorted(service_totals.items(), key=lambda kv: -kv[1])
    ]

    cancellation_rate_value = (total_cancelled / total_scheduled) if total_scheduled else None
    booking_conversion_value = (total_requested / total_conversations) if total_conversations else None

    has_real_activity = bool(total_requested or total_scheduled or total_conversations or total_new_customers)

    report = {
        "business_id": str(business_id),
        "business_name": business.name,
        "timezone": business.timezone,
        "year": year,
        "period_label": str(year),
        "conversations": {"total": total_conversations},
        "customers": {"new": total_new_customers},
        "appointments": {
            "requested": total_requested,
            "scheduled_for_year": total_scheduled,
            "cancelled_of_scheduled": total_cancelled,
            "completed": {
                "count": total_completed,
                "implemented": months[0]["appointments"]["completed"]["implemented"],
                "note": months[0]["appointments"]["completed"]["note"],
            },
            "rescheduled": {"events": total_reschedule_events},
        },
        "cancellation_rate": {
            "value": cancellation_rate_value,
            "numerator": total_cancelled,
            "denominator": total_scheduled,
            "definition": (
                "Of appointments SCHEDULED for this year (any current status, summed across all 12 "
                "real monthly reports), the fraction whose current status is CANCELLED."
            ),
        },
        "booking_conversion": {
            "value": booking_conversion_value,
            "numerator": total_requested,
            "denominator": total_conversations,
            "definition": (
                "Appointments requested (created) this year ÷ total conversations this year — the same "
                "honest proxy as the monthly report's booking_conversion, summed across all 12 months."
            ),
        },
        "revenue_estimate": {
            "value": str(total_revenue),
            "appointment_count": total_revenue_appointment_count,
            "definition": (
                "Sum of the 12 real monthly revenue_estimate figures for this year. "
                + months[0]["revenue_estimate"]["definition"]
            ),
        },
        "month_by_month": month_by_month,
        "most_requested_services": most_requested_services,
    }
    return report, has_real_activity


def _pct_change(current: float, prior: float) -> float | None:
    return (current - prior) / prior if prior else None


def generate_yearly_report(
    db: Session, *, business_id: uuid.UUID, year: int, _include_year_over_year: bool = True
) -> dict:
    """The real yearly report — gated to BusinessPlan.PREMIUM at the route
    layer (require_plan), same mechanism Phase 34 built.

    Year-over-year is only included when the prior year has real recorded
    activity — comparing against a genuinely empty year would be a fabricated
    "+infinite%" or misleading 0-baseline comparison, not an honest one, per
    this ticket's own "don't fabricate a comparison with no real prior data."
    `_include_year_over_year=False` is used internally for the one-level-deep
    recursive call for the PRIOR year itself, so this never recurses twice.
    """
    report, _has_activity = _aggregate_year(db, business_id=business_id, year=year)

    if not _include_year_over_year:
        return report

    prior_report, prior_has_activity = _aggregate_year(db, business_id=business_id, year=year - 1)

    if not prior_has_activity:
        report["year_over_year"] = {
            "available": False,
            "prior_year": year - 1,
            "note": (
                f"No real activity recorded for {year - 1} — a year-over-year comparison is not shown "
                "rather than fabricated against an empty baseline."
            ),
        }
        return report

    current_scheduled = report["appointments"]["scheduled_for_year"]
    prior_scheduled = prior_report["appointments"]["scheduled_for_year"]
    current_revenue = float(report["revenue_estimate"]["value"])
    prior_revenue = float(prior_report["revenue_estimate"]["value"])
    current_customers = report["customers"]["new"]
    prior_customers = prior_report["customers"]["new"]

    report["year_over_year"] = {
        "available": True,
        "prior_year": year - 1,
        "appointments_scheduled": {
            "current": current_scheduled,
            "prior": prior_scheduled,
            "change_pct": _pct_change(current_scheduled, prior_scheduled),
        },
        "revenue_estimate": {
            "current": report["revenue_estimate"]["value"],
            "prior": prior_report["revenue_estimate"]["value"],
            "change_pct": _pct_change(current_revenue, prior_revenue),
        },
        "new_customers": {
            "current": current_customers,
            "prior": prior_customers,
            "change_pct": _pct_change(current_customers, prior_customers),
        },
    }
    return report
