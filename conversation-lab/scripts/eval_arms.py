"""Score reply-generating arms on the SAME held-out inputs (held-out #1 = dev, #2 = clean) with the calibrated judge
(default effort, 5 samples). Arms: minimal (lab baseline), production (full intent.py system prompt), rules (production
reply-style rules as a DSPy instruction = the optimizer's start), optimized (path given). Paired per-item comparison with a
bootstrap CI over items. All replies are saved for reading."""
import argparse
import json
import random
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from statistics import mean

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import dspy

from lab.eval_items import HELDOUT1, HELDOUT2
from lab import fidelity
from lab.judge import ReplyJudge
from lab.llm import configure
from lab.production_prompt import production_reply
from lab.programs import RulesReceptionist, to_example
from lab.receptionist import Reply

ap = argparse.ArgumentParser()
ap.add_argument("--optimized", required=True, help="path to optimized_program.json")
ap.add_argument("--gens", type=int, default=3)
ap.add_argument("--samples", type=int, default=5)
ap.add_argument("--workers", type=int, default=3)
ap.add_argument("--ckpt", default=None, help="jsonl checkpoint; finished (arm,item,gen) jobs are skipped on re-run")
ap.add_argument("--arms", default="minimal,production,rules,optimized")
ap.add_argument("--out", default=None)
args = ap.parse_args()

lm = configure()
judge = ReplyJudge(samples=args.samples)
minimal = dspy.Predict(Reply)
rules = RulesReceptionist()
optimized = RulesReceptionist()
optimized.load(args.optimized)


def gen(arm, it):
    ex = to_example(it)
    kw = {k: ex[k] for k in ex.inputs()}
    if arm == "production":
        return production_reply(it, lm)
    if arm == "minimal":
        return minimal(business_facts=kw["business_facts"], conversation_so_far=kw["conversation_so_far"],
                       customer_message=kw["customer_message"]).response
    return (rules if arm == "rules" else optimized)(**kw).response


def run(job):
    arm, it, g = job
    reply = gen(arm, it)
    j = judge(it.customer, reply, conversation=it.convo(), facts=it.facts())
    return {"arm": arm, "item": it.id, "set": it.id.split(":")[0], "gen": g, "customer": it.customer, "reply": reply,
            "score": j.score, "criteria": j.criteria, "words": j.objective["word_count"], "ends_q": j.objective["ends_with_question"]}


def safe(job):
    """Azure 429 (tokens/min) happens with the 10k-token production prompt: back off and retry instead of dying."""
    for attempt in range(10):
        try:
            return run(job)
        except Exception as exc:  # noqa: BLE001
            if "RateLimit" in type(exc).__name__ or "429" in str(exc):
                time.sleep(15 * (attempt + 1))
                continue
            raise
    raise RuntimeError("rate limited 10 times in a row")


arms = args.arms.split(",")
items = HELDOUT1 + HELDOUT2
ckpt = Path(args.ckpt) if args.ckpt else Path(__file__).resolve().parents[1] / "results" / "eval_arms_ckpt.jsonl"
done = {(r["arm"], r["item"], r["gen"]): r for r in map(json.loads, ckpt.read_text().splitlines())} if ckpt.exists() else {}
jobs = [(a, it, g) for a in arms for it in items for g in range(args.gens)]
todo = [j for j in jobs if (j[0], j[1].id, j[2]) not in done]
print(f"{len(done)} done from checkpoint, {len(todo)} to run", flush=True)
t0 = time.time()


def run_and_save(job):
    r = safe(job)
    with open(ckpt, "a") as f:  # one short append per finished reply; safe enough for threads on this scale
        f.write(json.dumps(r, ensure_ascii=False) + "\n")
    return r


with ThreadPoolExecutor(args.workers) as ex:
    list(ex.map(run_and_save, todo))
done = {(r["arm"], r["item"], r["gen"]): r for r in map(json.loads, ckpt.read_text().splitlines())}
rows = [done[(a, it.id, g)] for a, it, g in jobs]
print(f"{len(rows)} replies x {args.samples} judge samples in {(time.time() - t0) / 60:.1f} min\n")
out = Path(args.out) if args.out else Path(__file__).resolve().parents[1] / "results" / f"eval_arms_{time.strftime('%Y%m%d_%H%M%S')}.json"
out.write_text(json.dumps(rows, ensure_ascii=False, indent=1))


def per_item(arm, sset=None):
    d = {}
    for r in rows:
        if r["arm"] == arm and (sset is None or r["set"] == sset):
            d.setdefault(r["item"], []).append(r["score"])
    return {k: mean(v) for k, v in d.items()}


def boot(diffs, n=5000, seed=0):
    rnd = random.Random(seed)
    ms = sorted(mean(rnd.choices(diffs, k=len(diffs))) for _ in range(n))
    return ms[int(.025 * n)], ms[int(.975 * n)]


print(f"{'arm':12}{'held-out #2 (clean)':>22}{'held-out #1 (dev)':>20}{'all 25':>10}   mean words  ends-in-?")
for a in arms:
    p2, p1, pa = per_item(a, "h2"), per_item(a, "h1"), per_item(a)
    rs = [r for r in rows if r["arm"] == a]
    print(f"{a:12}{mean(p2.values()):>22.1f}{mean(p1.values()):>20.1f}{mean(pa.values()):>10.1f}   {mean(r['words'] for r in rs):>9.0f}   {100 * mean(r['ends_q'] for r in rs):>6.0f}%")
print("\nPaired differences vs `production` (per-item means, bootstrap 95% CI over items; + = better than production):")
base = {s: per_item("production", s) for s in ("h2", "h1", None)}
for a in [x for x in arms if x != "production"]:
    for s, name in (("h2", "#2 clean"), ("h1", "#1 dev"), (None, "all 25")):
        p = per_item(a, s)
        d = [p[k] - base[s][k] for k in p]
        lo, hi = boot(d)
        w = sum(x > 5 for x in d); l = sum(x < -5 for x in d)
        print(f"  {a:10} {name:9} mean diff {mean(d):+6.1f}  95% CI [{lo:+.1f}, {hi:+.1f}]   items better/worse by >5pts: {w}/{l} of {len(d)}")
if "optimized" in arms and "rules" in arms:
    print("\nPaired: optimized vs rules (isolates what optimization itself added):")
    for s, name in (("h2", "#2 clean"), ("h1", "#1 dev"), (None, "all 25")):
        p, q = per_item("optimized", s), per_item("rules", s)
        d = [p[k] - q[k] for k in p]
        lo, hi = boot(d)
        print(f"  {name:9} mean diff {mean(d):+6.1f}  95% CI [{lo:+.1f}, {hi:+.1f}]")
print("\nDecline-wording fidelity vs the real production decline sentence (6 off-topic items x gens; mechanical string check):")
fidelity.report(rows)
print("\nPer-reply (not per-item-mean) paired differences vs production, optimized/rules:")
Pp = {(r["item"], r["gen"]): r["score"] for r in rows if r["arm"] == "production"}
for a in [x for x in arms if x in ("rules", "optimized")]:
    A = {(r["item"], r["gen"]): r["score"] for r in rows if r["arm"] == a}
    d = [A[k] - Pp[k] for k in Pp]
    from statistics import median
    print(f"  {a:10} mean {mean(d):+.1f}  median {median(d):+.1f}  better>5: {sum(x > 5 for x in d)}  worse>5: {sum(x < -5 for x in d)}  ties: {sum(abs(x) <= 5 for x in d)} of {len(d)}   replies <60: {sum(v < 60 for v in A.values())} (production {sum(v < 60 for v in Pp.values())})")
print("\nMean criterion scores (1-5):")
crit = list(rows[0]["criteria"])
print(f"{'':12}" + "".join(f"{c[:11]:>13}" for c in crit))
for a in arms:
    rs = [r for r in rows if r["arm"] == a]
    print(f"{a:12}" + "".join(f"{mean(r['criteria'][c] for r in rs):>13.2f}" for c in crit))
print("saved", out.name)
