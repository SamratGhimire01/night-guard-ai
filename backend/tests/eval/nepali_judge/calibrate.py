"""Measure judges against the gold set, and re-judge saved before/after replies with the trusted ones.

    python -m tests.eval.nepali_judge.calibrate gold --judges lint,claude,azure,groq/openai/gpt-oss-120b
    python -m tests.eval.nepali_judge.calibrate rejudge tests/eval/phase4_results_2026-09-29.json --judges lint,claude

`lint` is the deterministic layer alone (free, offline). Every LLM judge listed is ALSO paired with the lint caps in
the ensemble. Results are cached in --cache (default tests/eval/nepali_judge/cache.json) so a re-run only pays for
what's new.

A judge is TRUSTED when, on the gold set:
  - it picks the better reply on >= 90% of the pairs it is meant to judge (lint: only the pairs marked lint=True),
  - it gives the same answer in both orders on >= 85% of pairs (LLM judges; position bias otherwise),
  - and, once >= 10 native verdicts exist, its OK/not-OK call agrees with the native speaker at Cohen's kappa >= 0.6.
"""

import argparse
import hashlib
import json
import sys
from collections import defaultdict
from pathlib import Path

from tests.eval.nepali_judge import engine, gold
from tests.eval.nepali_judge import judges as judge_mod
from tests.eval.nepali_judge.lint import language_of

ACCURACY_BAR, CONSISTENCY_BAR, KAPPA_BAR, MIN_NATIVE = 0.90, 0.85, 0.60, 10
DEFAULT_CACHE = Path(__file__).with_name("cache.json")


def _good_is_a(pair_id: str) -> bool:
    """Deterministic but unbiased placement of the good reply (A half the time)."""
    return int(hashlib.sha256(pair_id.encode()).hexdigest(), 16) % 2 == 0


def cohen_kappa(a: list[bool], b: list[bool]) -> float | None:
    n = len(a)
    if n == 0:
        return None
    observed = sum(x == y for x, y in zip(a, b)) / n
    pa, pb = sum(a) / n, sum(b) / n
    expected = pa * pb + (1 - pa) * (1 - pb)
    return 1.0 if expected == 1 else round((observed - expected) / (1 - expected), 3)


class Cache:
    def __init__(self, path: Path | None):
        self.path, self.data = path, {}
        if path and path.exists():
            self.data = json.loads(path.read_text(encoding="utf-8"))

    def get(self, key):
        return self.data.get(key)

    def put(self, key, value):
        self.data[key] = value
        if self.path:
            self.path.write_text(json.dumps(self.data, ensure_ascii=False, indent=1), encoding="utf-8")


def _compare_cached(cache: Cache, judge_name: str, judge, a: str, b: str, customer: str, history=None) -> dict:
    key = "cmp|" + judge_name + "|" + hashlib.sha256(json.dumps([a, b, customer, history], ensure_ascii=False).encode()).hexdigest()
    hit = cache.get(key)
    if hit:
        return hit
    judges = {} if judge_name == "lint" else {judge_name: judge}
    c = engine.compare(a, b, customer, judges, history=history)
    result = {"verdict": c.verdict, "consistent": all(c.consistent.values()) if c.consistent else None, "errors": c.errors}
    if not c.errors:
        cache.put(key, result)
    return result


def _score_cached(cache: Cache, judge_name: str, judge, reply: str, customer: str) -> dict:
    key = "abs|" + judge_name + "|" + hashlib.sha256(json.dumps([reply, customer], ensure_ascii=False).encode()).hexdigest()
    hit = cache.get(key)
    if hit:
        return hit
    judges = {} if judge_name == "lint" else {judge_name: judge}
    s = engine.score(reply, customer, judges)
    result = {"overall": s.overall, "criteria": s.criteria, "errors": s.errors}
    if not s.errors:
        cache.put(key, result)
    return result


def evaluate_judge(judge_name: str, judge, cache: Cache, pairs: list[dict], native: list[dict]) -> dict:
    per_defect = defaultdict(lambda: [0, 0])  # defect -> [right, total]
    consistent = total_llm = errors = 0
    for p in pairs:
        if judge_name == "lint" and not p["lint"]:
            continue
        good_a = _good_is_a(p["id"])
        a, b = (p["good"], p["bad"]) if good_a else (p["bad"], p["good"])
        r = _compare_cached(cache, judge_name, judge, a, b, p["customer"], p.get("history"))
        if r["errors"]:
            errors += 1
            continue
        right = r["verdict"] == ("A" if good_a else "B")
        per_defect[p["defect"]][0] += right
        per_defect[p["defect"]][1] += 1
        if r["consistent"] is not None:
            total_llm += 1
            consistent += r["consistent"]
    right = sum(v[0] for v in per_defect.values())
    total = sum(v[1] for v in per_defect.values())
    accuracy = right / total if total else None
    consistency = consistent / total_llm if total_llm else None

    native_pred, native_true = [], []
    for e in native:
        s = _score_cached(cache, judge_name, judge, e["after"], e["customer"])
        if not s["errors"]:
            native_pred.append(s["overall"] >= 4.0)
            native_true.append(e["ok"])
    kappa = cohen_kappa(native_pred, native_true) if len(native_true) >= MIN_NATIVE else None

    trusted = (
        accuracy is not None and accuracy >= ACCURACY_BAR
        and (consistency is None or consistency >= CONSISTENCY_BAR)
        and (kappa is None or kappa >= KAPPA_BAR)
    )
    return {
        "judge": judge_name, "pairs": total, "accuracy": accuracy, "consistency": consistency,
        "native_n": len(native_true), "kappa": kappa, "errors": errors, "trusted": trusted,
        "per_defect": {d: {"right": v[0], "total": v[1]} for d, v in sorted(per_defect.items())},
    }


def _pct(x):
    return "—" if x is None else f"{x * 100:.0f}%"


def gold_report(results: list[dict]) -> str:
    lines = [
        "# Nepali judge calibration", "",
        f"Bars: accuracy ≥ {_pct(ACCURACY_BAR)}, same answer in both orders ≥ {_pct(CONSISTENCY_BAR)}, "
        f"native agreement κ ≥ {KAPPA_BAR} (once ≥ {MIN_NATIVE} native verdicts exist).", "",
        "| judge | pairs | picks the better reply | same answer both orders | native κ (n) | errors | trusted |",
        "|---|---|---|---|---|---|---|",
    ]
    for r in results:
        k = "—" if r["kappa"] is None else f"{r['kappa']:.2f}"
        lines.append(
            f"| {r['judge']} | {r['pairs']} | {_pct(r['accuracy'])} | {_pct(r['consistency'])} | {k} ({r['native_n']}) "
            f"| {r['errors']} | {'**yes**' if r['trusted'] else 'no'} |"
        )
    defects = sorted({d for r in results for d in r["per_defect"]})
    lines += ["", "## By defect (right / pairs)", "", "| defect | " + " | ".join(r["judge"] for r in results) + " |",
              "|---|" + "---|" * len(results)]
    for d in defects:
        cells = []
        for r in results:
            v = r["per_defect"].get(d)
            cells.append("—" if not v else f"{v['right']}/{v['total']}")
        lines.append(f"| {d} | " + " | ".join(cells) + " |")
    return "\n".join(lines) + "\n"


def run_gold(judge_names: list[str], cache: Cache) -> list[dict]:
    pairs = gold.PAIRS + gold.native_pairs()
    native = gold.native_labels()
    return [evaluate_judge(n, None if n == "lint" else judge_mod.get(n), cache, pairs, native) for n in judge_names]


def run_rejudge(path: Path, judge_names: list[str], cache: Cache) -> str:
    """Before vs after from a saved live_phase4_multijudge run, compared by the given judges (an ensemble)."""
    from tests.eval.phase4_cases import CASES

    messages = {c["id"]: c["message"] for c in CASES}
    gen = json.loads(path.read_text(encoding="utf-8"))["gen"]
    llm = {n: judge_mod.get(n) for n in judge_names if n != "lint"}
    tally = defaultdict(lambda: {"after": 0, "before": 0, "tie": 0})
    for key in sorted(gen):
        case_id, sample, arm = key.split("|")
        if arm != "after" or f"{case_id}|{sample}|before" not in gen or case_id not in messages:
            continue
        after, before = gen[key]["reply"], gen[f"{case_id}|{sample}|before"]["reply"]
        if not after or not before or after == before:
            continue
        cache_key = "rej|" + ",".join(judge_names) + "|" + hashlib.sha256(json.dumps([after, before, messages[case_id]], ensure_ascii=False).encode()).hexdigest()
        verdict = cache.get(cache_key)
        if verdict is None:
            c = engine.compare(after, before, messages[case_id], llm)
            verdict = c.verdict
            if not c.errors:
                cache.put(cache_key, verdict)
        outcome = {"A": "after", "B": "before"}.get(verdict, "tie")
        lang = language_of(messages[case_id])
        for bucket in ("all", lang):
            tally[bucket][outcome] += 1
    lines = [f"# Before vs after, re-judged by: {', '.join(judge_names)}", "", f"Source: `{path.name}` (only pairs whose replies differ)", "",
             "| slice | after better | before better | tie | after win rate (excl. ties) |", "|---|---|---|---|---|"]
    for bucket in ["all"] + sorted(b for b in tally if b != "all"):
        t = tally[bucket]
        decided = t["after"] + t["before"]
        lines.append(f"| {bucket} | {t['after']} | {t['before']} | {t['tie']} | {_pct(t['after'] / decided) if decided else '—'} |")
    return "\n".join(lines) + "\n"


def main(argv=None) -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("command", choices=["gold", "rejudge"])
    ap.add_argument("path", nargs="?", help="rejudge: a live_phase4_multijudge results JSON")
    ap.add_argument("--judges", default="lint", help="comma-separated: lint, claude, azure, groq/<model>")
    ap.add_argument("--cache", default=str(DEFAULT_CACHE), help="'' to disable")
    ap.add_argument("--out", help="also write the report (markdown) here")
    args = ap.parse_args(argv)
    names = [n.strip() for n in args.judges.split(",") if n.strip()]
    cache = Cache(Path(args.cache) if args.cache else None)
    if args.command == "gold":
        results = run_gold(names, cache)
        report = gold_report(results)
        Path(args.out or "/dev/null").write_text(report, encoding="utf-8") if args.out else None
        print(report)
        print(json.dumps(results, ensure_ascii=False, indent=1))
    else:
        if not args.path:
            sys.exit("rejudge needs the results JSON path")
        report = run_rejudge(Path(args.path), names, cache)
        if args.out:
            Path(args.out).write_text(report, encoding="utf-8")
        print(report)


if __name__ == "__main__":
    main()
