"""Guard check for the weekday fix: real-classifier samples of requests that do NOT need it (today, tomorrow, explicit dates) or that it
must deliberately leave alone (weekday + explicit date, "next Thursday", negation). For each sample: model date raw vs after the fix.
Every row must be UNCHANGED by the fix. Real clock ("today" is the real date). No DB writes. Not collected by pytest.
  python -m tests.eval.nonweekday_check <effort> <samples_per_case>"""
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from app.core.config import settings
from app.db.database import SessionLocal
from app.db.models.business import Business
from app.services import business_hours_service, service_service
from app.services.conversation import intent as intent_module
from app.services.conversation.orchestrator import _verify_weekday_date

CASES = [  # (text, accepted dates as offsets from today -- None = no date expected)
    ("book a teeth cleaning today at 4pm, I'm Sita, 9800011122", {0}),
    ("book a teeth cleaning tomorrow at 2pm, I'm Sita, 9800011122", {1}),
    ("book a teeth cleaning on {d4:%B} {d4.day} at 10am, I'm Sita, 9800011122", {4}),
    ("book a teeth cleaning on {d4:%Y-%m-%d} at 10am, I'm Sita, 9800011122", {4}),
    ("book a teeth cleaning on the {d4.day}th at 3pm, I'm Sita, 9800011122", {4}),
    ("book a teeth cleaning on {d4:%A} the {d4.day}th at 3pm, I'm Sita, 9800011122", {4}),  # weekday AND explicit date: leave alone
    ("book a teeth cleaning on {d4:%A}, {d4:%B} {d4.day} at 3pm, I'm Sita, 9800011122", {4}),
    ("not {d3:%A}, tomorrow at 2pm works for a teeth cleaning, I'm Sita, 9800011122", {1}),  # negation: leave alone
]


def main():
    effort, n = sys.argv[1], int(sys.argv[2])
    settings.azure_openai_reasoning_effort = effort
    db = SessionLocal()
    b = db.query(Business).filter(Business.name == "Samaj Dental Clinic").first()
    services = service_service.list_services(db, business_id=b.id)
    hours = business_hours_service.list_hours(db, business_id=b.id)
    today = datetime.now(ZoneInfo(b.timezone)).date()
    ns = {"d3": today + timedelta(days=3), "d4": today + timedelta(days=4)}
    texts = [(t.format(**ns), {(today + timedelta(days=o)).isoformat() for o in offs}) for t, offs in CASES]

    def one(job):
        text, _ok = texts[job]
        for attempt in range(6):
            try:
                c = intent_module.classify_and_respond(business=b, context={}, knowledge_results=[], customer_message=text,
                                                       services=services, locked_language=None, hours=hours)
                return job, c.intent.value, c.booking_request
            except RuntimeError:
                if attempt == 5:
                    raise
                time.sleep(15 * (attempt + 1))

    with ThreadPoolExecutor(2) as ex:
        res = list(ex.map(one, [i for i in range(len(texts)) for _ in range(n)]))
    changed = total = raw_ok = after_ok = 0
    print(f"effort={effort} n={n}/case today={today}")
    for i, (text, ok) in enumerate(texts):
        rows = [(it, br) for j, it, br in res if j == i]
        r_ok = a_ok = ch = 0
        for it, br in rows:
            raw = (br or {}).get("date")
            after = (_verify_weekday_date(br, text, today, fill_missing=it == "booking") if br is not None else None) or {}
            ch += raw != after.get("date") and br is not None
            r_ok += raw in ok
            a_ok += after.get("date") in ok
        total += len(rows)
        changed += ch
        raw_ok += r_ok
        after_ok += a_ok
        print(f"  raw {r_ok}/{len(rows)}  after {a_ok}/{len(rows)}  changed-by-fix {ch}  {text[:78]!r}")
    print(f"TOTAL raw correct {raw_ok}/{total}, after fix {after_ok}/{total}, samples changed by the fix: {changed}")


if __name__ == "__main__":
    main()
