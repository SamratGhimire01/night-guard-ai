from functools import lru_cache

from app.llm.azure_openai import AzureChatProvider, AzureEmbeddingProvider
from app.llm.base import ChatProvider, EmbeddingProvider

__all__ = ["ChatProvider", "EmbeddingProvider", "get_chat_provider", "get_embedding_provider"]


# Single seam for a future provider swap: change what these two return, nothing
# else in the codebase references "Azure" directly.
@lru_cache
def get_embedding_provider() -> EmbeddingProvider:
    return AzureEmbeddingProvider()


@lru_cache
def get_chat_provider() -> ChatProvider:
    return AzureChatProvider()
