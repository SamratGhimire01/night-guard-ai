"""Phase 3 model bake-off: runs the regression harness against whichever ChatProvider
`USING_LLM` (+ provider-specific *_CHAT_MODEL / AZURE_OPENAI_DEPLOYMENT) selects, so a
candidate model is swapped purely via env vars passed to `docker exec -e ...` -- no code
change per candidate. Reuses test_regression_suite.py's real provisioning/teardown and
check functions (the SAME checks the live orchestrator's pre-send guard runs) rather than
reimplementing them, so a case passing here is a real guarantee, not a parallel check that
could drift.

Measurement only -- this never flips production's USING_LLM, it only reads it in this one
throwaway process (see CLAUDE.md: eval runners are fresh-per-invocation, never stale).

Usage (run inside the backend container so DB/app imports resolve):
    docker exec -e RUN_LIVE_REGRESSION=1 -e USING_LLM=azure night_guard_ai-backend-1 \
        python tests/eval/model_bakeoff.py --n-cases 90 --price-input 0.25 --price-output 2.00

    docker exec -e RUN_LIVE_REGRESSION=1 -e USING_LLM=groq -e GROQ_CHAT_MODEL=openai/gpt-oss-120b \
        night_guard_ai-backend-1 python tests/eval/model_bakeoff.py --n-cases 25 --pace 20 \  # seconds between cases
        --price-input 0.15 --price-output 0.60

Prices are $ per MILLION tokens -- pass real published rates for the candidate you're
running (this script doesn't hardcode any pricing table; stale/guessed rates are worse
than no rate at all). Omit both --price-* to skip cost estimation and only report
pass-rate/tokens/latency.
"""

import argparse
import json
import os
import random
import sys
import time
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

if not os.environ.get("RUN_LIVE_REGRESSION"):
    print("Refusing to run: set RUN_LIVE_REGRESSION=1 (real LLM cost per case, same gate as test_regression_suite.py).")
    sys.exit(1)

from app.core.config import settings  # noqa: E402
from tests.eval.regression_cases import load_all_cases  # noqa: E402
from tests.eval.test_regression_suite import (  # noqa: E402
    SessionLocal,
    _case_specific_failures,
    _create_customer_and_conversation,
    _generic_check_failures,
    _provision_business,
    _run_turns,
    _teardown_business,
)

_usage_log: list[dict] = []


def _tracked(original_fn, *, chat_path: str):
    """Wraps a provider's raw POST function to record real token usage/latency for
    chat/completions calls only -- embedding calls (always Azure, identical cost across
    every candidate here) are deliberately not tracked; they'd be a constant offset that
    cancels out in a cost COMPARISON, so tracking them would only add noise."""

    def wrapper(*args, **kwargs):
        # azure_openai._post(path, body) is called positionally; groq/xai's shared
        # post(..., path=..., body=...) is called entirely by keyword -- handle both.
        path = kwargs.get("path", args[0] if args else "")
        t0 = time.monotonic()
        data = original_fn(*args, **kwargs)
        dt = time.monotonic() - t0
        if path == chat_path:
            usage = data.get("usage") or {}
            _usage_log.append(
                {
                    "prompt_tokens": usage.get("prompt_tokens", 0),
                    "completion_tokens": usage.get("completion_tokens", 0),
                    "latency_s": dt,
                }
            )
        return data

    return wrapper


def _patch_target() -> str:
    using_llm = settings.using_llm.strip().lower()
    if using_llm in {"grok", "xai"}:
        return "app.llm.xai.post"
    if using_llm == "groq":
        return "app.llm.groq.post"
    return "app.llm.azure_openai._post"


def _candidate_label() -> str:
    using_llm = settings.using_llm.strip().lower()
    if using_llm in {"grok", "xai"}:
        return f"xai/{settings.xai_chat_model}"
    if using_llm == "groq":
        return f"groq/{settings.groq_chat_model}"
    return f"azure/{settings.azure_openai_deployment}"


def _select_cases(n_cases: int, seed: int) -> list[dict]:
    all_cases = load_all_cases()
    synthetic = [c for c in all_cases if c["source"] == "synthetic"]
    real = [c for c in all_cases if c["source"] == "real"]
    rng = random.Random(seed)
    if n_cases <= len(synthetic):
        return rng.sample(synthetic, n_cases)
    return synthetic + rng.sample(real, min(n_cases - len(synthetic), len(real)))


def run(n_cases: int, seed: int, pace: float, price_input: float | None, price_output: float | None, out_path: str) -> None:
    cases = _select_cases(n_cases, seed)
    label = _candidate_label()
    target = _patch_target()
    chat_path = "chat/completions"

    results = []
    t_start = time.monotonic()
    module_path, attr = target.rsplit(".", 1)
    import importlib

    mod = importlib.import_module(module_path)
    original = getattr(mod, attr)

    with patch(target, _tracked(original, chat_path=chat_path)):
        for i, case in enumerate(cases, 1):
            db = SessionLocal()
            business = None
            customer_id = None
            case_result = {"id": case["id"], "source": case["source"]}
            try:
                business = _provision_business(db, case["business"])
                customer_id, conversation_id = _create_customer_and_conversation(db, business)
                t0 = time.monotonic()
                replies = _run_turns(db, business, conversation_id, case["turns"])
                case_result["wall_s"] = round(time.monotonic() - t0, 2)

                failures: list[str] = []
                for reply in replies:
                    failures.extend(_generic_check_failures(reply, case["business"]))
                failures.extend(_case_specific_failures(db, business, replies, case["expect"]))

                case_result["pass"] = not failures
                case_result["failures"] = failures
                case_result["replies"] = replies
            except Exception as exc:  # noqa: BLE001 -- a provider outage on one case must not kill the whole run
                case_result["pass"] = False
                case_result["failures"] = [f"exception: {type(exc).__name__}: {exc}"]
            finally:
                if business is not None:
                    try:
                        _teardown_business(db, business, customer_id)
                    except Exception as exc:  # noqa: BLE001
                        print(f"  (teardown warning for {case['id']}: {exc})")
                db.close()

            results.append(case_result)
            status = "PASS" if case_result["pass"] else "FAIL"
            print(f"[{i}/{len(cases)}] {status}  {case['id']}")
            if pace:
                time.sleep(pace)

    total_wall_s = round(time.monotonic() - t_start, 1)
    n_pass = sum(1 for r in results if r["pass"])
    total_prompt = sum(u["prompt_tokens"] for u in _usage_log)
    total_completion = sum(u["completion_tokens"] for u in _usage_log)
    n_calls = len(_usage_log)
    avg_latency = round(sum(u["latency_s"] for u in _usage_log) / n_calls, 2) if n_calls else None

    cost_total = None
    cost_per_conversation = None
    if price_input is not None and price_output is not None:
        cost_total = round(total_prompt * price_input / 1_000_000 + total_completion * price_output / 1_000_000, 4)
        cost_per_conversation = round(cost_total / len(cases), 5) if cases else None

    summary = {
        "candidate": label,
        "n_cases": len(cases),
        "n_pass": n_pass,
        "pass_rate": round(n_pass / len(cases), 3) if cases else None,
        "n_llm_calls": n_calls,
        "total_prompt_tokens": total_prompt,
        "total_completion_tokens": total_completion,
        "avg_llm_latency_s": avg_latency,
        "total_wall_s": total_wall_s,
        "price_per_m_input": price_input,
        "price_per_m_output": price_output,
        "estimated_total_cost_usd": cost_total,
        "estimated_cost_per_conversation_usd": cost_per_conversation,
    }
    print(json.dumps(summary, indent=2))

    out = {"summary": summary, "cases": results}
    Path(out_path).parent.mkdir(parents=True, exist_ok=True)
    Path(out_path).write_text(json.dumps(out, indent=2))
    print(f"\nWrote full results to {out_path}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--n-cases", type=int, default=60)
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--pace", type=float, default=0.0, help="seconds to sleep after each case (rate-limit pacing)")
    parser.add_argument("--price-input", type=float, default=None, help="$ per million input tokens")
    parser.add_argument("--price-output", type=float, default=None, help="$ per million output tokens")
    parser.add_argument("--out", type=str, default=None)
    args = parser.parse_args()

    out_path = args.out or f"data/regression/bakeoff_results/{_candidate_label().replace('/', '_')}.json"
    run(args.n_cases, args.seed, args.pace, args.price_input, args.price_output, out_path)
