"""Central guard for every customer-facing link built from settings.backend_base_url
(chat QR check-in, email/SMS confirmation, eSewa/Khalti payment redirect + QR).

Root cause of the 2026-09-26 incident (CLAUDE.md): BACKEND_BASE_URL pointed at a dev
ngrok tunnel; the host rebooted, the tunnel died, and every link built from it silently
pointed at a domain no customer could ever reach -- nothing in code distinguished "a
real public domain" from "today's dev tunnel." A localhost/127.0.0.1/ngrok-tunnel
address is fine in development (that's the whole point of a dev tunnel) but must never
be handed to a real customer in production -- this is refused and logged instead,
never sent."""
import logging
import re
from urllib.parse import urlparse

from app.core.config import settings

logger = logging.getLogger(__name__)

# ngrok's own free/paid tunnel domains (ngrok.io is the legacy TLD, still issued
# alongside ngrok-free.app/ngrok.app) -- the specific class of "works today, dead the
# moment the dev laptop/tunnel isn't around" address this incident was caused by.
_UNSAFE_HOST_RE = re.compile(r"^(localhost|127\.0\.0\.1|.*\.ngrok(-free)?\.(dev|app|io))$", re.I)


class UnsafePublicURLError(RuntimeError):
    """settings.backend_base_url is a dev/tunnel address and this is production --
    raised instead of handing a dead link to a real customer. Callers decide how to
    degrade (omit the link, fail the payment) -- see call sites for the exact
    fallback; this only ever decides whether the URL is safe to hand out."""


def public_backend_base_url() -> str:
    """settings.backend_base_url, refused (logged CRITICAL + raised) when it is a
    localhost/tunnel address in a production environment. The ONLY function any
    customer-facing link should read backend_base_url through."""
    base_url = settings.backend_base_url
    host = urlparse(base_url).hostname or ""
    if settings.environment == "production" and _UNSAFE_HOST_RE.match(host):
        logger.critical(
            "refusing to build a customer-facing link: BACKEND_BASE_URL=%r is a dev/tunnel "
            "address, not a real public domain, in a production environment",
            base_url,
        )
        raise UnsafePublicURLError(base_url)
    return base_url
