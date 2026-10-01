"""Language across a whole conversation, through the real engine. The model is a stub that always reports each message's
language CORRECTLY, so whatever these tests catch is the deterministic lock logic, not the model.

Rules (the 2026 production pattern: tag every turn, keep the conversation's language unless the signal is clear and
sustained, never flip on a short/ambiguous message):
  - "ok", "hmm", "price?", 👍 never change the language
  - a Romanized Nepali message full of English nouns ("booking cancel garna milcha?") is still Nepali
  - an English sentence that names a Nepali place is still English
  - an explicit request ("nepali ma bhannus", "reply in English") switches at once
  - one stray English line inside a Nepali chat doesn't switch"""

import json

import pytest

from app.db.database import SessionLocal
from app.db.models.conversation import Conversation
from tests.eval.simulator import run as sim
from tests.eval.simulator.businesses import BY_KEY

_REPLY = {"en": "Sure, happy to help.", "ne_roman": "Huncha hajur, bhannus na.", "mixed": "Huncha hajur, bhannus na.",
          "ne_deva": "हुन्छ, भन्नुस् न।", "unclear": "Huncha hajur."}


class _Chat:
    """Reports the language a careful reader would give each message."""

    def __init__(self, labels):
        self.labels = labels

    def chat(self, messages):
        current = messages[-1]["content"] if isinstance(messages[-1].get("content"), str) else ""
        # the prompt also carries the history: the CURRENT message is the one that appears last
        found = [(current.rfind(text), lab) for text, lab in self.labels.items() if text in current]
        label = max(found)[1] if found else "unclear"
        return json.dumps({"intent": "general_question", "response": _REPLY[label], "message_language": label,
                           "needs_human_handoff": False})


class _Embed:
    def embed(self, texts):
        return [[0.01] * 1536 for _ in texts]


@pytest.fixture
def chat_session(monkeypatch):
    import app.services.conversation.intent as intent_module
    import app.services.conversation.orchestrator as orchestrator_module
    from app.services.channels.base import get_or_create_conversation
    from app.services.conversation.orchestrator import handle_incoming_message

    monkeypatch.setattr(orchestrator_module, "get_embedding_provider", lambda: _Embed())
    db = SessionLocal()
    business = sim.create_business(db, BY_KEY["dental"], with_knowledge=False)
    counter = iter(range(10_000))

    def run(turns):
        """turns: [(message, true_label)] -> [(message, locked_language_after, reply)]"""
        labels = dict(turns)
        chat = _Chat(labels)
        monkeypatch.setattr(intent_module, "get_chat_provider", lambda: chat)
        monkeypatch.setattr("app.llm.get_chat_provider", lambda: chat)
        conv = get_or_create_conversation(db, business_id=business.id, channel="website",
                                          external_ref=f"lang-{next(counter)}", default_customer_name="Website Visitor")
        out = []
        for text, _ in turns:
            result = handle_incoming_message(db, conversation_id=conv.id, business_id=business.id, content=text)
            db.expire_all()
            out.append((text, db.get(Conversation, conv.id).detected_language, (result or {}).get("response")))
        return out

    yield run
    sim.delete_sim_businesses(db)
    db.close()


def _locks(rows):
    return [lock for _, lock, _ in rows]


def test_short_messages_never_flip_romanized_nepali(chat_session):
    rows = chat_session([("namaste, Teeth Cleaning kati parcha?", "ne_roman"), ("ok", "unclear"),
                         ("price?", "unclear"), ("👍", "unclear"), ("hmm thik xa", "ne_roman")])
    assert _locks(rows) == ["ne_roman"] * 5, rows


def test_short_messages_never_flip_english(chat_session):
    rows = chat_session([("Hi, how much is a teeth cleaning?", "en"), ("ok", "unclear"), ("hmm", "unclear"),
                         ("thanks", "en")])
    assert _locks(rows) == ["en"] * 4, rows


def test_nepali_with_english_nouns_is_nepali(chat_session):
    rows = chat_session([("Teeth Cleaning ko booking cancel garna milcha?", "ne_roman"),
                         ("online payment accept garnuhunxa?", "ne_roman")])
    assert set(_locks(rows)) <= {"ne_roman", "mixed"}, rows


def test_english_with_place_names_is_english(chat_session):
    rows = chat_session([("Hi, I live near Baneshwor. Can I come tomorrow for a cleaning?", "en"), ("ok", "unclear")])
    assert _locks(rows) == ["en", "en"], rows


@pytest.mark.xfail(strict=True, reason="BUG found 2026-10-01: 'malai nepali ma bhannus na' in an English-locked chat is "
                   "ignored and the next Nepali messages stay locked to English; fix pending in orchestrator's lock logic")
def test_explicit_request_switches_at_once(chat_session):
    rows = chat_session([("Hello, what are your opening hours?", "en"), ("malai nepali ma bhannus na", "ne_roman"),
                         ("Teeth Cleaning kati parcha?", "ne_roman")])
    assert _locks(rows)[1:] == ["ne_roman", "ne_roman"], rows
    rows = chat_session([("namaste", "ne_roman"), ("Teeth Cleaning kati ho?", "ne_roman"),
                         ("Can you reply in English please? My Nepali is not good.", "en")])
    assert _locks(rows)[-1] == "en", rows


def test_one_stray_english_line_does_not_switch(chat_session):
    rows = chat_session([("dai Teeth Cleaning ko barema bhannus na", "ne_roman"),
                         ("Is it available tomorrow?", "en"), ("kati baje aauna milxa?", "ne_roman")])
    assert _locks(rows) == ["ne_roman"] * 3, rows


def test_devanagari_stays_devanagari(chat_session):
    rows = chat_session([("नमस्ते, Teeth Cleaning कति हो?", "ne_deva"), ("ok", "unclear")])
    assert _locks(rows) == ["ne_deva", "ne_deva"], rows
