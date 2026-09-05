import json
import logging
import sys
from datetime import datetime, timezone

# The standard attributes every LogRecord carries regardless of what's logged —
# anything else on record.__dict__ came from a caller's logger.info(..., extra={...})
# and is a real, deliberately-structured field (Phase 31: LLM latency, webhook
# outcome counts, etc.) that must survive into the JSON output, not silently drop.
_STANDARD_LOG_RECORD_ATTRS = frozenset(vars(logging.LogRecord("", 0, "", 0, "", (), None))) | {"message", "asctime"}


class JSONFormatter(logging.Formatter):
    """Renders log records as single-line JSON for structured log aggregation.
    Any `extra={...}` fields a caller passes are included as top-level keys —
    real, queryable structured data (e.g. via `jq`), not just embedded in the
    message string."""

    def format(self, record: logging.LogRecord) -> str:
        payload = {
            "timestamp": datetime.fromtimestamp(record.created, tz=timezone.utc).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
        }
        for key, value in record.__dict__.items():
            if key not in _STANDARD_LOG_RECORD_ATTRS:
                payload[key] = value
        if record.exc_info:
            payload["exception"] = self.formatException(record.exc_info)
        return json.dumps(payload, default=str)


def configure_logging(log_level: str = "INFO") -> None:
    """Configures the root logger to emit structured JSON to stdout."""
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(JSONFormatter())

    root_logger = logging.getLogger()
    root_logger.handlers = [handler]
    root_logger.setLevel(log_level.upper())

    # httpx logs the full request URL (including query params) at INFO level —
    # for LLM provider calls that URL is our Azure endpoint. Silence it; no
    # secret value (the api-key is a header, never logged by httpx) but the
    # endpoint itself must not appear in logs either.
    logging.getLogger("httpx").setLevel(logging.WARNING)
