# ruff: noqa: F811  (fixtures imported from the sibling suites are re-declared as test arguments — the pytest idiom)
"""Phase 47: a deposit-required booking is reserved at once but not yet paid, so its first chat message reads "reserved,
pending your deposit" (never "you're all set"), and the definitive "confirmed" wording is the payment-received message.
A booking with no deposit keeps the original "you're all set" text byte-for-byte. All three languages, deterministic
templates only.
"""

from datetime import datetime, timezone
from decimal import Decimal
from types import SimpleNamespace
from zoneinfo import ZoneInfo

import pytest

from app.db.database import SessionLocal
from app.db.models.appointment import Appointment
from app.db.models.conversation import Conversation
from app.db.models.payment import Payment
from app.services import payment_service
from app.services.conversation.orchestrator import _format_booking_result
from app.services.conversation.response_templates import render
from tests.integration.test_payment_choice import (  # noqa: F401
    _agent_messages,
    _pending_chat_payment,
    _say,
    _set_providers,
    chat,
    gateways,
)
from tests.integration.test_payments import premium_npr_ready, two_businesses  # noqa: F401

LANGS = ["en", "ne_deva", "ne_roman"]
BOOKING_ID = "11bed445-3b1b-4d96-9f1d-985120789685"
# the phrase each language's booking_success / payment_received uses for "all set" — must NOT open a pending booking
ALL_SET = {"en": "all set", "ne_deva": "भइसक्यो", "ne_roman": "Sabai milyo"}
RESERVED = {"en": "reserved", "ne_deva": "रिजर्भ", "ne_roman": "reserve gari"}
CONFIRMED = {"en": "is now confirmed", "ne_deva": "अब पक्का भयो", "ne_roman": "ab pakka bhayo"}

_SERVICE = SimpleNamespace(name="Tooth Filling")
_TZ = ZoneInfo("Asia/Kathmandu")
_APPT = {
    "id": BOOKING_ID,
    "confirmation_code": BOOKING_ID,
    "scheduled_at": datetime(2026, 9, 22, 4, 45, tzinfo=timezone.utc),
    "duration_minutes": 30,
}
_PAY = {
    "percentage": 1,
    "currency": "NPR",
    "amount": Decimal("12.00"),
    "remaining": Decimal("1188.00"),
    "payment_url": "https://pay.example/redirect/abc",
    "qr_url": "https://pay.example/pay-qr/abc",
}


def _fmt(payment, lang):
    return _format_booking_result(
        {"success": True, "appointment": _APPT, "payment": payment},
        service=_SERVICE, tz=_TZ, customer_name="Ram", language=lang,
    )


@pytest.mark.parametrize("lang", LANGS)
def test_deposit_booking_with_a_link_reads_reserved_pending_payment(lang):
    text = _fmt(_PAY, lang)
    assert RESERVED[lang] in text
    assert ALL_SET[lang].lower() not in text.lower()
    assert "https://pay.example/redirect/abc" in text and "https://pay.example/pay-qr/abc" in text
    assert "NPR 12.00" in text and "NPR 1188.00" in text and "Tooth Filling" in text
    assert text.count(BOOKING_ID) == 1, "the booking id appears once, low-key, as a reference"
    assert "Booking ID" not in text and "बुकिङ आईडी" not in text


@pytest.mark.parametrize("lang", LANGS)
def test_deposit_booking_still_choosing_a_gateway_reads_reserved_and_asks(lang):
    text = _fmt({**_PAY, "payment_url": None, "qr_url": None}, lang)
    assert RESERVED[lang] in text and ALL_SET[lang].lower() not in text.lower()
    assert "eSewa" in text and "Khalti" in text and "NPR 12.00" in text
    assert text.count(BOOKING_ID) == 1


@pytest.mark.parametrize("lang", LANGS)
def test_no_deposit_booking_message_is_completely_unchanged(lang):
    expected = render(
        "booking_success", lang, who=", Ram", service="Tooth Filling",
        when="Tuesday, September 22 at 10:30 AM", duration="30", id=BOOKING_ID,
    )
    assert _fmt(None, lang) == expected
    assert ALL_SET[lang].lower() in expected.lower()
    assert "deposit" not in expected.lower() and "डिपोजिट" not in expected


def test_no_deposit_english_text_is_byte_identical_to_the_original():
    assert _fmt(None, "en") == (
        f"You're all set, Ram! I've booked Tooth Filling for Tuesday, September 22 at 10:30 AM (30 min). "
        f"Your booking ID is {BOOKING_ID}."
    )


@pytest.mark.parametrize("lang", LANGS)
def test_payment_received_is_the_definitive_confirmation_in_every_language(lang):
    text = render(
        "payment_received", lang, who=", Ram", service="Tooth Filling", when="Tuesday, September 22 at 10:30 AM",
        currency="NPR", amount="12.00", id=BOOKING_ID,
    )
    assert ALL_SET[lang].lower() in text.lower() and CONFIRMED[lang] in text
    assert "NPR 12.00" in text and BOOKING_ID in text and "Tuesday, September 22 at 10:30 AM" in text


# --- end to end through the real orchestrator + the real verified-completion path ------------------------------------


def test_chat_deposit_booking_then_verified_payment_gives_reserved_then_definitive_messages(
    premium_npr_ready, gateways, chat
):
    _, _, payment, booked = _pending_chat_payment(premium_npr_ready, chat)
    first = booked["response"]
    assert "reserved" in first and "all set" not in first.lower()
    assert "https://esewa.fake/redirect/abc" in first and f"/pay-qr/{payment.id}" in first
    with SessionLocal() as db:
        assert db.get(Appointment, payment.appointment_id).confirmation_code in first

    conv = payment.conversation_id
    with SessionLocal() as db:
        payment_service.verify_and_update(db, db.get(Payment, payment.id))
    final = _agent_messages(conv)[-1]
    assert "Payment received — you're all set" in final and "is now confirmed" in final
    with SessionLocal() as db:
        confirmation_code = db.get(Appointment, payment.appointment_id).confirmation_code
    assert "NPR 9000.00" in final and confirmation_code in final


@pytest.mark.parametrize("lang", LANGS)
def test_real_payment_received_message_uses_the_conversations_locked_language(lang, premium_npr_ready, gateways, chat):
    _, _, payment, _ = _pending_chat_payment(premium_npr_ready, chat)
    with SessionLocal() as db:
        db.get(Conversation, payment.conversation_id).detected_language = lang
        db.commit()
        payment_service.verify_and_update(db, db.get(Payment, payment.id))
    final = _agent_messages(payment.conversation_id)[-1]
    with SessionLocal() as db:
        confirmation_code = db.get(Appointment, payment.appointment_id).confirmation_code
    assert CONFIRMED[lang] in final and confirmation_code in final


def test_chat_no_deposit_booking_is_the_original_all_set_message(premium_npr_ready, gateways, chat):
    import json

    from tests.integration.test_payment_choice import _conversation, _customer_with_email, _next_monday

    chat.reply = json.dumps(
        {
            "intent": "booking", "response": "x",
            "booking_request": {"service": "Checkup", "date": _next_monday().isoformat(), "time": "14:00"},
        }
    )
    conv = _conversation(premium_npr_ready, _customer_with_email(premium_npr_ready))
    reply = _say(premium_npr_ready, conv, "checkup monday 2pm")["response"]
    assert reply.startswith("You're all set") and "Your booking ID is " in reply
    assert "reserved" not in reply and "deposit" not in reply.lower()
