"""Scoring and comparison over an ensemble of LLM judges plus the deterministic lint.

score():   every judge scores the five criteria; per criterion the ensemble takes the median (robust to one odd judge),
           then lint caps apply. overall = weighted mean of the capped criteria.
compare(): every judge compares A vs B twice, in both orders. A verdict that flips with the order is position bias,
           so it counts as a tie. The ensemble verdict is the majority of the non-tie votes.

Judges are any callables messages -> str (judges.py), so tests pass fakes and no network is needed."""

import statistics
from collections import Counter
from dataclasses import dataclass, field

from tests.eval.nepali_judge import lint as lint_mod
from tests.eval.nepali_judge import rubric

_RETRIES = 3  # malformed JSON / out-of-range score: ask the same judge again


@dataclass
class Score:
    criteria: dict[str, float]  # final, after lint caps
    overall: float
    raw: dict[str, dict[str, int]]  # judge -> its own criterion scores
    findings: list[lint_mod.Finding]
    problems: dict[str, list[str]] = field(default_factory=dict)  # judge -> quoted problems
    errors: dict[str, str] = field(default_factory=dict)  # judge -> why it gave nothing usable


@dataclass
class Comparison:
    verdict: str  # "A" | "B" | "tie"
    votes: dict[str, str]  # judge -> "A" | "B" | "tie" (after the both-orders check)
    consistent: dict[str, bool]  # judge -> same answer in both orders
    criteria: dict[str, str]  # criterion -> ensemble winner
    lint_a: list[lint_mod.Finding]
    lint_b: list[lint_mod.Finding]
    errors: dict[str, str] = field(default_factory=dict)


def _ask(judge, messages, parse):
    last = None
    for _ in range(_RETRIES):
        try:
            return parse(judge(messages))
        except rubric.BadJudgeOutput as exc:
            last = exc
    raise rubric.BadJudgeOutput(f"no usable answer after {_RETRIES} tries: {last}")


def overall_of(criteria: dict[str, float]) -> float:
    return round(sum(rubric.WEIGHTS[c] * criteria[c] for c in rubric.WEIGHTS), 2)


def score(reply: str, customer: str, judges: dict, *, history=None, locked_language=None) -> Score:
    findings = lint_mod.lint(reply, customer, history, locked_language=locked_language)
    caps = lint_mod.caps(findings)
    raw, problems, errors = {}, {}, {}
    messages = rubric.absolute_messages(reply, customer, history, locked_language)
    for name, judge in judges.items():
        try:
            result = _ask(judge, messages, rubric.parse_absolute)
        except Exception as exc:  # noqa: BLE001 -- one broken judge must not sink the ensemble
            errors[name] = f"{type(exc).__name__}: {exc}"[:300]
            continue
        raw[name], problems[name] = result["scores"], result["problems"]
    if raw:
        criteria = {c: float(statistics.median(r[c] for r in raw.values())) for c in lint_mod.CRITERIA}
    else:  # lint only: start from the top and let the findings pull it down
        criteria = {c: 5.0 for c in lint_mod.CRITERIA}
    criteria = {c: min(v, caps[c]) for c, v in criteria.items()}
    return Score(criteria, overall_of(criteria), raw, findings, problems, errors)


def _flip(v: str) -> str:
    return {"A": "B", "B": "A"}.get(v, "tie")


def compare(reply_a: str, reply_b: str, customer: str, judges: dict, *, history=None, locked_language=None) -> Comparison:
    lint_a = lint_mod.lint(reply_a, customer, history, locked_language=locked_language)
    lint_b = lint_mod.lint(reply_b, customer, history, locked_language=locked_language)
    votes, consistent, errors = {}, {}, {}
    per_criterion: dict[str, Counter] = {c: Counter() for c in lint_mod.CRITERIA}
    forward = rubric.pairwise_messages(reply_a, reply_b, customer, history, locked_language)
    backward = rubric.pairwise_messages(reply_b, reply_a, customer, history, locked_language)
    for name, judge in judges.items():
        try:
            first = _ask(judge, forward, rubric.parse_pairwise)
            second = _ask(judge, backward, rubric.parse_pairwise)
        except Exception as exc:  # noqa: BLE001
            errors[name] = f"{type(exc).__name__}: {exc}"[:300]
            continue
        second_overall = _flip(second["overall"])  # back into A/B of the original order
        consistent[name] = first["overall"] == second_overall
        votes[name] = first["overall"] if consistent[name] else "tie"
        for c in lint_mod.CRITERIA:
            a, b = first["winner"][c], _flip(second["winner"][c])
            per_criterion[c][a if a == b else "tie"] += 1

    tally = Counter(v for v in votes.values() if v != "tie")
    if not votes and (lint_a or lint_b):
        # No LLM judges: the reply with fewer/lighter hard defects wins; equal -> tie.
        weight = lambda fs: sum(6 - f.cap for f in fs)  # noqa: E731
        verdict = "A" if weight(lint_a) < weight(lint_b) else "B" if weight(lint_b) < weight(lint_a) else "tie"
    elif tally["A"] > tally["B"]:
        verdict = "A"
    elif tally["B"] > tally["A"]:
        verdict = "B"
    else:
        verdict = "tie"
    criteria = {}
    for c, counts in per_criterion.items():
        criteria[c] = "A" if counts["A"] > counts["B"] else "B" if counts["B"] > counts["A"] else "tie"
    return Comparison(verdict, votes, consistent, criteria, lint_a, lint_b, errors)
