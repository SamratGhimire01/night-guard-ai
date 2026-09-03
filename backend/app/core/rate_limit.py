"""A minimal in-memory rate limiter for login attempts.

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


class LoginRateLimiter:
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


login_rate_limiter = LoginRateLimiter()
