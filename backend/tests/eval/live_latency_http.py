"""LIVE end-to-end latency over HTTP against the real running backend (what a widget/website customer waits for): the same fixed 10 real
customer messages as latency_bench.py, each as the first message of a fresh widget session. Not collected by pytest.
  python live_latency_http.py <label> [rounds] [business_id]"""
import json
import statistics
import sys
import time
import urllib.request

sys.path.insert(0, ".")
BIZ = sys.argv[3] if len(sys.argv) > 3 else "f0ca2a54-d76b-4c48-b727-1b0a0faea4cd"  # Samaj Dental Clinic
MESSAGES = [
    "hlo, malai teeth cleaning ko barema janna man cha", "kati ho price", "Do you have an appointment tomorrow?",
    "Actually, can you tell me what time you open on weekends?", "open cha?", "Great, can you book that for me?",
    "भोलि दाँत सफा गर्न मिल्छ?", "I want to cancel my appointment, I can't make it", "thanks!",
    "My tooth has been hurting for two days, what should I do?",
]
walls = []
for r in range(int(sys.argv[2]) if len(sys.argv) > 2 else 2):
    for m in MESSAGES:
        body = json.dumps({"content": m}).encode()
        req = urllib.request.Request(f"http://localhost:8010/api/v1/widget/{BIZ}/messages", body, {"Content-Type": "application/json"})
        t = time.perf_counter()
        with urllib.request.urlopen(req, timeout=120) as resp:
            out = json.load(resp)
        walls.append((time.perf_counter() - t) * 1000)
        print(f"r{r} {walls[-1]:7.0f}ms  {m[:40]!r:44} -> {out['response'][:70]!r}", flush=True)
w = sorted(walls)
print(f"\n{sys.argv[1]}: n={len(w)} mean={statistics.mean(w):.0f}ms median={statistics.median(w):.0f}ms min={w[0]:.0f} p90={w[int(0.9 * (len(w) - 1))]:.0f} max={w[-1]:.0f}")
