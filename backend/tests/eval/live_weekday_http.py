"""LIVE check over HTTP (real running backend + real Azure LLM + real DB) of weekday -> date resolution, two real shapes:
  clear: one message "book a teeth cleaning on <Weekday> at 10am"          -> the reply states the resolved date
  terse: "what times do you have for a teeth cleaning tomorrow?" then "actually, is <Weekday> morning possible instead?"
A session passes when the reply to the weekday message states the CORRECT calendar date for that weekday. Cycles through all 7 weekdays.
Uses whichever business id is given (a throwaway test business); leaves its conversations in place.
  python live_weekday_http.py <label> <business_id> [rounds] [only_weekday_index]
When the weekday named IS today's weekday, today and next week are both accepted ("Sunday" said on a Sunday is ambiguous)."""
import json
import sys
import urllib.request
from datetime import date, timedelta

BIZ, ROUNDS = sys.argv[2], int(sys.argv[3]) if len(sys.argv) > 3 else 7
ONLY = int(sys.argv[4]) if len(sys.argv) > 4 else None
DAYS = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"]
today = date.today()


def post(content, token=None):
    body = json.dumps({"content": content, **({"session_token": token} if token else {})}).encode()
    req = urllib.request.Request(f"http://localhost:8010/api/v1/widget/{BIZ}/messages", body, {"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=120) as r:
        return json.load(r)


def stated(d: date) -> str:
    return f"{d:%A}, {d:%B} {d.day}"


tally = {"clear": [0, 0], "terse": [0, 0]}
for r in range(ROUNDS):
    for wd in ([ONLY] if ONLY is not None else range(7)):
        delta = (wd - today.weekday()) % 7
        accepted = [today + timedelta(days=delta)] if delta else [today, today + timedelta(days=7)]
        want = accepted[0]
        # business is closed Sat/Sun: the date is still stated (as an unavailable-day reply), so the check reads the date it names
        for shape in ("clear", "terse"):
            if shape == "clear":
                out = post(f"book a teeth cleaning on {DAYS[wd]} at 10am")
            else:
                first = post("what times do you have for a teeth cleaning tomorrow?")
                out = post(f"actually, is {DAYS[wd]} morning possible instead?", first["session_token"])
            ok = any(stated(d) in out["response"] for d in accepted)
            tally[shape][0] += ok
            tally[shape][1] += 1
            if not ok:
                print(f"  MISS [{shape}] {DAYS[wd]} (want {stated(want)}): {out['response'][:150]!r}", flush=True)
print(f"{sys.argv[1]}: clear {tally['clear'][0]}/{tally['clear'][1]}   terse {tally['terse'][0]}/{tally['terse'][1]}   (today={today} {DAYS[today.weekday()]})")
