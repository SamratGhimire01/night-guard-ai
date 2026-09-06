import json
import logging
from typing import AsyncIterator

import httpx
import websockets

from app.core.config import settings
from app.voice.base import STTProvider, STTSession, TTSProvider

logger = logging.getLogger(__name__)

_STT_URL = "wss://api.deepgram.com/v1/listen"
_TTS_URL = "https://api.deepgram.com/v1/speak"
_STT_MODEL = "nova-2"
_TTS_MODEL = "aura-asteria-en"

# Real, provider-side end-of-utterance detection (Deepgram's own VAD), not a
# fixed reply timer we invented: `endpointing` closes out a Results segment
# after this many ms of silence within an utterance; `utterance_end_ms` fires
# a separate UtteranceEnd event after this much silence even if the last
# Results segment never got a final speech_final flag (e.g. background noise
# kept the segment "open"). The call handler treats either signal as "the
# customer is done talking, respond now" -- see app/api/routes/voice.py.
_ENDPOINTING_MS = 500
_UTTERANCE_END_MS = 1000


def _require_key() -> str:
    if not settings.deepgram_api_key:
        raise RuntimeError("DEEPGRAM_API_KEY is not configured.")
    return settings.deepgram_api_key


class DeepgramSTTSession(STTSession):
    def __init__(self, ws) -> None:
        self._ws = ws

    async def send_audio(self, chunk: bytes) -> None:
        await self._ws.send(chunk)

    async def events(self) -> AsyncIterator[dict]:
        async for raw in self._ws:
            try:
                message = json.loads(raw)
            except (TypeError, ValueError):
                continue

            message_type = message.get("type")
            if message_type == "Results":
                alternatives = message.get("channel", {}).get("alternatives", [])
                text = alternatives[0].get("transcript", "") if alternatives else ""
                if text:
                    yield {
                        "type": "transcript",
                        "text": text,
                        "is_final": bool(message.get("is_final")),
                        "speech_final": bool(message.get("speech_final")),
                    }
            elif message_type == "UtteranceEnd":
                yield {"type": "utterance_end"}
            elif message_type == "SpeechStarted":
                yield {"type": "speech_started"}

    async def close(self) -> None:
        await self._ws.close()


class DeepgramSTTProvider(STTProvider):
    async def connect(self) -> DeepgramSTTSession:
        key = _require_key()
        # No `encoding`/`sample_rate` params: the browser sends a containerized
        # WebM/Opus stream (see widget.js's MediaRecorder), and Deepgram
        # auto-detects container format from its headers. Specifying a raw
        # `encoding=opus` here would tell it to expect a headerless Opus
        # bitstream instead, which the WebM container is not.
        url = (
            f"{_STT_URL}?model={_STT_MODEL}&interim_results=true&smart_format=true"
            f"&endpointing={_ENDPOINTING_MS}&utterance_end_ms={_UTTERANCE_END_MS}&vad_events=true"
        )
        # additional_headers, not the older extra_headers -- this repo pins
        # websockets==17.1 (via uvicorn[standard]), which uses the new name.
        ws = await websockets.connect(url, additional_headers={"Authorization": f"Token {key}"})
        return DeepgramSTTSession(ws)


class DeepgramTTSProvider(TTSProvider):
    def synthesize(self, text: str) -> bytes:
        key = _require_key()
        response = httpx.post(
            f"{_TTS_URL}?model={_TTS_MODEL}&encoding=mp3",
            headers={"Authorization": f"Token {key}", "Content-Type": "application/json"},
            json={"text": text},
            timeout=30.0,
        )
        response.raise_for_status()
        return response.content
