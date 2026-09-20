from pydantic import BaseModel


class GoogleCalendarAuthorizationURL(BaseModel):
    """GET /integrations/google-calendar/connect's real response — the
    dashboard SPA navigates the whole page to this URL itself (a plain GET
    can't carry a bearer token to Google, so this JSON round-trip through
    apiFetch is what lets the connect action stay premium/role-gated)."""

    authorization_url: str


class GoogleCalendarStatus(BaseModel):
    """Never carries a token — connected + the real connected calendar's
    display name only, per the ticket's explicit requirement.
    `needs_reconnect`: Google rejected the stored token (a real check, see
    google_calendar_service.get_status). `verified=False`: Google couldn't be
    reached, so the token's state is unknown."""

    connected: bool
    calendar_name: str | None = None
    needs_reconnect: bool = False
    verified: bool = True
