"""Groq ChatProvider -- Phase 39. Groq (api.groq.com) is a fast-inference
host for open-weight models (Llama, gpt-oss, Qwen, ...) -- a DIFFERENT
company/product from xAI's "Grok" (app/llm/xai.py) despite the near-identical
name; do not confuse the two USING_LLM values. Same OpenAI-compatible REST
shape as xAI, so retry/error discipline is shared via
app/llm/_openai_compatible.py.

Real model catalog confirmed via `GET {groq_endpoint}/models` against the
actual account (PHASE_STATUS.md Phase 39) -- groq_chat_model defaults to
"openai/gpt-oss-120b", a real, currently-active model on that account, not a
guess. Like xAI, Groq has no embeddings API as of this phase --
get_embedding_provider() stays on Azure regardless of USING_LLM."""

from app.core.config import settings
from app.llm._openai_compatible import post
from app.llm.base import ChatProvider


class GroqChatProvider(ChatProvider):
    def chat(self, messages: list[dict[str, str]]) -> str:
        data = post(
            provider="groq",
            base_url=settings.groq_endpoint,
            api_key=settings.groq_api_key,
            path="chat/completions",
            body={"messages": messages, "model": settings.groq_chat_model},
        )
        return data["choices"][0]["message"]["content"] or ""
