import sys
sys.path.insert(0, "/app")
from tests.eval.regression_cases import load_all_cases
from tests.eval.test_regression_suite import (
    _case_specific_failures, _create_customer_and_conversation, _generic_check_failures,
    _provision_business, _run_turns, _teardown_business,
)
from app.db.database import SessionLocal

case_id_substr = sys.argv[1]
case = next(c for c in load_all_cases() if case_id_substr in c["id"])
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
    print("===", case["id"], "PASS" if not failures else "FAIL")
    if failures:
        print("  failures:", failures)
    print("  replies:", replies)
finally:
    if business is not None:
        _teardown_business(db, business, customer_id)
    db.close()
