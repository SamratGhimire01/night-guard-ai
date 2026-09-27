# ruff: noqa: F811  (fixtures imported from the sibling suites are re-declared as test arguments — the pytest idiom)
"""Richer chat booking confirmation: the booking message carries the customer's name, the business's details and the
real check-in QR link (the exact signed link a resend returns) at the moment of booking, and says the same details are
in the email — but only when that email was really sent. All three languages; deposit and no-deposit bookings.
"""

import json
import re
import uuid
from datetime import datetime, timezone
from decimal import Decimal
from types import SimpleNamespace
from zoneinfo import ZoneInfo

import pytest
from fastapi.testclient import TestClient

from app.db.database import SessionLocal
from app.db.models.appointment import Appointment
from app.db.models.notification import Notification
from app.main import app
from app.services import qr_link_service
from app.services.conversation.orchestrator import _format_booking_result
from tests.integration.test_payment_choice import (  # noqa: F401
    _auth_header,
    _conversation,
    _next_monday,
    _pending_chat_payment,
    _say,
    chat,
    gateways,
)
from tests.integration.test_payments import premium_npr_ready, two_businesses  # noqa: F401

client = TestClient(app)
LANGS = ["en", "ne_deva", "ne_roman"]
BOOKING_ID = "11bed445-3b1b-4d96-9f1d-985120789685"
_SERVICE = SimpleNamespace(name="Tooth Filling")
_TZ = ZoneInfo("Asia/Kathmandu")
_APPT = {
    "id": BOOKING_ID,
    "confirmation_code": "7K3QXF9",
    "scheduled_at": datetime(2026, 9, 22, 4, 45, tzinfo=timezone.utc),
    "duration_minutes": 30,
}
_PAY = {
    "currency": "NPR", "amount": Decimal("12.00"), "remaining": Decimal("1188.00"),
    "payment_url": "https://pay.example/redirect/abc", "qr_url": "https://pay.example/pay-qr/abc",
}
_CONF = {
    "place": "Samaj Dental · Baneshwor · 9800000000",
    "checkin_qr_url": "https://app.example/qr/TOKEN.123.SIG",
    "email_to": "r***@example.com",
}
_QR_LINK = re.compile(r"/qr/([0-9a-f]{32}\.\d+\.[\w-]+)")


def _fmt(payment, lang, confirmation=_CONF, name="Ram"):
    return _format_booking_result(
        {"success": True, "appointment": _APPT, "payment": payment, "confirmation": confirmation},
        service=_SERVICE, tz=_TZ, customer_name=name, language=lang,
    )


# --- the message itself, every language, every booking shape ---------------------------------------------------------


@pytest.mark.parametrize("lang", LANGS)
@pytest.mark.parametrize("payment", [None, _PAY, {**_PAY, "payment_url": None, "qr_url": None}], ids=["free", "deposit", "choose"])
def test_confirmation_carries_name_place_qr_link_and_email_note(lang, payment):
    text = _fmt(payment, lang)
    assert "Ram" in text and "Samaj Dental · Baneshwor · 9800000000" in text
    assert "https://app.example/qr/TOKEN.123.SIG" in text
    assert "r***@example.com" in text


@pytest.mark.parametrize("payment", [None, _PAY], ids=["free", "deposit"])
def test_each_language_gets_its_own_scaffold(payment):
    lines = {lang: _fmt(payment, lang).splitlines()[1:] for lang in LANGS}
    assert len({tuple(v) for v in lines.values()}) == 3, "the extra lines are translated, not English in every language"
    assert "Booked for: Ram" in lines["en"] and "बुकिङ गरिएको: Ram" in lines["ne_deva"] and "Tapaiko naam ma: Ram" in lines["ne_roman"]


@pytest.mark.parametrize("lang", LANGS)
def test_no_email_claim_when_no_email_was_sent(lang):
    text = _fmt(None, lang, {**_CONF, "email_to": None})
    assert "https://app.example/qr/TOKEN.123.SIG" in text
    assert "email" not in text.lower().split("\n", 1)[1] and "इमेल" not in text


@pytest.mark.parametrize("lang", LANGS)
def test_message_without_confirmation_data_is_unchanged(lang):
    plain = _fmt(None, lang, confirmation=None)
    assert "\n" not in plain and "/qr/" not in plain
    assert _fmt(None, lang).startswith(plain)


def test_deposit_message_keeps_both_qrs_and_stays_reserved_not_confirmed():
    text = _fmt(_PAY, "en")
    assert "https://pay.example/pay-qr/abc" in text and "https://app.example/qr/TOKEN.123.SIG" in text
    assert "reserved" in text and "all set" not in text.lower()


# --- end to end: the real orchestrator, the real booking, the real QR page --------------------------------------------


def _booking_reply(service: str) -> str:
    return json.dumps(
        {"intent": "booking", "response": "x", "booking_request": {"service": service, "date": _next_monday().isoformat(), "time": "14:00"}}
    )


def _customer(ctx, *, email: str | None) -> uuid.UUID:
    body = {"name": "Chat Customer", **({"email": email} if email else {"phone": "+9779800000001"})}
    resp = client.post("/api/v1/customers", json=body, headers=_auth_header(ctx["token_a"]))
    assert resp.status_code == 201, resp.text
    return uuid.UUID(resp.json()["id"])


def _only_appointment(ctx) -> Appointment:
    with SessionLocal() as db:
        return db.query(Appointment).filter(Appointment.business_id == ctx["business_id_a"]).one()


def test_real_no_deposit_booking_gives_a_working_qr_link_and_the_email_really_exists(premium_npr_ready, gateways, chat):
    ctx = premium_npr_ready
    chat.reply = _booking_reply("Checkup")
    email = f"qr-{uuid.uuid4().hex[:8]}@example.com"
    reply = _say(ctx, _conversation(ctx, _customer(ctx, email=email)), "checkup monday 2pm")["response"]

    appointment = _only_appointment(ctx)
    assert reply.startswith("You're all set, Chat Customer!") and "Booked for: Chat Customer" in reply
    (token,) = _QR_LINK.findall(reply)
    assert qr_link_service.verify_token(token) == appointment.id, "the chat link is the real signed link for THIS booking"
    page = client.get(f"/qr/{token}")
    assert page.status_code == 200 and "data:image/png;base64," in page.text and "Checkup" in page.text

    assert qr_link_service.mask_email(email) in reply and email not in reply, "masked, exactly like a resend"
    with SessionLocal() as db:
        sent = db.query(Notification).filter_by(appointment_id=appointment.id, event_type="booking_confirmed").one()
        assert sent.channel == "email" and sent.status.value in ("sent", "simulated"), "the email the message mentions exists"


def test_customer_with_no_email_gets_the_qr_link_but_no_email_claim(premium_npr_ready, gateways, chat):
    ctx = premium_npr_ready
    chat.reply = _booking_reply("Checkup")
    reply = _say(ctx, _conversation(ctx, _customer(ctx, email=None)), "checkup monday 2pm")["response"]
    assert _QR_LINK.search(reply) and "in your email" not in reply


def test_real_deposit_booking_has_the_check_in_qr_next_to_the_payment_qr(premium_npr_ready, gateways, chat):
    _, _, payment, booked = _pending_chat_payment(premium_npr_ready, chat)
    reply = booked["response"]
    assert "reserved" in reply and f"/pay-qr/{payment.id}" in reply and "Booked for: Chat Customer" in reply
    (token,) = _QR_LINK.findall(reply)
    assert qr_link_service.verify_token(token) == payment.appointment_id
    assert client.get(f"/qr/{token}").status_code == 200
    assert "in your email" in reply
