"""LIVE replay (real running backend: real orchestrator + real Azure LLM + real DB, standing test business only) of the
real reported scenario: customer asks for "bholi" (tomorrow); the day has no availability so the SYSTEM offers the next
open day; the customer picks "first one". The reply to the pick must NOT restate a date "switch" the customer never made.
Not collected by pytest (no test_ prefix). usage: python live_replay_slot_pick.py <label> [n_sessions] [offered|genuine]
  offered (default): the reported scenario -- must produce NO switch line and must not confirm the closed day.
  genuine: Monday is the working date with its slots just shown, then "actually let's do Tuesday instead" -- MUST still be acknowledged."""
import json
import re
import sys
import time
import urllib.request

BASE = "http://localhost:8010"
BIZ = "4ff5b470-2451-4647-a72a-71686f25fa9f"  # "Standing Test Biz Premium": Basic Cleaning, Whitening; Mon-Thu 9-5, Fri 9-2, Sat/Sun closed
MODES = {
    "offered": ["bholi Basic Cleaning book garna paryo", "first one"],
    "genuine": ["Monday ko lagi Basic Cleaning book garna paryo, kun samaya khali cha?", "actually let's do Tuesday instead"],
}
SWITCH = re.compile(r"ko sattama|instead of|को सट्टा|switching to", re.I)


def post(content, token=None):
    body = json.dumps({"content": content, **({"session_token": token} if token else {})}).encode()
    req = urllib.request.Request(f"{BASE}/api/v1/widget/{BIZ}/messages", body, {"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=120) as r:
        return json.load(r)


label, n = sys.argv[1], int(sys.argv[2]) if len(sys.argv) > 2 else 3
mode = sys.argv[3] if len(sys.argv) > 3 else "offered"
STEPS = MODES[mode]
hits = 0
for i in range(n):
    token = None
    print(f"--- session {i + 1}")
    for step in STEPS:
        out = post(step, token)
        token = out["session_token"]
        print(f"  CUSTOMER: {step}\n  AGENT   : {out['response']}   [{out['intent']}]")
    fired = bool(SWITCH.search(out["response"]))
    wrong_day = mode == "offered" and "Sunday" in out["response"]  # the pick must never re-confirm the closed day
    hits += fired or wrong_day if mode == "offered" else 0
    hits += fired if mode == "genuine" else 0
    print(f"  => switch acknowledgment present: {fired}" + (f" | confirms the CLOSED day: {wrong_day}" if mode == "offered" else ""))
    time.sleep(4)
print(f"\n{label} [{mode}]: " + (f"BAD outcome (redundant acknowledgment or closed-day confirmation) in {hits}/{n} sessions" if mode == "offered" else f"genuine switch acknowledged in {hits}/{n} sessions (want {n}/{n})"))
