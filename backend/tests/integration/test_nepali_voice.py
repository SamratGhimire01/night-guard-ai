# ruff: noqa: F811  (fixtures imported from the sibling suite are re-declared as test arguments — the pytest idiom)
"""Natural-voice pass (2026-10-01), end to end through the real orchestrator with a stubbed LLM: a Romanized-Nepali
chat gets the word bank, the customer's own spelling, Nepali-style times, and never the same fixed text twice."""

import json

from app.db.database import SessionLocal
from app.db.models.conversation import Conversation
from app.services.conversation.nepali_wordbank import find_issues
from tests.integration.test_conversation import (  # noqa: F401
    _create_conversation,
    _create_customer,
    _next_monday,
    _partial_booking_reply,
    _say,
    _setup_booking_business,
    _stub_providers,
    two_businesses,
)


def _lock_romanized(conversation_id):
    with SessionLocal() as db:
        db.get(Conversation, conversation_id).detected_language = "ne_roman"
        db.commit()


def test_romanized_chat_reads_natural_mirrors_spelling_and_never_repeats_the_contact_ask(two_businesses, monkeypatch):
    token, business_id = two_businesses["token_a"], two_businesses["business_id_a"]
    _setup_booking_business(token)
    conversation_id = _create_conversation(business_id, _create_customer(token))
    _lock_romanized(conversation_id)
    monday = _next_monday()

    # An LLM draft in textbook Nepali comes out the way people text -- in the customer's own x/v spelling.
    _stub_providers(monkeypatch, json.dumps({
        "intent": "follow_up",
        "response": "Huncha, kripaya ek chin pratiksha garnuhos. Aru kehi sahayog chahiyo bhane bhanuhos.",
        "message_language": "ne_roman",
        "needs_human_handoff": False,
    }))
    first = _say(token, conversation_id, "ok xa, voli milxa?")
    assert not find_issues(first), first
    assert first == "Hunxa, ek chin wait garnus.", first

    # Booking with no contact on file: the gate is asked, and asked DIFFERENTLY when the customer still hasn't answered.
    asks = []
    for time_ in ("10:00", "11:00", "10:30"):
        _stub_providers(monkeypatch, _partial_booking_reply(service="Cleaning", date=monday.isoformat(), time=time_))
        asks.append(_say(token, conversation_id, f"{time_} ma book garidinus"))
    assert all("naam" in a.lower() and "number" in a for a in asks), asks
    assert len(set(asks)) == 3, f"the same contact ask was sent twice: {asks}"
    assert "bihana 10 baje" in asks[0] and "Sombar (" in asks[0], asks[0]
    assert "bihana sadhe 10 baje" in asks[2], asks[2]
    assert all("AM" not in a for a in asks), "no English clock time inside a Nepali reply"
    assert all(not find_issues(a) for a in asks), asks
    sentences = [s for a in asks for s in a.split(". ") if "naam" in s.lower()]
    assert len(set(sentences)) == 3, f"the contact request itself must be worded differently each time: {asks}"
    assert "bhaihalcha" not in " ".join(asks) and "huncha" not in " ".join(asks), "x/v spelling throughout"
