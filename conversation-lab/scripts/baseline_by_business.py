"""Generalization check: run the SAME unoptimized baseline + the SAME judge over the same conversation
scenarios for every sandbox business (dental / salon / trek). If the greeting-dump / reflexive-offer
problems show up for all of them, the lab measures a general conversation-quality issue, not a dental one."""
import json
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from statistics import mean

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from lab.businesses import BUSINESSES, facts_text
from lab.judge import ReplyJudge
from lab.llm import configure
from lab.receptionist import BaselineReceptionist

GENS, JUDGE_SAMPLES = 3, 3
PRICE = {"dental": ("teeth cleaning ko price kati ho?", "Teeth Cleaning NPR 1500 ho, 30 minute lagcha."),
         "salon": ("haircut ko price kati ho?", "Haircut NPR 600 ho, 30 minute lagcha."),
         "trek": ("Everest Base Camp trek ko price kati ho?", "Everest Base Camp Trek USD 1400 ho, 14 din ko.")}
configure()
judge = ReplyJudge(samples=JUDGE_SAMPLES)


def scenarios(biz):
    q, a = PRICE[biz]
    return [("greeting", "hlo", []), ("hours-roman", "open cha?", []), ("hours-english", "Are you open on Saturday?", []),
            ("price", q, []), ("thanks", "thank you", [("Customer", q), ("Assistant", a)])]


def run(job):
    biz, name, msg, hist, i = job
    r = BaselineReceptionist(biz)(customer_message=msg, history=hist).response
    conv = "\n".join(f"{a}: {b}" for a, b in hist)
    j = judge(msg, r, conversation=conv, facts=facts_text(biz))
    return {"biz": biz, "scenario": name, "customer": msg, "reply": r, "score": j.score, "criteria": j.criteria,
            "words": j.objective["word_count"], "ends_q": j.objective["ends_with_question"]}


jobs = [(b, n, m, h, i) for b in BUSINESSES for n, m, h in scenarios(b) for i in range(GENS)]
t0 = time.time()
with ThreadPoolExecutor(4) as ex:
    rows = list(ex.map(run, jobs))
print(f"{len(rows)} replies x {JUDGE_SAMPLES} judge samples in {time.time() - t0:.0f}s\n")
print(f"{'scenario':14}" + "".join(f"{b:>22}" for b in BUSINESSES) + "   (mean judge score / mean words / % ending in '?')")
for n, *_ in scenarios("dental"):
    line = f"{n:14}"
    for b in BUSINESSES:
        rs = [r for r in rows if r["biz"] == b and r["scenario"] == n]
        line += f"{mean(r['score'] for r in rs):>9.1f} /{mean(r['words'] for r in rs):>4.0f}w /{100 * mean(r['ends_q'] for r in rs):>3.0f}%"
    print(line)
print()
for b in BUSINESSES:
    print(f"{b:7} overall mean {mean(r['score'] for r in rows if r['biz'] == b):.1f}")
    for n in ("greeting", "hours-english", "thanks"):
        r = next(r for r in rows if r["biz"] == b and r["scenario"] == n)
        print(f"   [{n}] {r['customer']!r} -> {r['reply'][:170]!r}  ({r['score']})")
p = Path(__file__).resolve().parents[1] / "results" / f"baseline_by_business_{time.strftime('%Y%m%d_%H%M%S')}.json"
p.write_text(json.dumps(rows, ensure_ascii=False, indent=1))
print("saved", p.name)
