"""Phase 39: proves app/llm/__init__.py's get_chat_provider() is the ONLY
place that branches on USING_LLM, and that embeddings never follow it."""

from app.llm import get_chat_provider, get_embedding_provider
from app.llm.azure_openai import AzureChatProvider, AzureEmbeddingProvider
from app.llm.groq import GroqChatProvider
from app.llm.xai import GrokChatProvider


def test_using_llm_azure_returns_azure_chat_provider(monkeypatch):
    monkeypatch.setattr("app.llm.settings.using_llm", "azure")
    get_chat_provider.cache_clear()
    assert isinstance(get_chat_provider(), AzureChatProvider)


def test_using_llm_grok_returns_grok_chat_provider(monkeypatch):
    monkeypatch.setattr("app.llm.settings.using_llm", "grok")
    get_chat_provider.cache_clear()
    try:
        assert isinstance(get_chat_provider(), GrokChatProvider)
    finally:
        get_chat_provider.cache_clear()


def test_using_llm_xai_alias_also_returns_grok_chat_provider(monkeypatch):
    monkeypatch.setattr("app.llm.settings.using_llm", "xai")
    get_chat_provider.cache_clear()
    try:
        assert isinstance(get_chat_provider(), GrokChatProvider)
    finally:
        get_chat_provider.cache_clear()


def test_using_llm_groq_returns_groq_chat_provider(monkeypatch):
    monkeypatch.setattr("app.llm.settings.using_llm", "groq")
    get_chat_provider.cache_clear()
    try:
        assert isinstance(get_chat_provider(), GroqChatProvider)
    finally:
        get_chat_provider.cache_clear()


def test_unrecognized_using_llm_falls_back_to_azure(monkeypatch):
    monkeypatch.setattr("app.llm.settings.using_llm", "something-unrecognized")
    get_chat_provider.cache_clear()
    try:
        assert isinstance(get_chat_provider(), AzureChatProvider)
    finally:
        get_chat_provider.cache_clear()


def test_embedding_provider_stays_azure_regardless_of_using_llm(monkeypatch):
    monkeypatch.setattr("app.llm.settings.using_llm", "grok")
    assert isinstance(get_embedding_provider(), AzureEmbeddingProvider)
