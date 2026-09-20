"""Weekday -> calendar-date accuracy of the REAL classifier, across every possible "today" (the model is told today's date+weekday in its
prompt; the harness fakes that clock per call, thread-safely) and clear + terse + Roman-Nepali phrasings. Saves every raw model date so a
deterministic post-fix can be scored on the very same samples. No DB writes. Not collected by pytest.
  python -m tests.eval.weekday_accuracy collect <effort> <samples_per_cell> <out.json> [business name]
  python -m tests.eval.weekday_accuracy score <out.json>            (scores raw model dates, and after the orchestrator's weekday fix)"""
import json
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import date, datetime, timedelta

from app.core.config import settings
from app.db.database import SessionLocal
from app.db.models.business import Business
from app.services import business_hours_service, service_service
from app.services.conversation import intent as intent_module

DAYS = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"]
ROMAN = ["sombar", "mangalbar", "budhabar", "bihibar", "sukrabar", "sanibar", "aitabar"]
# (kind, template, context). {D} = weekday name. "clear" = a full booking request; "terse" = the short follow-ups real customers send
# MID-conversation, so they get a realistic booking conversation as context (without it the model, correctly, reads "what about
# Thursday?" as an opening-hours question -- an intent question, not a date one).
_ASKED = [{"sender_type": "customer", "content": "I'd like to book a teeth cleaning"},
          {"sender_type": "agent", "content": "Sure -- which day works for you?"}]
_HAS_DATE = [{"sender_type": "customer", "content": "book a teeth cleaning tomorrow at 10am"},
             {"sender_type": "agent", "content": "Got it -- Teeth Cleaning tomorrow at 10:00 AM. I just need your name and a phone number."}]
TEMPLATES = [
    ("clear", "book a teeth cleaning on {D} at 10am, I'm Sita, 9800011122", []),
    ("terse", "{D} works?", _ASKED),
    ("terse", "actually, is {D} morning possible instead?", _HAS_DATE),
    ("roman", "{R} ko lagi teeth cleaning milcha?", []),
]
BASE = date(2026, 9, 20)  # a Sunday; the 7 fake "today" values are BASE..BASE+6, i.e. every weekday once

_local = threading.local()


class _FakeDatetime(datetime):
    @classmethod
    def now(cls, tz=None):
        d = getattr(_local, "today", None)
        return datetime(d.year, d.month, d.day, 9, 0, tzinfo=tz) if d else datetime.now(tz)


def expected(today: date, weekday: int) -> set[str]:
    """The nearest upcoming such weekday; when it IS today's weekday, today or next week are both fine."""
    delta = (weekday - today.weekday()) % 7
    ok = {today + timedelta(days=delta)} if delta else {today, today + timedelta(days=7)}
    return {d.isoformat() for d in ok}


def collect(effort: str, n: int, out: str, name: str):
    settings.azure_openai_reasoning_effort = effort
    intent_module.datetime = _FakeDatetime
    db = SessionLocal()
    b = db.query(Business).filter(Business.name == name).first()
    services = service_service.list_services(db, business_id=b.id)
    hours = business_hours_service.list_hours(db, business_id=b.id)
    jobs = []
    for off in range(7):
        for wd in range(7):  # every (today's weekday, weekday named) pair, for every template
            for ti, (kind, tpl, _ctx) in enumerate(TEMPLATES):
                for k in range(n):
                    jobs.append({"today": (BASE + timedelta(days=off)).isoformat(), "kind": kind, "tpl": ti, "weekday": wd,
                                 "text": tpl.format(D=DAYS[wd], R=ROMAN[wd]), "k": k})

    def one(job):
        _local.today = date.fromisoformat(job["today"])
        for attempt in range(6):
            try:
                c = intent_module.classify_and_respond(business=b, context={"recent_messages": TEMPLATES[job["tpl"]][2]}, knowledge_results=[], customer_message=job["text"],
                                                       services=services, locked_language=None, hours=hours)
                return {**job, "intent": c.intent.value, "booking_request": c.booking_request}
            except RuntimeError:
                if attempt == 5:
                    raise
                time.sleep(15 * (attempt + 1))

    with ThreadPoolExecutor(2) as ex:
        rows = list(ex.map(one, jobs))
    json.dump({"effort": effort, "business_tz": b.timezone, "rows": rows}, open(out, "w"), ensure_ascii=False)
    print(f"collected {len(rows)} samples at effort={effort} -> {out}")


def score(path: str):
    from app.services.conversation.orchestrator import _verify_weekday_date  # the production fix (absent before the fix exists)

    data = json.load(open(path))
    print(f"effort={data['effort']}  samples={len(data['rows'])}")
    for label, fix in (("model raw", False), ("after weekday fix", True)):
        buckets: dict[str, list[int]] = {}
        for r in data["rows"]:
            today = date.fromisoformat(r["today"])
            br = r["booking_request"]
            if fix and br is not None:
                br = _verify_weekday_date(br, r["text"], today)
            got = (br or {}).get("date")
            ok = got in expected(today, r["weekday"])
            for key in ("ALL", r["kind"]):
                buckets.setdefault(key, []).append(1 if ok else 0)
        print(f"  {label:18} " + "  ".join(f"{k}: {sum(v)}/{len(v)} ({100 * sum(v) / len(v):.0f}%)" for k, v in sorted(buckets.items())))
    wrong = [r for r in data["rows"] if (r["booking_request"] or {}).get("date") not in expected(date.fromisoformat(r["today"]), r["weekday"])]
    kinds = {"none": sum(1 for r in wrong if (r["booking_request"] or {}).get("date") is None)}
    kinds["wrong date"] = len(wrong) - kinds["none"]
    print(f"  raw failures split: {kinds}")


if __name__ == "__main__":
    if sys.argv[1] == "collect":
        collect(sys.argv[2], int(sys.argv[3]), sys.argv[4], sys.argv[5] if len(sys.argv) > 5 else "Samaj Dental Clinic")
    else:
        score(sys.argv[2])
