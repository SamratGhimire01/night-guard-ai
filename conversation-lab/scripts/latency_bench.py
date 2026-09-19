"""Real latency numbers for interactive use. Run alone (no other API load), it measures:
  A. 16000-token cap: same prompt with max_tokens 16000 vs 2000 (does the cap itself cost time?)
  B. reply latency + tokens vs reasoning_effort (default / low / minimal), and the reply QUALITY at each
     (scored by the standard default-effort x3 judge, so the yardstick doesn't move)
  C. judge latency vs effort for 1 sample, and 1 vs 3 vs 5 samples (are samples really parallel?)
Everything sequential except the samples inside one judge call (that is what is being tested)."""
import json
import sys
import time
from pathlib import Path
from statistics import mean

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import dspy
import litellm

from lab.businesses import facts_text
from lab.env import azure_settings
from lab.judge import ReplyJudge
from lab.llm import build_lm, configure
from lab.receptionist import BaselineReceptionist

REPS = 3
CASES = [  # (customer, history)
    ("hlo", []),
    ("open cha?", []),
    ("teeth cleaning ko price kati ho?", []),
    ("thank you", [("Customer", "teeth cleaning ko price kati ho?"), ("Assistant", "Teeth Cleaning NPR 1500 ho, 30 minute lagcha.")]),
]
EFFORTS = [None, "low", "minimal"]
out: dict = {}
configure()
bot = BaselineReceptionist("dental")
std_judge = ReplyJudge(samples=3)  # the yardstick for reply quality; default effort

# A. token cap (direct call, same prompt; cap is only a ceiling)
s = azure_settings()
prompt = f"{facts_text('dental')}\n\nCustomer: open cha?\nReply as the receptionist."
A = {}
for cap in (16000, 2000):
    lat = []
    for _ in range(REPS):
        t = time.time()
        litellm.completion(model=f"azure_ai/{s['AZURE_OPENAI_DEPLOYMENT']}", api_key=s["AZURE_OPENAI_API_KEY"],
                           api_base=s["AZURE_OPENAI_ENDPOINT"] + "/models", messages=[{"role": "user", "content": prompt}],
                           max_tokens=cap, temperature=1.0)
        lat.append(time.time() - t)
    A[cap] = round(mean(lat), 2)
out["A_cap_mean_latency_s"] = A
print("A. mean latency by max_tokens cap:", A, flush=True)

# B. reply latency/tokens/quality by effort
B = {}
for eff in EFFORTS:
    lm = build_lm(reasoning_effort=eff)
    lat, toks, scores = [], [], []
    for cust, hist in CASES:
        for _ in range(REPS):
            n0 = len(lm.history)
            t = time.time()
            r = bot(customer_message=cust, history=hist, lm=lm).response
            lat.append(time.time() - t)
            u = lm.history[-1].get("usage", {}) if len(lm.history) > n0 else {}
            toks.append(u.get("completion_tokens", 0))
            conv = "\n".join(f"{a}: {b}" for a, b in hist)
            scores.append(std_judge(cust, r, conversation=conv, facts=facts_text("dental")).score)
    B[str(eff)] = {"mean_latency_s": round(mean(lat), 2), "max_latency_s": round(max(lat), 2),
                   "mean_completion_tokens": round(mean(toks)), "mean_quality_score": round(mean(scores), 1), "n": len(lat)}
    print("B. reply effort", eff, B[str(eff)], flush=True)
out["B_reply_by_effort"] = B

# C. judge latency
sample_reply = "Ho — Demo Dental Clinic ko samanya khulaune samaya Monday–Friday 9:00 AM–6:00 PM ho. Saturday ra Sunday hami band chhau."
C = {}
for eff in EFFORTS:
    lm = build_lm(reasoning_effort=eff)
    for k in (1, 3, 5):
        if eff and k != 1 and eff == "minimal":
            continue
        lat = []
        for _ in range(REPS):
            t = time.time()
            ReplyJudge(samples=k, lm=lm)("open cha?", sample_reply, facts=facts_text("dental"))
            lat.append(time.time() - t)
        C[f"{eff}_x{k}"] = round(mean(lat), 2)
        print("C. judge", eff, f"x{k}", C[f"{eff}_x{k}"], "s", flush=True)
out["C_judge_mean_latency_s"] = C

p = Path(__file__).resolve().parents[1] / "results" / f"latency_bench_{time.strftime('%Y%m%d_%H%M%S')}.json"
p.write_text(json.dumps(out, indent=1))
print("saved", p.name)
