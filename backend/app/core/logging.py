import json
import logging
import sys
from datetime import datetime, timezone


class JSONFormatter(logging.Formatter):
    """Renders log records as single-line JSON for structured log aggregation."""

    def format(self, record: logging.LogRecord) -> str:
        payload = {
            "timestamp": datetime.fromtimestamp(record.created, tz=timezone.utc).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
        }
        if record.exc_info:
            payload["exception"] = self.formatException(record.exc_info)
        return json.dumps(payload)


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
