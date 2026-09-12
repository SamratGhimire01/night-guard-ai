import asyncio
import logging
import uuid

from fastapi import APIRouter, Depends, File, Form, Request, UploadFile
from sqlalchemy.orm import Session

from app.api.dependencies import get_db
from app.core.exceptions import NotFoundError, PayloadTooLargeError, TooManyRequestsError
from app.core.rate_limit import widget_business_rate_limiter, widget_ip_rate_limiter, widget_session_rate_limiter
from app.schemas.widget import WidgetVoiceMessageResponse
from app.services.channels import widget_service
from app.voice import get_stt_provider

logger = logging.getLogger(__name__)

router = APIRouter()

# Phase 43h: a real, enforced ceiling on one push-to-talk recording's size --
# this is a public, unauthenticated endpoint accepting raw binary uploads,
# same real-cost-exposure discipline as Phase 29's widget message length cap
# (WidgetMessageRequest._MAX_MESSAGE_CHARS). A one-shot push-to-talk clip is
# a few sentences, not a multi-minute recording -- 15MB is comfortably
# generous headroom for that at typical browser WebM/Opus bitrates.
_MAX_AUDIO_BYTES = 15 * 1024 * 1024

_NO_SPEECH_MESSAGE = "I didn't catch that. Could you try recording your message again?"
_STT_FAILURE_MESSAGE = (
    "Sorry, I'm having trouble understanding voice messages right now. Please try typing instead."
)

# Phase 43h: voice-originated turns get one deliberate override the typed-text
# path (Phase 25b) never gets. If the customer's SPOKEN input was Nepali, the
# reply is composed in ROMANIZED Nepali specifically, regardless of whatever
# the conversation's own text-based language lock would otherwise pick
# (which could be ne_deva, still unset, or something else entirely). This is
# deliberate: Deepgram's real Nepali STT model always transcribes speech to
# Devanagari script (see app/voice/deepgram.py), but Devanagari isn't what's
# actually readable/expected in a chat bubble that started life as spoken
# audio -- Romanized text is. English speech gets normal existing behavior
# (no override at all).
_VOICE_LANGUAGE_OVERRIDE = {"ne": "ne_roman"}


@router.post("/api/v1/widget/{business_id}/voice-message", response_model=WidgetVoiceMessageResponse)
async def post_widget_voice_message(
    business_id: uuid.UUID,
    request: Request,
    audio: UploadFile = File(...),
    session_token: str | None = Form(None),
    db: Session = Depends(get_db),
) -> WidgetVoiceMessageResponse:
    """Push-to-talk voice input for the widget (Phase 43h) -- replaces the
    former real-time streaming voice call entirely. The browser records ONE
    complete utterance (click to start, click to stop -- see widget.js's
    MediaRecorder usage), uploads it here as a single blob, and gets back a
    normal text reply. No persistent connection, no spoken audio output.

    Same public/anonymous trust tier as POST .../widget/{id}/messages (see
    that route's docstring for the full threat-model reasoning): same three
    rate limiters, same session-token resolution, same 404-on-unknown-
    business. The transcript is handed to the EXACT SAME
    widget_service.send_widget_message the typed-text endpoint calls -- same
    orchestrator, same booking tools, same memory. Voice is only ever a
    different way of producing `content`, never a parallel conversation
    brain.
    """
    business_key = str(business_id)
    if widget_business_rate_limiter.is_blocked(business_key):
        raise TooManyRequestsError("Too many messages right now. Please try again shortly.")
    widget_business_rate_limiter.record_attempt(business_key)

    client_ip = request.client.host if request.client else "unknown"
    if widget_ip_rate_limiter.is_blocked(client_ip):
        raise TooManyRequestsError("Too many messages from this connection. Please slow down and try again.")
    widget_ip_rate_limiter.record_attempt(client_ip)

    if session_token:
        session_key = f"{business_id}:{session_token}"
        if widget_session_rate_limiter.is_blocked(session_key):
            raise TooManyRequestsError("Too many messages in this conversation. Please slow down and try again.")
        widget_session_rate_limiter.record_attempt(session_key)

    if widget_service.get_widget_config(db, business_id=business_id) is None:
        raise NotFoundError("Business not found.")

    audio_bytes = await audio.read(_MAX_AUDIO_BYTES + 1)
    if len(audio_bytes) > _MAX_AUDIO_BYTES:
        raise PayloadTooLargeError("Recording is too large.")

    try:
        transcription = await get_stt_provider().transcribe(
            audio_bytes, content_type=audio.content_type or "audio/webm"
        )
    except Exception:
        logger.exception("Voice message transcription failed")
        return WidgetVoiceMessageResponse(session_token=session_token, transcript="", response=_STT_FAILURE_MESSAGE)

    transcript = transcription["text"].strip()
    if not transcript:
        return WidgetVoiceMessageResponse(session_token=session_token, transcript="", response=_NO_SPEECH_MESSAGE)

    force_language = _VOICE_LANGUAGE_OVERRIDE.get(transcription["language"])
    result = await asyncio.to_thread(
        widget_service.send_widget_message,
        db,
        business_id=business_id,
        session_token=session_token,
        content=transcript,
        force_language=force_language,
    )
    if result is None:
        raise NotFoundError("Business not found.")

    new_session_token, orchestrated = result
    return WidgetVoiceMessageResponse(
        session_token=new_session_token,
        transcript=transcript,
        response=orchestrated["response"],
        intent=orchestrated["intent"].value,
    )
