"""A minimal in-memory fixed-window rate limiter, generic (keyed by any
string) — originally built for login attempts (Phase 3), reused as-is for
Phase 21's public widget endpoint rather than writing a second
implementation.

Known limitation (documented, not hidden): this state lives in one process's
memory. It resets on restart and is NOT shared across multiple backend
replicas/workers — a horizontally scaled deployment would let an attacker get
MAX_ATTEMPTS tries per process instead of per deployment. Fine for a single
dev/foundation-phase instance; replace with a Redis-backed limiter before
running more than one backend process.
"""

import time
from collections import defaultdict

MAX_ATTEMPTS = 5
WINDOW_SECONDS = 60

# Phase 21: the widget endpoint is public internet-facing with no login wall
# at all, so it needs its own (more generous, since real chatting sends more
# than 5 messages/min, but still bounded) limits — two independent limiters,
# not one:
#   - per-IP: bounds how much any single source can spend of a business's
#     real LLM budget, and catches an attacker who never bothers persisting
#     a session token at all.
#   - per-session: bounds a single (even legitimate-looking) conversation
#     from being used to hammer the endpoint once a session exists, without
#     punishing every other visitor sharing the same IP (e.g. behind NAT/a
#     shared office network).
WIDGET_IP_MAX_ATTEMPTS = 20
WIDGET_SESSION_MAX_ATTEMPTS = 10
WIDGET_WINDOW_SECONDS = 60


class RateLimiter:
    def __init__(self, max_attempts: int = MAX_ATTEMPTS, window_seconds: int = WINDOW_SECONDS):
        self.max_attempts = max_attempts
        self.window_seconds = window_seconds
        self._attempts: dict[str, list[float]] = defaultdict(list)

    def _prune(self, key: str, now: float) -> None:
        cutoff = now - self.window_seconds
        self._attempts[key] = [t for t in self._attempts[key] if t > cutoff]

    def is_blocked(self, key: str) -> bool:
        now = time.monotonic()
        self._prune(key, now)
        return len(self._attempts[key]) >= self.max_attempts

    def record_attempt(self, key: str) -> None:
        now = time.monotonic()
        self._prune(key, now)
        self._attempts[key].append(now)


login_rate_limiter = RateLimiter()
widget_ip_rate_limiter = RateLimiter(max_attempts=WIDGET_IP_MAX_ATTEMPTS, window_seconds=WIDGET_WINDOW_SECONDS)
widget_session_rate_limiter = RateLimiter(
    max_attempts=WIDGET_SESSION_MAX_ATTEMPTS, window_seconds=WIDGET_WINDOW_SECONDS
)
