"""Extraction reliability at a given reasoning effort: the SAME real customer messages sent N times each to the real classifier
(intent.classify_and_respond -- the exact call the orchestrator makes; real Azure LLM; no DB writes). Scores only what the
orchestrator's deterministic booking logic depends on: did `booking_request` carry the service the customer named, and the
date/time they stated. Not collected by pytest.
  python -m tests.eval.extraction_reliability <effort> [n_samples] [business name]"""
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from zoneinfo import ZoneInfo

from app.core.config import settings
from app.db.database import SessionLocal
from app.db.models.business import Business
from app.services import business_hours_service, service_service
from app.services.conversation.intent import classify_and_respond
from app.schemas.conversation import ConversationIntent
from app.services.conversation.orchestrator import _resolve_service_by_name, _service_named_in

# (message, expects_service, expected_date_offset_days_or_None, expected_time_or_None)
CASES = [
    ("book a teeth cleaning tomorrow at 2pm, I'm Sita, 9800011122", True, 1, "14:00"),
    ("what times do you have for a teeth cleaning tomorrow?", True, 1, None),
    ("bholi 2 baje teeth cleaning ko lagi milcha?", True, 1, "14:00"),
    ("malai bholi teeth cleaning ko appointment chaiyo", True, 1, None),
    ("teeth cleaning book garnu paryo, bholi 10 baje, Sita, 9800011122", True, 1, "10:00"),
    ("do you have any teeth cleaning appointments available tomorrow", True, 1, None),
    ("teeth cleaning ko price kati ho?", True, None, None),
]


def main():
    effort = sys.argv[1]
    n = int(sys.argv[2]) if len(sys.argv) > 2 else 10
    name = sys.argv[3] if len(sys.argv) > 3 else "Samaj Dental Clinic"
    settings.azure_openai_reasoning_effort = effort
    db = SessionLocal()
    business = db.query(Business).filter(Business.name == name).first()
    services = service_service.list_services(db, business_id=business.id)
    hours = business_hours_service.list_hours(db, business_id=business.id)
    tomorrow = (datetime.now(ZoneInfo(business.timezone)).date().toordinal() + 1)

    def one(job):
        text, _svc, _off, _t = CASES[job[0]]
        for attempt in range(6):  # 429 (rate limit) is not retried by the production client; the bench backs off instead
            try:
                c = classify_and_respond(business=business, context={}, knowledge_results=[], customer_message=text,
                                         services=services, locked_language=None, hours=hours)
                return job[0], (c.intent, c.booking_request)
            except RuntimeError:
                if attempt == 5:
                    raise
                time.sleep(15 * (attempt + 1))

    jobs = [(i, k) for i in range(len(CASES)) for k in range(n)]
    with ThreadPoolExecutor(2) as ex:
        results = list(ex.map(one, jobs))
    tot_svc = tot_ok = tot_after = tot_dt = tot_dt_n = 0
    print(f"effort={effort} n={n} per message")
    for i, (text, exp_svc, off, t) in enumerate(CASES):
        both = [ib for j, ib in results if j == i]
        rs = [br for _, br in both]
        svc_ok = sum(1 for br in rs if br and br.get("service") and _resolve_service_by_name(services, br["service"]) is not None)
        # what the orchestrator does after the model: booking intent + no service + one real service named in the message -> filled
        after = sum(
            1 for it, br in both
            if (br and br.get("service") and _resolve_service_by_name(services, br["service"]) is not None)
            or (it == ConversationIntent.BOOKING and br is not None and _service_named_in(services, text) is not None)
        )
        dt_n = dt_ok = 0
        if off is not None:
            dt_n = len(rs)
            want = datetime.fromordinal(tomorrow).strftime("%Y-%m-%d")
            dt_ok = sum(1 for br in rs if br and br.get("date") == want and (t is None or br.get("time") == t))
        tot_svc += len(rs)
        tot_ok += svc_ok
        tot_after += after
        tot_dt += dt_ok
        tot_dt_n += dt_n
        print(f"  service raw {svc_ok:2d}/{len(rs)} -> after backfill {after:2d}/{len(rs)}  date/time ok {dt_ok:2d}/{dt_n}  {text[:62]!r}")
    print(f"TOTAL service raw: {tot_ok}/{tot_svc} ({100 * tot_ok / tot_svc:.0f}%) -> after backfill: {tot_after}/{tot_svc} ({100 * tot_after / tot_svc:.0f}%)   date/time correct: {tot_dt}/{tot_dt_n}")


if __name__ == "__main__":
    main()
