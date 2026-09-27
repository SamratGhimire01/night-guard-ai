"""Loads the regression dataset (backend/data/regression/{real_conversations,synthetic_conversations}/*.json)
into one flat list of cases for test_regression_suite.py.

Real cases get their `expect` block synthesized from the human/LLM-verified failure log
(backend/data/regression/failure_log_batches/*.json, produced by the read-through pass —
see PHASE_STATUS.md): a confirmed failure becomes a regression guard against that exact
recurrence; a clean conversation gets no case-specific expectation, only the generic
invariants test_regression_suite.py applies to every case. Synthetic cases carry their own
authored `expect` block (see backend/scripts/generate_synthetic_cases.py) since we know the
intended behavior up front.
"""

import json
from pathlib import Path

DATA_DIR = Path(__file__).resolve().parent.parent.parent / "data" / "regression"
REAL_DIR = DATA_DIR / "real_conversations"
SYNTHETIC_DIR = DATA_DIR / "synthetic_conversations"
FAILURE_LOG_DIR = DATA_DIR / "failure_log_batches"

# Findings in this category mean "should have escalated and didn't" -- the regression guard
# is positive (assert it DOES escalate now), not a substring-absence check like every other
# category (which is "don't repeat this exact wrong claim").
ESCALATION_CATEGORIES = {"missed_escalation"}

# Too short/generic to safely assert "never appears again" without risking false failures
# on unrelated, correct replies that happen to share a common word.
_MIN_EVIDENCE_LEN = 12


def _load_failure_log() -> dict[str, dict]:
    by_conversation: dict[str, dict] = {}
    if not FAILURE_LOG_DIR.exists():
        return by_conversation
    for f in FAILURE_LOG_DIR.glob("*.json"):
        for rec in json.loads(f.read_text()):
            by_conversation[rec["conversation_id"]] = rec
    return by_conversation


def _expect_from_failure_record(rec: dict | None) -> dict:
    if rec is None or rec.get("verdict") != "fail":
        return {}
    expect: dict = {}
    not_contains: list[str] = []
    for finding in rec.get("findings", []):
        category = finding.get("category", "other")
        evidence = (finding.get("evidence") or "").strip()
        if category in ESCALATION_CATEGORIES:
            expect["expect_escalation"] = True
        elif len(evidence) >= _MIN_EVIDENCE_LEN:
            not_contains.append(evidence)
    if not_contains:
        expect["expect_reply_not_contains"] = not_contains
    return expect


def load_real_cases() -> list[dict]:
    failure_log = _load_failure_log()
    cases = []
    if not REAL_DIR.exists():
        return cases
    for f in sorted(REAL_DIR.glob("*.json")):
        rec = json.loads(f.read_text())
        if not rec["messages"]:
            continue  # nothing to replay
        turns = [m["content"] for m in rec["messages"] if m["sender_type"] == "customer"]
        if not turns:
            continue  # agent-only/staff-only conversation, no customer input to replay
        failure_rec = failure_log.get(rec["conversation_id"])
        cases.append(
            {
                "id": f"real-{rec['conversation_id']}",
                "source": "real",
                "business": rec["business"],
                "turns": turns,
                "expect": _expect_from_failure_record(failure_rec),
                "verdict_from_read_through": (failure_rec or {}).get("verdict", "unread"),
            }
        )
    return cases


def load_synthetic_cases() -> list[dict]:
    cases = []
    if not SYNTHETIC_DIR.exists():
        return cases
    for f in sorted(SYNTHETIC_DIR.glob("*.json")):
        rec = json.loads(f.read_text())
        cases.append(
            {
                "id": f"syn-{rec['id']}",
                "source": "synthetic",
                "business": rec["business"],
                "turns": rec["turns"],
                "expect": rec["expect"],
                "verdict_from_read_through": "n/a",
            }
        )
    return cases


def load_all_cases() -> list[dict]:
    return load_real_cases() + load_synthetic_cases()
