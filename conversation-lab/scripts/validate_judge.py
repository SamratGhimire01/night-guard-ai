"""Acceptance step 3: does the judge score real good replies above real bad
ones? Runs every labeled reply `--samples` times, prints scores, per-group
pairwise accuracy (every good must outscore every bad for the same customer
message), the mean good-vs-bad gap, and run-to-run noise."""
import argparse
import json
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from statistics import mean, pstdev

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import importlib

from lab.judge import ReplyJudge
from lab.llm import build_lm, configure

ap = argparse.ArgumentParser()
ap.add_argument("--set", default="validation_set", help="validation_set (calibration) or heldout_set")
ap.add_argument("--samples", type=int, default=3)
ap.add_argument("--workers", type=int, default=6)
ap.add_argument("--effort", default=None, help="judge reasoning_effort override (minimal/low); default = deployment default")
ap.add_argument("--threshold-from", default=None, help="results json whose best threshold is APPLIED (not refit) to this set")
args = ap.parse_args()
GROUPS = importlib.import_module(f"lab.{args.set}").GROUPS

configure()
judge = ReplyJudge(samples=args.samples, lm=build_lm(reasoning_effort=args.effort) if args.effort else None)

jobs = [(g, label, text, prov) for g in GROUPS for label, text, prov in g["replies"]]


def run(job):
    g, label, text, prov = job
    j = judge(g["customer"], text, conversation=g.get("conversation", ""), facts=g.get("facts", ""))
    return {"group": g["id"], "kind": g["kind"], "label": label, "text": text, "provenance": prov,
            "customer": g["customer"], "score": j.score, "per_sample": j.per_sample_scores,
            "weighted_v1": j.weighted_score, "criteria": j.criteria, "objective": j.objective}


t0 = time.time()
with ThreadPoolExecutor(args.workers) as ex:
    results = list(ex.map(run, jobs))

print(f"\n{len(results)} replies x {args.samples} judge samples in {time.time() - t0:.0f}s\n")
pairs_total = pairs_ok = 0
per_kind = {}
for g in GROUPS:
    rows = [r for r in results if r["group"] == g["id"]]
    print(f"== {g['id']} [{g['kind']}]  customer: {g['customer']!r}")
    for r in rows:
        spread = f"{min(r['per_sample']):.0f}-{max(r['per_sample']):.0f}"
        print(f"   {r['label']:>4}  {r['score']:5.1f}  (samples {spread})  {r['text'][:78]!r}")
    goods = [r["score"] for r in rows if r["label"] == "good"]
    bads = [r["score"] for r in rows if r["label"] == "bad"]
    if goods and bads:
        ok = sum(1 for gs in goods for bs in bads if gs > bs)
        n = len(goods) * len(bads)
        pairs_total += n
        pairs_ok += ok
        k = per_kind.setdefault(g["kind"], [0, 0])
        k[0] += ok
        k[1] += n
        print(f"   pairwise good>bad: {ok}/{n}   worst good {min(goods):.1f} vs best bad {max(bads):.1f}")
    print()

def best_threshold(key):
    vals = sorted({r[key] for r in results})
    best = (0, None)
    for t in vals:
        acc = sum((r[key] >= t) == (r["label"] == "good") for r in results) / len(results)
        best = max(best, (acc, t))
    return best


for key, name in (("weighted_v1", "v1 weighted mean"), ("score", "v2 weakest-link blend")):
    good = [r[key] for r in results if r["label"] == "good"]
    bad = [r[key] for r in results if r["label"] == "bad"]
    acc, t = best_threshold(key)
    print(f"[{name}] good mean {mean(good):.1f} (min {min(good):.1f}) | bad mean {mean(bad):.1f} (max {max(bad):.1f}) | "
          f"best single threshold >= {t}: {acc:.0%} of {len(results)} replies classified right")
if args.threshold_from:
    prev = json.loads(Path(args.threshold_from).read_text())["results"]
    _, thr = (lambda vals: max((sum((r["score"] >= t) == (r["label"] == "good") for r in prev) / len(prev), t) for t in vals))(
        sorted({r["score"] for r in prev}))
    right = sum((r["score"] >= thr) == (r["label"] == "good") for r in results)
    print(f"HELD-OUT threshold accuracy: threshold {thr} fitted on {Path(args.threshold_from).name} (NOT refit here) -> "
          f"{right}/{len(results)} = {right / len(results):.0%}")
    for r in results:
        if (r["score"] >= thr) != (r["label"] == "good"):
            print(f"   MISS ({r['label']}, {r['score']}): {r['text'][:90]!r}")
all_good = [r["score"] for r in results if r["label"] == "good"]
all_bad = [r["score"] for r in results if r["label"] == "bad"]
noise = mean(pstdev(r["per_sample"]) for r in results) if args.samples > 1 else 0
print(f"OVERALL pairwise accuracy: {pairs_ok}/{pairs_total} = {pairs_ok / pairs_total:.0%}")
for kind, (ok, n) in per_kind.items():
    print(f"   {kind}: {ok}/{n}")
print(f"mean score good={mean(all_good):.1f}  bad={mean(all_bad):.1f}  gap={mean(all_good) - mean(all_bad):.1f}")
print(f"mean per-reply sample stdev (judge noise): {noise:.1f} points")

out = Path(__file__).resolve().parents[1] / "results"
out.mkdir(exist_ok=True)
path = out / f"judge_{args.set}{'_' + args.effort if args.effort else ''}_{time.strftime('%Y%m%d_%H%M%S')}.json"
path.write_text(json.dumps({"set": args.set, "effort": args.effort, "samples": args.samples, "elapsed_s": round(time.time() - t0), "results": results}, ensure_ascii=False, indent=1))
print("saved", path.name)
