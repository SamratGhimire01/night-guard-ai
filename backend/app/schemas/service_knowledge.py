import uuid

from pydantic import BaseModel


class ServiceKnowledgeDocumentAttach(BaseModel):
    knowledge_document_id: uuid.UUID
