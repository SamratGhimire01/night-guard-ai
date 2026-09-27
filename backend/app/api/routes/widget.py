import uuid
from pathlib import Path

from fastapi import APIRouter, Depends, Request
from fastapi.responses import FileResponse
from sqlalchemy.orm import Session

from app.api.dependencies import get_db
from app.core.exceptions import NotFoundError, TooManyRequestsError
from app.core.rate_limit import (
    widget_business_rate_limiter,
    widget_ip_rate_limiter,
    widget_poll_rate_limiter,
    widget_session_rate_limiter,
)
from app.schemas.widget import (
    WidgetConfigResponse,
    WidgetMessageRequest,
    WidgetMessageResponse,
    WidgetUpdate,
    WidgetUpdatesResponse,
)
from app.services.channels import widget_service

router = APIRouter()

_WIDGET_JS_PATH = Path(__file__).resolve().parents[2] / "static" / "widget.js"
_TEST_CHAT_PATH = Path(__file__).resolve().parents[2] / "static" / "test-chat.html"
_WIDGET_DEMO_PATH = Path(__file__).resolve().parents[2] / "static" / "widget-demo.html"


@router.get("/widget.js", include_in_schema=False)
def get_widget_script() -> FileResponse:
    """Served at the site root (not under /api/v1) so a business's own
    website can embed it exactly like the master plan's pattern:
    `<script src=".../widget.js" data-business-id="...">`. The script reads
    its own `data-business-id` attribute and this same origin at runtime —
    no separate config step."""
    return FileResponse(_WIDGET_JS_PATH, media_type="application/javascript")


@router.get("/test-chat", include_in_schema=False)
def get_test_chat_page() -> FileResponse:
    """Dev/test-only chat UI for hitting the real widget endpoint by hand.
    Not for production exposure -- see comment at top of test-chat.html."""
    return FileResponse(_TEST_CHAT_PATH, media_type="text/html")


@router.get("/widget-demo", include_in_schema=False)
def get_widget_demo_page() -> FileResponse:
    """Dev/test-only page that loads the REAL widget.js as a top-level page
    (not a sandboxed iframe) -- needed for a real live microphone test of the
    push-to-talk voice input (Phase 43h), since the dashboard's own widget
    preview is a sandboxed srcDoc iframe that cannot be granted microphone
    access. Not for production exposure -- see comment at top of
    widget-demo.html."""
    return FileResponse(_WIDGET_DEMO_PATH, media_type="text/html")


@router.get("/api/v1/widget/{business_id}/config", response_model=WidgetConfigResponse)
def get_widget_config(business_id: uuid.UUID, db: Session = Depends(get_db)) -> WidgetConfigResponse:
    """Public — same trust tier as `POST .../messages` above (see that
    route's docstring for the business_id-enumeration reasoning, which
    applies identically here): the widget script fetches this BEFORE
    rendering so it can show the business's real name/color/logo instead of
    a generic default. Nothing returned here is private — it's exactly what
    already appears on the business's own public website once the widget is
    embedded."""
    business = widget_service.get_widget_config(db, business_id=business_id)
    if business is None:
        raise NotFoundError("Business not found.")
    return WidgetConfigResponse(name=business.name, brand_color=business.brand_color, logo_url=business.logo_url)


@router.post("/api/v1/widget/{business_id}/messages", response_model=WidgetMessageResponse)
def post_widget_message(
    business_id: uuid.UUID,
    payload: WidgetMessageRequest,
    request: Request,
    db: Session = Depends(get_db),
) -> WidgetMessageResponse:
    """Public, unauthenticated-by-business-login endpoint for an anonymous
    website visitor — NOT the same trust tier as every other endpoint in this
    codebase, which requires a real BusinessUser JWT. Full threat-model
    reasoning (session isolation, rate limiting, cross-business replay,
    business_id enumeration) is in PHASE_STATUS.md Phase 21; summarized here:

    - Rate limiting: real per-IP, per-session, AND per-business_id limiters
      (app/core/rate_limit.py), checked before any DB/LLM work, so a burst is
      rejected cheaply rather than after spending real LLM budget. The
      per-business_id limiter (Phase 29) exists specifically because the
      CORS wildcard below means a flood can be distributed across many
      distinct visitor IPs/sessions, which the other two limiters can't see
      in aggregate — see PHASE_STATUS.md Phase 29 and
      tests/security/test_phase29_widget_distributed_flood.py.
    - Session isolation: session_token is opaque and unguessable (256-bit
      random, hashed at rest — see widget_service.py); a token that doesn't
      resolve to a real, business-scoped identity is silently replaced with a
      fresh one rather than ever attaching to, or revealing anything about,
      someone else's conversation.
    - business_id existence: a genuinely unknown business_id gets an honest
      404. business_id is a 128-bit UUID meant to be public (it's literally
      embedded in a business's own public website source as
      `data-business-id`), so confirming/denying one specific UUID's
      existence leaks nothing exploitable — brute-forcing the full keyspace
      to find OTHER real UUIDs is computationally infeasible regardless of
      this response.
    """
    business_key = str(business_id)
    if widget_business_rate_limiter.is_blocked(business_key):
        raise TooManyRequestsError("Too many messages right now. Please try again shortly.")
    widget_business_rate_limiter.record_attempt(business_key)

    client_ip = request.client.host if request.client else "unknown"
    if widget_ip_rate_limiter.is_blocked(client_ip):
        raise TooManyRequestsError("Too many messages from this connection. Please slow down and try again.")
    widget_ip_rate_limiter.record_attempt(client_ip)

    if payload.session_token:
        session_key = f"{business_id}:{payload.session_token}"
        if widget_session_rate_limiter.is_blocked(session_key):
            raise TooManyRequestsError("Too many messages in this conversation. Please slow down and try again.")
        widget_session_rate_limiter.record_attempt(session_key)

    result = widget_service.send_widget_message(
        db, business_id=business_id, session_token=payload.session_token, content=payload.content
    )
    if result is None:
        raise NotFoundError("Business not found.")

    session_token, orchestrated = result
    return WidgetMessageResponse(
        session_token=session_token,
        response=orchestrated["response"],
        intent=orchestrated["intent"].value if orchestrated["intent"] is not None else None,
        agent_message_id=orchestrated.get("agent_message_id"),
        customer_message_id=orchestrated.get("customer_message_id"),
    )


@router.get("/api/v1/widget/{business_id}/updates", response_model=WidgetUpdatesResponse)
def get_widget_updates(
    business_id: uuid.UUID, session_token: str, after: uuid.UUID, db: Session = Depends(get_db)
) -> WidgetUpdatesResponse:
    """Public, session-token-gated: messages the system sent into this widget session unprompted since the reply
    `after` (e.g. the "payment received" confirmation) — the widget polls this while a payment link is outstanding.
    Same session isolation as `POST .../messages`: a token that isn't this business's own gets an empty list, never
    an error that tells a guesser anything."""
    session_key = f"{business_id}:{session_token[:500]}"
    if widget_poll_rate_limiter.is_blocked(session_key):
        raise TooManyRequestsError("Too many requests. Please slow down.")
    widget_poll_rate_limiter.record_attempt(session_key)
    messages = widget_service.get_agent_messages_after(
        db, business_id=business_id, session_token=session_token[:500], after_message_id=after
    )
    return WidgetUpdatesResponse(
        messages=[WidgetUpdate(id=m.id, content=m.content, created_at=m.created_at) for m in messages or []]
    )
