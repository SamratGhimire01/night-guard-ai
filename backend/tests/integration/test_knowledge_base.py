"""Phase 5 — knowledge base ingestion endpoints.

Covers the manual-entry CRUD + status lifecycle (approved on creation -> archived ->
re-approved), file upload (.txt and a real .pdf fixture), invalid-upload rejection,
cross-tenant isolation, and RBAC (owner/admin write including archive, any role read).

Every ingestion path (manual entry, upload, URL) lands APPROVED immediately, not
DRAFT: only owner/admin can call any of them, so a separate approval click reviewed
nothing a second person hadn't already seen, and it left real ingested content
silently unusable by the AI until someone remembered to click it (a real reported
bug). `status="archived"` (still reachable via PATCH) is what now stands in for
"don't use this one," not "not yet reviewed."
"""

import uuid
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.core.security import create_access_token
from app.db.database import SessionLocal
from app.db.models.business import Business, BusinessUser, BusinessUserRole
from app.db.models.knowledge import EMBEDDING_DIMENSIONS
from app.main import app
from app.services import knowledge_service

client = TestClient(app)

_FIXTURES = Path(__file__).parent.parent / "fixtures"


class _FakeEmbeddingProvider:
    """Deterministic, zero-cost stand-in for the real Azure embedding provider —
    this suite tests chunking/approval wiring, not the live embedding API. Real
    embedding/search behavior is verified with real API calls (see PHASE_STATUS.md
    Phase 6), not here."""

    def embed(self, texts: list[str]) -> list[list[float]]:
        return [[0.01] * EMBEDDING_DIMENSIONS for _ in texts]


@pytest.fixture(autouse=True)
def _stub_embeddings(monkeypatch):
    monkeypatch.setattr(knowledge_service, "get_embedding_provider", lambda: _FakeEmbeddingProvider())


def _unique_email(label: str) -> str:
    return f"{label}-{uuid.uuid4().hex[:10]}@example.com"


def _auth_header(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


@pytest.fixture
def two_businesses():
    email_a = _unique_email("kb-a-owner")
    email_b = _unique_email("kb-b-owner")

    resp_a = client.post(
        "/api/v1/auth/register",
        json={"business_name": "KB A", "timezone": "UTC", "email": email_a, "password": "correcthorse1"},
    )
    resp_b = client.post(
        "/api/v1/auth/register",
        json={"business_name": "KB B", "timezone": "UTC", "email": email_b, "password": "correcthorse1"},
    )
    assert resp_a.status_code == 201, resp_a.text
    assert resp_b.status_code == 201, resp_b.text

    login_a = client.post("/api/v1/auth/login", json={"email": email_a, "password": "correcthorse1"})
    login_b = client.post("/api/v1/auth/login", json={"email": email_b, "password": "correcthorse1"})

    data = {
        "business_id_a": resp_a.json()["business_id"],
        "business_id_b": resp_b.json()["business_id"],
        "token_a": login_a.json()["access_token"],
        "token_b": login_b.json()["access_token"],
    }
    yield data

    with SessionLocal() as db:
        for business_id in (data["business_id_a"], data["business_id_b"]):
            business = db.get(Business, uuid.UUID(business_id))
            if business is not None:
                db.delete(business)
        db.commit()


@pytest.fixture
def staff_token(two_businesses):
    business_id_a = uuid.UUID(two_businesses["business_id_a"])
    with SessionLocal() as db:
        staff_user = BusinessUser(
            business_id=business_id_a,
            email=_unique_email("kb-staff"),
            hashed_password="not-used-in-this-test",
            role=BusinessUserRole.STAFF,
        )
        db.add(staff_user)
        db.commit()
        db.refresh(staff_user)
        return create_access_token(user_id=staff_user.id, business_id=business_id_a, role=staff_user.role.value)


def test_manual_entry_full_lifecycle(two_businesses):
    token_a = two_businesses["token_a"]

    create = client.post(
        "/api/v1/knowledge",
        json={"title": "Cancellation Policy", "content": "Cancel 24h ahead, no fee."},
        headers=_auth_header(token_a),
    )
    assert create.status_code == 201, create.text
    doc = create.json()
    assert doc["status"] == "approved"  # live immediately, no separate approval click
    assert doc["approved_by"] is not None
    assert doc["approved_at"] is not None
    assert doc["source"] == "manual"
    assert doc["version"] == 1
    doc_id = doc["id"]

    listing = client.get("/api/v1/knowledge", headers=_auth_header(token_a)).json()
    assert any(d["id"] == doc_id for d in listing)

    edit = client.patch(
        f"/api/v1/knowledge/{doc_id}",
        json={"content": "Cancel 48h ahead, no fee."},
        headers=_auth_header(token_a),
    )
    assert edit.status_code == 200, edit.text
    assert edit.json()["version"] == 2  # content edit bumps the version counter
    assert edit.json()["status"] == "approved"  # editing an approved doc doesn't demote it
    reread = client.get(f"/api/v1/knowledge/{doc_id}", headers=_auth_header(token_a)).json()
    assert reread["content"] == "Cancel 48h ahead, no fee."

    filtered = client.get("/api/v1/knowledge?status=approved", headers=_auth_header(token_a)).json()
    assert any(d["id"] == doc_id for d in filtered)
    filtered_draft = client.get("/api/v1/knowledge?status=draft", headers=_auth_header(token_a)).json()
    assert all(d["id"] != doc_id for d in filtered_draft)

    archive = client.patch(
        f"/api/v1/knowledge/{doc_id}", json={"status": "archived"}, headers=_auth_header(token_a)
    )
    assert archive.status_code == 200, archive.text
    assert archive.json()["status"] == "archived"
    assert archive.json()["approved_by"] is not None  # retained as history

    # archiving isn't final -- re-approving brings it straight back
    reapprove = client.patch(
        f"/api/v1/knowledge/{doc_id}", json={"status": "approved"}, headers=_auth_header(token_a)
    )
    assert reapprove.status_code == 200, reapprove.text
    assert reapprove.json()["status"] == "approved"

    delete = client.delete(f"/api/v1/knowledge/{doc_id}", headers=_auth_header(token_a))
    assert delete.status_code == 204

    final = client.get(f"/api/v1/knowledge/{doc_id}", headers=_auth_header(token_a))
    assert final.status_code == 404


def test_upload_txt_extracts_content(two_businesses):
    token_a = two_businesses["token_a"]
    text = "Business hours: Mon-Fri 9-5.\n"

    resp = client.post(
        "/api/v1/knowledge/upload",
        files={"file": ("hours.txt", text.encode("utf-8"), "text/plain")},
        headers=_auth_header(token_a),
    )
    assert resp.status_code == 201, resp.text
    doc = resp.json()
    assert doc["source"] == "upload"
    assert doc["status"] == "approved"  # live immediately, same as manual entry
    assert doc["content"] == text


def test_upload_pdf_extracts_content(two_businesses):
    token_a = two_businesses["token_a"]
    pdf_bytes = (_FIXTURES / "sample.pdf").read_bytes()

    resp = client.post(
        "/api/v1/knowledge/upload",
        files={"file": ("sample.pdf", pdf_bytes, "application/pdf")},
        headers=_auth_header(token_a),
    )
    assert resp.status_code == 201, resp.text
    doc = resp.json()
    assert doc["source"] == "upload"
    assert "Refund Policy" in doc["content"]
    assert "5 to 7 business days" in doc["content"]


def test_upload_rejects_invalid_type_and_oversized_file(two_businesses):
    token_a = two_businesses["token_a"]

    bad_type = client.post(
        "/api/v1/knowledge/upload",
        files={"file": ("malware.exe", b"not a real exe", "application/octet-stream")},
        headers=_auth_header(token_a),
    )
    assert bad_type.status_code == 415, bad_type.text

    oversized = client.post(
        "/api/v1/knowledge/upload",
        files={"file": ("huge.txt", b"A" * (11 * 1024 * 1024), "text/plain")},
        headers=_auth_header(token_a),
    )
    assert oversized.status_code == 413, oversized.text

    listing = client.get("/api/v1/knowledge", headers=_auth_header(token_a)).json()
    assert listing == []  # neither rejected upload created a document


def test_cross_tenant_knowledge_documents_are_isolated(two_businesses):
    token_a = two_businesses["token_a"]
    token_b = two_businesses["token_b"]

    doc = client.post(
        "/api/v1/knowledge",
        json={"title": "B's secret doc", "content": "confidential"},
        headers=_auth_header(token_b),
    ).json()

    assert client.get(f"/api/v1/knowledge/{doc['id']}", headers=_auth_header(token_a)).status_code == 404
    assert (
        client.patch(
            f"/api/v1/knowledge/{doc['id']}", json={"content": "hacked"}, headers=_auth_header(token_a)
        ).status_code
        == 404
    )
    assert (
        client.patch(
            f"/api/v1/knowledge/{doc['id']}", json={"status": "approved"}, headers=_auth_header(token_a)
        ).status_code
        == 404
    )
    assert (
        client.delete(f"/api/v1/knowledge/{doc['id']}", headers=_auth_header(token_a)).status_code == 404
    )

    still_there = client.get(f"/api/v1/knowledge/{doc['id']}", headers=_auth_header(token_b))
    assert still_there.status_code == 200
    assert still_there.json()["content"] == "confidential"
    assert still_there.json()["status"] == "approved"


def test_rbac_staff_can_read_but_not_approve_archive_or_delete(staff_token, two_businesses):
    token_a = two_businesses["token_a"]

    doc = client.post(
        "/api/v1/knowledge",
        json={"title": "Doc", "content": "content"},
        headers=_auth_header(token_a),
    ).json()

    assert client.get("/api/v1/knowledge", headers=_auth_header(staff_token)).status_code == 200
    assert client.get(f"/api/v1/knowledge/{doc['id']}", headers=_auth_header(staff_token)).status_code == 200

    assert (
        client.post(
            "/api/v1/knowledge", json={"title": "x", "content": "y"}, headers=_auth_header(staff_token)
        ).status_code
        == 403
    )
    assert (
        client.patch(
            f"/api/v1/knowledge/{doc['id']}", json={"status": "approved"}, headers=_auth_header(staff_token)
        ).status_code
        == 403
    )
    assert (
        client.patch(
            f"/api/v1/knowledge/{doc['id']}", json={"status": "archived"}, headers=_auth_header(staff_token)
        ).status_code
        == 403
    )
    assert (
        client.delete(f"/api/v1/knowledge/{doc['id']}", headers=_auth_header(staff_token)).status_code == 403
    )

    # owner (token_a) still can approve the same document, proving it's a role gate
    approve = client.patch(
        f"/api/v1/knowledge/{doc['id']}", json={"status": "approved"}, headers=_auth_header(token_a)
    )
    assert approve.status_code == 200, approve.text


@pytest.mark.parametrize(
    "body",
    [
        {"title": "", "content": "x"},
        {"title": "x", "content": ""},
    ],
)
def test_create_rejects_blank_fields_with_422(two_businesses, body):
    resp = client.post("/api/v1/knowledge", json=body, headers=_auth_header(two_businesses["token_a"]))
    assert resp.status_code == 422, resp.text


def test_filter_for_llm_drops_noise_keeps_real_matches():
    """Real conversation-quality fix (PHASE_STATUS.md, "greeting verbosity"):
    real-measured score distribution on this project's own real business
    ("Samaj Dental Clinic") showed genuinely relevant top-1 matches at
    0.379-0.645 and irrelevant ones (a bare greeting, "thank you," an
    unrelated question) at 0.080-0.207 — LLM_RELEVANCE_FLOOR (0.25) sits in
    that real gap. `filter_for_llm` never touches the chunk/document objects
    themselves, only the similarity score, so plain placeholders are enough
    here — this is a pure filtering-logic test, not a real search test (that
    coverage already exists via the manual-entry/search tests above)."""
    assert knowledge_service.LLM_RELEVANCE_FLOOR == 0.25
    results = [
        ("chunk_real_match", "doc", 0.645),
        ("chunk_weak_match", "doc", 0.379),
        ("chunk_borderline", "doc", 0.25),
        ("chunk_noise_1", "doc", 0.207),
        ("chunk_noise_2", "doc", 0.108),
    ]
    filtered = knowledge_service.filter_for_llm(results)
    assert [r[0] for r in filtered] == ["chunk_real_match", "chunk_weak_match", "chunk_borderline"]


# --- Phase 58 Part 2B: website-URL ingestion (Chatbase parity) ------------------------------------------------------
# Feeds a fetched page's clean text into the SAME create_document() pipeline as manual entry/upload -- approved
# immediately (real bug fix: a fetched page used to land as an invisible, unusable draft), same chunking/embedding --
# so these tests mock only the network fetch (url_ingestion.fetch_and_extract / crawl_site), never knowledge_service
# itself, to prove the wiring is the real pipeline.


def test_ingest_url_creates_an_approved_document_from_the_fetched_page(two_businesses, monkeypatch):
    from app.services import url_ingestion

    monkeypatch.setattr(
        url_ingestion, "fetch_and_extract", lambda url: ("Acme FAQ", "We are open 9am-5pm.\nWalk-ins welcome.")
    )
    resp = client.post(
        "/api/v1/knowledge/ingest-url",
        json={"url": "https://acme.example.com/faq"},
        headers=_auth_header(two_businesses["token_a"]),
    )
    assert resp.status_code == 201, resp.text
    docs = resp.json()
    assert len(docs) == 1
    assert docs[0]["title"] == "Acme FAQ"
    assert docs[0]["content"] == "We are open 9am-5pm.\nWalk-ins welcome."
    assert docs[0]["source"] == "url"
    assert docs[0]["status"] == "approved", "fetched content must be usable by the AI immediately, not stuck as an invisible draft"

    listed = client.get("/api/v1/knowledge", headers=_auth_header(two_businesses["token_a"])).json()
    assert len(listed) == 1 and listed[0]["id"] == docs[0]["id"]


def test_ingest_url_with_crawl_creates_one_approved_document_per_page(two_businesses, monkeypatch):
    from app.services import url_ingestion

    pages = [
        ("https://acme.example.com/", "Acme Home", "Welcome to Acme."),
        ("https://acme.example.com/pricing", "Acme Pricing", "Plans start at $10."),
    ]
    monkeypatch.setattr(url_ingestion, "crawl_site", lambda url, max_pages: pages)
    resp = client.post(
        "/api/v1/knowledge/ingest-url",
        json={"url": "https://acme.example.com/", "crawl": True, "max_pages": 5},
        headers=_auth_header(two_businesses["token_a"]),
    )
    assert resp.status_code == 201, resp.text
    docs = resp.json()
    assert {d["title"] for d in docs} == {"Acme Home", "Acme Pricing"}
    assert all(d["status"] == "approved" and d["source"] == "url" for d in docs)


def test_ingest_url_surfaces_a_real_fetch_error_and_creates_nothing(two_businesses, monkeypatch):
    from app.services import url_ingestion

    def _raise(url):
        raise url_ingestion.URLFetchError("Refusing to fetch a non-public / internal address.")

    monkeypatch.setattr(url_ingestion, "fetch_and_extract", _raise)
    resp = client.post(
        "/api/v1/knowledge/ingest-url",
        json={"url": "http://169.254.169.254/latest/meta-data/"},
        headers=_auth_header(two_businesses["token_a"]),
    )
    assert resp.status_code == 422, resp.text
    assert "non-public" in resp.json()["error"]["message"]
    assert client.get("/api/v1/knowledge", headers=_auth_header(two_businesses["token_a"])).json() == []


def test_ingest_url_is_owner_admin_only(staff_token, two_businesses, monkeypatch):
    from app.services import url_ingestion

    monkeypatch.setattr(url_ingestion, "fetch_and_extract", lambda url: ("T", "content"))
    resp = client.post(
        "/api/v1/knowledge/ingest-url",
        json={"url": "https://acme.example.com/faq"},
        headers=_auth_header(staff_token),
    )
    assert resp.status_code == 403, resp.text
    assert client.get("/api/v1/knowledge", headers=_auth_header(two_businesses["token_a"])).json() == []


def test_ingest_url_rejects_blank_and_over_length_url_with_422(two_businesses):
    assert client.post(
        "/api/v1/knowledge/ingest-url", json={"url": ""}, headers=_auth_header(two_businesses["token_a"])
    ).status_code == 422
    assert client.post(
        "/api/v1/knowledge/ingest-url", json={"url": "x" * 2049}, headers=_auth_header(two_businesses["token_a"])
    ).status_code == 422


# --- app.services.url_ingestion: real extraction + SSRF-safety unit tests (no network) ------------------------------


def test_extract_title_and_text_strips_boilerplate_and_keeps_real_content():
    from app.services.url_ingestion import extract_title_and_text

    html = """
    <html><head><title>FAQ - Acme</title></head>
    <body>
      <nav>Home | About | Contact</nav>
      <header>Acme Corp</header>
      <main>
        <h1>Frequently Asked Questions</h1>
        <p>What are your hours?</p>
        <p>We are open 9am-5pm.</p>
        <script>var x = 1;</script>
      </main>
      <footer>Copyright 2026 Acme</footer>
    </body></html>
    """
    title, text = extract_title_and_text(html)
    assert title == "FAQ - Acme"
    assert "Home | About | Contact" not in text
    assert "Copyright 2026 Acme" not in text
    assert "var x = 1" not in text
    assert "Frequently Asked Questions" in text
    assert "We are open 9am-5pm." in text


def test_extract_title_and_text_falls_back_to_h1_when_no_title_tag():
    from app.services.url_ingestion import extract_title_and_text

    title, text = extract_title_and_text("<html><body><h1>Trekking Packages</h1><p>Everest Base Camp, 14 days.</p></body></html>")
    assert title == "Trekking Packages"
    assert "Everest Base Camp, 14 days." in text


# Real bug: a JS-rendered page (React/Next/etc.) serves a near-empty shell over plain
# HTTP -- ingestion "succeeded" and created a document, but its content was just
# nav/empty-state copy ("0 notices found"), leaving the AI nothing real to answer
# from when asked about it later. fetch_and_extract/crawl_site must now refuse that
# case loudly instead of silently saving it as if it were real content.


def test_fetch_and_extract_rejects_a_js_rendered_shell_page(monkeypatch):
    from app.services import url_ingestion

    monkeypatch.setattr(
        url_ingestion, "_fetch_raw_html", lambda url: "<html><body><div id='root'>0 notices found</div></body></html>"
    )
    with pytest.raises(url_ingestion.URLFetchError, match="loads its real content dynamically"):
        url_ingestion.fetch_and_extract("https://example.com/notices")


def test_crawl_site_skips_a_thin_js_rendered_seed_page(monkeypatch):
    from app.services import url_ingestion

    monkeypatch.setattr(url_ingestion, "_robots_allows", lambda base, path: True)
    monkeypatch.setattr(
        url_ingestion, "_fetch_raw_html", lambda url: "<html><body>0 notices found</body></html>"
    )
    with pytest.raises(url_ingestion.URLFetchError, match="No extractable page content"):
        url_ingestion.crawl_site("https://example.com/")


def test_fetch_and_extract_keeps_a_genuinely_short_real_page(monkeypatch):
    """The thin-content floor must not punish a real page that's just short."""
    from app.services import url_ingestion

    monkeypatch.setattr(
        url_ingestion,
        "_fetch_raw_html",
        lambda url: (
            "<html><body><main>"
            + " ".join(f"word{i}" for i in range(45))
            + "</main></body></html>"
        ),
    )
    _title, text = url_ingestion.fetch_and_extract("https://example.com/short")
    assert len(text.split()) == 45


@pytest.mark.parametrize(
    "bad_url",
    [
        "http://127.0.0.1/",
        "http://localhost:8000/",
        "http://169.254.169.254/latest/meta-data/",  # cloud metadata endpoint
        "http://10.0.0.5/",
        "http://192.168.1.1/",
        "ftp://example.com/",
        "not-a-url",
    ],
)
def test_validate_public_url_rejects_non_public_and_non_http_urls(bad_url):
    from app.services.url_ingestion import URLFetchError, _validate_public_url

    with pytest.raises(URLFetchError):
        _validate_public_url(bad_url)


def test_validate_public_url_allows_a_real_public_host():
    from app.services.url_ingestion import _validate_public_url

    _validate_public_url("https://example.com/")  # must not raise
    assert knowledge_service.filter_for_llm([]) == []
