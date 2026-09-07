"""Real Google Calendar OAuth + Calendar API integration (Phase 40, Premium-only).

Two jobs, kept in one module because they share the same token/integration
plumbing:
  1. Availability: exclude_google_busy_slots() lets booking_service treat a
     real Google Calendar busy interval as unavailable, IN ADDITION TO the
     existing Postgres appointment-conflict/business-hours logic. This is an
     additional signal, never a replacement for Phase 10's EXCLUDE constraint,
     which remains the only real race-proof guarantee against double-booking.
  2. Reflection: sync_appointment_created/cancelled/rescheduled() create/
     delete/update the corresponding Google Calendar event after a real
     booking/cancel/reschedule has already committed in Postgres.

Every function a booking-flow caller touches (exclude_google_busy_slots,
sync_appointment_*) is a real, best-effort side effect: a Google API failure
is logged and swallowed, never allowed to block, reverse, or corrupt a
Night Guard booking that has already succeeded — same discipline as Phase 13's
NotificationProvider dispatch. sync_appointment_* additionally leaves an
honest Appointment.calendar_sync_status ("synced"/"failed") so failures are
visible in our own data, not silent.

Deliberately out of scope (Phase 40 ticket, stated explicitly, not an
oversight): no push notifications when someone edits the connected Google
Calendar directly (Google's watch/channel webhook system). Availability
checks are pull-based — queried fresh on every get_available_slots call —
never push-based.
"""

import logging
import uuid
from datetime import datetime, time, timedelta, timezone
from urllib.parse import urlencode
from zoneinfo import ZoneInfo

import httpx
from sqlalchemy.orm import Session

from app.core.config import settings
from app.db.models.appointment import Appointment
from app.db.models.business import Business, BusinessPlan
from app.db.models.customer import Customer
from app.db.models.integration import Integration
from app.db.models.service import Service
from app.services import integration_service

logger = logging.getLogger(__name__)

_AUTH_URL = "https://accounts.google.com/o/oauth2/v2/auth"
_TOKEN_URL = "https://oauth2.googleapis.com/token"
_REVOKE_URL = "https://oauth2.googleapis.com/revoke"
_CALENDAR_API_BASE = "https://www.googleapis.com/calendar/v3"
_SCOPE = "https://www.googleapis.com/auth/calendar"
INTEGRATION_TYPE = "google_calendar"
_CALENDAR_ID = "primary"
_TOKEN_REFRESH_BUFFER = timedelta(minutes=2)
_TIMEOUT_SECONDS = 15


class GoogleCalendarError(Exception):
    """Raised by every real Google API call in this module on any failure —
    network, auth, or a non-2xx response. Deliberately never logs `str(exc)`
    or a response body (could echo back a token/auth header) — only status
    codes and exception class names, same log-scrubbing discipline as
    app/llm/azure_openai.py."""


# --- OAuth connect/disconnect/status ---------------------------------------


def build_authorization_url(state: str) -> str:
    params = {
        "client_id": settings.google_client_id,
        "redirect_uri": settings.google_redirect_uri,
        "response_type": "code",
        "scope": _SCOPE,
        "access_type": "offline",
        # Forces Google to re-issue a refresh_token every time (Google only
        # returns one on a user's very first consent otherwise) — needed
        # because Integration.config always fully replaces the prior row,
        # not merges, so a reconnect with no refresh_token would silently
        # discard the ability to ever refresh again.
        "prompt": "consent",
        "state": state,
    }
    return f"{_AUTH_URL}?{urlencode(params)}"


def _post_token_endpoint(data: dict) -> dict:
    try:
        response = httpx.post(_TOKEN_URL, data=data, timeout=_TIMEOUT_SECONDS)
    except httpx.TransportError as exc:
        raise GoogleCalendarError(f"token endpoint transport error: {type(exc).__name__}") from None
    if response.status_code != 200:
        raise GoogleCalendarError(f"token endpoint failed with HTTP {response.status_code}")
    return response.json()


def _exchange_code_for_tokens(code: str) -> dict:
    return _post_token_endpoint(
        {
            "client_id": settings.google_client_id,
            "client_secret": settings.google_client_secret,
            "code": code,
            "redirect_uri": settings.google_redirect_uri,
            "grant_type": "authorization_code",
        }
    )


def _get_calendar_summary(access_token: str) -> str:
    try:
        response = httpx.get(
            f"{_CALENDAR_API_BASE}/calendars/{_CALENDAR_ID}",
            headers={"Authorization": f"Bearer {access_token}"},
            timeout=_TIMEOUT_SECONDS,
        )
    except httpx.TransportError as exc:
        raise GoogleCalendarError(f"calendar lookup transport error: {type(exc).__name__}") from None
    if response.status_code != 200:
        raise GoogleCalendarError(f"calendar lookup failed with HTTP {response.status_code}")
    return response.json().get("summary") or "Google Calendar"


def complete_oauth_connection(db: Session, *, business_id: uuid.UUID, code: str) -> Integration:
    """Real code-for-tokens exchange + real calendar lookup, then stores the
    result via the shared Integration upsert (never through the public,
    hand-typed-config IntegrationUpsert schema — these tokens only ever come
    from a real Google redirect, never client-supplied JSON). Raises
    GoogleCalendarError on any real failure; the callback route is
    responsible for turning that into an honest redirect, never a raw 500."""
    token_data = _exchange_code_for_tokens(code)
    access_token = token_data.get("access_token")
    refresh_token = token_data.get("refresh_token")
    if not access_token or not refresh_token:
        raise GoogleCalendarError(
            "Google did not return a refresh_token. Revoke prior access at "
            "https://myaccount.google.com/permissions and try connecting again."
        )
    expires_in = token_data.get("expires_in", 3600)
    token_expiry = (datetime.now(timezone.utc) + timedelta(seconds=expires_in)).isoformat()
    calendar_summary = _get_calendar_summary(access_token)

    config = {
        "access_token": access_token,
        "refresh_token": refresh_token,
        "calendar_id": _CALENDAR_ID,
        "calendar_summary": calendar_summary,
        "token_expiry": token_expiry,
    }
    return integration_service.save_integration_config(
        db, business_id=business_id, type_=INTEGRATION_TYPE, config=config, enabled=True
    )


def disconnect(db: Session, *, business_id: uuid.UUID) -> bool:
    """Real revoke + real delete. The revoke call is itself best-effort — a
    business must always be able to disconnect locally even if Google's
    revoke endpoint is unreachable or the token was already invalid."""
    integration = integration_service.get_integration(db, business_id=business_id, type_=INTEGRATION_TYPE)
    if integration is None:
        return False
    refresh_token = integration.config.get("refresh_token")
    if refresh_token:
        try:
            httpx.post(_REVOKE_URL, params={"token": refresh_token}, timeout=_TIMEOUT_SECONDS)
        except httpx.TransportError:
            logger.warning(
                "google calendar token revoke request failed for business_id=%s (non-fatal, "
                "proceeding with local delete)",
                business_id,
            )
    return integration_service.delete_integration(db, business_id=business_id, type_=INTEGRATION_TYPE)


def get_status(db: Session, *, business_id: uuid.UUID) -> dict:
    """Never returns raw tokens — only connected + the connected calendar's
    real display name, per the ticket's explicit requirement."""
    integration = integration_service.get_integration(db, business_id=business_id, type_=INTEGRATION_TYPE)
    if integration is None or not integration.enabled:
        return {"connected": False, "calendar_name": None}
    return {"connected": True, "calendar_name": integration.config.get("calendar_summary")}


# --- Token refresh + applicability ------------------------------------------


def _active_integration(db: Session, business: Business | None) -> Integration | None:
    """Only a Premium business with an enabled, connected Google Calendar
    integration gets real calendar behavior. A Free-plan business — even one
    with a stale row left over from a downgrade — is treated exactly like
    "not connected," never partially honored."""
    if business is None or business.plan != BusinessPlan.PREMIUM:
        return None
    integration = integration_service.get_integration(db, business_id=business.id, type_=INTEGRATION_TYPE)
    if integration is None or not integration.enabled:
        return None
    return integration


def _fresh_access_token(db: Session, integration: Integration) -> str:
    """Refreshes and persists a new access token if the stored one is expired
    or within a small buffer of expiring — a real OAuth refresh call, not
    assumed to "just work." Google's refresh response never returns a new
    refresh_token, so the original is always preserved in the new config."""
    config = integration.config
    expiry = datetime.fromisoformat(config["token_expiry"])
    if datetime.now(timezone.utc) < expiry - _TOKEN_REFRESH_BUFFER:
        return config["access_token"]

    data = _post_token_endpoint(
        {
            "client_id": settings.google_client_id,
            "client_secret": settings.google_client_secret,
            "refresh_token": config["refresh_token"],
            "grant_type": "refresh_token",
        }
    )
    new_access_token = data["access_token"]
    new_expiry = (datetime.now(timezone.utc) + timedelta(seconds=data.get("expires_in", 3600))).isoformat()
    new_config = {**config, "access_token": new_access_token, "token_expiry": new_expiry}
    integration_service.save_integration_config(
        db, business_id=integration.business_id, type_=INTEGRATION_TYPE, config=new_config, enabled=integration.enabled
    )
    return new_access_token


# --- Availability: real Free/Busy query -------------------------------------


def _query_freebusy(access_token: str, *, calendar_id: str, time_min: datetime, time_max: datetime) -> list[dict]:
    try:
        response = httpx.post(
            f"{_CALENDAR_API_BASE}/freeBusy",
            headers={"Authorization": f"Bearer {access_token}"},
            json={"timeMin": time_min.isoformat(), "timeMax": time_max.isoformat(), "items": [{"id": calendar_id}]},
            timeout=_TIMEOUT_SECONDS,
        )
    except httpx.TransportError as exc:
        raise GoogleCalendarError(f"freeBusy transport error: {type(exc).__name__}") from None
    if response.status_code != 200:
        raise GoogleCalendarError(f"freeBusy failed with HTTP {response.status_code}")
    return response.json()["calendars"][calendar_id]["busy"]


def get_busy_intervals(
    db: Session, business: Business, *, date_from, date_to
) -> list[tuple[datetime, datetime]] | None:
    """Real Free/Busy query for [date_from, date_to] (inclusive calendar
    dates, business's own timezone). Returns None — not [] — when Google
    Calendar sync isn't applicable at all (free plan / not connected) OR the
    real API call failed for any reason, so the caller can treat both the
    same way: fall back to Postgres-only availability. Google Calendar is an
    additional signal for proposing slots, never the source of truth —
    Phase 10's EXCLUDE constraint is what actually prevents double-booking.
    Never raises."""
    integration = _active_integration(db, business)
    if integration is None:
        return None
    try:
        access_token = _fresh_access_token(db, integration)
        tz = ZoneInfo(business.timezone)
        time_min = datetime.combine(date_from, time.min, tzinfo=tz)
        time_max = datetime.combine(date_to + timedelta(days=1), time.min, tzinfo=tz)
        calendar_id = integration.config["calendar_id"]
        busy = _query_freebusy(access_token, calendar_id=calendar_id, time_min=time_min, time_max=time_max)
        return [(datetime.fromisoformat(b["start"]), datetime.fromisoformat(b["end"])) for b in busy]
    except Exception:
        logger.warning(
            "google calendar freebusy check failed for business_id=%s (non-fatal, falling back to "
            "DB-only availability)",
            business.id,
            exc_info=True,
        )
        return None


def exclude_google_busy_slots(
    db: Session, *, business: Business, slots: list[datetime], duration_minutes: int, date_from, date_to
) -> list[datetime]:
    """The one function booking_service.get_available_slots calls — returns
    `slots` completely unchanged whenever Google Calendar sync isn't
    applicable or the real API call failed (see get_busy_intervals)."""
    busy = get_busy_intervals(db, business, date_from=date_from, date_to=date_to)
    if busy is None:
        return slots
    duration = timedelta(minutes=duration_minutes)
    return [slot for slot in slots if not any(slot < b_end and b_start < slot + duration for b_start, b_end in busy)]


# --- Two-way reflection: real event create/update/delete --------------------


def _event_summary_and_description(db: Session, appointment: Appointment) -> tuple[str, str]:
    service = db.get(Service, appointment.service_id)
    customer = db.get(Customer, appointment.customer_id)
    service_name = service.name if service else "Appointment"
    customer_name = customer.name if customer else "Customer"
    return f"{service_name} — {customer_name}", f"Booked via Night Guard AI. Booking ID: {appointment.id}"


def _create_event(access_token: str, *, calendar_id: str, summary: str, description: str, start: datetime, end: datetime) -> str:
    try:
        response = httpx.post(
            f"{_CALENDAR_API_BASE}/calendars/{calendar_id}/events",
            headers={"Authorization": f"Bearer {access_token}"},
            json={
                "summary": summary,
                "description": description,
                "start": {"dateTime": start.isoformat()},
                "end": {"dateTime": end.isoformat()},
            },
            timeout=_TIMEOUT_SECONDS,
        )
    except httpx.TransportError as exc:
        raise GoogleCalendarError(f"event create transport error: {type(exc).__name__}") from None
    if response.status_code not in (200, 201):
        raise GoogleCalendarError(f"event create failed with HTTP {response.status_code}")
    return response.json()["id"]


def _update_event(access_token: str, *, calendar_id: str, event_id: str, start: datetime, end: datetime) -> None:
    try:
        response = httpx.patch(
            f"{_CALENDAR_API_BASE}/calendars/{calendar_id}/events/{event_id}",
            headers={"Authorization": f"Bearer {access_token}"},
            json={"start": {"dateTime": start.isoformat()}, "end": {"dateTime": end.isoformat()}},
            timeout=_TIMEOUT_SECONDS,
        )
    except httpx.TransportError as exc:
        raise GoogleCalendarError(f"event update transport error: {type(exc).__name__}") from None
    # 404/410: the event no longer exists on Google's side (e.g. deleted
    # directly in Google Calendar — the one gap this phase explicitly does
    # NOT solve, see the module docstring). Nothing left to update; not
    # treated as a real failure.
    if response.status_code not in (200, 404, 410):
        raise GoogleCalendarError(f"event update failed with HTTP {response.status_code}")


def _delete_event(access_token: str, *, calendar_id: str, event_id: str) -> None:
    try:
        response = httpx.delete(
            f"{_CALENDAR_API_BASE}/calendars/{calendar_id}/events/{event_id}",
            headers={"Authorization": f"Bearer {access_token}"},
            timeout=_TIMEOUT_SECONDS,
        )
    except httpx.TransportError as exc:
        raise GoogleCalendarError(f"event delete transport error: {type(exc).__name__}") from None
    if response.status_code not in (200, 204, 404, 410):
        raise GoogleCalendarError(f"event delete failed with HTTP {response.status_code}")


def sync_appointment_created(db: Session, appointment: Appointment) -> None:
    """Best-effort reflection into Google Calendar, called right after a real
    booking's own commit — same resilience discipline as Phase 13's
    dispatch_notification: NEVER raises. A sync failure must never be
    reported to the customer as a failed booking — the booking already
    committed in Postgres before this ever runs. Leaves a real, honest
    calendar_sync_status; NULL (untouched) when sync isn't even applicable
    (free plan / not connected), never conflated with a real failure."""
    business = db.get(Business, appointment.business_id)
    integration = _active_integration(db, business)
    if integration is None:
        return
    try:
        access_token = _fresh_access_token(db, integration)
        summary, description = _event_summary_and_description(db, appointment)
        end = appointment.scheduled_at + timedelta(minutes=appointment.duration_minutes)
        event_id = _create_event(
            access_token,
            calendar_id=integration.config["calendar_id"],
            summary=summary,
            description=description,
            start=appointment.scheduled_at,
            end=end,
        )
        appointment.google_calendar_event_id = event_id
        appointment.calendar_sync_status = "synced"
    except Exception:
        logger.warning(
            "google calendar event create failed for appointment_id=%s (non-fatal, booking already "
            "confirmed)",
            appointment.id,
            exc_info=True,
        )
        appointment.calendar_sync_status = "failed"
    db.commit()


def sync_appointment_cancelled(db: Session, appointment: Appointment) -> None:
    """Deletes the real Google Calendar event for a real cancellation. A
    no-op (not a failure) if this appointment was never synced in the first
    place (free plan the whole time, or the original sync failed with no
    event ever created)."""
    business = db.get(Business, appointment.business_id)
    integration = _active_integration(db, business)
    if integration is None or not appointment.google_calendar_event_id:
        return
    try:
        access_token = _fresh_access_token(db, integration)
        _delete_event(access_token, calendar_id=integration.config["calendar_id"], event_id=appointment.google_calendar_event_id)
        appointment.calendar_sync_status = "synced"
    except Exception:
        logger.warning(
            "google calendar event delete failed for appointment_id=%s (non-fatal, cancellation "
            "already confirmed)",
            appointment.id,
            exc_info=True,
        )
        appointment.calendar_sync_status = "failed"
    db.commit()


def sync_appointment_rescheduled(db: Session, appointment: Appointment) -> None:
    """Updates the SAME Google Calendar event's time — never creates a
    duplicate. If this appointment has no stored event_id yet (its original
    booking's sync had failed, or the connection was made after it was
    booked), this self-heals by creating the event fresh now rather than
    leaving it permanently unreflected."""
    business = db.get(Business, appointment.business_id)
    integration = _active_integration(db, business)
    if integration is None:
        return
    try:
        access_token = _fresh_access_token(db, integration)
        calendar_id = integration.config["calendar_id"]
        end = appointment.scheduled_at + timedelta(minutes=appointment.duration_minutes)
        if appointment.google_calendar_event_id:
            _update_event(access_token, calendar_id=calendar_id, event_id=appointment.google_calendar_event_id, start=appointment.scheduled_at, end=end)
        else:
            summary, description = _event_summary_and_description(db, appointment)
            appointment.google_calendar_event_id = _create_event(
                access_token, calendar_id=calendar_id, summary=summary, description=description,
                start=appointment.scheduled_at, end=end,
            )
        appointment.calendar_sync_status = "synced"
    except Exception:
        logger.warning(
            "google calendar event update failed for appointment_id=%s (non-fatal, reschedule "
            "already confirmed)",
            appointment.id,
            exc_info=True,
        )
        appointment.calendar_sync_status = "failed"
    db.commit()
