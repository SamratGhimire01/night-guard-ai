import uuid
from datetime import datetime

from typing import Literal

from pydantic import BaseModel, Field, field_validator

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
    # None (Phase 52) = a staff member owns this conversation: the message was stored, no AI reply is coming. The widget
    # shows nothing for it and picks the staff reply up through GET .../updates.
    response: str | None = None
    # Additive, optional: the SAME text as `response`, pre-split into up to 3 fragments (see
    # style_checks.split_into_bubbles) for a widget UI that wants to render several chat bubbles instead of one
    # block, purely a rendering hint -- None whenever `response` is None/short, or for any client that doesn't ask
    # for it. `response` itself is untouched either way (full text, same as before this field existed), so an old
    # client, the dashboard's conversation log, and the regression suite all see zero change.
    response_bubbles: list[str] | None = None
    intent: str | None = None
    # what the widget passes back to GET .../updates so it only ever receives messages newer than this reply
    agent_message_id: uuid.UUID | None = None
    # the visitor's own message id: the polling cursor when there is no AI reply (a staff member owns the conversation)
    customer_message_id: uuid.UUID | None = None


class WidgetUpdate(BaseModel):
    id: uuid.UUID
    content: str
    created_at: datetime


class WidgetUpdatesResponse(BaseModel):
    messages: list[WidgetUpdate]


class WidgetVoiceMessageResponse(BaseModel):
    """Phase 43h: push-to-talk voice input. `session_token`/`intent` are
    None on the (rare) failure paths that never reach the real orchestrator
    at all -- a transcription failure, or a recording with no detectable
    speech in it -- since there's no real turn to report an intent for."""

    session_token: str | None = None
    transcript: str
    response: str | None = None  # None: a staff member owns this conversation (Phase 52), see WidgetMessageResponse
    intent: str | None = None
    agent_message_id: uuid.UUID | None = None
    customer_message_id: uuid.UUID | None = None


LauncherIcon = Literal["chat", "sparkles", "headset", "question", "calendar", "logo"]


class WidgetSettings(BaseModel):
    """How the website chat widget looks and what it says before the visitor types. Stored as Business.widget_settings
    (JSONB). Every field has a default, so a business that never opened the customizer gets a complete, working widget,
    and a stored dict missing newer keys still validates. Blank strings mean "use the default"."""

    display_name: safe_str(40) = ""  # header title; blank = the business name
    subtitle: safe_str(80) = ""  # small line under the title; blank = a default that fits an instant AI reply
    welcome_message: safe_str(400) = ""  # first message shown in the chat; blank = a default greeting
    suggested_questions: list[safe_str(80)] = Field(default_factory=list, max_length=4)
    input_placeholder: safe_str(60) = ""
    launcher_icon: LauncherIcon = "chat"
    launcher_label: safe_str(30) = ""  # optional text pill beside the round button, e.g. "Chat with us"
    position: Literal["right", "left"] = "right"
    theme: Literal["light", "dark"] = "light"
    show_popup: bool = True  # the welcome message floats above the button once per visit
    popup_delay_seconds: int = Field(default=4, ge=0, le=60)
    show_branding: bool = True

    @field_validator("suggested_questions")
    @classmethod
    def drop_blank_questions(cls, value: list[str]) -> list[str]:
        return [q.strip() for q in value if q.strip()]


class WidgetConfigResponse(WidgetSettings):
    """Public branding for the embedded widget — same public-data tier as
    `business_id` itself (already embedded in the business's own public
    website source as `data-business-id`), never anything private. The name,
    colour and logo come from the business profile; the rest from WidgetSettings."""

    name: str
    brand_color: str
    logo_url: str | None
