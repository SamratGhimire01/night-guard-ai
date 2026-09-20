"""Phase 18: a weekday the customer literally types is resolved against the REAL calendar, and the model's date is overridden when
it disagrees (live bug: "Thursday" came back as Wednesday's date -- always exactly a day early -- ~8% on clear requests and up to
40% on terse ones, at both reasoning efforts). Stubbed LLM; the pure function is tested exhaustively, the wiring end-to-end."""

import json
from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

import pytest

from app.db.database import SessionLocal
from app.db.models.appointment import Appointment
from app.services import booking_service
from app.services.conversation.orchestrator import _named_weekday, _verify_weekday_date
from tests.integration import test_conversation as _tc
from tests.integration.test_conversation import (
    _auth_header,
    _create_conversation,
    _create_customer_with_contact,
    _create_customer,
    _partial_booking_reply,
    _reschedule_reply,
    _setup_booking_business,
    _stub_providers,
    client,
)

two_businesses = _tc.two_businesses  # the shared fixture, re-exported so pytest finds it in this module

SUNDAY = date(2026, 9, 20)  # a fixed "today" for the pure-function tests
DAYS = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"]


def _req(d: str | None) -> dict:
    return {"service": None, "date": d, "time": None, "wants_availability": True}


def test_named_weekday_reads_english_roman_and_devanagari_and_refuses_ambiguity():
    assert _named_weekday("is Thursday morning possible instead?") == 3
    assert _named_weekday("THURS works?") == 3 and _named_weekday("book me on tuesday") == 1
    assert _named_weekday("sukrabar ko lagi teeth cleaning milcha?") == 4
    assert _named_weekday("शनिबारमा मिल्छ?") == 5
    assert _named_weekday("Thursday or Friday?") is None  # two different weekdays: not ours to pick
    assert _named_weekday("Thursday, thursday morning") == 3  # the same weekday twice is still one weekday
    assert _named_weekday("what times do you have tomorrow?") is None
    assert _named_weekday("I sat in the sun") is None  # "sat"/"sun" are ordinary English words, never abbreviations here


@pytest.mark.parametrize("today_offset", range(7))
def test_every_wrong_weekday_date_is_pulled_to_the_named_weekday_for_every_possible_today(today_offset):
    """Exhaustive: every 'today' weekday x every named weekday x every model date in the next two weeks."""
    today = SUNDAY + timedelta(days=today_offset)
    for weekday in range(7):
        for model_offset in range(14):
            model = today + timedelta(days=model_offset)
            fixed = date.fromisoformat(_verify_weekday_date(_req(model.isoformat()), f"is {DAYS[weekday]} ok?", today)["date"])
            assert fixed.weekday() == weekday, (today, weekday, model, fixed)
            assert fixed >= today, "never resolves into the past"
            if model.weekday() == weekday:
                assert fixed == model, "a date already on the named weekday (it may be next week's) is never changed"
            else:
                assert abs((fixed - model).days) <= 3 or fixed == model + timedelta(days=(weekday - model.weekday() + 3) % 7 - 3 + 7), (
                    "within +-3 days of the model's date (a right week stays the right week), or one week on if that would be past"
                )


def test_the_live_bug_thursday_from_sunday_is_thursday_not_wednesday():
    fixed = _verify_weekday_date(_req("2026-09-23"), "actually, is Thursday morning possible instead?", SUNDAY)
    assert fixed["date"] == "2026-09-24" and fixed["wants_availability"] is True  # other fields untouched


def test_a_missing_date_is_filled_only_when_asked_and_never_for_todays_own_weekday():
    assert _verify_weekday_date(_req(None), "Monday works?", SUNDAY, fill_missing=True)["date"] == "2026-09-21"
    assert _verify_weekday_date(_req(None), "Monday works?", SUNDAY)["date"] is None  # non-booking intent: not filled
    assert _verify_weekday_date(_req(None), "Sunday works?", SUNDAY, fill_missing=True)["date"] is None  # today or next week?


@pytest.mark.parametrize(
    "text",
    [
        "not Thursday, tomorrow works",  # negation + another date reference
        "I can't do Thursday",
        "Thursday the 24th please",  # explicit calendar date alongside the weekday
        "Thursday, September 24",
        "Thursday 2026-09-24",
        "next week Thursday",
        "next Thursday",
        "Thursday or Friday?",
        "book me tomorrow",  # no weekday at all
        "today at 4pm",
        "on 2026-09-24 at 10am",
    ],
)
def test_guards_and_no_weekday_requests_leave_the_models_date_exactly_as_it_was(text):
    """Genuine same-day / explicit-date requests (and every ambiguous shape) are untouched -- status quo."""
    for model in ("2026-09-23", None):
        request = _req(model)
        assert _verify_weekday_date(request, text, SUNDAY, fill_missing=True) == request


def _next_friday() -> date:
    today = date.today()
    return today + timedelta(days=(4 - today.weekday()) % 7 or 7)


def _booked_dates(customer_id) -> list[date]:
    with SessionLocal() as db:
        return [a.scheduled_at.date() for a in db.query(Appointment).filter(Appointment.customer_id == customer_id)]


def test_end_to_end_a_booking_the_model_put_a_day_early_lands_on_the_weekday_the_customer_typed(two_businesses, monkeypatch):
    """Stubbed model returns THURSDAY's date for "on friday at 2pm"; the appointment must be created on Friday."""
    token_a, business_id_a = two_businesses["token_a"], two_businesses["business_id_a"]
    _setup_booking_business(token_a)
    customer_id = _create_customer_with_contact(token_a)
    conversation_id = _create_conversation(business_id_a, customer_id)
    friday = _next_friday()
    _stub_providers(monkeypatch, _partial_booking_reply(service="Cleaning", date=(friday - timedelta(days=1)).isoformat(), time="14:00"))
    resp = client.post(
        f"/api/v1/conversations/{conversation_id}/messages", headers=_auth_header(token_a), json={"content": "book a cleaning on friday at 2pm"}
    )
    assert resp.status_code == 201, resp.text
    assert _booked_dates(customer_id) == [friday], resp.json()["response"]


def test_end_to_end_explicit_date_and_tomorrow_requests_are_booked_exactly_as_the_model_said(two_businesses, monkeypatch):
    token_a, business_id_a = two_businesses["token_a"], two_businesses["business_id_a"]
    _setup_booking_business(token_a)
    customer_id = _create_customer_with_contact(token_a)
    conversation_id = _create_conversation(business_id_a, customer_id)
    target = date.today() + timedelta(days=9)
    while target.weekday() == 6:  # the fixture business is closed Sundays
        target += timedelta(days=1)
    _stub_providers(monkeypatch, _partial_booking_reply(service="Cleaning", date=target.isoformat(), time="14:00"))
    resp = client.post(
        f"/api/v1/conversations/{conversation_id}/messages",
        headers=_auth_header(token_a),
        json={"content": f"book a cleaning on {target.isoformat()} at 2pm"},  # an explicit date, no weekday named
    )
    assert resp.status_code == 201, resp.text
    assert _booked_dates(customer_id) == [target]


def test_the_stub_shape_used_above_is_a_booking_intent_json():  # guards the helper the two tests above rely on
    assert json.loads(_partial_booking_reply(service="Cleaning", date="2026-09-24", time="14:00"))["intent"] == "booking"


def test_end_to_end_a_reschedule_the_model_put_a_day_early_lands_on_the_weekday_the_customer_typed(two_businesses, monkeypatch):
    """The same fix covers reschedule requests -- and this turn type must not crash (the result object is immutable; found by the full
    suite when the first version assigned to it)."""
    token_a, business_id_a = two_businesses["token_a"], two_businesses["business_id_a"]
    service_id = _setup_booking_business(token_a)
    customer_id = _create_customer(token_a)
    conversation_id = _create_conversation(business_id_a, customer_id)
    friday = _next_friday()
    start = friday + timedelta(days=3)  # the appointment being moved: a Monday, then moved to the customer's Friday
    with SessionLocal() as db:
        appointment_id = booking_service.create_appointment(
            db, business_id=business_id_a, customer_id=customer_id, service_id=service_id, staff_id=None,
            scheduled_at=datetime(start.year, start.month, start.day, 10, 0, tzinfo=ZoneInfo("UTC")),
        ).id
    _stub_providers(monkeypatch, _reschedule_reply(str(appointment_id), (friday - timedelta(days=1)).isoformat(), "15:00"))
    resp = client.post(
        f"/api/v1/conversations/{conversation_id}/messages", headers=_auth_header(token_a), json={"content": "please move it to friday at 3pm"}
    )
    assert resp.status_code == 201, resp.text
    assert _booked_dates(customer_id) == [friday], resp.json()["response"]
