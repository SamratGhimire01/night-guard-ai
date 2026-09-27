"""Run scripted multi-turn language scenarios through each mechanism arm (real Azure gpt-5-mini) and label every reply's
language with an independent labeler. One JSONL row per (arm, scenario, rep); finished rows are skipped on re-run.
  python scripts/lang_run.py --set dev --arms pre25,prod,hybrid,hybrid_nt --reps 3 --out results/lang_dev_v1.jsonl
Reply generation uses the deployment's DEFAULT reasoning effort (that is what production runs); labeling uses low effort."""
import argparse
import json
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from lab.lang_mech import ARMS, ConvState, label_reply, step
from lab.lang_scenarios import ALL, DEV, HELD, PROBE
from lab.llm import build_lm

ap = argparse.ArgumentParser()
ap.add_argument("--set", default="dev", choices=["dev", "held", "all", "probe"])
ap.add_argument("--arms", default=",".join(ARMS))
ap.add_argument("--reps", type=int, default=3)
ap.add_argument("--workers", type=int, default=6)
ap.add_argument("--only", default="", help="comma-separated scenario ids")
ap.add_argument("--out", required=True)
args = ap.parse_args()

lm, label_lm = build_lm(), build_lm(reasoning_effort="low")
pool = {"dev": DEV, "held": HELD, "all": DEV + HELD, "probe": PROBE}[args.set]
if args.only:
    pool = [ALL[i] for i in args.only.split(",")]
out = Path(args.out)
done = set()
if out.exists():
    done = {(r["arm"], r["scenario"], r["rep"]) for r in map(json.loads, out.read_text().splitlines()) if r}
jobs = [(a, s, r) for s in pool for a in args.arms.split(",") for r in range(args.reps) if (a, s.id, r) not in done]
print(f"{len(jobs)} conversation-runs to do ({len(done)} already done)", flush=True)
lock = threading.Lock()


def _step(arm, state, history, t, sc):
    """Azure's content filter occasionally false-positives (seen: 'violence: high' on an ordinary dental chat prompt) and
    rate limits happen; retry a few times, then let the failure be logged rather than aborting the whole batch."""
    for attempt in range(6):
        try:
            return step(arm, state, history, t.text, sc.biz, lm)
        except Exception as e:  # noqa: BLE001
            err = f"{type(e).__name__}: {str(e)[:160]}"
            if attempt == 5:
                raise RuntimeError(err) from e
            time.sleep(0 if "content" in err.lower() else 20 * (attempt + 1))  # rate limit: back off; content filter: just retry


def run(job):
    try:
        return _run(job)
    except Exception as e:  # noqa: BLE001
        arm, sc, rep = job
        print(f"FAILED {arm} {sc.id} rep{rep}: {e}", flush=True)
        with lock, Path(args.out + ".failed").open("a") as f:
            f.write(json.dumps({"arm": arm, "scenario": sc.id, "rep": rep, "error": str(e)}) + "\n")


def _run(job):
    arm, sc, rep = job
    state, history, turns = ConvState(), [], []
    for t in sc.turns:
        r = _step(arm, state, history, t, sc)
        history += [("Customer", t.text), ("Assistant", r["reply"])]
        turns.append({"customer": t.text, "exp": t.exp, "kind": t.kind, "reply": r["reply"], "meta": r["meta"],
                      "label": label_reply(r["reply"], label_lm)})
    row = {"arm": arm, "scenario": sc.id, "type": sc.type, "rep": rep, "turns": turns}
    with lock:
        with out.open("a") as f:
            f.write(json.dumps(row, ensure_ascii=False) + "\n")
    print(f"done {arm:9} {sc.id:34} rep{rep}: " + " ".join(x["label"][:5] for x in turns), flush=True)
    return row


with ThreadPoolExecutor(args.workers) as ex:
    list(ex.map(run, jobs))
