# ruff: noqa: F811  (fixtures imported from the Phase 20 suite are re-declared as test arguments — the pytest idiom)
"""Training Room, second path: the owner writes a question AND its correct answer directly (POST /training/qa) — no test
run first. It becomes approved knowledge at once through the same create_document pipeline a correction uses, and a
real later customer conversation retrieves and uses it. Real DB + HTTP; embeddings stubbed as in test_training.py (real
embedding behaviour: Phase 6 and the live proof in PHASE_STATUS.md)."""

import json as jsonlib

from app.db.database import SessionLocal
from app.db.models.knowledge import KnowledgeChunk, KnowledgeDocument, KnowledgeDocumentStatus
from app.services.conversation.response_templates import render
from tests.integration.test_training import (  # noqa: F401
    _CORRECTION,
    _HONEST_FALLBACK,
    _QUESTION,
    _auth_header,
    _stub_chat,
    _stub_embeddings,
    client,
    staff_token,
    two_businesses,
)

_ANSWER = "Yes — we whiten teeth with the Zoom WhiteSpeed laser, 60 minutes, NPR 12000."


def _author(token, question=_QUESTION, answer=_ANSWER):
    return client.post("/api/v1/training/qa", json={"question": question, "answer": answer}, headers=_auth_header(token))


def test_authored_qa_becomes_approved_knowledge_with_real_chunks(two_businesses):
    resp = _author(two_businesses["token_a"])
    assert resp.status_code == 201, resp.text
    with SessionLocal() as db:
        doc = db.get(KnowledgeDocument, resp.json()["knowledge_document_id"])
        assert doc.business_id == two_businesses["business_id_a"]
        assert doc.status == KnowledgeDocumentStatus.APPROVED and doc.approved_by is not None
        assert doc.source == "training_room" and doc.title == f"Training Q&A: {_QUESTION}"
        assert doc.content == f"Q: {_QUESTION}\nA: {_ANSWER}"
        chunks = db.query(KnowledgeChunk).filter_by(knowledge_document_id=doc.id).all()
        assert chunks and all(_ANSWER in c.content and _QUESTION in c.content for c in chunks)


def test_authored_qa_is_used_by_the_training_room_test_without_any_feedback_step(two_businesses, monkeypatch):
    _stub_chat(monkeypatch, marker=_ANSWER, intent="service_question", matched_response=_ANSWER, fallback_response=_HONEST_FALLBACK)
    token = two_businesses["token_a"]
    before = client.post("/api/v1/training/ask", json={"question": _QUESTION}, headers=_auth_header(token)).json()
    assert before["answer"] == _HONEST_FALLBACK and before["knowledge_chunks_used"] == []
    _author(token)
    after = client.post("/api/v1/training/ask", json={"question": _QUESTION}, headers=_auth_header(token)).json()
    assert after["answer"] == _ANSWER
    assert any(_ANSWER in c["content"] for c in after["knowledge_chunks_used"])


def test_authored_qa_reaches_a_real_customer_conversation_and_not_another_business(two_businesses, monkeypatch):
    import app.services.conversation.orchestrator as orchestrator_module
    from tests.integration.test_payment_choice import _conversation

    monkeypatch.setattr(orchestrator_module, "get_embedding_provider", lambda: _Embed())
    _stub_chat(monkeypatch, marker=_ANSWER, intent="service_question", matched_response=_ANSWER, fallback_response=_HONEST_FALLBACK)
    _author(two_businesses["token_a"])

    def ask_as_customer(business: str) -> str:
        token = two_businesses[f"token_{business}"]
        customer = client.post("/api/v1/customers", json={"name": "Cust"}, headers=_auth_header(token)).json()["id"]
        conv = _conversation({"business_id_a": two_businesses[f"business_id_{business}"]}, customer)
        resp = client.post(f"/api/v1/conversations/{conv}/messages", json={"content": _QUESTION}, headers=_auth_header(token))
        assert resp.status_code == 201, resp.text
        return resp.json()["response"]

    assert ask_as_customer("a").startswith(_ANSWER)
    other = ask_as_customer("b")
    # Business B has no matching knowledge, so the orchestrator's zero-retrieval
    # backstop (orchestrator.py, "using honest fallback") overrides the stubbed
    # LLM reply with this real deterministic template -- never the raw stub text.
    assert other.startswith(render("unconfirmed_fact_fallback", "en"))
    assert _ANSWER not in other, "another business never sees it"


def test_authoring_validates_and_is_owner_admin_only(two_businesses, staff_token):
    token = two_businesses["token_a"]
    assert _author(token, question="  ").status_code == 422
    assert _author(token, answer="").status_code == 422
    assert client.post("/api/v1/training/qa", json={"question": "q"}, headers=_auth_header(token)).status_code == 422
    assert _author(staff_token).status_code == 403
    assert client.post("/api/v1/training/qa", json={"question": "q", "answer": "a"}).status_code in (401, 403)
    with SessionLocal() as db:
        assert db.query(KnowledgeDocument).filter_by(business_id=two_businesses["business_id_a"]).count() == 0


class _Embed:
    def embed(self, texts):
        return [[0.01] * 1536 for _ in texts]
