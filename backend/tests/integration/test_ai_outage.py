"""When the AI provider is unreachable, screens that can't degrade (saving knowledge, the Training Room) answer with a
clear 503 instead of crashing, nothing is half-saved, and every error response keeps its CORS headers so the dashboard
can show the message.

Real HTTP through the app, real Postgres; only the embedding provider is replaced (a working one or one that fails
exactly like the real client does after its retries)."""

import uuid

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import func, select

import app.services.knowledge_service as knowledge_service_module
import app.services.training_service as training_service_module
from app.core.exceptions import AI_UNAVAILABLE_MESSAGE
from app.db.database import SessionLocal
from app.db.models.business import Business
from app.db.models.knowledge import EMBEDDING_DIMENSIONS, KnowledgeChunk, KnowledgeDocument
from app.llm.base import LLMProviderError
from app.main import app

client = TestClient(app)
DASHBOARD = {"Origin": "http://localhost:5173"}


class _Working:
    def embed(self, texts):
        return [[0.01] * EMBEDDING_DIMENSIONS for _ in texts]


class _Down:
    def embed(self, texts):
        raise LLMProviderError("LLM provider request failed: ConnectError")


def _provider(monkeypatch, provider):
    monkeypatch.setattr(knowledge_service_module, "get_embedding_provider", lambda: provider)
    monkeypatch.setattr(training_service_module, "get_embedding_provider", lambda: provider)


@pytest.fixture
def owner():
    email = f"outage-{uuid.uuid4().hex[:10]}@example.com"
    reg = client.post(
        "/api/v1/auth/register",
        json={"business_name": "Outage Clinic", "timezone": "UTC", "email": email, "password": "correcthorse1"},
    )
    token = client.post("/api/v1/auth/login", json={"email": email, "password": "correcthorse1"}).json()["access_token"]
    business_id = reg.json()["business_id"]
    yield business_id, {"Authorization": f"Bearer {token}", **DASHBOARD}
    with SessionLocal() as db:
        db.delete(db.get(Business, uuid.UUID(business_id)))
        db.commit()


def _document_count(business_id: str) -> int:
    with SessionLocal() as db:
        return db.execute(
            select(func.count()).select_from(KnowledgeDocument).where(KnowledgeDocument.business_id == uuid.UUID(business_id))
        ).scalar_one()


def test_saving_knowledge_while_ai_is_down_is_a_clear_503_and_saves_nothing(owner, monkeypatch):
    business_id, headers = owner
    _provider(monkeypatch, _Down())
    resp = client.post("/api/v1/knowledge", headers=headers, json={"title": "Parking", "content": "Free parking behind."})
    assert resp.status_code == 503
    assert resp.json()["error"] == {"type": "ai_unavailable", "message": AI_UNAVAILABLE_MESSAGE}
    assert resp.headers["access-control-allow-origin"] == "http://localhost:5173"
    assert _document_count(business_id) == 0


def test_editing_knowledge_while_ai_is_down_leaves_the_document_and_its_search_index_unchanged(owner, monkeypatch):
    business_id, headers = owner
    _provider(monkeypatch, _Working())
    doc = client.post("/api/v1/knowledge", headers=headers, json={"title": "Hours", "content": "Open 9 to 5."}).json()
    with SessionLocal() as db:
        chunks_before = db.execute(
            select(KnowledgeChunk.content).where(KnowledgeChunk.knowledge_document_id == uuid.UUID(doc["id"]))
        ).scalars().all()
    assert chunks_before

    _provider(monkeypatch, _Down())
    resp = client.patch(f"/api/v1/knowledge/{doc['id']}", headers=headers, json={"content": "Open 10 to 6."})
    assert resp.status_code == 503

    reread = client.get(f"/api/v1/knowledge/{doc['id']}", headers=headers).json()
    assert reread["content"] == "Open 9 to 5."
    assert reread["version"] == doc["version"]
    with SessionLocal() as db:
        chunks_after = db.execute(
            select(KnowledgeChunk.content).where(KnowledgeChunk.knowledge_document_id == uuid.UUID(doc["id"]))
        ).scalars().all()
    assert chunks_after == chunks_before


def test_saving_knowledge_normally_still_indexes_it(owner, monkeypatch):
    business_id, headers = owner
    _provider(monkeypatch, _Working())
    resp = client.post("/api/v1/knowledge", headers=headers, json={"title": "Parking", "content": "Free parking behind."})
    assert resp.status_code == 201
    with SessionLocal() as db:
        n = db.execute(
            select(func.count()).select_from(KnowledgeChunk).where(KnowledgeChunk.knowledge_document_id == uuid.UUID(resp.json()["id"]))
        ).scalar_one()
    assert n >= 1


def test_archiving_needs_no_ai_and_removes_the_document_from_search(owner, monkeypatch):
    _, headers = owner
    _provider(monkeypatch, _Working())
    doc = client.post("/api/v1/knowledge", headers=headers, json={"title": "Hours", "content": "Open 9 to 5."}).json()
    _provider(monkeypatch, _Down())
    resp = client.patch(f"/api/v1/knowledge/{doc['id']}", headers=headers, json={"status": "archived"})
    assert resp.status_code == 200
    with SessionLocal() as db:
        n = db.execute(
            select(func.count()).select_from(KnowledgeChunk).where(KnowledgeChunk.knowledge_document_id == uuid.UUID(doc["id"]))
        ).scalar_one()
    assert n == 0


def test_training_room_question_while_ai_is_down_is_a_clear_503(owner, monkeypatch):
    _, headers = owner
    _provider(monkeypatch, _Down())
    resp = client.post("/api/v1/training/ask", headers=headers, json={"question": "When are you open?"})
    assert resp.status_code == 503
    assert resp.json()["error"]["type"] == "ai_unavailable"


def test_an_unexpected_error_is_json_and_keeps_cors_headers(owner, monkeypatch):
    _, headers = owner
    import app.api.routes.business as business_routes

    def boom(*args, **kwargs):
        raise ValueError("something unexpected")

    monkeypatch.setattr(business_routes.business_service, "get_business", boom)
    resp = client.get("/api/v1/business/plan", headers=headers)
    assert resp.status_code == 500
    assert resp.json() == {"error": {"type": "internal_error", "message": "An unexpected error occurred."}}
    assert resp.headers["access-control-allow-origin"] == "http://localhost:5173"
