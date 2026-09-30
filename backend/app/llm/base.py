from abc import ABC, abstractmethod


class LLMProviderError(RuntimeError):
    """The AI provider could not be reached or refused the request after its own retries. A RuntimeError subclass, so
    every existing `except RuntimeError` fallback (the chat's graceful degradation) keeps working; routes that cannot
    degrade let it propagate and the app turns it into a 503 with a plain message (app/core/exceptions.py)."""


class EmbeddingProvider(ABC):
    """Turns text into vectors. Implementations wrap a specific backend (Azure
    OpenAI, etc.) so business logic never depends on a specific provider."""

    @abstractmethod
    def embed(self, texts: list[str]) -> list[list[float]]:
        """Returns one embedding vector per input text, same order."""


class ChatProvider(ABC):
    """Runs a chat/completion call against an LLM backend. Not used until
    Phase 7+ (conversation engine); the interface exists now so that phase
    doesn't have to invent the provider-swap seam from scratch."""

    @abstractmethod
    def chat(self, messages: list[dict[str, str]]) -> str:
        """Returns the assistant's reply text for the given message history."""
