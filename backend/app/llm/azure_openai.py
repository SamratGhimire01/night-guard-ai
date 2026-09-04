import time

import httpx

from app.core.config import settings
from app.llm.base import ChatProvider, EmbeddingProvider

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
    raises immediately, not retried."""
    url = f"{settings.azure_openai_endpoint}/models/{path}"
    last_response = None
    for attempt in range(_MAX_ATTEMPTS):
        response = httpx.post(
            url,
            params={"api-version": settings.azure_openai_api_version},
            headers={"api-key": settings.azure_openai_api_key, "Content-Type": "application/json"},
            json=body,
            timeout=30,
        )
        if response.status_code == 200:
            return response.json()
        last_response = response
        if response.status_code == 404 and attempt < _MAX_ATTEMPTS - 1:
            time.sleep(_RETRY_DELAY_SECONDS)
            continue
        break
    # Deliberately not httpx's raise_for_status(): its exception message embeds
    # the full request URL (our Azure endpoint), which would then propagate into
    # any logger.exception() call an unhandled-error handler makes upstream —
    # `from None` drops the chained httpx exception (and its URL) entirely, real
    # leak found and fixed during Phase 9's own acceptance testing.
    raise RuntimeError(f"LLM provider request failed with HTTP {last_response.status_code}") from None


class AzureEmbeddingProvider(EmbeddingProvider):
    def embed(self, texts: list[str]) -> list[list[float]]:
        data = _post("embeddings", {"input": texts, "model": settings.azure_openai_embedding_deployment})
        return [item["embedding"] for item in data["data"]]


class AzureChatProvider(ChatProvider):
    def chat(self, messages: list[dict[str, str]]) -> str:
        data = _post(
            "chat/completions", {"messages": messages, "model": settings.azure_openai_deployment}
        )
        return data["choices"][0]["message"]["content"] or ""
