"""Runs every case in the regression dataset (real + synthetic) concurrently against
the real orchestrator, reusing the exact same provisioning/check logic as
tests/eval/test_regression_suite.py (imported directly, not reimplemented) -- this
script exists only to get real wall-clock time down via a thread pool (each turn is
an I/O-bound Azure HTTP call; SQLAlchemy's default pool comfortably covers a handful
of concurrent sessions), which plain `pytest -q` runs serially. Same
RUN_LIVE_REGRESSION opt-in discipline; same real Azure cost per case.

Usage (inside the backend container):
    RUN_LIVE_REGRESSION=1 python scripts/run_full_regression.py [--workers N] [-k substring]

Writes one JSON line per case to data/regression/regression_results.jsonl (truncated
at the start of each run) and prints a final pass/fail summary.
"""

import argparse
import json
import os
import sys
import time
import traceback
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.db.database import SessionLocal  # noqa: E402

from app.db.models.business import Business  # noqa: E402

from tests.eval.regression_cases import load_all_cases  # noqa: E402
from tests.eval.test_regression_suite import (  # noqa: E402
    _case_specific_failures,
    _create_customer_and_conversation,
    _generic_check_failures,
    _provision_business,
    _run_turns,
    _teardown_business,
)

RESULTS_PATH = Path(__file__).resolve().parent.parent / "data" / "regression" / "regression_results.jsonl"


# The orchestrator's own real fallback text when the Azure provider call fails after its
# internal retries (see handoff_service._handoff_reason's is_provider_failure path) -- under
# heavy concurrency this is Azure rate-limiting our OWN test harness, not a real agent bug.
# Retried a few times with backoff before being counted as a genuine failure.
_PROVIDER_FAILURE_TEXT = "having trouble connecting"
_MAX_ATTEMPTS = 4


def _run_once(case: dict) -> dict:
    db = SessionLocal()
    business = None
    customer_id = None
    started = time.time()
    try:
        business = _provision_business(db, case["business"])
        customer_id, conversation_id = _create_customer_and_conversation(db, business)
        replies = _run_turns(db, business, conversation_id, case["turns"])

        failures: list[str] = []
        for reply in replies:
            failures.extend(_generic_check_failures(reply, case["business"]))
        failures.extend(_case_specific_failures(db, business, replies, case["expect"]))

        return {
            "id": case["id"],
            "source": case["source"],
            "pass": not failures,
            "failures": failures,
            "replies": replies,
            "seconds": round(time.time() - started, 1),
        }
    except Exception as exc:  # noqa: BLE001 -- a pipeline crash IS a failure result, not a script bug
        return {
            "id": case["id"],
            "source": case["source"],
            "pass": False,
            "failures": [f"EXCEPTION: {exc}"],
            "traceback": traceback.format_exc(),
            "replies": [],
            "seconds": round(time.time() - started, 1),
        }
    finally:
        try:
            if business is not None:
                _teardown_business(db, business, customer_id)
        finally:
            db.close()


def run_one(case: dict) -> dict:
    result = _run_once(case)
    for attempt in range(1, _MAX_ATTEMPTS):
        if _PROVIDER_FAILURE_TEXT not in " ".join(result.get("replies", [])):
            break
        time.sleep(2 * attempt)
        result = _run_once(case)
    return result


def main() -> None:
    if not os.environ.get("RUN_LIVE_REGRESSION"):
        print("RUN_LIVE_REGRESSION=1 not set -- refusing to hit the real Azure LLM. See module docstring.")
        raise SystemExit(1)

    parser = argparse.ArgumentParser()
    parser.add_argument("--workers", type=int, default=8)
    parser.add_argument("-k", dest="substring", default=None)
    parser.add_argument(
        "--max-customer-turns", type=int, default=None,
        help="skip any case with more customer turns than this (a handful of real conversations run "
        "50-100+ turns and dominate wall-clock time under live replay; they're already covered by the "
        "qualitative read-through -- see PHASE_STATUS.md)",
    )
    args = parser.parse_args()

    cases = load_all_cases()
    if args.substring:
        cases = [c for c in cases if args.substring in c["id"]]
    skipped = []
    if args.max_customer_turns is not None:
        kept = [c for c in cases if len(c["turns"]) <= args.max_customer_turns]
        skipped = [c["id"] for c in cases if len(c["turns"]) > args.max_customer_turns]
        cases = kept
        if skipped:
            print(f"skipping {len(skipped)} case(s) over --max-customer-turns={args.max_customer_turns}: {skipped}")

    RESULTS_PATH.parent.mkdir(parents=True, exist_ok=True)
    RESULTS_PATH.write_text("")

    print(f"running {len(cases)} cases with {args.workers} workers...")
    t0 = time.time()
    passed = failed = 0
    with ThreadPoolExecutor(max_workers=args.workers) as ex, RESULTS_PATH.open("a") as out:
        futures = {ex.submit(run_one, c): c["id"] for c in cases}
        done = 0
        for fut in as_completed(futures):
            result = fut.result()
            out.write(json.dumps(result) + "\n")
            out.flush()
            done += 1
            if result["pass"]:
                passed += 1
            else:
                failed += 1
            elapsed = time.time() - t0
            print(f"[{done}/{len(cases)}] {'PASS' if result['pass'] else 'FAIL'} {result['id']} "
                  f"({result['seconds']}s, {elapsed:.0f}s elapsed, pass={passed} fail={failed})")

    print(f"\nDONE in {time.time() - t0:.0f}s -- {passed} passed, {failed} failed, {len(cases)} total"
          + (f" ({len(skipped)} skipped)" if skipped else ""))
    print(f"results -> {RESULTS_PATH}")

    # Belt-and-suspenders: each case tears down its own ephemeral business already, but sweep for
    # any stragglers a rare mid-run crash could still leave behind, so runs never accumulate junk.
    sweep_db = SessionLocal()
    try:
        leftovers = sweep_db.query(Business).filter(Business.name.like("[regression]%")).all()
        for b in leftovers:
            _teardown_business(sweep_db, b, None)
        if leftovers:
            print(f"swept {len(leftovers)} leftover ephemeral business(es) from this run")
    finally:
        sweep_db.close()


if __name__ == "__main__":
    main()
