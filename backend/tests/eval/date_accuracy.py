"""Weekday -> calendar-date accuracy of the real classifier at a given reasoning effort: the same customer messages N times each,
scored against the date computed by Python (the model is told today's date and weekday in its prompt). No DB writes. Not collected
by pytest.   python -m tests.eval.date_accuracy <effort> [n] [business name]"""
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from app.core.config import settings
from app.db.database import SessionLocal
from app.db.models.business import Business
from app.services import business_hours_service, service_service
from app.services.conversation.intent import classify_and_respond

DAYS = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"]
# (message template, weekday index) -- the expected date is the next upcoming such weekday strictly after today
CASES = [
    ("book a teeth cleaning on {d} at 10am, I'm Sita, 9800011122", 3),
    ("can I come in on {d} at 2pm for a teeth cleaning?", 4),
    ("actually, is {d} morning possible instead?", 3),
    ("{d} ko lagi teeth cleaning milcha?", 2),
    ("what times do you have for a teeth cleaning on {d}?", 3),
    ("let's do {d} instead", 4),
]


def main():
    effort, n = sys.argv[1], int(sys.argv[2]) if len(sys.argv) > 2 else 10
    name = sys.argv[3] if len(sys.argv) > 3 else "Samaj Dental Clinic"
    settings.azure_openai_reasoning_effort = effort
    db = SessionLocal()
    b = db.query(Business).filter(Business.name == name).first()
    services = service_service.list_services(db, business_id=b.id)
    hours = business_hours_service.list_hours(db, business_id=b.id)
    today = datetime.now(ZoneInfo(b.timezone)).date()

    def expected(wd):
        return (today + timedelta(days=(wd - today.weekday()) % 7 or 7)).isoformat()

    def one(job):
        i, _ = job
        text = CASES[i][0].format(d=DAYS[CASES[i][1]])
        for attempt in range(6):
            try:
                c = classify_and_respond(business=b, context={}, knowledge_results=[], customer_message=text, services=services,
                                         locked_language=None, hours=hours)
                return i, (c.booking_request or {}).get("date")
            except RuntimeError:
                if attempt == 5:
                    raise
                time.sleep(15 * (attempt + 1))

    with ThreadPoolExecutor(2) as ex:
        res = list(ex.map(one, [(i, k) for i in range(len(CASES)) for k in range(n)]))
    print(f"effort={effort} n={n} today={today} ({DAYS[today.weekday()]})")
    ok_total = 0
    for i, (tpl, wd) in enumerate(CASES):
        got = [d for j, d in res if j == i]
        ok = sum(1 for d in got if d == expected(wd))
        ok_total += ok
        bad = sorted({d for d in got if d != expected(wd)}, key=str)
        print(f"  {ok:2d}/{len(got)} correct (want {expected(wd)})  {tpl.format(d=DAYS[wd])[:58]!r}  wrong: {bad}")
    print(f"TOTAL {ok_total}/{len(res)}")


if __name__ == "__main__":
    main()
