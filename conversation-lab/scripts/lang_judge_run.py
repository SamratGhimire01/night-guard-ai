"""Judge every reply of a lang_run.py output with the validated judge (unchanged rubric; the conversation shown to the judge is
that run's OWN preceding turns). Writes one JSONL row per turn with language_match + total score. Resumable.
  python scripts/lang_judge_run.py results/lang/x.jsonl --arms prod,hybrid --reps 0,1,2 --samples 3 --effort low --out results/lang/x_judged.jsonl"""
import argparse
import json
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from lab.businesses import facts_text
from lab.judge import ReplyJudge
from lab.lang_scenarios import ALL
from lab.llm import build_lm

ap = argparse.ArgumentParser()
ap.add_argument("src", nargs="+")
ap.add_argument("--arms", default="")
ap.add_argument("--reps", default="")
ap.add_argument("--samples", type=int, default=3)
ap.add_argument("--effort", default="low")
ap.add_argument("--workers", type=int, default=3)
ap.add_argument("--out", required=True)
args = ap.parse_args()

rows = [json.loads(l) for p in args.src for l in open(p) if l.strip()]
rows = [r for r in rows if r["scenario"] in ALL]  # drops the retired HB3 (content-filter false positive) rows
if args.arms:
    rows = [r for r in rows if r["arm"] in args.arms.split(",")]
if args.reps:
    rows = [r for r in rows if r["rep"] in [int(x) for x in args.reps.split(",")]]
out = Path(args.out)
done = set()
if out.exists():
    done = {(r["arm"], r["scenario"], r["rep"], r["turn"]) for r in map(json.loads, out.read_text().splitlines()) if r}
judge = ReplyJudge(samples=args.samples, lm=build_lm(reasoning_effort=args.effort or None))
jobs = [(r, i) for r in rows for i in range(len(r["turns"])) if (r["arm"], r["scenario"], r["rep"], i) not in done]
print(len(jobs), "replies to judge", flush=True)
lock = threading.Lock()


def one(job):
    r, i = job
    t = r["turns"][i]
    conv = "\n".join(f"{'Customer' if k == 0 else 'Assistant'}: {x}" for j in range(i)
                     for k, x in enumerate((r["turns"][j]["customer"], r["turns"][j]["reply"])))
    for attempt in range(6):  # rate limits / content-filter false positives: back off and retry, never abort the batch
        try:
            j = judge(t["customer"], t["reply"], conversation=conv, facts=facts_text(ALL[r["scenario"]].biz, sandbox_note=False))
            break
        except Exception as e:  # noqa: BLE001
            if attempt == 5:
                print(f"JUDGE FAILED {r['arm']} {r['scenario']} rep{r['rep']} t{i}: {str(e)[:80]}", flush=True)
                return
            time.sleep(20 * (attempt + 1))
    row = {"arm": r["arm"], "scenario": r["scenario"], "type": r["type"], "rep": r["rep"], "turn": i, "kind": t["kind"],
           "score": j.score, "criteria": j.criteria, "reply": t["reply"], "customer": t["customer"]}
    with lock:
        with out.open("a") as f:
            f.write(json.dumps(row, ensure_ascii=False) + "\n")


with ThreadPoolExecutor(args.workers) as ex:
    list(ex.map(one, jobs))
print("done")
