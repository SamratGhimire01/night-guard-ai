import uuid
from datetime import date, datetime, timedelta
from typing import Literal
from zoneinfo import ZoneInfo

from sqlalchemy import extract, func, select
from sqlalchemy.orm import Session

from app.core.exceptions import NotFoundError
from app.db.models.appointment import Appointment, AppointmentStatus
from app.db.models.business import Business

Granularity = Literal["day", "week", "month"]

# Outcomes that say what actually happened to an appointment whose time has come. CONFIRMED/PENDING are still "unknown"
# (upcoming, or too old for the no-show scan to have judged), CANCELLED never had an outcome to judge.
_RESOLVED = (AppointmentStatus.NO_SHOW, AppointmentStatus.ARRIVED, AppointmentStatus.COMPLETED)


def _next_bucket(d: date, granularity: Granularity) -> date:
    if granularity == "day":
        return d + timedelta(days=1)
    if granularity == "week":
        return d + timedelta(days=7)
    return date(d.year + (d.month == 12), d.month % 12 + 1, 1)


def _bucket_start(d: date, granularity: Granularity) -> date:
    """The same bucket start Postgres's date_trunc produces (ISO weeks start Monday)."""
    if granularity == "day":
        return d
    if granularity == "week":
        return d - timedelta(days=d.weekday())
    return d.replace(day=1)


def booking_analytics(
    db: Session, *, business_id: uuid.UUID, date_from: date, date_to: date, granularity: Granularity
) -> dict:
    """Cal.com-style booking analytics for the dashboard, over appointments whose scheduled time falls in
    [date_from, date_to] in the BUSINESS's own timezone. Everything is computed by SQL over real rows.

    * bookings_trend — non-cancelled appointments per day/week/month bucket (empty buckets included, so the chart is
      continuous).
    * no_show_rate — NO_SHOW / (NO_SHOW + ARRIVED + COMPLETED): the share of appointments that reached a recorded
      outcome. Upcoming appointments, and old ones the no-show scan never judged, are in neither side (they are in
      `outcomes` so the UI can say how many were left out); None when nothing has an outcome yet.
    * median_lead_time_hours — the MEDIAN of (scheduled_at - created_at) over non-cancelled appointments, via Postgres's
      percentile_cont(0.5). Deliberately not the mean: a handful of bookings made months ahead drag an average far from
      any typical booking (Cal.com's own finding). Appointments created after their own scheduled time (a staff
      back-fill) have no lead time and are excluded; `lead_time_sample_size` says how many count.
    * popular_slots — non-cancelled appointment counts per (weekday, hour) in local time; weekday 0 = Monday."""
    business = db.get(Business, business_id)
    if business is None:
        raise NotFoundError("Business not found.")

    local = func.timezone(business.timezone, Appointment.scheduled_at)
    in_range = [
        Appointment.business_id == business_id,
        func.date(local) >= date_from,
        func.date(local) <= date_to,
    ]
    live = [*in_range, Appointment.status != AppointmentStatus.CANCELLED]

    bucket_expr = func.date_trunc(granularity, local)
    counts_by_bucket = {
        row[0].date(): row[1]
        for row in db.execute(select(bucket_expr, func.count()).where(*live).group_by(bucket_expr)).all()
    }
    trend, bucket = [], _bucket_start(date_from, granularity)
    while bucket <= date_to:
        trend.append({"period": bucket.isoformat(), "bookings": counts_by_bucket.get(bucket, 0)})
        bucket = _next_bucket(bucket, granularity)

    outcomes = {s.value: 0 for s in AppointmentStatus}
    for status, n in db.execute(
        select(Appointment.status, func.count()).where(*in_range).group_by(Appointment.status)
    ).all():
        outcomes[status.value] = n
    resolved = sum(outcomes[s.value] for s in _RESOLVED)
    no_show_rate = round(100 * outcomes[AppointmentStatus.NO_SHOW.value] / resolved, 1) if resolved else None

    # created_at is a timestamp WITHOUT time zone holding UTC wall-clock (server_default now() under a UTC session);
    # timezone('UTC', ...) says so explicitly instead of leaning on the DB session's TimeZone setting.
    created_utc = func.timezone("UTC", Appointment.created_at)
    lead_seconds = func.extract("epoch", Appointment.scheduled_at - created_utc)
    median_seconds, sample = db.execute(
        select(func.percentile_cont(0.5).within_group(lead_seconds), func.count()).where(
            *live, Appointment.scheduled_at >= created_utc
        )
    ).one()

    weekday_expr, hour_expr = extract("isodow", local), extract("hour", local)
    slots = [
        {"weekday": int(dow) - 1, "hour": int(hour), "count": n}
        for dow, hour, n in db.execute(
            select(weekday_expr, hour_expr, func.count())
            .where(*live)
            .group_by(weekday_expr, hour_expr)
            .order_by(weekday_expr, hour_expr)
        ).all()
    ]

    return {
        "timezone": business.timezone,
        "date_from": date_from.isoformat(),
        "date_to": date_to.isoformat(),
        "granularity": granularity,
        "total_bookings": sum(t["bookings"] for t in trend),
        "bookings_trend": trend,
        "outcomes": outcomes,
        "no_show_rate": no_show_rate,
        "no_show_denominator": resolved,
        "median_lead_time_hours": round(median_seconds / 3600, 1) if median_seconds is not None else None,
        "lead_time_sample_size": sample,
        "popular_slots": slots,
    }


def default_range(today: date) -> tuple[date, date]:
    return today - timedelta(days=89), today


def local_today(business: Business) -> date:
    return datetime.now(ZoneInfo(business.timezone)).date()
