"""LIVE check (real running backend + real Azure LLM + real DB) of the per-business language mode. Uses the business owner's
API (the same PATCH /business/me the dashboard calls) to toggle the mode, and the public website-widget API as the customer.
Not collected by pytest. usage: python live_replay_language_mode.py <owner_email> <password>"""
import json
import sys
import urllib.request

BASE = "http://localhost:8010/api/v1"


def call(method, path, body=None, token=None):
    req = urllib.request.Request(BASE + path, json.dumps(body).encode() if body is not None else None,
                                 {"Content-Type": "application/json", **({"Authorization": "Bearer " + token} if token else {})}, method=method)
    with urllib.request.urlopen(req, timeout=120) as r:
        return json.load(r)


tok = call("POST", "/auth/login", {"email": sys.argv[1], "password": sys.argv[2]})["access_token"]
biz = call("GET", "/business/me", token=tok)["id"]


def set_mode(mode):
    got = call("PATCH", "/business/me", {"language_mode": mode}, tok)["language_mode"]
    print(f"\n##### owner sets language_mode={mode} -> API now reports {got}")


def visitor(steps):
    token = None
    for s in steps:
        out = call("POST", f"/widget/{biz}/messages", {"content": s, **({"session_token": token} if token else {})})
        token = out["session_token"]
        print(f"  CUSTOMER: {s}\n  AGENT   : {out['response'][:260].replace(chr(10), ' / ')}")


set_mode("automatic")
print("-- new conversation, automatic mode: goes straight to the assistant (no language question)")
visitor(["hello, how much is a cleaning?"])

set_mode("ask")
print("-- new conversation, ask mode, customer answers 'Nepali', then writes plain English, then explicitly asks for English")
visitor(["hello", "Nepali", "What are your opening hours?", "Do you take walk-ins?", "How much is a cleaning?",
         "Is there parking nearby?", "Can we switch to English please?", "And how long does a cleaning take?"])
print("-- new conversation, ask mode, customer answers 'English', then writes Romanized Nepali (no passive switch in ask mode)")
visitor(["hi", "English please", "malai bholi bihana cleaning garna man cha, milcha?", "ani kati parcha?"])

set_mode("automatic")
print("-- new conversation after toggling back: no language question again")
visitor(["hello"])
