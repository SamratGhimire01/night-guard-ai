"""Score a real backend conversation-quality run (JSON from
backend/tests/eval/run_conversation_quality_eval.py --json <path>) with the
already-calibrated ReplyJudge (see LAB_STATUS.md Phases L1-L6). Reuses the
judge and rubric as-is -- no new judge built for this.

Usage: python scripts/score_conversation_quality.py <run.json> [--samples 5]
"""
import argparse
import json
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from lab.judge import ReplyJudge
from lab.llm import configure

ap = argparse.ArgumentParser()
ap.add_argument("run_json")
ap.add_argument("--samples", type=int, default=5)
ap.add_argument("--workers", type=int, default=6)
args = ap.parse_args()

turns = json.loads(Path(args.run_json).read_text())
configure()
judge = ReplyJudge(samples=args.samples)


def conversation_text(turn: dict) -> str:
    lines = []
    for t in turn["conversation_so_far"]:
        lines.append(f"customer: {t['customer']}")
        lines.append(f"agent: {t['agent']}")
    return "\n".join(lines)


def run(turn: dict) -> dict:
    j = judge(turn["customer_message"], turn["reply"], conversation=conversation_text(turn))
    return {**turn, "score": j.score, "per_sample": j.per_sample_scores, "criteria": j.criteria,
            "objective": j.objective, "reasoning": j.reasoning}


t0 = time.time()
with ThreadPoolExecutor(args.workers) as ex:
    results = list(ex.map(run, turns))
print(f"{len(results)} turns x {args.samples} judge samples in {time.time() - t0:.0f}s\n")

for i, r in enumerate(results, 1):
    spread = f"{min(r['per_sample']):.0f}-{max(r['per_sample']):.0f}"
    print(f"[{i}] {r['case_id']}  score {r['score']:.1f} (range {spread})")
    print(f"    customer: {r['customer_message']!r}")
    print(f"    agent:    {r['reply'][:200]!r}")
    print(f"    criteria: {r['criteria']}")
    if r["reasoning"]:
        print(f"    why:      {r['reasoning'][:200]}")
    print()

out = Path(__file__).resolve().parents[1] / "results" / f"cq_scored_{time.strftime('%Y%m%d_%H%M%S')}.json"
out.write_text(json.dumps(results, ensure_ascii=False, indent=1))
print("saved", out)
