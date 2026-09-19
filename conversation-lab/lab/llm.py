"""One place that builds the DSPy LM for the real Azure AI Foundry gpt-5-mini
deployment (same resource/key the production backend uses, read via lab.env).

Real friction found (see README): DSPy refuses gpt-5-* unless
temperature=1.0 and max_tokens>=16000, and the Foundry resource needs
LiteLLM's `azure_ai/` route with api_base=<endpoint>/models -- not the classic
`azure/` route."""
import dspy

from lab.env import azure_settings


def build_lm(*, num_retries: int = 4, reasoning_effort: str | None = None) -> dspy.LM:
    """reasoning_effort: None = deployment default (medium); 'low' / 'minimal' = faster, less thinking."""
    s = azure_settings()
    extra = {"reasoning_effort": reasoning_effort} if reasoning_effort else {}
    return dspy.LM(
        f"azure_ai/{s['AZURE_OPENAI_DEPLOYMENT']}",
        api_key=s["AZURE_OPENAI_API_KEY"],
        api_base=s["AZURE_OPENAI_ENDPOINT"] + "/models",
        temperature=1.0,
        max_tokens=16000,
        num_retries=num_retries,
        cache=False,  # experiments must never silently reuse a cached completion
        **extra,
    )


def configure() -> dspy.LM:
    lm = build_lm()
    dspy.configure(lm=lm)
    return lm
