import logging
import time

import httpx

from app.core.config import settings
from app.llm.base import ChatProvider, EmbeddingProvider, LLMProviderError

logger = logging.getLogger(__name__)

# This resource is an Azure AI Foundry endpoint (*.services.ai.azure.com), which
# uses the unified "/models/..." inference API — a different URL shape than a
# classic Azure OpenAI resource's "/openai/deployments/{name}/..." path. Confirmed
# by direct testing against the real resource (see PHASE_STATUS.md Phase 6).
_MAX_ATTEMPTS = 4
_RETRY_DELAY_SECONDS = 3


def _post(path: str, body: dict) -> dict:
    """POSTs to the Foundry inference API with retry on the transient
    DeploymentNotFound 404 this resource intermittently returns for a
    confirmed-live deployment (observed ~50% failure rate — an Azure-side
    propagation issue, not a real missing deployment). Any other error status
    raises immediately, not retried.

    Urgent fix (real 500 found live, PHASE_STATUS.md): `httpx.post` itself can
    raise before any HTTP response exists at all — a real, live-captured
    `httpx.ConnectError: [Errno -2] Name or service not known` (a transient
    DNS resolution failure reaching this same Azure endpoint) propagated
    straight past this function's old response-status-only retry loop as an
    unhandled exception, producing a raw 500. Resending the identical request
    moments later succeeded — a genuine transient network blip, not a bug in
    what was sent. `httpx.TransportError` (base class of ConnectError and the
    various timeout/network exceptions) is now retried with the exact same
    budget as the 404 case, since a later attempt is what actually resolved
    it in the live-verified failure."""
    url = f"{settings.azure_openai_endpoint}/models/{path}"
    last_response = None
    last_transport_error: httpx.TransportError | None = None
    start = time.monotonic()
    for attempt in range(_MAX_ATTEMPTS):
        try:
            response = httpx.post(
                url,
                params={"api-version": settings.azure_openai_api_version},
                headers={"api-key": settings.azure_openai_api_key, "Content-Type": "application/json"},
                json=body,
                timeout=30,
            )
        except httpx.TransportError as exc:
            last_response, last_transport_error = None, exc
            if attempt < _MAX_ATTEMPTS - 1:
                time.sleep(_RETRY_DELAY_SECONDS)
                continue
            break
        if response.status_code == 200:
            # Phase 31: real latency + outcome per LLM call, structured (see
            # app.core.logging.JSONFormatter) so it's genuinely queryable —
            # never logs the request/response body (could contain business
            # data) or the endpoint URL, only timing/outcome metadata.
            logger.info(
                "llm provider call succeeded",
                extra={
                    "llm_path": path,
                    "llm_outcome": "success",
                    "llm_attempts": attempt + 1,
                    "llm_duration_ms": round((time.monotonic() - start) * 1000, 1),
                },
            )
            return response.json()
        last_response, last_transport_error = response, None
        if response.status_code == 404 and attempt < _MAX_ATTEMPTS - 1:
            time.sleep(_RETRY_DELAY_SECONDS)
            continue
        break
    # A transport error (network/DNS) or a repeated 404 is "transient" — Azure-
    # side, resolved by retrying, and the retry budget was genuinely exhausted.
    # Any other non-200 status (401, 400, ...) broke out on its FIRST attempt,
    # never retried — that's a real, permanent failure (bad request/auth/etc.),
    # not an outage. This is the exact transient-vs-permanent split Phase 6/25c
    # already reasoned about for retry behavior; now it's also what the metrics
    # outcome field reports.
    outcome = "transient_retry_exhausted" if (last_response is None or last_response.status_code == 404) else "permanent_failure"
    logger.warning(
        "llm provider call failed",
        extra={
            "llm_path": path,
            "llm_outcome": outcome,
            "llm_attempts": attempt + 1,
            "llm_duration_ms": round((time.monotonic() - start) * 1000, 1),
        },
    )
    # Deliberately not httpx's raise_for_status(): its exception message embeds
    # the full request URL (our Azure endpoint), which would then propagate into
    # any logger.exception() call an unhandled-error handler makes upstream —
    # `from None` drops the chained httpx exception (and its URL) entirely, real
    # leak found and fixed during Phase 9's own acceptance testing. Same
    # discipline applies to `last_transport_error`: its class name only
    # (e.g. "ConnectError"), never `str(exc)`, which can itself embed the URL.
    if last_response is None:
        raise LLMProviderError(
            f"LLM provider request failed: {type(last_transport_error).__name__}"
        ) from None
    raise LLMProviderError(f"LLM provider request failed with HTTP {last_response.status_code}") from None


class AzureEmbeddingProvider(EmbeddingProvider):
    def embed(self, texts: list[str]) -> list[list[float]]:
        data = _post("embeddings", {"input": texts, "model": settings.azure_openai_embedding_deployment})
        return [item["embedding"] for item in data["data"]]


class AzureChatProvider(ChatProvider):
    def chat(self, messages: list[dict[str, str]]) -> str:
        body = {"messages": messages, "model": settings.azure_openai_deployment}
        effort = settings.azure_openai_reasoning_effort.strip().lower()
        if effort and effort != "default":
            body["reasoning_effort"] = effort
        data = _post("chat/completions", body)
        return data["choices"][0]["message"]["content"] or ""
