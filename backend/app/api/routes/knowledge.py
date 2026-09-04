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
)
from app.services import knowledge_service

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

    content = _extract_pdf_text(raw) if extension == ".pdf" else _extract_txt_text(raw)
    if not content.strip():
        raise UnprocessableEntityError("No extractable text was found in this file.")

    document = knowledge_service.create_document(
        db,
        business_id=current_user.business_id,
        title=file.filename or "Untitled",
        content=content,
        source="upload",
    )
    return KnowledgeDocumentRead.model_validate(document)


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
