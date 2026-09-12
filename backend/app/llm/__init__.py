from functools import lru_cache

from app.core.config import settings
from app.llm.azure_openai import AzureChatProvider, AzureEmbeddingProvider
from app.llm.base import ChatProvider, EmbeddingProvider
from app.llm.groq import GroqChatProvider
from app.llm.xai import GrokChatProvider

__all__ = ["ChatProvider", "EmbeddingProvider", "get_chat_provider", "get_embedding_provider"]


# Single seam for a provider swap: change what these two return, nothing else
# in the codebase (orchestrator, memory, training room, ...) ever references
# "Azure" or "Grok" directly -- this function is the ONLY place that branches
# on USING_LLM (Phase 39).
#
# Embeddings deliberately stay on Azure regardless of USING_LLM: xAI has no
# embeddings API, so forcing embeddings to follow the chat provider would
# either break Grok mode outright or silently mismatch dimensions against the
# existing pgvector column (Phase 6, 1536-dim). Chat and embeddings are
# independently configurable by design, not an oversight.
@lru_cache
def get_embedding_provider() -> EmbeddingProvider:
    return AzureEmbeddingProvider()


@lru_cache
def get_chat_provider() -> ChatProvider:
    using_llm = settings.using_llm.strip().lower()
    if using_llm in {"grok", "xai"}:
        return GrokChatProvider()
    if using_llm == "groq":
        return GroqChatProvider()
    return AzureChatProvider()
