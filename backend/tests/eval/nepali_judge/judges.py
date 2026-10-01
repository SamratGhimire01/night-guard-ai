"""LLM judges, each a function messages -> raw text. Mix model families: a judge tends to prefer replies from its own
family, and the bot itself runs on Azure gpt-5-mini, so an ensemble with Claude and an open model is less biased.

    claude              Anthropic claude-opus-5-5 (pip install anthropic; ANTHROPIC_API_KEY)
    azure               the app's own Azure deployment (AZURE_OPENAI_*), same family as the bot -- keep it, but never alone
    groq/<model>        any Groq-hosted model (GROQ_API_KEY), e.g. groq/openai/gpt-oss-120b, groq/qwen/qwen3.8-27b
"""

import os
import time
from collections.abc import Callable

import httpx

Judge = Callable[[list[dict]], str]

CLAUDE_MODEL = "claude-opus-5-5"


def claude(messages: list[dict]) -> str:
    import anthropic  # eval-only dependency: imported here so the app never needs it

    client = anthropic.Anthropic(max_retries=6)
    system = "\n\n".join(m["content"] for m in messages if m["role"] == "system")
    turns = [m for m in messages if m["role"] != "system"]
    response = client.beta.messages.create(
        model=CLAUDE_MODEL,
        max_tokens=16000,
        system=system,
        messages=turns,
        output_config={"effort": "medium"},
        # A judge reading customer chats can trip a safety classifier on a rude or medical message; "default"
        # fallbacks re-run such a request on a fallback model instead of returning nothing.
        betas=["server-side-fallback-2026-07-01"],
        fallbacks="default",
    )
    if response.stop_reason == "refusal":
        raise RuntimeError(f"claude judge refused: {response.stop_details}")
    return "".join(block.text for block in response.content if block.type == "text")


def azure(messages: list[dict]) -> str:
    from app.llm.azure_openai import AzureChatProvider

    for attempt in range(6):
        try:
            return AzureChatProvider().chat(messages)
        except RuntimeError:  # 429 / transient; the provider already retried transport errors itself
            time.sleep(15 * (attempt + 1))
    raise RuntimeError("azure judge: retries exhausted")


def groq(model: str) -> Judge:
    def call(messages: list[dict]) -> str:
        for attempt in range(10):
            try:
                r = httpx.post(
                    "https://api.groq.com/openai/v1/chat/completions",
                    headers={"Authorization": f"Bearer {os.environ['GROQ_API_KEY']}"},
                    json={"model": model, "messages": messages, "temperature": 0},
                    timeout=120,
                )
            except httpx.TransportError:
                time.sleep(10)
                continue
            if r.status_code == 200:
                return r.json()["choices"][0]["message"]["content"] or ""
            if r.status_code in (429, 500, 502, 503, 504):
                time.sleep(min(float(r.headers.get("retry-after", 0) or 0) + 2 + attempt * 3, 120))
                continue
            raise RuntimeError(f"groq {model} HTTP {r.status_code}: {r.text[:200]}")
        raise RuntimeError(f"groq {model}: retries exhausted")

    return call


def get(name: str) -> Judge:
    if name == "claude":
        return claude
    if name == "azure":
        return azure
    if name.startswith("groq/"):
        return groq(name.removeprefix("groq/"))
    raise ValueError(f"unknown judge {name!r} (claude, azure, groq/<model>)")
