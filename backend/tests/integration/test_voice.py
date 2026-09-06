"""Phase 43 -- in-app voice call (app/api/routes/voice.py, app/voice/).

Deepgram STT/TTS are stubbed with fakes (same discipline as test_widget.py's
stubbed ChatProvider/EmbeddingProvider) so this suite is fast, free, and
deterministic. The point of these tests is the real wiring this phase adds:
that a transcribed voice turn goes through the EXACT SAME orchestrator/
session machinery as the text widget (real Conversation/Message rows, same
session_token continuity), that the max-call-duration guardrail actually
cuts a session off, and that a Deepgram failure degrades gracefully instead
of hanging. Real Deepgram API acceptance (actual STT/TTS calls, actual live
audio) is the user's own live microphone test -- not reproducible here.
"""

import json as jsonlib
import uuid

import pytest
from fastapi.testclient import TestClient

import app.api.routes.voice as voice_module
from app.core.rate_limit import WIDGET_IP_MAX_ATTEMPTS, WIDGET_SESSION_MAX_ATTEMPTS, WIDGET_WINDOW_SECONDS, RateLimiter
from app.db.database import SessionLocal
from app.db.models.business import Business
from app.db.models.conversation import Conversation, Message
from app.main import app
from app.voice.deepgram import DeepgramSTTProvider, DeepgramTTSProvider

client = TestClient(app)


_STUB_RESPONSE = "Thanks for calling!"
# This business has no knowledge base, so a general_question also triggers a
# real Phase 19 handoff, appended verbatim -- same real behavior documented
# in test_widget.py, not a voice-specific quirk.
_EXPECTED_RESPONSE = _STUB_RESPONSE + " I've also let our team know, so a real person will follow up with you."


class _StubChat:
    def chat(self, messages):
        return jsonlib.dumps({"intent": "general_question", "response": _STUB_RESPONSE})


class _StubEmbed:
    def embed(self, texts):
        return [[0.01] * 1536 for _ in texts]


@pytest.fixture(autouse=True)
def _stub_llm_providers(monkeypatch):
    import app.services.conversation.intent as intent_module
    import app.services.conversation.orchestrator as orchestrator_module

    monkeypatch.setattr(intent_module, "get_chat_provider", lambda: _StubChat())
    monkeypatch.setattr(orchestrator_module, "get_embedding_provider", lambda: _StubEmbed())


@pytest.fixture(autouse=True)
def _fresh_rate_limiters(monkeypatch):
    monkeypatch.setattr(
        voice_module, "widget_ip_rate_limiter", RateLimiter(max_attempts=WIDGET_IP_MAX_ATTEMPTS, window_seconds=WIDGET_WINDOW_SECONDS)
    )
    monkeypatch.setattr(
        voice_module,
        "widget_session_rate_limiter",
        RateLimiter(max_attempts=WIDGET_SESSION_MAX_ATTEMPTS, window_seconds=WIDGET_WINDOW_SECONDS),
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


class _FakeSTTSession:
    """Yields a scripted list of events, one per items in `events`, then ends
    (mirrors a real Deepgram session that closes after the call ends)."""

    def __init__(self, events):
        self._events = events
        self.sent_audio = []

    async def send_audio(self, chunk):
        self.sent_audio.append(chunk)

    async def events(self):
        for event in self._events:
            yield event

    async def close(self):
        pass


class _HangingSTTSession:
    """Never yields anything and never returns -- simulates an open mic with
    no speech, so the only thing that can end the call is the max-duration
    guardrail in the audio-pump loop, not this task finishing on its own."""

    async def send_audio(self, chunk):
        pass

    async def events(self):
        import asyncio

        await asyncio.Event().wait()
        yield {}  # pragma: no cover -- unreachable, only present to make this an async generator

    async def close(self):
        pass


class _RaisingSTTSession:
    """Simulates a real Deepgram disconnect/error mid-call."""

    async def send_audio(self, chunk):
        pass

    async def events(self):
        raise ConnectionError("simulated Deepgram disconnect")
        yield {}  # pragma: no cover -- unreachable, only present to make this an async generator

    async def close(self):
        pass


class _FakeSTTProvider:
    def __init__(self, session):
        self._session = session

    async def connect(self):
        return self._session


class _FailingSTTProvider:
    async def connect(self):
        raise ConnectionError("simulated Deepgram connect failure")


class _FakeTTSProvider:
    def __init__(self):
        self.calls = []

    def synthesize(self, text):
        self.calls.append(text)
        return b"FAKE_AUDIO:" + text.encode()


def test_a_full_voice_turn_reuses_the_real_orchestrator_and_persists_real_rows(business, monkeypatch):
    events = [{"type": "transcript", "text": "Do you take walk-ins?", "is_final": True, "speech_final": True}]
    monkeypatch.setattr(voice_module, "get_stt_provider", lambda: _FakeSTTProvider(_FakeSTTSession(events)))
    fake_tts = _FakeTTSProvider()
    monkeypatch.setattr(voice_module, "get_tts_provider", lambda: fake_tts)

    with client.websocket_connect(f"/api/v1/widget/{business}/voice") as ws:
        transcript_msg = ws.receive_json()
        assert transcript_msg == {"type": "transcript", "text": "Do you take walk-ins?"}

        thinking_msg = ws.receive_json()
        assert thinking_msg == {"type": "state", "value": "thinking"}

        agent_msg = ws.receive_json()
        assert agent_msg["type"] == "agent_text"
        assert agent_msg["text"] == _EXPECTED_RESPONSE
        session_token = agent_msg["session_token"]
        assert session_token

        speaking_msg = ws.receive_json()
        assert speaking_msg == {"type": "state", "value": "speaking"}

        audio_bytes = ws.receive_bytes()
        assert audio_bytes == b"FAKE_AUDIO:" + _EXPECTED_RESPONSE.encode()

        listening_msg = ws.receive_json()
        assert listening_msg == {"type": "state", "value": "listening"}

    assert fake_tts.calls == [_EXPECTED_RESPONSE]

    # Real DB rows, same shape as the text widget path -- proof this is the
    # SAME orchestrator/session machinery, not a parallel voice-only path.
    with SessionLocal() as db:
        conversations = db.query(Conversation).filter(Conversation.business_id == uuid.UUID(business)).all()
        assert len(conversations) == 1
        assert conversations[0].channel == "website"
        messages = db.query(Message).filter(Message.conversation_id == conversations[0].id).all()
        assert len(messages) == 2  # customer (transcribed) + agent


def test_voice_and_text_share_the_same_conversation_via_the_same_session_token(business, monkeypatch):
    events = [{"type": "transcript", "text": "Hi from voice", "is_final": True, "speech_final": True}]
    monkeypatch.setattr(voice_module, "get_stt_provider", lambda: _FakeSTTProvider(_FakeSTTSession(events)))
    monkeypatch.setattr(voice_module, "get_tts_provider", lambda: _FakeTTSProvider())

    with client.websocket_connect(f"/api/v1/widget/{business}/voice") as ws:
        ws.receive_json()  # transcript
        ws.receive_json()  # state: thinking
        agent_msg = ws.receive_json()  # agent_text
        session_token = agent_msg["session_token"]
        ws.receive_json()  # state: speaking
        ws.receive_bytes()  # audio
        ws.receive_json()  # state: listening

    # Continuing with the SAME token via the ORDINARY text endpoint must land
    # in the SAME conversation -- this is the whole point of Phase 43 reusing
    # widget_service.send_widget_message rather than a separate voice path.
    text_resp = client.post(
        f"/api/v1/widget/{business}/messages", json={"session_token": session_token, "content": "Now I'm typing"}
    )
    assert text_resp.status_code == 200, text_resp.text
    assert text_resp.json()["session_token"] == session_token

    with SessionLocal() as db:
        conversations = db.query(Conversation).filter(Conversation.business_id == uuid.UUID(business)).all()
        assert len(conversations) == 1  # NOT a second conversation
        messages = db.query(Message).filter(Message.conversation_id == conversations[0].id).all()
        assert len(messages) == 4  # 2 from voice + 2 from the follow-up text message


def test_max_call_duration_guardrail_actually_cuts_the_call_off(business, monkeypatch):
    monkeypatch.setattr(voice_module, "get_stt_provider", lambda: _FakeSTTProvider(_HangingSTTSession()))
    monkeypatch.setattr(voice_module, "get_tts_provider", lambda: _FakeTTSProvider())
    monkeypatch.setattr(voice_module, "MAX_CALL_SECONDS", 0.3)

    with client.websocket_connect(f"/api/v1/widget/{business}/voice") as ws:
        msg = ws.receive_json()
        assert msg == {"type": "call_ended", "reason": "max_duration"}


def test_simulated_deepgram_connect_failure_degrades_gracefully_instead_of_hanging(business, monkeypatch):
    monkeypatch.setattr(voice_module, "get_stt_provider", lambda: _FailingSTTProvider())

    with client.websocket_connect(f"/api/v1/widget/{business}/voice") as ws:
        msg = ws.receive_json()
        assert msg == {"type": "error", "message": voice_module._DEGRADE_MESSAGE}


def test_simulated_deepgram_disconnect_mid_call_degrades_gracefully_instead_of_hanging(business, monkeypatch):
    monkeypatch.setattr(voice_module, "get_stt_provider", lambda: _FakeSTTProvider(_RaisingSTTSession()))
    monkeypatch.setattr(voice_module, "get_tts_provider", lambda: _FakeTTSProvider())

    with client.websocket_connect(f"/api/v1/widget/{business}/voice") as ws:
        msg = ws.receive_json()
        assert msg == {"type": "error", "message": voice_module._DEGRADE_MESSAGE}


def test_business_id_that_does_not_exist_closes_with_a_plain_error():
    with client.websocket_connect(f"/api/v1/widget/{uuid.uuid4()}/voice") as ws:
        msg = ws.receive_json()
        assert msg == {"type": "error", "message": "Business not found."}


def test_deepgram_providers_refuse_to_run_with_no_api_key_configured(monkeypatch):
    import asyncio

    from app.voice import deepgram as deepgram_module

    monkeypatch.setattr(deepgram_module.settings, "deepgram_api_key", "")

    with pytest.raises(RuntimeError):
        asyncio.run(DeepgramSTTProvider().connect())

    with pytest.raises(RuntimeError):
        DeepgramTTSProvider().synthesize("hello")
