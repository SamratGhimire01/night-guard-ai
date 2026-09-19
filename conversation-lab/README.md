# conversation-lab  —  NON-PRODUCTION, EXPERIMENTAL

A sandbox for experimenting with DSPy-based prompt / few-shot optimization of Night Guard's
conversation style.

* **Not production.** Nothing here is imported by, deployed with, or served by `backend/` or `frontend/`.
* **Never touches real customer data.** It uses a fictional business (`lab/receptionist.py`), no database,
  no Postgres, no WhatsApp/email/booking code. Validation transcripts are verbatim from real work but have
  customer name/phone/email redacted to placeholders.
* **Own environment.** DSPy is installed only here (`requirements.txt`); it is NOT in `backend/requirements.txt`.
* **No production side effects.** It only calls the same Azure OpenAI gpt-5-mini deployment (costs tokens).

## Secrets
`lab/env.py` reads only `AZURE_OPENAI_API_KEY`, `AZURE_OPENAI_ENDPOINT`, `AZURE_OPENAI_DEPLOYMENT` **directly, read-only,
from `../backend/.env`** (already gitignored). Nothing is copied to a new file. Override with exported env vars or
`LAB_ENV_FILE=/path/to/other.env`. `.venv/` and `.env*` are covered by the repo-root `.gitignore`.

## Setup / run
```bash
cd conversation-lab
python3 -m venv .venv && .venv/bin/pip install -r requirements.txt
.venv/bin/python scripts/hello_world.py            # proves the real Azure connection
.venv/bin/python scripts/validate_judge.py         # proves the judge ranks real good/bad replies (~4 min, real API calls)
.venv/bin/python -m lab.webapp                     # chat UI at http://127.0.0.1:8765
```
This runs on the host (venv), not Docker, so the backend-container "force-recreate" rule does not apply here.

## Layout
| file | purpose |
|---|---|
| `lab/llm.py` | builds the DSPy LM for the real Azure AI Foundry deployment |
| `lab/rubric.py` | quality criteria from `intent.py` rules 3-7/13/16/17 + objective checks (reads backend's `spec_conformance_cases.py` by path, read-only) |
| `lab/judge.py` | LLM-as-judge → 0-100 score with per-criterion breakdown |
| `lab/validation_set.py` | CALIBRATION set: labeled real good/bad replies (+ 3 synthetic probes); the rubric was iterated on it |
| `lab/heldout_set.py` | SPENT held-out set (exposed the scope gap; now a dev set) |
| `lab/heldout_set_2.py` | fresh HELD-OUT set incl. scope cases (`validate_judge.py --set heldout_set_2 --threshold-from <calibration json>`) |
| `lab/businesses.py` | 3 fictional sandbox businesses (dental / salon / trek) rendered to facts text |
| `lab/receptionist.py` | UNOPTIMIZED, business-agnostic baseline DSPy program (what a later phase optimizes) |
| `lab/webapp.py` | local chat UI (business picker, judge x1 by default at low effort, per-reply x5 re-score) |
| `lab/production_prompt.py`, `lab/seed_set.py`, `lab/programs.py`, `scripts/optimize.py`, `scripts/eval_arms.py` | production-prompt baseline (read-only AST extract of backend intent.py), seed set, MIPROv2 run, held-out arm comparison |
| `lab/fidelity.py`, `lab/thanks_patch.py`, `scripts/thanks_experiment.py` | mechanical decline-wording check vs the real production sentence; in-memory what-if patches of the production template (intent.py is never modified) |
| `scripts/latency_bench.py`, `scripts/baseline_by_business.py` | latency measurements; same-baseline-across-businesses check |
| `results/` | saved output of the last judge validation |

## Known friction (details in LAB_STATUS.md)
* DSPy refuses gpt-5-* unless `temperature=1.0` and `max_tokens>=16000`.
* The Foundry resource needs LiteLLM's `azure_ai/` route with `api_base=<endpoint>/models`.
* The judge is noisy per-sample (~5 pts stdev, occasional outliers): use ≥5 samples and treat single-run
  differences under ~15 points as noise.
