"""Phase 43h -- push-to-talk voice input (app/api/routes/voice.py, app/voice/).

Replaces the former real-time streaming voice call (Phases 43/43b/43d/43e/43f/
43g) entirely: no WebSocket, no barge-in, no keepalive loop, no spoken TTS
output. One HTTP POST per recording -- Deepgram's real pre-recorded/batch STT
is stubbed (same discipline as test_widget.py's stubbed ChatProvider/
EmbeddingProvider) so this suite is fast, free, and deterministic. The point
of these tests is the real wiring this phase adds: a transcribed voice
message goes through the EXACT SAME orchestrator/session machinery as the
text widget (real Conversation/Message rows, same session_token continuity),
a Nepali-detected recording forces a Romanized-Nepali reply regardless of the
conversation's own text-based lock, and every real failure mode (no speech,
STT failure, oversized upload, unknown business) degrades gracefully instead
of a raw 500. Real Deepgram API acceptance (an actual recorded voice clip) is
the user's own live test -- not reproducible here.
"""

import json as jsonlib
import uuid

import pytest
from fastapi.testclient import TestClient

import app.api.routes.voice as voice_module
from app.core.rate_limit import (
    WIDGET_BUSINESS_MAX_ATTEMPTS,
    WIDGET_IP_MAX_ATTEMPTS,
    WIDGET_SESSION_MAX_ATTEMPTS,
    WIDGET_WINDOW_SECONDS,
    RateLimiter,
)
from app.db.database import SessionLocal
from app.db.models.business import Business
from app.db.models.conversation import Conversation, Message
from app.main import app
from app.services.conversation.response_templates import render

client = TestClient(app)

_STUB_RESPONSE = "Thanks for calling!"
# This business has no knowledge base, so a general_question also triggers the
# zero-retrieval grounding backstop (orchestrator.py, "using honest fallback"),
# which overrides the stubbed LLM reply with this real deterministic template
# -- never the raw stub text -- plus the real Phase 19 handoff addendum, same
# real behavior documented in test_widget.py, not a voice-specific quirk.
_EXPECTED_RESPONSE = (
    render("unconfirmed_fact_fallback", "en") + " " + render("handoff_addendum", "en")
)

_FAKE_AUDIO = b"fake webm bytes, never actually decoded -- Deepgram is stubbed"


class _StubChat:
    """Records every `messages` list it's called with, so a test can inspect
    the real user-prompt text the orchestrator built for the LLM -- this is
    how force_language's effect (Phase 43h) is actually verified: not by
    trusting a comment, but by checking the real string the language
    override put in front of the model."""

    def __init__(self):
        self.calls = []

    def chat(self, messages):
        self.calls.append(messages)
        return jsonlib.dumps({"intent": "general_question", "response": _STUB_RESPONSE})


class _StubEmbed:
    def embed(self, texts):
        return [[0.01] * 1536 for _ in texts]


@pytest.fixture(autouse=True)
def _stub_llm_providers(monkeypatch):
    import app.services.conversation.intent as intent_module
    import app.services.conversation.orchestrator as orchestrator_module

    stub_chat = _StubChat()
    monkeypatch.setattr(intent_module, "get_chat_provider", lambda: stub_chat)
    monkeypatch.setattr(orchestrator_module, "get_embedding_provider", lambda: _StubEmbed())
    return stub_chat


@pytest.fixture(autouse=True)
def _fresh_rate_limiters(monkeypatch):
    """Rate limiters are process-wide singletons, imported by name into
    voice_module at module load time -- reset to a fresh instance per test
    so one test's requests never consume another test's (or another test
    file's) budget, same discipline as test_widget.py."""
    monkeypatch.setattr(
        voice_module, "widget_ip_rate_limiter", RateLimiter(max_attempts=WIDGET_IP_MAX_ATTEMPTS, window_seconds=WIDGET_WINDOW_SECONDS)
    )
    monkeypatch.setattr(
        voice_module,
        "widget_session_rate_limiter",
        RateLimiter(max_attempts=WIDGET_SESSION_MAX_ATTEMPTS, window_seconds=WIDGET_WINDOW_SECONDS),
    )
    monkeypatch.setattr(
        voice_module,
        "widget_business_rate_limiter",
        RateLimiter(max_attempts=WIDGET_BUSINESS_MAX_ATTEMPTS, window_seconds=WIDGET_WINDOW_SECONDS),
    )


def _unique_email(label: str) -> str:
    return f"{label}-{uuid.uuid4().hex[:10]}@example.com"


@pytest.fixture
def business():
    email = _unique_email("voice-owner")
    resp = client.post(
        "/api/v1/auth/register",
        json={"business_name": "Voice Test Biz", "timezone": "UTC", "email": email, "password": "correcthorse1"},
    )
    assert resp.status_code == 201, resp.text
    business_id = resp.json()["business_id"]
    yield business_id
    with SessionLocal() as db:
        b = db.get(Business, uuid.UUID(business_id))
        if b is not None:
            db.delete(b)
        db.commit()


class _FakeSTTProvider:
    """Stands in for app.voice.deepgram.DeepgramSTTProvider -- a real batch
    transcription result, without a real network call or Deepgram cost."""

    def __init__(self, *, text="Hello, do you take walk-ins?", language="en", confidence=0.95, raise_exc=None):
        self.text = text
        self.language = language
        self.confidence = confidence
        self.raise_exc = raise_exc
        self.calls = 0

    async def transcribe(self, audio: bytes, *, content_type: str) -> dict:
        self.calls += 1
        if self.raise_exc is not None:
            raise self.raise_exc
        return {"text": self.text, "language": self.language, "confidence": self.confidence}


def _stub_stt(monkeypatch, **kwargs) -> _FakeSTTProvider:
    provider = _FakeSTTProvider(**kwargs)
    monkeypatch.setattr(voice_module, "get_stt_provider", lambda: provider)
    return provider


def _post_voice(business_id, *, session_token: str | None = None, audio: bytes = _FAKE_AUDIO):
    data = {"session_token": session_token} if session_token else {}
    return client.post(
        f"/api/v1/widget/{business_id}/voice-message",
        files={"audio": ("voice-message.webm", audio, "audio/webm")},
        data=data,
    )


def test_english_voice_message_transcribes_and_reuses_the_real_orchestrator_and_persists_real_rows(business, monkeypatch):
    provider = _stub_stt(monkeypatch, text="Hello, do you take walk-ins?", language="en", confidence=0.95)

    resp = _post_voice(business)

    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert provider.calls == 1
    assert body["transcript"] == "Hello, do you take walk-ins?"
    assert body["response"] == _EXPECTED_RESPONSE
    assert body["intent"] == "general_question"
    assert body["session_token"]

    with SessionLocal() as db:
        conversation = db.query(Conversation).filter_by(business_id=uuid.UUID(business)).one()
        messages = db.query(Message).filter_by(conversation_id=conversation.id).order_by(Message.created_at).all()
        assert len(messages) == 2
        assert messages[0].content == "Hello, do you take walk-ins?"
        assert messages[1].content == _EXPECTED_RESPONSE


def test_voice_and_text_share_the_same_conversation_via_the_same_session_token(business, monkeypatch):
    text_resp = client.post(f"/api/v1/widget/{business}/messages", json={"content": "Hi there"})
    assert text_resp.status_code == 200, text_resp.text
    token = text_resp.json()["session_token"]

    _stub_stt(monkeypatch, text="Following up by voice", language="en", confidence=0.9)
    voice_resp = _post_voice(business, session_token=token)
    assert voice_resp.status_code == 200, voice_resp.text
    assert voice_resp.json()["session_token"] == token

    with SessionLocal() as db:
        conversations = db.query(Conversation).filter_by(business_id=uuid.UUID(business)).all()
        assert len(conversations) == 1
        messages = db.query(Message).filter_by(conversation_id=conversations[0].id).all()
        # 2 messages from the text turn + 2 from the voice turn, same conversation.
        assert len(messages) == 4


def test_nepali_detected_speech_forces_romanized_nepali_in_the_llm_prompt_regardless_of_lock(
    business, monkeypatch, _stub_llm_providers
):
    _stub_stt(monkeypatch, text="नमस्ते", language="ne", confidence=0.88)
    stub_chat = _stub_llm_providers

    resp = _post_voice(business)
    assert resp.status_code == 200, resp.text

    # The user prompt the orchestrator actually sent to the LLM must contain
    # the real Romanized-Nepali instruction (response_templates.LANGUAGE_LABELS
    # ["ne_roman"]) -- proof force_language reached classify_and_respond's
    # locked_language, not just a comment claiming it does.
    last_call_messages = stub_chat.calls[-1]
    user_prompt = last_call_messages[1]["content"]
    assert "Romanized/Latin" in user_prompt

    with SessionLocal() as db:
        conversation = db.query(Conversation).filter_by(business_id=uuid.UUID(business)).one()
        # The persisted lock itself is untouched by a voice turn -- still
        # unset, exactly as it would be before any typed message ever
        # arrived. Only THIS turn's reply was forced into Romanized Nepali.
        assert conversation.detected_language is None


def test_english_detected_speech_does_not_force_any_language_override(business, monkeypatch, _stub_llm_providers):
    _stub_stt(monkeypatch, text="Hello there", language="en", confidence=0.95)
    stub_chat = _stub_llm_providers

    resp = _post_voice(business)
    assert resp.status_code == 200, resp.text

    last_call_messages = stub_chat.calls[-1]
    user_prompt = last_call_messages[1]["content"]
    assert "locked language" not in user_prompt.lower()


def test_no_speech_detected_returns_a_clear_message_without_touching_the_orchestrator(business, monkeypatch):
    provider = _stub_stt(monkeypatch, text="   ", language="en", confidence=0.0)

    resp = _post_voice(business)

    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert provider.calls == 1
    assert body["transcript"] == ""
    assert "didn't catch" in body["response"].lower()
    assert body["intent"] is None

    with SessionLocal() as db:
        assert db.query(Conversation).filter_by(business_id=uuid.UUID(business)).count() == 0


def test_stt_provider_failure_degrades_gracefully_instead_of_a_500(business, monkeypatch):
    _stub_stt(monkeypatch, raise_exc=RuntimeError("DEEPGRAM_API_KEY is not configured."))

    resp = _post_voice(business)

    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert "trouble understanding" in body["response"].lower()
    assert body["intent"] is None

    with SessionLocal() as db:
        assert db.query(Conversation).filter_by(business_id=uuid.UUID(business)).count() == 0


def test_business_id_that_does_not_exist_returns_404_and_never_calls_stt(monkeypatch):
    provider = _stub_stt(monkeypatch)

    resp = _post_voice(str(uuid.uuid4()))

    assert resp.status_code == 404, resp.text
    assert provider.calls == 0


def test_recording_larger_than_the_max_size_is_rejected_with_413(business, monkeypatch):
    provider = _stub_stt(monkeypatch)
    oversized = b"a" * (voice_module._MAX_AUDIO_BYTES + 1)

    resp = _post_voice(business, audio=oversized)

    assert resp.status_code == 413, resp.text
    assert provider.calls == 0


def test_business_rate_limit_blocks_excessive_voice_messages(business, monkeypatch):
    monkeypatch.setattr(voice_module, "widget_business_rate_limiter", RateLimiter(max_attempts=2, window_seconds=60))
    _stub_stt(monkeypatch, text="hi", language="en", confidence=0.9)

    statuses = [_post_voice(business).status_code for _ in range(4)]

    assert statuses[:2] == [200, 200]
    assert all(s == 429 for s in statuses[2:])


def test_voice_reply_never_gets_response_bubbles_even_when_long(business, monkeypatch):
    """WidgetVoiceMessageResponse deliberately never got the response_bubbles field (see
    style_checks.split_into_bubbles / app/api/routes/widget.py's text-message route, which
    DOES get it) -- confirmed here with a reply long enough that the text widget path would
    populate it, to prove this is a real schema difference, not a coincidence of short stub
    text everywhere else in this file."""
    import app.services.conversation.intent as intent_module

    long_reply = (
        "We can absolutely help you get that rescheduled to a time that works better for you. "
        "Our team looks over every request personally to make sure nothing about your original booking gets lost "
        "in the process, so please do not worry about starting over from scratch. "
        "Once you tell us the new day and time you would like, we will confirm it back to you right away. "
        "We really do want to make this as easy as possible for you."
    )
    assert len(long_reply.split()) > 40

    class _StubChatWithLongReply:
        def chat(self, messages):
            return jsonlib.dumps({"intent": "cancellation", "response": long_reply})

    monkeypatch.setattr(intent_module, "get_chat_provider", lambda: _StubChatWithLongReply())
    _stub_stt(monkeypatch, text="Can I move my appointment?", language="en", confidence=0.95)

    resp = _post_voice(business)

    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["response"] == long_reply
    assert "response_bubbles" not in body, "voice's response schema must never grow this field"
