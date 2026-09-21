# ruff: noqa: F811  (fixtures imported from the Phase 45 suite are re-declared as test arguments — the pytest idiom)
"""Phase 48 — dashboard booking analytics (`GET /reports/analytics`): bookings trend, no-show rate, MEDIAN lead time,
popular (weekday x hour) slots. Seeded with known rows so every number is checked against an independent Python
computation, in a non-UTC business timezone so local-time bucketing is exercised.
"""

import statistics
import uuid
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

import pytest
from fastapi.testclient import TestClient

from app.core.security import create_access_token
from app.db.database import SessionLocal
from app.db.models.appointment import Appointment, AppointmentStatus
from app.db.models.business import Business, BusinessUser, BusinessUserRole
from app.main import app
from tests.integration.test_reminders import _auth_header, _unique_email, business_ready  # noqa: F401

client = TestClient(app)
KTM = ZoneInfo("Asia/Kathmandu")  # UTC+5:45


@pytest.fixture
def kathmandu(business_ready):
    with SessionLocal() as db:
        db.get(Business, business_ready["business_id"]).timezone = "Asia/Kathmandu"
        db.commit()
    return business_ready


def _add(ctx, local_dt: datetime, *, lead_hours: float, status=AppointmentStatus.CONFIRMED) -> None:
    """One appointment at a Kathmandu wall-clock time, created `lead_hours` before it was scheduled."""
    scheduled = local_dt.replace(tzinfo=KTM).astimezone(timezone.utc)
    with SessionLocal() as db:
        db.add(
            Appointment(
                business_id=ctx["business_id"], customer_id=ctx["customer_id"], service_id=ctx["service_id"],
                staff_id=None, scheduled_at=scheduled, duration_minutes=30, status=status,
                created_at=scheduled - timedelta(hours=lead_hours),
            )
        )
        db.commit()


def _get(ctx, **params) -> dict:
    resp = client.get("/api/v1/reports/analytics", params=params, headers=_auth_header(ctx["token"]))
    assert resp.status_code == 200, resp.text
    return resp.json()


# Mon 2026-08-03 .. Sun 2026-08-09 (week 1), Mon 08-10.. (week 2). Lead times chosen so mean and median differ hugely.
def _seed(ctx):
    d = datetime
    _add(ctx, d(2026, 8, 3, 10, 0), lead_hours=1, status=AppointmentStatus.COMPLETED)        # Mon 10
    _add(ctx, d(2026, 8, 3, 10, 30), lead_hours=2, status=AppointmentStatus.ARRIVED)         # Mon 10
    _add(ctx, d(2026, 8, 4, 15, 0), lead_hours=3, status=AppointmentStatus.NO_SHOW)          # Tue 15
    _add(ctx, d(2026, 8, 5, 10, 0), lead_hours=4, status=AppointmentStatus.COMPLETED)        # Wed 10
    _add(ctx, d(2026, 8, 11, 9, 0), lead_hours=2000, status=AppointmentStatus.NO_SHOW)       # Tue 09, week 2, made ~83 days ahead
    _add(ctx, d(2026, 8, 11, 12, 0), lead_hours=5, status=AppointmentStatus.CANCELLED)       # excluded from bookings/lead/slots
    _add(ctx, d(2026, 8, 12, 12, 0), lead_hours=6, status=AppointmentStatus.CONFIRMED)       # outcome still unknown
    # 00:45 local on Sat 08-08 is 19:00 UTC on Fri 08-07: must bucket as SATURDAY hour 0 (local), not Friday 19
    _add(ctx, d(2026, 8, 8, 0, 45), lead_hours=10, status=AppointmentStatus.COMPLETED)


def test_median_lead_time_is_a_real_median_not_a_mean(kathmandu):
    _seed(kathmandu)
    data = _get(kathmandu, date_from="2026-08-03", date_to="2026-08-16", granularity="week")
    leads = [1, 2, 3, 4, 2000, 6, 10]  # every non-cancelled row's lead time in hours
    assert data["lead_time_sample_size"] == 7
    assert data["median_lead_time_hours"] == statistics.median(leads) == 4
    assert statistics.mean(leads) > 250, "the seed really does have a mean far from any typical booking"
    assert data["median_lead_time_hours"] != round(statistics.mean(leads), 1)


def test_median_of_an_even_count_averages_the_two_middle_values(kathmandu):
    for i, lead in enumerate([1, 2, 3, 10]):
        _add(kathmandu, datetime(2026, 8, 3, 9 + i, 0), lead_hours=lead)
    assert _get(kathmandu, date_from="2026-08-03", date_to="2026-08-03")["median_lead_time_hours"] == 2.5


def test_no_show_rate_uses_only_appointments_with_a_recorded_outcome(kathmandu):
    _seed(kathmandu)
    data = _get(kathmandu, date_from="2026-08-03", date_to="2026-08-16")
    # outcomes: NO_SHOW x2, ARRIVED x1, COMPLETED x3 -> 2 / 6; the CONFIRMED and CANCELLED rows are in neither side
    assert data["outcomes"]["no_show"] == 2 and data["outcomes"]["completed"] == 3 and data["outcomes"]["arrived"] == 1
    assert data["outcomes"]["confirmed"] == 1 and data["outcomes"]["cancelled"] == 1
    assert data["no_show_denominator"] == 6 and data["no_show_rate"] == 33.3


def test_no_show_rate_is_none_when_nothing_has_an_outcome_yet(kathmandu):
    _add(kathmandu, datetime(2026, 8, 3, 10, 0), lead_hours=3)  # CONFIRMED only
    data = _get(kathmandu, date_from="2026-08-03", date_to="2026-08-03")
    assert data["no_show_rate"] is None and data["no_show_denominator"] == 0
    assert data["median_lead_time_hours"] == 3


def test_trend_buckets_by_week_day_and_month_excluding_cancelled_and_filling_gaps(kathmandu):
    _seed(kathmandu)
    weekly = _get(kathmandu, date_from="2026-08-03", date_to="2026-08-16", granularity="week")
    # week of 08-03: Mon x2, Tue, Wed, Sat(local) = 5 ; week of 08-10: Tue 08-11 09:00 + Wed 08-12 (Tue-noon is cancelled) = 2
    assert weekly["bookings_trend"] == [{"period": "2026-08-03", "bookings": 5}, {"period": "2026-08-10", "bookings": 2}]
    assert weekly["total_bookings"] == 7  # 8 rows minus the cancelled one

    daily = _get(kathmandu, date_from="2026-08-03", date_to="2026-08-09", granularity="day")
    by_day = {t["period"]: t["bookings"] for t in daily["bookings_trend"]}
    assert len(daily["bookings_trend"]) == 7 and by_day["2026-08-03"] == 2 and by_day["2026-08-06"] == 0
    assert by_day["2026-08-08"] == 1, "00:45 local belongs to Saturday the 8th, not Friday the 7th (its UTC date)"
    assert by_day["2026-08-07"] == 0

    monthly = _get(kathmandu, date_from="2026-07-15", date_to="2026-09-10", granularity="month")
    assert [(t["period"], t["bookings"]) for t in monthly["bookings_trend"]] == [
        ("2026-07-01", 0), ("2026-08-01", 7), ("2026-09-01", 0)
    ]


def test_popular_slots_are_weekday_by_hour_in_local_time_without_cancelled(kathmandu):
    _seed(kathmandu)
    slots = {(s["weekday"], s["hour"]): s["count"] for s in _get(kathmandu, date_from="2026-08-03", date_to="2026-08-16")["popular_slots"]}
    assert slots[(0, 10)] == 2  # Monday 10:xx
    assert slots[(1, 15)] == 1 and slots[(1, 9)] == 1  # Tuesday 15:00 and 09:00
    assert slots[(5, 0)] == 1, "Saturday 00:45 local"
    assert (1, 12) not in slots, "the cancelled Tuesday-noon booking never counts"
    assert sum(slots.values()) == 7


def test_only_appointments_inside_the_range_count(kathmandu):
    _seed(kathmandu)
    data = _get(kathmandu, date_from="2026-08-04", date_to="2026-08-04")
    assert data["total_bookings"] == 1 and data["outcomes"]["no_show"] == 1 and data["outcomes"]["completed"] == 0


def test_empty_business_returns_zeros_and_nulls_not_errors(business_ready):
    data = _get(business_ready)
    assert data["total_bookings"] == 0 and data["no_show_rate"] is None
    assert data["median_lead_time_hours"] is None and data["popular_slots"] == []
    assert len(data["bookings_trend"]) >= 12  # default 90 days, weekly buckets


def test_range_validation(business_ready):
    for params in ({"date_from": "2026-08-10", "date_to": "2026-08-01"}, {"date_from": "2025-01-01", "date_to": "2026-08-01"}):
        resp = client.get("/api/v1/reports/analytics", params=params, headers=_auth_header(business_ready["token"]))
        assert resp.status_code == 422, resp.text
    assert client.get("/api/v1/reports/analytics", params={"granularity": "hour"}, headers=_auth_header(business_ready["token"])).status_code == 422


def test_staff_cannot_read_and_unauthenticated_is_rejected(business_ready):
    with SessionLocal() as db:
        user = BusinessUser(
            business_id=business_ready["business_id"], email=_unique_email("staff"), hashed_password="x", role=BusinessUserRole.STAFF
        )
        db.add(user)
        db.commit()
        token = create_access_token(user_id=user.id, business_id=business_ready["business_id"], role="staff")
    assert client.get("/api/v1/reports/analytics", headers=_auth_header(token)).status_code == 403
    assert client.get("/api/v1/reports/analytics").status_code in (401, 403)


def test_analytics_are_tenant_scoped(kathmandu):
    _seed(kathmandu)
    other = client.post(
        "/api/v1/auth/register",
        json={"business_name": "Analytics Other", "timezone": "UTC", "email": _unique_email("an-other"), "password": "correcthorse1"},
    )
    other_id = uuid.UUID(other.json()["business_id"])
    try:
        login = client.post("/api/v1/auth/login", json={"email": other.json()["email"], "password": "correcthorse1"})
        data = client.get(
            "/api/v1/reports/analytics", params={"date_from": "2026-08-03", "date_to": "2026-08-16"},
            headers=_auth_header(login.json()["access_token"]),
        ).json()
        assert data["total_bookings"] == 0 and data["popular_slots"] == []
    finally:
        with SessionLocal() as db:
            db.delete(db.get(Business, other_id))
            db.commit()

