"""Phase 20 — AI training room (app/services/training_service.py,
POST/GET /api/v1/training/*).

Real DB and real HTTP throughout. The embedding provider is stubbed
(deterministic, zero-cost — real embedding/search behavior is already proven
in Phase 6) and the chat provider is stubbed per-test with a small function
that inspects the ACTUAL user prompt handed to it (specifically, whether the
corrected knowledge text appears in the "Retrieved knowledge" section) —
this proves the real wiring (search_chunks actually finding the new chunk,
classify_and_respond actually receiving it) rather than faking the outcome
directly. Real, un-stubbed end-to-end proof against the live Azure API is in
PHASE_STATUS.md.
"""

import json as jsonlib
import uuid

import pytest
from fastapi.testclient import TestClient

from app.core.security import create_access_token
from app.db.database import SessionLocal
from app.db.models.business import Business, BusinessUser, BusinessUserRole
from app.db.models.knowledge import EMBEDDING_DIMENSIONS, KnowledgeChunk, KnowledgeDocument
from app.db.models.training import TrainingQuestion
from app.main import app
from app.services import training_service

client = TestClient(app)


class _FakeEmbeddingProvider:
    def embed(self, texts: list[str]) -> list[list[float]]:
        return [[0.01] * EMBEDDING_DIMENSIONS for _ in texts]


@pytest.fixture(autouse=True)
def _stub_embeddings(monkeypatch):
    monkeypatch.setattr(training_service, "get_embedding_provider", lambda: _FakeEmbeddingProvider())
    # knowledge_service.create_document -> _regenerate_chunks also needs a stub
    # embedding provider for any document approved directly by feedback.
    import app.services.knowledge_service as knowledge_service_module

    monkeypatch.setattr(knowledge_service_module, "get_embedding_provider", lambda: _FakeEmbeddingProvider())


def _stub_chat(monkeypatch, *, marker: str | None, intent: str, matched_response: str, fallback_response: str):
    """A deterministic stand-in for the real LLM that answers based on whether
    `marker` text actually appears in the real "Retrieved knowledge" section of
    the real prompt built by intent._build_user_prompt — this is what proves
    the retrieval wiring is real (search_chunks found the new chunk and it
    reached the prompt), not a canned answer regardless of input."""
    import app.services.conversation.intent as intent_module

    class _StubChat:
        def chat(self, messages):
            user_content = messages[1]["content"]
            if marker and marker in user_content:
                return jsonlib.dumps({"intent": intent, "response": matched_response})
            return jsonlib.dumps({"intent": intent, "response": fallback_response})

    monkeypatch.setattr(intent_module, "get_chat_provider", lambda: _StubChat())


def _unique_email(label: str) -> str:
    return f"{label}-{uuid.uuid4().hex[:10]}@example.com"


def _auth_header(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


@pytest.fixture
def two_businesses():
    email_a = _unique_email("tr-a-owner")
    email_b = _unique_email("tr-b-owner")
    resp_a = client.post(
        "/api/v1/auth/register",
        json={"business_name": "Training Test A", "timezone": "UTC", "email": email_a, "password": "correcthorse1"},
    )
    resp_b = client.post(
        "/api/v1/auth/register",
        json={"business_name": "Training Test B", "timezone": "UTC", "email": email_b, "password": "correcthorse1"},
    )
    assert resp_a.status_code == 201, resp_a.text
    assert resp_b.status_code == 201, resp_b.text
    login_a = client.post("/api/v1/auth/login", json={"email": email_a, "password": "correcthorse1"})
    login_b = client.post("/api/v1/auth/login", json={"email": email_b, "password": "correcthorse1"})
    data = {
        "business_id_a": uuid.UUID(resp_a.json()["business_id"]),
        "business_id_b": uuid.UUID(resp_b.json()["business_id"]),
        "token_a": login_a.json()["access_token"],
        "token_b": login_b.json()["access_token"],
    }
    yield data
    with SessionLocal() as db:
        for business_id in (data["business_id_a"], data["business_id_b"]):
            business = db.get(Business, business_id)
            if business is not None:
                db.delete(business)
        db.commit()


@pytest.fixture
def staff_token(two_businesses):
    business_id_a = two_businesses["business_id_a"]
    with SessionLocal() as db:
        staff_user = BusinessUser(
            business_id=business_id_a,
            email=_unique_email("tr-staff"),
            hashed_password="unused",
            role=BusinessUserRole.STAFF,
        )
        db.add(staff_user)
        db.commit()
        db.refresh(staff_user)
        return create_access_token(user_id=staff_user.id, business_id=business_id_a, role=staff_user.role.value)


_QUESTION = "Do you offer laser teeth whitening, and what brand of laser do you use?"
_CORRECTION = "We offer laser teeth whitening using the Zoom WhiteSpeed laser system."
_HONEST_FALLBACK = "I don't have that information in my records."
_MATCHED_ANSWER = f"Yes — {_CORRECTION}"


def test_ask_with_no_matching_knowledge_returns_honest_answer_and_empty_chunks(two_businesses, monkeypatch):
    _stub_chat(monkeypatch, marker=_CORRECTION, intent="service_question", matched_response=_MATCHED_ANSWER, fallback_response=_HONEST_FALLBACK)
    token = two_businesses["token_a"]

    resp = client.post("/api/v1/training/ask", json={"question": _QUESTION}, headers=_auth_header(token))
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["question"] == _QUESTION
    assert body["answer"] == _HONEST_FALLBACK
    assert body["intent"] == "service_question"
    assert body["knowledge_chunks_used"] == []

    with SessionLocal() as db:
        tq = db.get(TrainingQuestion, uuid.UUID(body["training_question_id"]))
        assert tq is not None
        assert tq.answer == _HONEST_FALLBACK
        assert tq.is_correct is None
        assert tq.correction_knowledge_document_id is None


def test_correct_feedback_creates_no_knowledge_document(two_businesses, monkeypatch):
    _stub_chat(monkeypatch, marker=_CORRECTION, intent="service_question", matched_response=_MATCHED_ANSWER, fallback_response=_HONEST_FALLBACK)
    token = two_businesses["token_a"]

    ask_resp = client.post("/api/v1/training/ask", json={"question": "Are you open on weekends?"}, headers=_auth_header(token))
    tq_id = ask_resp.json()["training_question_id"]

    before_count = _knowledge_document_count(two_businesses["business_id_a"])
    fb_resp = client.post(
        "/api/v1/training/feedback",
        json={"training_question_id": tq_id, "is_correct": True},
        headers=_auth_header(token),
    )
    assert fb_resp.status_code == 200, fb_resp.text
    body = fb_resp.json()
    assert body["is_correct"] is True
    assert body["corrected_answer"] is None
    assert body["correction_knowledge_document_id"] is None
    after_count = _knowledge_document_count(two_businesses["business_id_a"])
    assert after_count == before_count  # no new document from a "correct" mark


def test_incorrect_feedback_creates_real_approved_document_with_real_chunks(two_businesses, monkeypatch):
    _stub_chat(monkeypatch, marker=_CORRECTION, intent="service_question", matched_response=_MATCHED_ANSWER, fallback_response=_HONEST_FALLBACK)
    token = two_businesses["token_a"]

    ask_resp = client.post("/api/v1/training/ask", json={"question": _QUESTION}, headers=_auth_header(token))
    tq_id = ask_resp.json()["training_question_id"]

    fb_resp = client.post(
        "/api/v1/training/feedback",
        json={"training_question_id": tq_id, "is_correct": False, "corrected_answer": _CORRECTION},
        headers=_auth_header(token),
    )
    assert fb_resp.status_code == 200, fb_resp.text
    body = fb_resp.json()
    assert body["is_correct"] is False
    assert body["corrected_answer"] == _CORRECTION
    doc_id = body["correction_knowledge_document_id"]
    assert doc_id is not None

    with SessionLocal() as db:
        doc = db.get(KnowledgeDocument, uuid.UUID(doc_id))
        assert doc is not None
        assert doc.source == "training_room"
        assert doc.status.value == "approved"
        assert doc.approved_by is not None
        assert doc.approved_at is not None
        assert doc.content == _CORRECTION

        chunks = db.query(KnowledgeChunk).filter(KnowledgeChunk.knowledge_document_id == doc.id).all()
        assert len(chunks) >= 1
        for chunk in chunks:
            assert chunk.embedding is not None
            assert len(chunk.embedding) == EMBEDDING_DIMENSIONS


def test_loop_closes_reasking_the_same_question_reflects_the_correction(two_businesses, monkeypatch):
    _stub_chat(monkeypatch, marker=_CORRECTION, intent="service_question", matched_response=_MATCHED_ANSWER, fallback_response=_HONEST_FALLBACK)
    token = two_businesses["token_a"]

    first = client.post("/api/v1/training/ask", json={"question": _QUESTION}, headers=_auth_header(token))
    assert first.json()["answer"] == _HONEST_FALLBACK
    tq_id = first.json()["training_question_id"]

    client.post(
        "/api/v1/training/feedback",
        json={"training_question_id": tq_id, "is_correct": False, "corrected_answer": _CORRECTION},
        headers=_auth_header(token),
    )

    second = client.post("/api/v1/training/ask", json={"question": _QUESTION}, headers=_auth_header(token))
    assert second.status_code == 200, second.text
    body = second.json()
    assert body["answer"] == _MATCHED_ANSWER  # now reflects the correction
    assert any(_CORRECTION in c["content"] for c in body["knowledge_chunks_used"])


def test_cross_tenant_training_and_corrections_are_isolated(two_businesses, monkeypatch):
    _stub_chat(monkeypatch, marker=_CORRECTION, intent="service_question", matched_response=_MATCHED_ANSWER, fallback_response=_HONEST_FALLBACK)
    token_a = two_businesses["token_a"]
    token_b = two_businesses["token_b"]

    ask_a = client.post("/api/v1/training/ask", json={"question": _QUESTION}, headers=_auth_header(token_a))
    tq_a_id = ask_a.json()["training_question_id"]
    client.post(
        "/api/v1/training/feedback",
        json={"training_question_id": tq_a_id, "is_correct": False, "corrected_answer": _CORRECTION},
        headers=_auth_header(token_a),
    )

    # Business B asks the identical question — must NOT see Business A's correction.
    ask_b = client.post("/api/v1/training/ask", json={"question": _QUESTION}, headers=_auth_header(token_b))
    assert ask_b.json()["answer"] == _HONEST_FALLBACK
    assert ask_b.json()["knowledge_chunks_used"] == []

    # Business B cannot submit feedback against Business A's training question id.
    fb_cross = client.post(
        "/api/v1/training/feedback",
        json={"training_question_id": tq_a_id, "is_correct": True},
        headers=_auth_header(token_b),
    )
    assert fb_cross.status_code == 404, fb_cross.text

    history_b = client.get("/api/v1/training/history", headers=_auth_header(token_b))
    assert tq_a_id not in {h["id"] for h in history_b.json()}


def test_staff_forbidden_from_ask_and_feedback(two_businesses, staff_token, monkeypatch):
    _stub_chat(monkeypatch, marker=_CORRECTION, intent="service_question", matched_response=_MATCHED_ANSWER, fallback_response=_HONEST_FALLBACK)
    resp = client.post("/api/v1/training/ask", json={"question": _QUESTION}, headers=_auth_header(staff_token))
    assert resp.status_code == 403

    resp = client.post(
        "/api/v1/training/feedback",
        json={"training_question_id": str(uuid.uuid4()), "is_correct": True},
        headers=_auth_header(staff_token),
    )
    assert resp.status_code == 403

    resp = client.get("/api/v1/training/history", headers=_auth_header(staff_token))
    assert resp.status_code == 403


def test_history_is_tenant_scoped_and_newest_first(two_businesses, monkeypatch):
    _stub_chat(monkeypatch, marker=None, intent="general_question", matched_response="n/a", fallback_response="First honest answer.")
    token = two_businesses["token_a"]

    client.post("/api/v1/training/ask", json={"question": "Question one?"}, headers=_auth_header(token))
    client.post("/api/v1/training/ask", json={"question": "Question two?"}, headers=_auth_header(token))

    resp = client.get("/api/v1/training/history", headers=_auth_header(token))
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert len(body) == 2
    assert body[0]["question"] == "Question two?"  # newest first
    assert body[1]["question"] == "Question one?"


def test_feedback_requires_corrected_answer_when_incorrect(two_businesses, monkeypatch):
    _stub_chat(monkeypatch, marker=_CORRECTION, intent="service_question", matched_response=_MATCHED_ANSWER, fallback_response=_HONEST_FALLBACK)
    token = two_businesses["token_a"]
    ask_resp = client.post("/api/v1/training/ask", json={"question": _QUESTION}, headers=_auth_header(token))
    tq_id = ask_resp.json()["training_question_id"]

    resp = client.post(
        "/api/v1/training/feedback",
        json={"training_question_id": tq_id, "is_correct": False},
        headers=_auth_header(token),
    )
    assert resp.status_code == 422


def _knowledge_document_count(business_id: uuid.UUID) -> int:
    with SessionLocal() as db:
        return db.query(KnowledgeDocument).filter(KnowledgeDocument.business_id == business_id).count()
