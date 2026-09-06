from functools import lru_cache

from app.voice.base import STTProvider, TTSProvider
from app.voice.deepgram import DeepgramSTTProvider, DeepgramTTSProvider

__all__ = ["STTProvider", "TTSProvider", "get_stt_provider", "get_tts_provider"]


# Single seam for a future provider swap (e.g. ElevenLabs for TTS, per the V2
# plan's fallback note) -- same pattern as app/llm/__init__.py. Nothing
# outside this module references "Deepgram" directly.
@lru_cache
def get_stt_provider() -> STTProvider:
    return DeepgramSTTProvider()


@lru_cache
def get_tts_provider() -> TTSProvider:
    return DeepgramTTSProvider()
