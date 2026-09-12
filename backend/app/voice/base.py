from abc import ABC, abstractmethod


class STTProvider(ABC):
    """Pre-recorded (batch) speech-to-text for one complete push-to-talk
    recording — not a streaming connection. Implementations wrap a specific
    backend (Deepgram, etc.) so the voice route never depends on a specific
    provider — mirrors app/llm/base.py's ChatProvider seam."""

    @abstractmethod
    async def transcribe(self, audio: bytes, *, content_type: str) -> dict:
        """Returns {"text": str, "language": "en" | "ne", "confidence": float}
        for one complete recording, or raises on a real provider failure.
        `text` is "" (never None) when no speech was detected in the clip."""
