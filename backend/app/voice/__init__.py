from functools import lru_cache

from app.voice.base import STTProvider
from app.voice.deepgram import DeepgramSTTProvider

__all__ = ["STTProvider", "get_stt_provider"]


# Single seam for a future provider swap — same pattern as app/llm/__init__.py.
# Nothing outside this module references "Deepgram" directly.
@lru_cache
def get_stt_provider() -> STTProvider:
    return DeepgramSTTProvider()
