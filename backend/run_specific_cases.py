import json, sys, traceback
sys.path.insert(0, "/app")
from tests.eval.regression_cases import load_all_cases
from tests.eval.test_regression_suite import (
    _case_specific_failures, _create_customer_and_conversation, _generic_check_failures,
    _provision_business, _run_turns, _teardown_business,
)
from app.db.database import SessionLocal

targets = ["f44c89d4", "f98ba2d8", "fd2859ae", "3db7b0b2", "6791f3a8"]
cases = [c for c in load_all_cases() if any(t in c["id"] for t in targets)]
print(f"running {len(cases)} cases", flush=True)
for case in cases:
    print(">>> starting", case["id"], flush=True)
    db = SessionLocal()
    business = None
    customer_id = None
    try:
        business = _provision_business(db, case["business"])
        customer_id, conversation_id = _create_customer_and_conversation(db, business)
        replies = _run_turns(db, business, conversation_id, case["turns"])
        failures = []
        for reply in replies:
            failures.extend(_generic_check_failures(reply, case["business"]))
        failures.extend(_case_specific_failures(db, business, replies, case["expect"]))
        print("===", case["id"], "PASS" if not failures else "FAIL", flush=True)
        if failures:
            print("  failures:", failures, flush=True)
            print("  replies:", replies, flush=True)
    except Exception:
        print("!!! EXCEPTION in", case["id"], flush=True)
        traceback.print_exc()
    finally:
        if business is not None:
            _teardown_business(db, business, customer_id)
        db.close()
print("ALL DONE", flush=True)
