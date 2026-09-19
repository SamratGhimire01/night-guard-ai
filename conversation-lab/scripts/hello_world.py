"""Acceptance step 2: prove the sandbox reaches the REAL Azure deployment."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import dspy

from lab.llm import configure

lm = configure()
out = dspy.Predict("question -> answer")(question="Reply with exactly: hello world from the conversation lab")
last = lm.history[-1]
print("answer        :", out.answer)
print("model         :", last.get("model"))
print("response model:", last["response"].model)
print("usage         :", dict(last["usage"]) if last.get("usage") else None)
