"""check_price_and_deposit trusts a deposit the approved KB states (2026-09-29 trekking tenant audit)."""

from app.services.conversation.fact_validator import _demo, check_price_and_deposit

# Verbatim from the Himalayan Trails approved KB ("How to Reserve a Trek Departure", "Gear Rental Price List").
_KB = (
    "To reserve a spot on any trek departure, book a free Trek Booking Consultation through chat or our office. "
    "During the call we confirm your chosen trek, departure date, and group size, and send a deposit link for 20% of "
    "the total package price to hold your spot. The remaining balance is due 7 days before departure.\n"
    "A full 14-day gear set (jacket, sleeping bag, poles, duffel bag) costs USD 55 for a 14-day trek. A refundable "
    "security deposit of USD 50 is collected at pickup and returned when gear is returned in good condition."
)
_SERVICES = [
    {"name": "Trek Booking Consultation", "price": 0, "deposit_enabled": False, "deposit_percentage": None},
    {"name": "Gear Rental Pickup", "price": 0, "deposit_enabled": False, "deposit_percentage": None},
]


def _check(reply, knowledge_text=_KB, known_text=""):
    return check_price_and_deposit(
        reply, currency="USD", services=_SERVICES, known_text=known_text or knowledge_text, knowledge_text=knowledge_text
    )


def test_kb_stated_deposits_are_trusted():
    assert not _check("Book a free Trek Booking Consultation; we then send a deposit link for 20% of the package price.")
    assert not _check("At your Gear Rental Pickup a refundable USD 50 security deposit is collected.")


def test_deposit_claims_the_kb_does_not_back_are_still_flagged():
    # no amount at all -> nothing verbatim to trust
    assert _check("The Trek Booking Consultation requires a deposit.")
    # an amount the KB never states for a deposit
    assert _check("For the Trek Booking Consultation we take a 30% deposit up front.")
    assert _check("At your Gear Rental Pickup a USD 80 security deposit is collected.")
    # the customer's own message is not the KB, even though it's in known_text
    asked = "Is there a 20% deposit for the Trek Booking Consultation?"
    assert _check("Yes, the Trek Booking Consultation needs a 20% deposit.", knowledge_text="", known_text=asked)
    # the original Samaj bug across two sentences
    assert _check("Trek Booking Consultation is free. A 20% advance deposit is required.", knowledge_text="")


def test_existing_demo_cases_still_hold():
    _demo()
