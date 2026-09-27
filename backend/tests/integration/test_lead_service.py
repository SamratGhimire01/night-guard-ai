"""app/services/lead_service.py — automatic buying-intent scoring for the inbox's Leads
tab. Runs off the customer-facing message path (see the module docstring for why), so
these tests call it directly rather than through a live conversation turn."""

import pytest

from app.db.database import SessionLocal
from app.db.models.conversation import Conversation, Message, MessageSenderType as S
from app.db.models.customer import Customer
from app.services import lead_service

from tests.integration.test_human_takeover import biz  # noqa: F401


def _conv(business_id, *, customer_messages: int):
    with SessionLocal() as db:
        customer = Customer(business_id=business_id, name="Lead Test Customer")
        db.add(customer)
        db.flush()
        conv = Conversation(business_id=business_id, customer_id=customer.id, channel="website", status="open")
        db.add(conv)
        db.flush()
        for i in range(customer_messages):
            db.add(Message(conversation_id=conv.id, sender_type=S.CUSTOMER, content=f"msg {i}"))
        db.commit()
        return conv.id


def _mark_scored(conv_id) -> None:
    """Stamps lead_scored_at as of right now -- a later transaction than any existing
    messages, so "was scored, nothing new since" holds without any timestamp arithmetic."""
    with SessionLocal() as db:
        conv = db.get(Conversation, conv_id)
        conv.lead_signal = "low"
        conv.lead_scored_at = lead_service.func.localtimestamp()
        db.commit()


def _add_customer_message(conv_id) -> None:
    with SessionLocal() as db:
        db.add(Message(conversation_id=conv_id, sender_type=S.CUSTOMER, content="a new message after scoring"))
        db.commit()


class _Chat:
    def __init__(self, reply: str):
        self.reply = reply
        self.calls = 0

    def chat(self, messages):
        self.calls += 1
        return self.reply


@pytest.fixture(autouse=True)
def _stub_chat(monkeypatch):
    """Default stub so nothing accidentally hits a real provider; tests that care what
    comes back override this with their own monkeypatch.setattr(lead_service, ...)."""
    monkeypatch.setattr(lead_service, "get_chat_provider", lambda: _Chat('{"buy_intent": "low", "summary": "n/a"}'))


def test_parse_accepts_a_valid_signal_and_strips_markdown_fences():
    signal, summary = lead_service._parse('```json\n{"buy_intent": "high", "summary": "Wants to book Friday."}\n```')
    assert signal == "high"
    assert summary == "Wants to book Friday."


def test_parse_rejects_an_invalid_signal_and_malformed_json():
    assert lead_service._parse('{"buy_intent": "extremely likely", "summary": "x"}') == (None, "x")
    assert lead_service._parse("not json at all") == (None, None)


def test_score_conversation_persists_signal_summary_and_scored_at(biz, monkeypatch):
    chat = _Chat('{"buy_intent": "high", "summary": "Wants the premium package, asked about price."}')
    monkeypatch.setattr(lead_service, "get_chat_provider", lambda: chat)
    conv_id = _conv(biz["business_id"], customer_messages=2)

    with SessionLocal() as db:
        conversation = db.get(Conversation, conv_id)
        lead_service.score_conversation(db, conversation)
        db.refresh(conversation)
        assert conversation.lead_signal == "high"
        assert conversation.lead_summary == "Wants the premium package, asked about price."
        assert conversation.lead_scored_at is not None
    assert chat.calls == 1


def test_score_conversation_excludes_staff_messages_from_the_transcript(biz, monkeypatch):
    seen = {}

    class _Capturing:
        def chat(self, messages):
            seen["transcript"] = messages[1]["content"]
            return '{"buy_intent": "low", "summary": "n/a"}'

    monkeypatch.setattr(lead_service, "get_chat_provider", lambda: _Capturing())
    conv_id = _conv(biz["business_id"], customer_messages=1)
    with SessionLocal() as db:
        db.add(Message(conversation_id=conv_id, sender_type=S.STAFF, content="internal note, never shown to the LLM"))
        db.commit()
        conversation = db.get(Conversation, conv_id)
        lead_service.score_conversation(db, conversation)

    assert "internal note" not in seen["transcript"]


def test_score_stale_conversations_skips_too_new_and_already_fresh(biz, monkeypatch):
    chat = _Chat('{"buy_intent": "medium", "summary": "n/a"}')
    monkeypatch.setattr(lead_service, "get_chat_provider", lambda: chat)

    too_new = _conv(biz["business_id"], customer_messages=1)  # below _MIN_CUSTOMER_MESSAGES
    never_scored = _conv(biz["business_id"], customer_messages=2)
    already_fresh = _conv(biz["business_id"], customer_messages=2)
    _mark_scored(already_fresh)  # scored AFTER its last message -- nothing new since

    with SessionLocal() as db:
        scored = lead_service.score_stale_conversations(db, business_id=biz["business_id"])
        assert scored == 1
        assert chat.calls == 1
        assert db.get(Conversation, never_scored).lead_signal == "medium"
        assert db.get(Conversation, too_new).lead_signal is None
        assert db.get(Conversation, already_fresh).lead_signal == "low"  # untouched by this tick


def test_score_stale_conversations_rescores_after_a_new_message(biz, monkeypatch):
    chat = _Chat('{"buy_intent": "high", "summary": "n/a"}')
    monkeypatch.setattr(lead_service, "get_chat_provider", lambda: chat)
    stale = _conv(biz["business_id"], customer_messages=2)
    _mark_scored(stale)
    _add_customer_message(stale)  # a new customer message arrived since it was last scored

    with SessionLocal() as db:
        assert lead_service.score_stale_conversations(db, business_id=biz["business_id"]) == 1
        assert db.get(Conversation, stale).lead_signal == "high"
