"""Reads ONLY the three Azure values the lab needs, directly from the
production backend's own gitignored .env (read-only). Nothing is copied to a
new file. Override the path with LAB_ENV_FILE, or just export the variables."""
import os
from pathlib import Path

_DEFAULT = Path(__file__).resolve().parents[2] / "backend" / ".env"
_KEYS = ("AZURE_OPENAI_API_KEY", "AZURE_OPENAI_ENDPOINT", "AZURE_OPENAI_DEPLOYMENT")


def azure_settings() -> dict[str, str]:
    values = {k: os.environ[k] for k in _KEYS if os.environ.get(k)}
    path = Path(os.environ.get("LAB_ENV_FILE", _DEFAULT))
    if len(values) < len(_KEYS) and path.exists():
        for line in path.read_text().splitlines():
            key, sep, val = line.partition("=")
            if sep and key.strip() in _KEYS and key.strip() not in values:
                values[key.strip()] = val.strip().strip("'\"")
    missing = [k for k in _KEYS if not values.get(k)]
    if missing:
        raise RuntimeError(f"Missing {missing}; set them or LAB_ENV_FILE (looked in {path}).")
    return values
