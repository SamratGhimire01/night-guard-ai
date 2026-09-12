"""Shared retry/error-classification logic for OpenAI-compatible chat REST
APIs (xAI/Grok, Groq -- Phase 39). Both providers expose the identical
`POST {base_url}/chat/completions` shape with bearer auth, differing only in
endpoint/key/model -- this is the one place that logic lives, rather than
duplicating app/llm/azure_openai.py's retry loop a second and third time.

Same transient-vs-permanent discipline as azure_openai.py (Phase 6/25c): a
network-level failure (DNS, connect, timeout) or a 429/5xx is retried a
bounded number of times; any other status (400/401/403/404) raises
immediately, never masked. No raw exception (which could embed the base URL)
ever escapes -- same leak discipline as Phase 9's Azure fix."""

import logging
import time

import httpx

logger = logging.getLogger(__name__)

MAX_ATTEMPTS = 4
RETRY_DELAY_SECONDS = 3
RETRYABLE_STATUSES = {429, 500, 502, 503, 504}


def post(*, provider: str, base_url: str, api_key: str, path: str, body: dict) -> dict:
    url = f"{base_url}/{path}"
    last_response = None
    last_transport_error: httpx.TransportError | None = None
    start = time.monotonic()
    for attempt in range(MAX_ATTEMPTS):
        try:
            response = httpx.post(
                url,
                headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
                json=body,
                timeout=30,
            )
        except httpx.TransportError as exc:
            last_response, last_transport_error = None, exc
            if attempt < MAX_ATTEMPTS - 1:
                time.sleep(RETRY_DELAY_SECONDS)
                continue
            break
        if response.status_code == 200:
            logger.info(
                "llm provider call succeeded",
                extra={
                    "llm_provider": provider,
                    "llm_path": path,
                    "llm_outcome": "success",
                    "llm_attempts": attempt + 1,
                    "llm_duration_ms": round((time.monotonic() - start) * 1000, 1),
                },
            )
            return response.json()
        last_response, last_transport_error = response, None
        if response.status_code in RETRYABLE_STATUSES and attempt < MAX_ATTEMPTS - 1:
            time.sleep(RETRY_DELAY_SECONDS)
            continue
        break
    outcome = (
        "transient_retry_exhausted"
        if (last_response is None or last_response.status_code in RETRYABLE_STATUSES)
        else "permanent_failure"
    )
    logger.warning(
        "llm provider call failed",
        extra={
            "llm_provider": provider,
            "llm_path": path,
            "llm_outcome": outcome,
            "llm_attempts": attempt + 1,
            "llm_duration_ms": round((time.monotonic() - start) * 1000, 1),
        },
    )
    # Never httpx's raise_for_status() (embeds the full request URL) and
    # never str(last_transport_error) (can also embed it) -- only the
    # exception's class name/status code, same discipline as azure_openai.py.
    if last_response is None:
        raise RuntimeError(f"LLM provider request failed: {type(last_transport_error).__name__}") from None
    raise RuntimeError(f"LLM provider request failed with HTTP {last_response.status_code}") from None
