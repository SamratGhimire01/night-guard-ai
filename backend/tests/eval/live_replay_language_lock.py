"""LIVE replay (real running backend: real orchestrator + real Azure LLM + real DB) of the language-lock anchoring bug: two Romanized
Nepali messages lock the conversation to ne_roman, then 4 plain, substantial English messages follow. By design 3 consecutive
differing messages move the lock (for the NEXT turn), so the 4th English message must be answered in English.
Prints the reply and the persisted lock/streak after every turn. Not collected by pytest (no test_ prefix).
  python live_replay_language_lock.py <label> [business_id] [n_sessions]
Reads the lock via `docker exec ... psql` (test infrastructure only)."""
import json
import subprocess
import sys
import time
import urllib.request

BASE = "http://localhost:8010"
BIZ = sys.argv[2] if len(sys.argv) > 2 else "4ff5b470-2451-4647-a72a-71686f25fa9f"  # standing test business
STEPS = [
    "hlo, malai teeth cleaning ko barema janna man cha",
    "kati ho price",
    "Actually, can you tell me what time you open on weekends?",
    "I think I'll come on Monday morning instead, does that work?",
    "Great, can you book that for me?",
    "Thanks, and is there parking near the clinic?",
]


def post(content, token=None):
    body = json.dumps({"content": content, **({"session_token": token} if token else {})}).encode()
    req = urllib.request.Request(f"{BASE}/api/v1/widget/{BIZ}/messages", body, {"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=120) as r:
        return json.load(r)


def lock_state():
    out = subprocess.run(
        ["docker", "exec", "night_guard_ai-postgres-1", "psql", "-U", "nightguard", "-d", "nightguard", "-tA", "-F", "|", "-c",
         f"select detected_language, language_switch_streak from conversations where business_id='{BIZ}' and channel='website' "
         "order by created_at desc limit 1"], capture_output=True, text=True).stdout.strip()
    return out


label = sys.argv[1]
n = int(sys.argv[3]) if len(sys.argv) > 3 else 1
english_replies_ok = 0
for i in range(n):
    token = None
    print(f"--- session {i + 1}")
    for k, step in enumerate(STEPS):
        out = post(step, token)
        token = out["session_token"]
        print(f"  CUSTOMER: {step}\n  AGENT   : {out['response'][:230]}\n  [lock|streak after turn {k + 1}] {lock_state()}")
    final = lock_state().split("|")[0]
    english_replies_ok += final == "en"
    print(f"  => lock after the 4 English messages: {final}")
    time.sleep(3)
print(f"\n{label}: lock moved to English in {english_replies_ok}/{n} sessions")
