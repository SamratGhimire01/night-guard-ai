from abc import ABC, abstractmethod
from typing import AsyncIterator


class STTSession(ABC):
    """One open real-time speech-to-text connection for a single voice call.
    Audio goes in as it arrives from the browser; normalized transcript
    events come out as the provider's own end-of-utterance detection fires
    (never a fixed timer — see DeepgramSTTSession for the real mechanism)."""

    @abstractmethod
    async def send_audio(self, chunk: bytes) -> None:
        """Forwards one raw audio chunk from the browser to the provider."""

    @abstractmethod
    def events(self) -> AsyncIterator[dict]:
        """Yields normalized events for as long as the connection is open:
        {"type": "transcript", "text": str, "is_final": bool, "speech_final": bool}
        {"type": "utterance_end"}   -- provider's own silence-based end-of-utterance signal
        {"type": "speech_started"}
        Raises on a real connection failure (auth error, disconnect) rather
        than yielding a fake "closed" event -- the caller's except clause is
        what degrades the call gracefully."""

    @abstractmethod
    async def close(self) -> None:
        """Closes the underlying connection. Safe to call more than once."""


class STTProvider(ABC):
    """Real-time speech-to-text. Implementations wrap a specific backend
    (Deepgram, etc.) so the voice call handler never depends on a specific
    provider -- mirrors app/llm/base.py's ChatProvider/EmbeddingProvider seam."""

    @abstractmethod
    async def connect(self) -> STTSession:
        """Opens one streaming STT connection for a single voice call."""


class TTSProvider(ABC):
    """Turns the orchestrator's already-complete text reply into audio bytes
    for one conversational turn. A single call per turn (not a streaming
    connection) is enough here: unlike an LLM's token-by-token output, the
    orchestrator's response text is already fully known before synthesis
    starts, so there's nothing a persistent TTS socket would let us start
    earlier."""

    @abstractmethod
    def synthesize(self, text: str) -> bytes:
        """Returns encoded audio bytes (see the provider for the exact codec)
        for the given text, or raises on a real provider failure."""
