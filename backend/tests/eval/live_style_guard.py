"""LIVE adversarial probe (real running backend: real orchestrator + real Azure LLM + real DB,
standing Samaj Dental Clinic test business) for the style guard added in orchestrator._handle_turn
(style_checks.check_response_style / repair_response_style): rule 4's banned-phrase list, rule 16's
one-question-per-turn limit, rule 17's per-category length budget.

Each case below is worded to *tempt* the model into a real violation, not to force one — if the
model doesn't take the bait even after the prompt-level rules are already doing their job, that's
a legitimate result: print it honestly rather than reshaping the message until something breaks.

Not collected by pytest (no test_ prefix). usage: python live_style_guard.py
"""
import json
import urllib.request

BASE = "http://localhost:8010"
DENTAL = "f0ca2a54-d76b-4c48-b727-1b0a0faea4cd"  # Samaj Dental Clinic


def post(business_id, content):
    body = json.dumps({"content": content}).encode()
    req = urllib.request.Request(
        f"{BASE}/api/v1/widget/{business_id}/messages", body, {"Content-Type": "application/json"}
    )
    with urllib.request.urlopen(req, timeout=120) as r:
        return json.load(r)


CASES = [
    (
        "banned-phrase bait (rule 4)",
        "Ok that answered everything, thank you so much for your help today, I really appreciate it!",
    ),
    (
        "two-questions bait (rule 16): ambiguous on service AND timing",
        "I want to come in for some dental work soon, not totally sure what I need done though -- "
        "whenever you have an opening works for me, what would you suggest?",
    ),
    (
        "length-ceiling bait (rule 17, SHORT budget = location intent, 45 words)",
        "Hi, where exactly is your clinic located? I'm coming from Kalanki and don't know the area at "
        "all, is there a landmark nearby I should look for, and is parking easy to find right there or "
        "should I plan for that?",
    ),
]

for label, message in CASES:
    print(f"\n=== {label} ===")
    print(f"CUSTOMER: {message}")
    out = post(DENTAL, message)
    print(f"intent: {out['intent']}")
    print(f"agent_message_id: {out['agent_message_id']}")
    print(f"AGENT (final, post-guard): {out['response']}")
