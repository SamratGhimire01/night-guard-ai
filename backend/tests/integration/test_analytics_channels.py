# ruff: noqa: F811  (fixtures imported from the sibling suites are re-declared as test arguments — the pytest idiom)
"""Analytics channel breakdown: bookings and conversations per channel (WhatsApp, Messenger, Instagram, Website widget,
Other) over the page's date range, plus the bookings whose channel was never recorded. Seeded rows in a non-UTC
business timezone, every number checked against an independent Python computation; and the write side: a real chat
booking records its conversation's channel, a dashboard booking records none."""

import uuid
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

from app.db.database import SessionLocal
from app.db.models.appointment import Appointment, AppointmentStatus
from app.db.models.conversation import Conversation
from tests.integration.test_analytics import KTM, _get, kathmandu  # noqa: F401
from tests.integration.test_payment_choice import (  # noqa: F401
    _booking_reply,
    _conversation,
    _customer_with_email,
    _say,
    chat,
    gateways,
)
from tests.integration.test_payments import premium_npr_ready, two_businesses  # noqa: F401
from tests.integration.test_group_booking import business_a_ready  # noqa: F401
from tests.integration.test_reminders import business_ready  # noqa: F401

RANGE = {"date_from": "2026-08-03", "date_to": "2026-08-16", "granularity": "week"}


def _appt(ctx, local_dt: datetime, channel: str | None, status=AppointmentStatus.CONFIRMED):
    scheduled = local_dt.replace(tzinfo=KTM).astimezone(timezone.utc)
    with SessionLocal() as db:
        db.add(
            Appointment(
                business_id=ctx["business_id"], customer_id=ctx["customer_id"], service_id=ctx["service_id"], staff_id=None,
                scheduled_at=scheduled, duration_minutes=30, status=status, source_channel=channel,
                created_at=scheduled - timedelta(hours=2),
            )
        )
        db.commit()


def _conv(ctx, utc_dt: datetime, channel: str):
    with SessionLocal() as db:
        db.add(
            Conversation(
                business_id=ctx["business_id"], customer_id=ctx["customer_id"], channel=channel, status="open",
                created_at=utc_dt.replace(tzinfo=None),  # the column is a naive UTC wall-clock (see analytics_service)
            )
        )
        db.commit()


def _by_channel(data) -> dict:
    return {c["channel"]: (c["bookings"], c["conversations"]) for c in data["channels"]}


def test_breakdown_matches_an_independent_count(kathmandu):
    d = datetime
    for local, channel, status in [
        (d(2026, 8, 3, 10, 0), "whatsapp", AppointmentStatus.CONFIRMED),
        (d(2026, 8, 4, 10, 0), "whatsapp", AppointmentStatus.COMPLETED),
        (d(2026, 8, 5, 10, 0), "website", AppointmentStatus.CONFIRMED),
        (d(2026, 8, 6, 10, 0), "instagram", AppointmentStatus.NO_SHOW),
        (d(2026, 8, 7, 10, 0), "sms", AppointmentStatus.CONFIRMED),          # not one of the four -> other
        (d(2026, 8, 8, 10, 0), "messenger", AppointmentStatus.CANCELLED),    # cancelled: not a booking
        (d(2026, 8, 9, 10, 0), None, AppointmentStatus.CONFIRMED),           # dashboard / pre-tracking
        (d(2026, 8, 10, 10, 0), None, AppointmentStatus.CONFIRMED),
        (d(2026, 8, 20, 10, 0), "whatsapp", AppointmentStatus.CONFIRMED),    # outside the range
    ]:
        _appt(kathmandu, local, channel, status)
    utc = lambda *a: datetime(*a, tzinfo=timezone.utc)  # noqa: E731
    for when, channel in [
        (utc(2026, 8, 3, 6), "whatsapp"), (utc(2026, 8, 5, 6), "whatsapp"), (utc(2026, 8, 5, 7), "website"),
        (utc(2026, 8, 6, 6), "messenger"), (utc(2026, 8, 7, 6), "debug_test"),
        (utc(2026, 8, 2, 20), "instagram"),   # 01:45 on Aug 3 in Kathmandu: INSIDE the range although 2 Aug in UTC
        (utc(2026, 8, 16, 19), "instagram"),  # 00:45 on Aug 17 in Kathmandu: OUTSIDE although 16 Aug in UTC
        (utc(2026, 8, 1, 6), "whatsapp"),     # before the range
    ]:
        _conv(kathmandu, when, channel)

    data = _get(kathmandu, **RANGE)
    assert [c["channel"] for c in data["channels"]] == ["whatsapp", "messenger", "instagram", "website", "other"]
    assert _by_channel(data) == {
        "whatsapp": (2, 2), "messenger": (0, 1), "instagram": (1, 1), "website": (1, 1), "other": (1, 1),
    }
    assert data["bookings_channel_not_recorded"] == 2
    attributed = sum(b for b, _ in _by_channel(data).values())
    assert attributed + data["bookings_channel_not_recorded"] == data["total_bookings"] == 7, "same bookings as the trend"


def test_empty_range_is_all_zero(kathmandu):
    data = _get(kathmandu, **RANGE)
    assert _by_channel(data) == {c: (0, 0) for c in ("whatsapp", "messenger", "instagram", "website", "other")}
    assert data["bookings_channel_not_recorded"] == 0


# --- the write side ---------------------------------------------------------------------------------------------------


def test_a_chat_booking_records_its_conversations_channel(premium_npr_ready, gateways, chat):
    ctx = premium_npr_ready
    chat.reply = _booking_reply()
    _say(ctx, _conversation(ctx, _customer_with_email(ctx), "whatsapp"), "root canal monday 2pm")
    with SessionLocal() as db:
        (appointment,) = db.query(Appointment).filter(Appointment.business_id == ctx["business_id_a"]).all()
        assert appointment.source_channel == "whatsapp"


def test_a_dashboard_booking_records_no_channel(premium_npr_ready):
    from fastapi.testclient import TestClient

    from app.main import app
    from tests.integration.test_payments import _auth_header, _next_weekday_datetime

    ctx = premium_npr_ready
    resp = TestClient(app).post(
        "/api/v1/appointments",
        json={
            "customer_id": str(ctx["customer_id"]), "service_id": str(ctx["no_deposit_service_id"]),
            "scheduled_at": _next_weekday_datetime(10),
        },
        headers=_auth_header(ctx["token_a"]),
    )
    assert resp.status_code == 201, resp.text
    with SessionLocal() as db:
        assert db.get(Appointment, uuid.UUID(resp.json()["id"])).source_channel is None


def test_a_group_booking_records_the_channel_in_both_modes(business_a_ready):
    from zoneinfo import ZoneInfo

    from app.services import booking_service
    from tests.integration.test_group_booking import _next_weekday, _person

    ctx = business_a_ready
    monday = datetime.combine(_next_weekday(0), datetime.min.time(), tzinfo=ZoneInfo("UTC"))
    with SessionLocal() as db:
        for all_or_nothing, hour in ((False, 10), (True, 12)):
            result = booking_service.create_group_appointments(
                db, business_id=ctx["business_id_a"], customer_id=ctx["customer_id"], all_or_nothing=all_or_nothing,
                people=[_person("A", ctx["cleaning_id"], monday.replace(hour=hour))], source_channel="messenger",
            )
            assert result["success"] is True
    with SessionLocal() as db:
        rows = db.query(Appointment).filter(Appointment.business_id == ctx["business_id_a"]).all()
        assert len(rows) == 2 and {r.source_channel for r in rows} == {"messenger"}
