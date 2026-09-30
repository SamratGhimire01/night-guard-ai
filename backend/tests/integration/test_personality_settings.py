"""The AI assistant personality in Settings actually reaches the AI.

End to end through the same API the Settings page uses (PATCH /business/me), then a real customer message through the
website chat: the AI provider is replaced by a recorder, so the test reads the exact system prompt the model would get."""

import json
import uuid

import pytest
from fastapi.testclient import TestClient

import app.api.routes.widget as widget_module
import app.services.conversation.intent as intent_module
import app.services.conversation.orchestrator as orchestrator_module
from app.core.rate_limit import WIDGET_IP_MAX_ATTEMPTS, WIDGET_WINDOW_SECONDS, RateLimiter
from app.db.database import SessionLocal
from app.db.models.business import Business
from app.main import app

client = TestClient(app)


class _RecordingChat:
    def __init__(self):
        self.prompts = []

    def chat(self, messages):
        self.prompts.append(messages[0]["content"])
        return json.dumps({"intent": "greeting", "response": "Hello!"})


class _Embed:
    def embed(self, texts):
        return [[0.01] * 1536 for _ in texts]


@pytest.fixture
def recorder(monkeypatch):
    chat = _RecordingChat()
    monkeypatch.setattr(intent_module, "get_chat_provider", lambda: chat)
    monkeypatch.setattr(orchestrator_module, "get_embedding_provider", lambda: _Embed())
    monkeypatch.setattr(
        widget_module, "widget_ip_rate_limiter", RateLimiter(max_attempts=WIDGET_IP_MAX_ATTEMPTS, window_seconds=WIDGET_WINDOW_SECONDS)
    )
    return chat


@pytest.fixture
def owner():
    email = f"persona-{uuid.uuid4().hex[:10]}@example.com"
    reg = client.post(
        "/api/v1/auth/register",
        json={"business_name": "Persona Clinic", "timezone": "UTC", "email": email, "password": "correcthorse1"},
    )
    token = client.post("/api/v1/auth/login", json={"email": email, "password": "correcthorse1"}).json()["access_token"]
    business_id = reg.json()["business_id"]
    yield business_id, {"Authorization": f"Bearer {token}"}
    with SessionLocal() as db:
        db.delete(db.get(Business, uuid.UUID(business_id)))
        db.commit()


def _system_prompt_after_a_customer_message(business_id, recorder):
    resp = client.post(f"/api/v1/widget/{business_id}/messages", json={"content": "Hello"})
    assert resp.status_code == 200, resp.text
    assert recorder.prompts, "the AI was never called"
    return recorder.prompts[-1]


def test_personality_saved_in_settings_reaches_the_ai(owner, recorder):
    business_id, headers = owner
    resp = client.patch(
        "/api/v1/business/me",
        headers=headers,
        json={"persona_name": "Priya", "formality": "formal", "emoji_policy": "none", "sign_off": "Team Persona Clinic"},
    )
    assert resp.status_code == 200, resp.text

    prompt = _system_prompt_after_a_customer_message(business_id, recorder)
    assert "Your name is Priya" in prompt
    assert "Lean more formal" in prompt
    assert "Emoji override: never use an emoji" in prompt
    assert "Team Persona Clinic" in prompt


def test_default_personality_adds_nothing(owner, recorder):
    business_id, _ = owner
    prompt = _system_prompt_after_a_customer_message(business_id, recorder)
    assert "Your name is" not in prompt
    assert "Emoji override" not in prompt
    assert "Lean casual" not in prompt and "Lean more formal" not in prompt


def test_clearing_the_name_in_settings_removes_it_from_the_ai(owner, recorder):
    business_id, headers = owner
    client.patch("/api/v1/business/me", headers=headers, json={"persona_name": "Priya"})
    client.patch("/api/v1/business/me", headers=headers, json={"persona_name": None})
    prompt = _system_prompt_after_a_customer_message(business_id, recorder)
    assert "Your name is" not in prompt
