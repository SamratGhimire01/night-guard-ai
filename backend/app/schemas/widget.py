from pydantic import BaseModel, field_validator

from app.schemas.common import safe_str

# Phase 29 — this is the most exposed field in the whole API (public, no
# auth at all): a NUL byte in `content` crashed with a raw 500 at the DB
# insert, and an uncapped `content` (tested with 5MB) sailed straight into a
# real LLM API call before anything rejected it — real cost/DoS exposure on
# an anonymous endpoint. 5,000 chars is generous for one chat turn (a real
# session_token is ~43 chars; 500 is generous headroom for that).
_MAX_MESSAGE_CHARS = 5_000
_MAX_SESSION_TOKEN_CHARS = 500


class WidgetMessageRequest(BaseModel):
    # Absent/null on a visitor's very first message — the server mints one.
    session_token: safe_str(_MAX_SESSION_TOKEN_CHARS) | None = None
    content: safe_str(_MAX_MESSAGE_CHARS)

    @field_validator("content")
    @classmethod
    def not_blank(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("This field must not be blank.")
        return value


class WidgetMessageResponse(BaseModel):
    session_token: str
    response: str
    intent: str


class WidgetVoiceMessageResponse(BaseModel):
    """Phase 43h: push-to-talk voice input. `session_token`/`intent` are
    None on the (rare) failure paths that never reach the real orchestrator
    at all -- a transcription failure, or a recording with no detectable
    speech in it -- since there's no real turn to report an intent for."""

    session_token: str | None = None
    transcript: str
    response: str
    intent: str | None = None


class WidgetConfigResponse(BaseModel):
    """Public branding for the embedded widget — same public-data tier as
    `business_id` itself (already embedded in the business's own public
    website source as `data-business-id`), never anything private."""

    name: str
    brand_color: str
    logo_url: str | None
