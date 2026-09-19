"""LIVE check against the REAL running backend (localhost:8010, real orchestrator + real Azure LLM + real DB):
10 fresh widget sessions on the standing test business -- an English question, then a closing ("thanks!"...).
Does the reply to the closing carry an unsolicited offer/tail? (same regex as scripts/thanks_experiment.py)
usage: live_thanks_check.py <label> [base|extra|all]   -> results/live_thanks_<label>.json   (base = 10 sessions, extra = 20 more, all = 30)"""
import json, re, sys, time, urllib.request
from pathlib import Path

BASE = "http://localhost:8010"
BIZ = "4ff5b470-2451-4647-a72a-71686f25fa9f"  # "Standing Test Biz Premium": Basic Cleaning $75/30min, Whitening $150/45min, Mon-Thu 9-5, Fri 9-2
SCEN = [("How much is the Whitening?", "thanks!"), ("How long does a basic cleaning take?", "thank you"),
        ("What are your hours?", "thanks!"), ("How much is a Basic Cleaning?", "thank you so much"),
        ("How much is the Whitening and how long does it take?", "thanks")] * 2
EXTRA = [("How long is a Whitening session?", "thanks"), ("Is Friday open all day?", "thank you"), ("do you have a cleaning service?", "thanks!"),
         ("What's the price of cleaning and whitening?", "ok thanks"), ("Are you open on Saturday?", "thanks!"),
         ("How much is a cleaning?", "Thanks a lot!"), ("What services do you offer?", "thank you!"), ("when do you close on Friday?", "thanks"),
         ("how long does whitening take?", "thank you very much"), ("What time do you open on Monday?", "thanks!")] * 2
TAIL = re.compile(r"if you(?:'d| would) like|let me know|anything else|need anything|feel free|would you like|do you want|want me to|"
                  r"\bbook|availab|more (?:details|information|info)|sahayog chahiyo|bhanuhos|any other|else|\?", re.I)


def post(content, token=None):
    body = json.dumps({"content": content, **({"session_token": token} if token else {})}).encode()
    req = urllib.request.Request(f"{BASE}/api/v1/widget/{BIZ}/messages", body, {"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=120) as r:
        return json.load(r)


label = sys.argv[1]
which = sys.argv[2] if len(sys.argv) > 2 else "base"
SCEN = {"base": SCEN, "extra": EXTRA, "all": SCEN + EXTRA}[which]
rows = []
for q, closing in SCEN:
    a = post(q)
    b = post(closing, a["session_token"])
    rows.append({"question": q, "answer": a["response"], "closing": closing, "reply": b["response"], "intent": b["intent"], "tail": bool(TAIL.search(b["response"]))})
    print(f"[{'TAIL' if rows[-1]['tail'] else 'ok  '}] {closing!r:22} (after {q[:34]!r}) -> {b['response'][:140]!r}  [{b['intent']}]", flush=True)
    time.sleep(6)
print(f"\n{label}: replies to the closing with an unsolicited tail: {sum(r['tail'] for r in rows)}/{len(rows)}")
(Path(__file__).resolve().parents[1] / "results" / f"live_thanks_{label}.json").write_text(json.dumps(rows, ensure_ascii=False, indent=1))
