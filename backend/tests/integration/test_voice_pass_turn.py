"""The voice pass inside a real turn: a flawed free-text draft is rewritten, a rewrite that changes a fact is not sent,
and a clean draft costs no second call."""

import json

import pytest

from app.core.config import settings
from app.db.database import SessionLocal
from tests.eval.simulator import run as sim
from tests.eval.simulator.businesses import BY_KEY


class _Chat:
    def __init__(self, draft, rewrite):
        self.replies, self.calls = [json.dumps({"intent": "pricing_question", "response": draft,
                                                "message_language": "ne_roman", "needs_human_handoff": False}),
                                    rewrite], []

    def chat(self, messages):
        self.calls.append(messages)
        return self.replies[min(len(self.calls) - 1, 1)]


class _Embed:
    def embed(self, texts):
        return [[0.01] * 1536 for _ in texts]


@pytest.fixture
def turn(monkeypatch):
    import app.services.conversation.intent as intent_module
    import app.services.conversation.orchestrator as orchestrator_module
    from app.services.channels.base import get_or_create_conversation
    from app.services.conversation.orchestrator import handle_incoming_message

    monkeypatch.setattr(settings, "voice_pass_mode", "auto")
    monkeypatch.setattr(orchestrator_module, "get_embedding_provider", lambda: _Embed())
    db = SessionLocal()
    business = sim.create_business(db, BY_KEY["dental"], with_knowledge=False)

    def run(draft, rewrite, message="Teeth Cleaning kati parcha?"):
        chat = _Chat(draft, rewrite)
        monkeypatch.setattr(intent_module, "get_chat_provider", lambda: chat)
        # voice_pass imports the provider lazily from app.llm
        monkeypatch.setattr("app.llm.get_chat_provider", lambda: chat)
        conv = get_or_create_conversation(db, business_id=business.id, channel="website",
                                          external_ref=f"vp-{len(draft)}-{len(rewrite)}",
                                          default_customer_name="Website Visitor")
        result = handle_incoming_message(db, conversation_id=conv.id, business_id=business.id, content=message)
        return result["response"], chat

    yield run
    sim.delete_sim_businesses(db)
    db.close()


def test_flawed_draft_is_rewritten(turn):
    reply, chat = turn("Teeth Cleaning ko 1500 parcha. Yo service ko barema aru bujhna chahanchu bhane sodhnus.",
                       "Teeth Cleaning ko 1500 parcha hajur. Kaile aauna milcha?")
    assert len(chat.calls) == 2
    assert "aauna milcha?" in reply and "chahanchu" not in reply


def test_rewrite_that_changes_the_price_is_not_sent(turn):
    reply, chat = turn("Teeth Cleaning ko 1500 parcha. Yo service ko barema aru bujhna chahanchu bhane sodhnus.",
                       "Teeth Cleaning ko 1200 parcha hajur.")
    assert len(chat.calls) == 2
    assert "1500" in reply and "1200" not in reply


def test_clean_draft_costs_no_second_call(turn):
    reply, chat = turn("Teeth Cleaning ko 1500 parcha hajur.", "SHOULD NOT BE USED")
    assert len(chat.calls) == 1 and "SHOULD NOT" not in reply
