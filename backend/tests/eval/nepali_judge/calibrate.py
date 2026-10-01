"""Measure judges against the gold set, and re-judge saved before/after replies with the trusted ones.

    python -m tests.eval.nepali_judge.calibrate gold --judges lint,hybrid:gemini/gemini-3.5-flash+azure
    python -m tests.eval.nepali_judge.calibrate rejudge tests/eval/phase4_results_2026-09-29.json --judges hybrid:azure

Judge specs (comma-separated in --judges):
    lint                      the rule layer alone (free, offline)
    <llm>                     one LLM, holistic pairwise in both orders (the first design; kept for comparison)
    check:<llm>[+<llm>...]    the yes/no checklist alone, each reply checked on its own (no lint)
    hybrid:<llm>[+<llm>...]   lint decides language defects; otherwise the checklist ensemble decides  <- recommended
<llm> is claude | azure | groq/<model> | gemini/<model> (judges.py).

Results are cached in --cache (default tests/eval/nepali_judge/cache.json): a re-run, or a new spec reusing a judge
already run, only pays for what's new. Pairs are judged in parallel (--workers); each judge paces itself to its own
rate limit.

TRUSTED overall when, on the gold pairs it judges: >= 90% correct picks, >= 85% same answer in both orders (holistic
pairwise only -- the checklist has no order), and, once >= 10 native verdicts exist, Cohen's kappa >= 0.6 against the
native speaker. TRUSTED FOR a defect type when it got >= 90% of at least 2 pairs of that type: a judge that fails
overall can still be the right tool for, say, warmth.
"""

import argparse
import hashlib
import json
import sys
import threading
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from tests.eval.nepali_judge import engine, gold
from tests.eval.nepali_judge import judges as judge_mod
from tests.eval.nepali_judge.lint import language_of

ACCURACY_BAR, CONSISTENCY_BAR, KAPPA_BAR, MIN_NATIVE = 0.90, 0.85, 0.60, 10
# "OK" for the checklist = at most 3 of the 9 questions answered "no" (score >= 6/9). Picked on the first 30 native
# verdicts (2026-10-01): stricter cut-offs disagreed with the native speaker on short replies they rated GOOD
# (Gemini answers "sounds like a template" for 10 of 17 replies the native marked OK). Tuned on the same 30 replies it
# is measured on, so the kappa it reaches there is optimistic -- confirm on a fresh native batch.
MIN_PER_DEFECT, NATIVE_OK_CHECKLIST = 2, 6 / 9 - 1e-9
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
    """JSON file cache, safe to share between worker threads."""

    def __init__(self, path: Path | None):
        self.path, self.data, self._lock = path, {}, threading.Lock()
        if path and path.exists():
            self.data = json.loads(path.read_text(encoding="utf-8"))

    def get(self, key):
        with self._lock:
            return self.data.get(key)

    def put(self, key, value):
        with self._lock:
            self.data[key] = value
            if self.path:
                tmp = self.path.with_suffix(".tmp")
                tmp.write_text(json.dumps(self.data, ensure_ascii=False, indent=1), encoding="utf-8")
                tmp.replace(self.path)


def _key(*parts) -> str:
    return hashlib.sha256(json.dumps(parts, ensure_ascii=False, default=str).encode()).hexdigest()


# --- one comparison / one OK-call per spec ---------------------------------------------------------------------------


def parse_spec(spec: str) -> tuple[str, list[str]]:
    """("lint"|"pairwise"|"check"|"hybrid", [llm names])."""
    if spec == "lint":
        return "lint", []
    for mode in ("check", "hybrid"):
        if spec.startswith(mode + ":"):
            return mode, [n for n in spec.removeprefix(mode + ":").split("+") if n]
    return "pairwise", [spec]


def _compare(spec: str, judges: dict, cache: Cache, a: str, b: str, customer: str, history) -> dict:
    """{"verdict": "A"|"B"|"tie", "consistent": bool|None, "errors": {...}, "decided_by": str}."""
    mode, _ = parse_spec(spec)
    if mode == "pairwise":
        key = "cmp|" + spec + "|" + _key(a, b, customer, history)
        hit = cache.get(key)
        if hit:
            return hit
        c = engine.compare(a, b, customer, judges, history=history)
        result = {"verdict": c.verdict, "consistent": all(c.consistent.values()) if c.consistent else None,
                  "errors": c.errors, "decided_by": "pairwise"}
        if not c.errors:
            cache.put(key, result)
        return result
    if mode == "lint":
        h = engine.hybrid_compare(a, b, customer, {}, history=history)
        return {"verdict": h.verdict, "consistent": None, "errors": {}, "decided_by": h.decided_by}
    if mode == "check":
        ca = engine.checklist(a, customer, judges, history=history, cache=cache)
        cb = engine.checklist(b, customer, judges, history=history, cache=cache)
        errors = {**ca.errors, **cb.errors}
        margin = 1 / len(engine.rubric.CHECKLIST) - 1e-9
        verdict = "A" if ca.score - cb.score >= margin else "B" if cb.score - ca.score >= margin else "tie"
        return {"verdict": verdict if ca.raw and cb.raw else "tie", "consistent": None, "errors": errors,
                "decided_by": "checklist"}
    h = engine.hybrid_compare(a, b, customer, judges, history=history, cache=cache)
    errors = {**(h.check_a.errors if h.check_a else {}), **(h.check_b.errors if h.check_b else {})}
    return {"verdict": h.verdict, "consistent": None, "errors": errors, "decided_by": h.decided_by}


def _native_ok(spec: str, judges: dict, cache: Cache, reply: str, customer: str) -> bool | None:
    """Would this judge call the reply OK (what the native speaker marks "OK")? None = no usable answer."""
    mode, _ = parse_spec(spec)
    findings = engine.lint_mod.lint(reply, customer)
    if mode == "lint":
        return not findings
    if mode in ("check", "hybrid"):
        c = engine.checklist(reply, customer, judges, cache=cache)
        if not c.raw:
            return None
        ok = c.score >= NATIVE_OK_CHECKLIST
        return ok and not findings if mode == "hybrid" else ok
    key = "abs|" + spec + "|" + _key(reply, customer)
    hit = cache.get(key)
    if hit is None:
        s = engine.score(reply, customer, judges)
        if s.errors:
            return None
        hit = {"overall": s.overall}
        cache.put(key, hit)
    return hit["overall"] >= 4.0


# --- evaluation -------------------------------------------------------------------------------------------------------


def _judges_for(spec: str, judge=None) -> dict:
    mode, names = parse_spec(spec)
    if mode == "lint":
        return {}
    if judge is not None:  # tests pass a fake callable (or a ready dict for check/hybrid)
        return judge if isinstance(judge, dict) else {names[0]: judge}
    return {n: judge_mod.get(n) for n in names}


def evaluate_judge(spec: str, judge, cache: Cache, pairs: list[dict], native: list[dict], *, workers: int = 1) -> dict:
    mode, _ = parse_spec(spec)
    judges = _judges_for(spec, judge)
    todo = [p for p in pairs if mode != "lint" or p["lint"]]

    def one(p):
        good_a = _good_is_a(p["id"])
        a, b = (p["good"], p["bad"]) if good_a else (p["bad"], p["good"])
        return p, good_a, _compare(spec, judges, cache, a, b, p["customer"], p.get("history"))

    with ThreadPoolExecutor(max(1, workers)) as pool:
        results = list(pool.map(one, todo))

    per_defect = defaultdict(lambda: [0, 0])
    consistent = total_ordered = errors = 0
    decided_by = defaultdict(int)
    for p, good_a, r in results:
        if r["errors"]:
            errors += 1
            continue
        right = r["verdict"] == ("A" if good_a else "B")
        per_defect[p["defect"]][0] += right
        per_defect[p["defect"]][1] += 1
        decided_by[r["decided_by"]] += 1
        if r["consistent"] is not None:
            total_ordered += 1
            consistent += r["consistent"]
    right = sum(v[0] for v in per_defect.values())
    total = sum(v[1] for v in per_defect.values())
    accuracy = right / total if total else None
    consistency = consistent / total_ordered if total_ordered else None

    with ThreadPoolExecutor(max(1, workers)) as pool:
        calls = list(pool.map(lambda e: (_native_ok(spec, judges, cache, e["after"], e["customer"]), e["ok"]), native))
    pred = [p for p, _ in calls if p is not None]
    true = [t for p, t in calls if p is not None]
    kappa = cohen_kappa(pred, true) if len(true) >= MIN_NATIVE else None

    trusted = (
        accuracy is not None and accuracy >= ACCURACY_BAR
        and (consistency is None or consistency >= CONSISTENCY_BAR)
        and (kappa is None or kappa >= KAPPA_BAR)
    )
    trusted_for = sorted(d for d, (r_, t) in per_defect.items() if t >= MIN_PER_DEFECT and r_ / t >= ACCURACY_BAR)
    return {
        "judge": spec, "pairs": total, "accuracy": accuracy, "consistency": consistency, "native_n": len(true),
        "kappa": kappa, "errors": errors, "trusted": trusted, "trusted_for": trusted_for,
        "decided_by": dict(decided_by),
        "per_defect": {d: {"right": v[0], "total": v[1]} for d, v in sorted(per_defect.items())},
    }


def _pct(x):
    return "—" if x is None else f"{x * 100:.0f}%"


def gold_report(results: list[dict]) -> str:
    lines = [
        "# Nepali judge calibration", "",
        f"Bars: correct picks ≥ {_pct(ACCURACY_BAR)}; same answer in both orders ≥ {_pct(CONSISTENCY_BAR)} (holistic "
        f"pairwise only); native agreement κ ≥ {KAPPA_BAR} once ≥ {MIN_NATIVE} native verdicts exist. 'Trusted for' = "
        f"defect types with ≥ {_pct(ACCURACY_BAR)} on at least {MIN_PER_DEFECT} pairs.", "",
        "| judge | pairs | picks the better reply | same answer both orders | native κ (n) | errors | trusted |",
        "|---|---|---|---|---|---|---|",
    ]
    for r in results:
        k = "—" if r["kappa"] is None else f"{r['kappa']:.2f}"
        lines.append(
            f"| {r['judge']} | {r['pairs']} | {_pct(r['accuracy'])} | {_pct(r['consistency'])} | {k} ({r['native_n']}) "
            f"| {r['errors']} | {'**yes**' if r['trusted'] else 'no'} |"
        )
    lines += ["", "## Trusted for", ""]
    for r in results:
        lines.append(f"- **{r['judge']}**: {', '.join(r.get('trusted_for') or []) or 'nothing yet'}")
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


def run_gold(specs: list[str], cache: Cache, workers: int = 6) -> list[dict]:
    pairs = gold.PAIRS + gold.native_pairs()
    native = gold.native_labels()
    return [evaluate_judge(s, None, cache, pairs, native, workers=workers) for s in specs]


def run_rejudge(path: Path, specs: list[str], cache: Cache, workers: int = 6) -> str:
    """Before vs after from a saved live_phase4_multijudge run, per spec ('after better' = the change helped)."""
    from tests.eval.phase4_cases import CASES

    messages = {c["id"]: c["message"] for c in CASES}
    gen = json.loads(path.read_text(encoding="utf-8"))["gen"]
    pairs = []
    for key in sorted(gen):
        case_id, sample, arm = key.split("|")
        if arm != "after" or f"{case_id}|{sample}|before" not in gen or case_id not in messages:
            continue
        after, before = gen[key]["reply"], gen[f"{case_id}|{sample}|before"]["reply"]
        if after and before and after != before:
            pairs.append((messages[case_id], after, before))
    out = ["# Before vs after, re-judged", "", f"Source: `{path.name}` ({len(pairs)} pairs whose replies differ)", ""]
    for spec in specs:
        judges = _judges_for(spec)
        with ThreadPoolExecutor(max(1, workers)) as pool:
            verdicts = list(pool.map(lambda t: (t[0], _compare(spec, judges, cache, t[1], t[2], t[0], None)), pairs))
        tally = defaultdict(lambda: {"after": 0, "before": 0, "tie": 0})
        for customer, r in verdicts:
            outcome = {"A": "after", "B": "before"}.get(r["verdict"], "tie")
            for bucket in ("all", language_of(customer)):
                tally[bucket][outcome] += 1
        out += [f"## {spec}", "", "| slice | after better | before better | tie | after win rate (excl. ties) |",
                "|---|---|---|---|---|"]
        for bucket in ["all"] + sorted(b for b in tally if b != "all"):
            t = tally[bucket]
            decided = t["after"] + t["before"]
            out.append(f"| {bucket} | {t['after']} | {t['before']} | {t['tie']} | {_pct(t['after'] / decided) if decided else '—'} |")
        out.append("")
    return "\n".join(out)


def main(argv=None) -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("command", choices=["gold", "rejudge"])
    ap.add_argument("path", nargs="?", help="rejudge: a live_phase4_multijudge results JSON")
    ap.add_argument("--judges", default="lint", help="comma-separated specs, see above")
    ap.add_argument("--cache", default=str(DEFAULT_CACHE), help="'' to disable")
    ap.add_argument("--workers", type=int, default=6, help="pairs judged in parallel")
    ap.add_argument("--out", help="also write the report (markdown) here")
    args = ap.parse_args(argv)
    specs = [n.strip() for n in args.judges.split(",") if n.strip()]
    cache = Cache(Path(args.cache) if args.cache else None)
    if args.command == "gold":
        results = run_gold(specs, cache, args.workers)
        report = gold_report(results)
        print(report)
        print(json.dumps(results, ensure_ascii=False, indent=1))
    else:
        if not args.path:
            sys.exit("rejudge needs the results JSON path")
        report = run_rejudge(Path(args.path), specs, cache, args.workers)
        print(report)
    if args.out:
        Path(args.out).write_text(report, encoding="utf-8")


if __name__ == "__main__":
    main()
