import asyncio

import httpx

from app.core.config import settings
from app.voice.base import STTProvider

_STT_URL = "https://api.deepgram.com/v1/listen"
_STT_MODEL = "nova-3"

# Phase 43h research finding (Deepgram's own docs, fetched live): pre-recorded
# `detect_language=true` auto-detect covers 35 languages, and Nepali is NOT
# one of them — the same real platform gap Phase 43e already found for the
# real-time `multi` mode. Explicit `language=ne` on nova-3 DOES work (its own
# multilingual language table lists Nepali), so for one complete recording
# (not a continuous stream) the simplest robust approach is to run BOTH real
# attempts and keep whichever Deepgram itself was more confident about for
# this specific clip, per the ticket's own explicit "or" allowance.
_CANDIDATE_LANGUAGES = ("en", "ne")


def _require_key() -> str:
    if not settings.deepgram_api_key:
        raise RuntimeError("DEEPGRAM_API_KEY is not configured.")
    return settings.deepgram_api_key


async def _transcribe_one(
    client: httpx.AsyncClient, *, key: str, audio: bytes, content_type: str, language: str
) -> tuple[str, float]:
    response = await client.post(
        _STT_URL,
        params={"model": _STT_MODEL, "language": language, "smart_format": "true"},
        headers={"Authorization": f"Token {key}", "Content-Type": content_type},
        content=audio,
        timeout=30.0,
    )
    response.raise_for_status()
    alternatives = response.json()["results"]["channels"][0]["alternatives"]
    alternative = alternatives[0] if alternatives else {}
    return alternative.get("transcript") or "", alternative.get("confidence") or 0.0


class DeepgramSTTProvider(STTProvider):
    async def transcribe(self, audio: bytes, *, content_type: str) -> dict:
        key = _require_key()
        async with httpx.AsyncClient() as client:
            results = await asyncio.gather(
                *(
                    _transcribe_one(client, key=key, audio=audio, content_type=content_type, language=language)
                    for language in _CANDIDATE_LANGUAGES
                )
            )
        # Ties (e.g. total silence -> 0.0 confidence both ways) keep the
        # first candidate, "en" — a reasonable default over an arbitrary one.
        best_index = max(range(len(results)), key=lambda i: results[i][1])
        best_text, best_confidence = results[best_index]
        return {"text": best_text, "language": _CANDIDATE_LANGUAGES[best_index], "confidence": best_confidence}
