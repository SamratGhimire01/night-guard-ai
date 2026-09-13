import json
import logging
import urllib.error
import urllib.request

logger = logging.getLogger(__name__)

_TIMEOUT_SECONDS = 10


def test_graph_credentials(*, object_id: str, access_token: str, api_version: str) -> tuple[bool, str]:
    """Real, lightweight `GET /{api_version}/{object_id}?access_token=...`
    against Meta's Graph API — the one mechanism genuinely identical across
    WhatsApp (a phone_number_id), Messenger (a page_id) and Instagram (an
    ig_account_id): each object is readable by its own credential when that
    credential is valid, and Meta returns a real, descriptive error
    (typically "Invalid OAuth access token") when it isn't. This never sends
    a message to a real customer — it's a read, safe to run before a
    business relies on the saved credentials.

    Never raises. Never logs/returns the access_token itself — it only ever
    appears in the outgoing request URL, never in a log line here.
    """
    if not object_id or not access_token:
        return False, "Missing phone number ID / account ID or access token."

    url = f"https://graph.facebook.com/{api_version}/{object_id}?access_token={access_token}"
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
