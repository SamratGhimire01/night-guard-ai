import asyncio
import io
import uuid
from pathlib import Path

from fastapi import APIRouter, Depends, File, Query, UploadFile
from pypdf import PdfReader
from pypdf.errors import PdfReadError
from sqlalchemy.orm import Session

from app.api.dependencies import get_current_user, get_db, require_role
from app.core.exceptions import (
    NotFoundError,
    PayloadTooLargeError,
    UnprocessableEntityError,
    UnsupportedMediaTypeError,
)
from app.db.models.business import BusinessUser
from app.db.models.knowledge import KnowledgeDocumentStatus
from app.llm import get_embedding_provider
from app.schemas.knowledge import (
    KnowledgeDocumentCreate,
    KnowledgeDocumentRead,
    KnowledgeDocumentUpdate,
    KnowledgeSearchRequest,
    KnowledgeSearchResponse,
    KnowledgeSearchResult,
    KnowledgeURLIngestRequest,
)
from app.services import knowledge_service, url_ingestion

router = APIRouter()

_ALLOWED_UPLOAD_EXTENSIONS = {".pdf", ".txt"}
_MAX_UPLOAD_BYTES = 10 * 1024 * 1024  # 10 MB — a reasonable cap, not a hard spec requirement.


@router.get("/knowledge", response_model=list[KnowledgeDocumentRead])
def list_knowledge_documents(
    status: KnowledgeDocumentStatus | None = Query(default=None),
    current_user: BusinessUser = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> list[KnowledgeDocumentRead]:
    documents = knowledge_service.list_documents(db, business_id=current_user.business_id, status=status)
    return [KnowledgeDocumentRead.model_validate(d) for d in documents]


@router.post("/knowledge", response_model=KnowledgeDocumentRead, status_code=201)
def create_knowledge_document(
    payload: KnowledgeDocumentCreate,
    current_user: BusinessUser = Depends(require_role(["owner", "admin"])),
    db: Session = Depends(get_db),
) -> KnowledgeDocumentRead:
    document = knowledge_service.create_document(
        db,
        business_id=current_user.business_id,
        title=payload.title,
        content=payload.content,
        source="manual",
        status=KnowledgeDocumentStatus.APPROVED,
        approved_by=current_user.id,
    )
    return KnowledgeDocumentRead.model_validate(document)


@router.get("/knowledge/{document_id}", response_model=KnowledgeDocumentRead)
def get_knowledge_document(
    document_id: uuid.UUID,
    current_user: BusinessUser = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> KnowledgeDocumentRead:
    document = knowledge_service.get_document(
        db, business_id=current_user.business_id, document_id=document_id
    )
    if document is None:
        raise NotFoundError("Knowledge document not found.")
    return KnowledgeDocumentRead.model_validate(document)


@router.patch("/knowledge/{document_id}", response_model=KnowledgeDocumentRead)
def update_knowledge_document(
    document_id: uuid.UUID,
    payload: KnowledgeDocumentUpdate,
    current_user: BusinessUser = Depends(require_role(["owner", "admin"])),
    db: Session = Depends(get_db),
) -> KnowledgeDocumentRead:
    document = knowledge_service.update_document(
        db,
        business_id=current_user.business_id,
        document_id=document_id,
        payload=payload,
        current_user_id=current_user.id,
    )
    if document is None:
        raise NotFoundError("Knowledge document not found.")
    return KnowledgeDocumentRead.model_validate(document)


@router.delete("/knowledge/{document_id}", status_code=204)
def delete_knowledge_document(
    document_id: uuid.UUID,
    current_user: BusinessUser = Depends(require_role(["owner", "admin"])),
    db: Session = Depends(get_db),
) -> None:
    deleted = knowledge_service.delete_document(
        db, business_id=current_user.business_id, document_id=document_id
    )
    if not deleted:
        raise NotFoundError("Knowledge document not found.")


def _extract_pdf_text(raw: bytes) -> str:
    try:
        reader = PdfReader(io.BytesIO(raw))
        return "\n".join(page.extract_text() or "" for page in reader.pages)
    except PdfReadError as exc:
        raise UnprocessableEntityError("Could not read this file as a PDF.") from exc


def _extract_txt_text(raw: bytes) -> str:
    try:
        return raw.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise UnprocessableEntityError("Text file must be UTF-8 encoded.") from exc


@router.post("/knowledge/upload", response_model=KnowledgeDocumentRead, status_code=201)
async def upload_knowledge_document(
    file: UploadFile = File(...),
    current_user: BusinessUser = Depends(require_role(["owner", "admin"])),
    db: Session = Depends(get_db),
) -> KnowledgeDocumentRead:
    extension = Path(file.filename or "").suffix.lower()
    if extension not in _ALLOWED_UPLOAD_EXTENSIONS:
        raise UnsupportedMediaTypeError(
            f"Unsupported file type '{extension or 'unknown'}'. Only .pdf and .txt are accepted."
        )

    raw = await file.read()
    if len(raw) > _MAX_UPLOAD_BYTES:
        raise PayloadTooLargeError(
            f"File exceeds the {_MAX_UPLOAD_BYTES // (1024 * 1024)}MB upload limit."
        )

    # PDF parsing and the embedding calls inside create_document are blocking: off the event loop (see webhooks.py).
    content = await asyncio.to_thread(_extract_pdf_text if extension == ".pdf" else _extract_txt_text, raw)
    if not content.strip():
        raise UnprocessableEntityError("No extractable text was found in this file.")

    document = await asyncio.to_thread(
        knowledge_service.create_document,
        db,
        business_id=current_user.business_id,
        title=file.filename or "Untitled",
        content=content,
        source="upload",
        status=KnowledgeDocumentStatus.APPROVED,
        approved_by=current_user.id,
    )
    return KnowledgeDocumentRead.model_validate(document)


@router.post("/knowledge/ingest-url", response_model=list[KnowledgeDocumentRead], status_code=201)
async def ingest_knowledge_url(
    payload: KnowledgeURLIngestRequest,
    current_user: BusinessUser = Depends(require_role(["owner", "admin"])),
    db: Session = Depends(get_db),
) -> list[KnowledgeDocumentRead]:
    """Part 2B (Chatbase parity): fetch a real page, strip boilerplate, and feed the
    clean text into the same create_document() pipeline as upload/manual entry -- lands
    approved immediately (owner/admin is already the only role that can call this, so a
    separate approval click added nothing). The fetch/parse/embed chain is blocking
    network + CPU work: off the event loop, same discipline as PDF upload and the webhook
    handlers (see webhooks.py)."""
    if payload.crawl:
        pages = await asyncio.to_thread(url_ingestion.crawl_site, payload.url, max_pages=payload.max_pages)
    else:
        title, text = await asyncio.to_thread(url_ingestion.fetch_and_extract, payload.url)
        pages = [(payload.url, title, text)]

    documents = [
        await asyncio.to_thread(
            knowledge_service.create_document,
            db,
            business_id=current_user.business_id,
            title=title,
            content=text,
            source="url",
            status=KnowledgeDocumentStatus.APPROVED,
            approved_by=current_user.id,
        )
        for _url, title, text in pages
    ]
    return [KnowledgeDocumentRead.model_validate(d) for d in documents]


@router.post("/knowledge/search", response_model=KnowledgeSearchResponse)
def search_knowledge(
    payload: KnowledgeSearchRequest,
    current_user: BusinessUser = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> KnowledgeSearchResponse:
    query_vector = get_embedding_provider().embed([payload.query])[0]
    rows = knowledge_service.search_chunks(
        db, business_id=current_user.business_id, query_vector=query_vector, top_k=payload.top_k
    )
    return KnowledgeSearchResponse(
        results=[
            KnowledgeSearchResult(
                chunk_id=chunk.id,
                document_id=doc.id,
                document_title=doc.title,
                content=chunk.content,
                similarity=similarity,
            )
            for chunk, doc, similarity in rows
        ]
    )
