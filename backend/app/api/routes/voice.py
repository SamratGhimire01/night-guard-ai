import asyncio
import json
import logging
import time
import uuid

from fastapi import APIRouter, Depends, WebSocket, WebSocketDisconnect
from sqlalchemy.orm import Session

from app.api.dependencies import get_db
from app.core.rate_limit import widget_business_rate_limiter, widget_ip_rate_limiter, widget_session_rate_limiter
from app.services.channels import widget_service
from app.voice import get_stt_provider, get_tts_provider

logger = logging.getLogger(__name__)

router = APIRouter()

# Phase 43 cost/safety guardrail: a real, enforced ceiling on one call's
# duration, checked against wall-clock time in the receive loop below (not
# just documented) -- see test_voice.py's shortened-deadline proof.
MAX_CALL_SECONDS = 600

_DEGRADE_MESSAGE = "I'm having trouble hearing you right now. Would you like to type instead?"
_RATE_LIMIT_MESSAGE = "Too many messages right now. Please try again shortly."


async def _send_json(websocket: WebSocket, payload: dict) -> None:
    await websocket.send_text(json.dumps(payload))


class _CallState:
    """Mutable state shared between the audio-forwarding and transcript-
    handling tasks below. session_token starts as whatever the browser
    already had (None on a voice-first session, or the SAME token the text
    widget already stored in localStorage if voice is resumed mid-
    conversation) and is updated in place the instant the orchestrator
    confirms one, so this call always keeps using the one real session/
    conversation -- this is the entire mechanism that makes voice and text
    share memory: both ultimately call widget_service.send_widget_message
    with the same session_token."""

    def __init__(self, session_token: str | None) -> None:
        self.session_token = session_token
        self.ended = False
        self.timed_out = False


async def _process_utterance(
    db: Session, *, business_id: uuid.UUID, client_ip: str, state: _CallState, text: str, websocket: WebSocket
) -> None:
    text = text.strip()
    if not text:
        return

    await _send_json(websocket, {"type": "transcript", "text": text})

    # Same three limiters, same discipline as the HTTP widget route
    # (app/api/routes/widget.py) -- a voice call is just another way of
    # driving the same public, unauthenticated conversation surface.
    business_key = str(business_id)
    if widget_business_rate_limiter.is_blocked(business_key) or widget_ip_rate_limiter.is_blocked(client_ip):
        await _send_json(websocket, {"type": "error", "message": _RATE_LIMIT_MESSAGE})
        return
    if state.session_token:
        session_key = f"{business_id}:{state.session_token}"
        if widget_session_rate_limiter.is_blocked(session_key):
            await _send_json(websocket, {"type": "error", "message": _RATE_LIMIT_MESSAGE})
            return
        widget_session_rate_limiter.record_attempt(session_key)
    widget_business_rate_limiter.record_attempt(business_key)
    widget_ip_rate_limiter.record_attempt(client_ip)

    await _send_json(websocket, {"type": "state", "value": "thinking"})

    # The EXACT same function the text widget endpoint calls -- same
    # orchestrator, same booking tools, same memory, same hallucination-proof
    # discipline. Voice never touches app/services/conversation/ directly.
    result = await asyncio.to_thread(
        widget_service.send_widget_message,
        db,
        business_id=business_id,
        session_token=state.session_token,
        content=text,
    )
    if result is None:
        # business_id resolved fine when the call started (see voice_call
        # below) -- this can only mean the business was deleted mid-call.
        await _send_json(websocket, {"type": "error", "message": "This business is no longer available."})
        state.ended = True
        return

    session_token, orchestrated = result
    state.session_token = session_token
    response_text = orchestrated["response"]

    await _send_json(websocket, {"type": "agent_text", "text": response_text, "session_token": session_token})
    await _send_json(websocket, {"type": "state", "value": "speaking"})

    audio = await asyncio.to_thread(get_tts_provider().synthesize, response_text)
    await websocket.send_bytes(audio)

    await _send_json(websocket, {"type": "state", "value": "listening"})


@router.websocket("/api/v1/widget/{business_id}/voice")
async def voice_call(websocket: WebSocket, business_id: uuid.UUID, db: Session = Depends(get_db)) -> None:
    """A real, live spoken conversation with the same brain the text widget
    uses. Public/anonymous, same trust tier as POST .../widget/{id}/messages
    -- see that route's docstring for the full threat-model reasoning, which
    applies identically here (business_id is meant to be public, session
    tokens are unguessable and business-scoped).

    Protocol (browser <-> here): binary WS frames are raw browser microphone
    audio in (WebM/Opus from MediaRecorder) and synthesized speech audio out
    (MP3). Text WS frames are small JSON control/status messages both ways
    ({"type": "end_call"} in; {"type": "transcript"|"agent_text"|"state"|
    "error"|"call_ended", ...} out). See app/static/widget.js for the client.
    """
    await websocket.accept()

    business = widget_service.get_widget_config(db, business_id=business_id)
    if business is None:
        await _send_json(websocket, {"type": "error", "message": "Business not found."})
        await websocket.close(code=4404)
        return

    client_ip = websocket.client.host if websocket.client else "unknown"
    state = _CallState(websocket.query_params.get("session_token") or None)

    try:
        stt = await get_stt_provider().connect()
    except Exception:
        logger.exception("Voice call failed to open the STT connection")
        await _send_json(websocket, {"type": "error", "message": _DEGRADE_MESSAGE})
        await websocket.close(code=1011)
        return

    deadline = time.monotonic() + MAX_CALL_SECONDS
    stop_event = asyncio.Event()

    async def pump_browser_audio() -> None:
        while not stop_event.is_set():
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                state.timed_out = True
                stop_event.set()
                return
            try:
                message = await asyncio.wait_for(websocket.receive(), timeout=remaining)
            except asyncio.TimeoutError:
                state.timed_out = True
                stop_event.set()
                return
            if message["type"] == "websocket.disconnect":
                stop_event.set()
                return
            data_bytes = message.get("bytes")
            if data_bytes is not None:
                await stt.send_audio(data_bytes)
                continue
            data_text = message.get("text")
            if data_text is not None:
                try:
                    control = json.loads(data_text)
                except (TypeError, ValueError):
                    continue
                if control.get("type") == "end_call":
                    stop_event.set()
                    return

    async def pump_transcripts() -> None:
        buffer = ""
        async for event in stt.events():
            if stop_event.is_set():
                return
            event_type = event["type"]
            if event_type == "transcript":
                if event["is_final"]:
                    buffer = (buffer + " " + event["text"]).strip()
                if event["speech_final"] and buffer:
                    text, buffer = buffer, ""
                    await _process_utterance(
                        db, business_id=business_id, client_ip=client_ip, state=state, text=text, websocket=websocket
                    )
                    if state.ended:
                        stop_event.set()
                        return
            elif event_type == "utterance_end" and buffer:
                text, buffer = buffer, ""
                await _process_utterance(
                    db, business_id=business_id, client_ip=client_ip, state=state, text=text, websocket=websocket
                )
                if state.ended:
                    stop_event.set()
                    return

    try:
        audio_task = asyncio.create_task(pump_browser_audio())
        transcript_task = asyncio.create_task(pump_transcripts())
        done, pending = await asyncio.wait({audio_task, transcript_task}, return_when=asyncio.FIRST_COMPLETED)
        for task in pending:
            task.cancel()
        await asyncio.gather(*pending, return_exceptions=True)
        for task in done:
            exc = task.exception()
            if exc is not None:
                raise exc
    except (WebSocketDisconnect, asyncio.CancelledError):
        pass
    except Exception:
        logger.exception("Voice call ended abnormally -- degrading instead of hanging")
        try:
            await _send_json(websocket, {"type": "error", "message": _DEGRADE_MESSAGE})
        except Exception:
            pass
    finally:
        stop_event.set()
        try:
            await stt.close()
        except Exception:
            pass
        if state.timed_out:
            try:
                await _send_json(websocket, {"type": "call_ended", "reason": "max_duration"})
            except Exception:
                pass
        try:
            await websocket.close()
        except Exception:
            pass
