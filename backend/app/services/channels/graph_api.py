import json
import logging
import urllib.error
import urllib.request

logger = logging.getLogger(__name__)

_TIMEOUT_SECONDS = 10

# Real, confirmed-live finding (PHASE_STATUS.md — the WhatsApp Embedded
# Signup phase's root-cause investigation): Instagram has two structurally
# incompatible connection products. "Instagram API with Instagram Login"
# issues IGAA-prefixed Instagram User access tokens that are ONLY ever valid
# against graph.instagram.com; the older Instagram-via-linked-Facebook-Page
# product issues ordinary Facebook (EAA-prefixed) tokens, valid only against
# graph.facebook.com. Confirmed live: the same saved token that got "Cannot
# parse access token" from graph.facebook.com resolved successfully via
# graph.instagram.com/me. Detected by prefix, not hardcoded to one host, so a
# future business connected the other way isn't silently broken.
_INSTAGRAM_LOGIN_TOKEN_PREFIX = "IGAA"


def instagram_graph_host(access_token: str) -> str:
    return "graph.instagram.com" if access_token.startswith(_INSTAGRAM_LOGIN_TOKEN_PREFIX) else "graph.facebook.com"


def test_graph_credentials(
    *, object_id: str, access_token: str, api_version: str, host: str = "graph.facebook.com"
) -> tuple[bool, str]:
    """Real, lightweight `GET /{api_version}/{object_id}?access_token=...`
    against Meta's Graph API — a real object read, safe to run before a
    business relies on the saved credentials, never sending a message to a
    real customer. `host` defaults to graph.facebook.com (WhatsApp/Messenger
    Page-linked Instagram); pass `host="graph.instagram.com"` for an
    Instagram-Login-style token (see instagram_graph_host above) — that
    other host cannot parse this one's tokens at all, confirmed live.

    Never raises. Never logs/returns the access_token itself — it only ever
    appears in the outgoing request URL, never in a log line here.
    """
    if not object_id or not access_token:
        return False, "Missing phone number ID / account ID or access token."

    url = f"https://{host}/{api_version}/{object_id}?access_token={access_token}"
    request = urllib.request.Request(url, method="GET")
    try:
        with urllib.request.urlopen(request, timeout=_TIMEOUT_SECONDS) as response:
            payload = json.loads(response.read())
            summary = {k: v for k, v in payload.items() if k != "id"}
            return True, f"Connected — Meta returned: {summary}" if summary else "Connected."
    except urllib.error.HTTPError as exc:
        try:
            body = json.loads(exc.read())
            message = (body.get("error") or {}).get("message") or f"HTTP {exc.code}"
        except (ValueError, json.JSONDecodeError):
            message = f"HTTP {exc.code}"
        logger.info("graph API test-connection failed: HTTP %s", exc.code)
        return False, message
    except urllib.error.URLError as exc:
        logger.info("graph API test-connection could not reach Graph API (%s)", type(exc.reason).__name__)
        return False, "Could not reach Meta's Graph API. Please try again."


def test_messenger_credentials(*, access_token: str, api_version: str) -> tuple[bool, str]:
    """Real, harmless `GET /me/messenger_profile` — gated by the SAME
    `pages_messaging` permission the real Send API (`POST /me/messages`)
    uses. Deliberately NOT the generic test_graph_credentials object-read
    above for Messenger: a plain `GET /{page_id}` requires
    `pages_read_engagement` / Page Public Content Access, a permission this
    app's Messenger integration was never granted and doesn't need for
    sending — confirmed live to be a false negative (PHASE_STATUS.md): a
    fully valid, never-expiring, `pages_messaging`-scoped token failed that
    check while genuinely being able to send. This endpoint reflects real
    send capability instead: a 200 here (even with empty fields, meaning
    nothing's configured) proves the token can authenticate a real
    pages_messaging-gated call; an actual auth failure here would mean
    sending is ALSO broken, a real signal, not a false one.

    Never raises. Never logs/returns the access_token itself.
    """
    if not access_token:
        return False, "Missing access token."

    url = (
        f"https://graph.facebook.com/{api_version}/me/messenger_profile"
        f"?fields=whitelisted_domains,greeting&access_token={access_token}"
    )
    request = urllib.request.Request(url, method="GET")
    try:
        with urllib.request.urlopen(request, timeout=_TIMEOUT_SECONDS) as response:
            json.loads(response.read())
            return True, "Connected — the pages_messaging-scoped Messenger Profile API accepted this token."
    except urllib.error.HTTPError as exc:
        try:
            body = json.loads(exc.read())
            message = (body.get("error") or {}).get("message") or f"HTTP {exc.code}"
        except (ValueError, json.JSONDecodeError):
            message = f"HTTP {exc.code}"
        logger.info("messenger test-connection failed: HTTP %s", exc.code)
        return False, message
    except urllib.error.URLError as exc:
        logger.info("messenger test-connection could not reach Graph API (%s)", type(exc.reason).__name__)
        return False, "Could not reach Meta's Graph API. Please try again."


def fetch_instagram_user_id(*, access_token: str, api_version: str) -> str | None:
    """The Instagram professional account id (`user_id`) behind this token, or None. Instagram gives every account TWO ids:
    `id` (what `GET /me` returns as the app-scoped id — what a person typically copies into "Instagram Account ID") and
    `user_id` (the professional account id — what Meta puts in `entry[].id` of every WEBHOOK). Matching incoming webhooks to
    a business needs the second one; a business that typed only the first had every inbound DM dropped. Best-effort, never
    raises, never logs the token."""
    if not access_token:
        return None
    host = instagram_graph_host(access_token)
    request = urllib.request.Request(
        f"https://{host}/{api_version}/me?fields=user_id&access_token={access_token}", method="GET"
    )
    try:
        with urllib.request.urlopen(request, timeout=_TIMEOUT_SECONDS) as response:
            user_id = json.loads(response.read()).get("user_id")
            return str(user_id) if user_id else None
    except (urllib.error.URLError, ValueError, json.JSONDecodeError):
        logger.info("could not look up the Instagram professional account id (non-fatal)")
        return None
