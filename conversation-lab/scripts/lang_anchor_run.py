"""Run the L8 anchor scenarios through the prod / prod_fix / prod_fixA / prod_fixB arms (real Azure gpt-5-mini, default reasoning
effort for replies, low for the reply-language labeler). One JSONL row per (arm, scenario, rep); finished rows are skipped on re-run.
  python scripts/lang_anchor_run.py --arms prod,prod_fix --reps 3 --out results/lang/anchor_v1.jsonl"""
import argparse
import json
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from lab.lang_anchor import ANCHOR, ARMS, step
from lab.lang_mech import ConvState, label_reply
from lab.llm import build_lm

ap = argparse.ArgumentParser()
ap.add_argument("--arms", default=",".join(ARMS))
ap.add_argument("--reps", type=int, default=3)
ap.add_argument("--workers", type=int, default=4)
ap.add_argument("--only", default="")
ap.add_argument("--out", required=True)
args = ap.parse_args()

lm, label_lm = build_lm(), build_lm(reasoning_effort="low")
pool = [s for s in ANCHOR if not args.only or s["id"] in args.only.split(",")]
out = Path(args.out)
done = set()
if out.exists():
    done = {(r["arm"], r["scenario"], r["rep"]) for r in map(json.loads, out.read_text().splitlines()) if r}
jobs = [(a, s, r) for s in pool for a in args.arms.split(",") for r in range(args.reps) if (a, s["id"], r) not in done]
print(f"{len(jobs)} conversation-runs to do ({len(done)} already done)", flush=True)
lock = threading.Lock()


def _step(arm, state, history, text, biz):
    for attempt in range(6):
        try:
            return step(arm, state, history, text, biz, lm)
        except Exception as e:  # noqa: BLE001  rate limit / content-filter false positives: retry, then log and move on
            err = f"{type(e).__name__}: {str(e)[:160]}"
            if attempt == 5:
                raise RuntimeError(err) from e
            time.sleep(0 if "content" in err.lower() else 20 * (attempt + 1))


def run(job):
    arm, sc, rep = job
    try:
        state, history, turns = ConvState(), [], []
        for text, truth in sc["turns"]:
            r = _step(arm, state, history, text, sc["biz"])
            history += [("Customer", text), ("Assistant", r["reply"])]
            turns.append({"customer": text, "truth": truth, "reply": r["reply"], "meta": r["meta"],
                          "label": label_reply(r["reply"], label_lm)})
        row = {"arm": arm, "scenario": sc["id"], "expect": sc["expect"], "rep": rep, "turns": turns}
        with lock, out.open("a") as f:
            f.write(json.dumps(row, ensure_ascii=False) + "\n")
        print(f"done {arm:10} {sc['id']:36} rep{rep}: lock " + ">".join(str(t["meta"]["lock_after"])[:5] for t in turns), flush=True)
    except Exception as e:  # noqa: BLE001
        print(f"FAILED {arm} {sc['id']} rep{rep}: {e}", flush=True)
        with lock, Path(args.out + ".failed").open("a") as f:
            f.write(json.dumps({"arm": arm, "scenario": sc["id"], "rep": rep, "error": str(e)}) + "\n")


with ThreadPoolExecutor(args.workers) as ex:
    list(ex.map(run, jobs))
