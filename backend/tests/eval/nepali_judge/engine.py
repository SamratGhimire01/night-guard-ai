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


# --- Checklist + hybrid ----------------------------------------------------------------------------------------------


@dataclass
class Checklist:
    answers: dict[str, float]  # question -> share of judges that said yes (good)
    score: float  # mean over questions, 0..1
    raw: dict[str, dict[str, bool]]  # judge -> its answers
    errors: dict[str, str] = field(default_factory=dict)


def checklist(reply: str, customer: str, judges: dict, *, history=None, locked_language=None, cache=None) -> Checklist:
    """Every judge answers the yes/no checklist about this ONE reply. `cache`: optional get/put object keyed per
    (judge, reply, context), so the same reply is never paid for twice across comparisons and runs."""
    messages = rubric.checklist_messages(reply, customer, history, locked_language)
    raw, errors = {}, {}
    for name, judge in judges.items():
        key = None
        if cache is not None:
            key = "chk|" + name + "|" + _digest(reply, customer, history, locked_language)
            hit = cache.get(key)
            if hit:
                raw[name] = hit
                continue
        try:
            raw[name] = _ask(judge, messages, rubric.parse_checklist)
        except Exception as exc:  # noqa: BLE001
            errors[name] = f"{type(exc).__name__}: {exc}"[:300]
            continue
        if cache is not None:
            cache.put(key, raw[name])
    if not raw:
        return Checklist({}, 0.0, raw, errors)
    answers = {q: sum(r[q] for r in raw.values()) / len(raw) for q in rubric.CHECKLIST}
    return Checklist(answers, sum(answers.values()) / len(answers), raw, errors)  # unrounded: one question = 1/9 exactly


def _digest(*parts) -> str:
    import hashlib
    import json

    return hashlib.sha256(json.dumps(parts, ensure_ascii=False, default=str).encode()).hexdigest()


def _lint_weight(findings) -> int:
    return sum(6 - f.cap for f in findings)


@dataclass
class HybridComparison:
    verdict: str  # "A" | "B" | "tie"
    decided_by: str  # "lint" | "checklist" | "none"
    lint_a: list[lint_mod.Finding]
    lint_b: list[lint_mod.Finding]
    check_a: Checklist | None
    check_b: Checklist | None


def hybrid_compare(reply_a, reply_b, customer, judges: dict, *, history=None, locked_language=None, cache=None) -> HybridComparison:
    """Language first, by rule: if one reply has heavier hard defects (Hindi, textbook words, script, spelling,
    repeats...) the other wins -- the lint is exact there and the LLMs measurably are not. Otherwise each reply gets
    the yes/no checklist on its own (no A/B order to be biased by); a difference of at least one question decides."""
    lint_a = lint_mod.lint(reply_a, customer, history, locked_language=locked_language)
    lint_b = lint_mod.lint(reply_b, customer, history, locked_language=locked_language)
    wa, wb = _lint_weight(lint_a), _lint_weight(lint_b)
    if wa != wb:
        return HybridComparison("A" if wa < wb else "B", "lint", lint_a, lint_b, None, None)
    if not judges:
        return HybridComparison("tie", "none", lint_a, lint_b, None, None)
    ca = checklist(reply_a, customer, judges, history=history, locked_language=locked_language, cache=cache)
    cb = checklist(reply_b, customer, judges, history=history, locked_language=locked_language, cache=cache)
    if not ca.raw or not cb.raw:
        return HybridComparison("tie", "none", lint_a, lint_b, ca, cb)
    margin = 1 / len(rubric.CHECKLIST) - 1e-9  # one question's worth
    if ca.score - cb.score >= margin:
        return HybridComparison("A", "checklist", lint_a, lint_b, ca, cb)
    if cb.score - ca.score >= margin:
        return HybridComparison("B", "checklist", lint_a, lint_b, ca, cb)
    return HybridComparison("tie", "checklist", lint_a, lint_b, ca, cb)
