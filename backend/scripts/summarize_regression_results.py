"""Rolls up backend/data/regression/failure_log_batches/*.json (the real-conversation
read-through) into one report: dataset size, pass/fail split, finding-category
breakdown. Pure local file processing, run any time after the read-through batches
finish -- python backend/scripts/summarize_regression_results.py
"""

import json
import collections
from pathlib import Path

BATCH_DIR = Path(__file__).resolve().parent.parent / "data" / "regression" / "failure_log_batches"
REAL_DIR = Path(__file__).resolve().parent.parent / "data" / "regression" / "real_conversations"
SYNTHETIC_DIR = Path(__file__).resolve().parent.parent / "data" / "regression" / "synthetic_conversations"


def main() -> None:
    records = []
    for f in sorted(BATCH_DIR.glob("*.json")):
        records.extend(json.loads(f.read_text()))

    seen = set()
    dupes = 0
    for r in records:
        if r["conversation_id"] in seen:
            dupes += 1
        seen.add(r["conversation_id"])

    total_real_files = len(list(REAL_DIR.glob("*.json")))
    total_synthetic = len(list(SYNTHETIC_DIR.glob("*.json")))

    passed = sum(1 for r in records if r["verdict"] == "pass")
    failed = sum(1 for r in records if r["verdict"] == "fail")

    by_business = collections.Counter(r["business_name"] for r in records)
    by_business_fail = collections.Counter(r["business_name"] for r in records if r["verdict"] == "fail")

    cat_counts = collections.Counter()
    for r in records:
        for finding in r.get("findings", []):
            cat_counts[finding["category"]] += 1

    print("=" * 78)
    print("REAL CONVERSATION READ-THROUGH -- ROLLUP")
    print("=" * 78)
    print(f"real conversation files on disk : {total_real_files}")
    print(f"conversations read & classified  : {len(records)}  (duplicate ids: {dupes})")
    print(f"  pass (clean baseline)          : {passed}")
    print(f"  fail (at least one finding)    : {failed}")
    print()
    print("by business (fail / total):")
    for name, total in by_business.most_common():
        print(f"  {by_business_fail.get(name, 0):3d} / {total:3d}   {name}")
    print()
    print("finding categories (a failing conversation can have >1):")
    for cat, n in cat_counts.most_common():
        print(f"  {n:4d}  {cat}")
    print()
    print(f"synthetic cases generated: {total_synthetic}")


if __name__ == "__main__":
    main()
