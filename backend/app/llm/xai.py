"""xAI (Grok) ChatProvider -- Phase 39. Grok's REST API is OpenAI-compatible
(a real, documented xAI design choice, not this codebase's assumption):
POST {endpoint}/chat/completions with {"model", "messages"} and a bearer
token. Retry/error discipline lives in app/llm/_openai_compatible.py, shared
with app/llm/groq.py -- both providers expose the identical shape.

xAI has no embeddings API as of this phase (confirmed: no documented
`/v1/embeddings` endpoint) -- get_embedding_provider() in
app/llm/__init__.py stays on Azure regardless of USING_LLM, so chat and
embeddings are independently configured rather than forced to match."""

from app.core.config import settings
from app.llm._openai_compatible import post
from app.llm.base import ChatProvider


class GrokChatProvider(ChatProvider):
    def chat(self, messages: list[dict[str, str]]) -> str:
        data = post(
            provider="xai",
            base_url=settings.xai_endpoint,
            api_key=settings.xai_api_key,
            path="chat/completions",
            body={"messages": messages, "model": settings.xai_chat_model},
        )
        return data["choices"][0]["message"]["content"] or ""
