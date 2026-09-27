"""Aggregate L8 anchor runs. Metrics (fixed before any run):
  mislabel   turns whose truth CONTRADICTS the current lock (plain English while locked to Roman/Devanagari Nepali, or Roman while
             locked to English): the fraction where the LLM's raw `message_language` != truth. This is the anchoring bug itself.
  streak     for expect=switch_*: the lock moved to the target language; `at` = the customer turn index (1-based) whose processing
             moved it. By design (3 consecutive differing messages) the ideal is the 3rd differing turn. `never` = never moved.
  post-reply for switch runs: the reply label on every turn AFTER the lock moved is in the target family (the customer actually
             gets the new language).
  hold       for expect=hold_roman: the lock never leaves ne_roman and every reply is in the Roman/mixed family."""
import json
import sys
from collections import defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from lab.lang_report_shim import family  # noqa: E402

TARGET = {"switch_to_en": "en", "switch_to_roman": "ne_roman"}
RAW = {"en": {"en"}, "roman": {"ne_roman"}, "deva": {"ne_deva"}}


def load(paths):
    rows = []
    for p in paths:
        rows += [json.loads(l) for l in open(p) if l.strip()]
    return rows


def lock_lang_of(truth):
    return {"en": "en", "roman": "ne_roman", "deva": "ne_deva"}[truth]


def main(paths):
    rows = load(paths)
    arms = list(dict.fromkeys(r["arm"] for r in rows))
    print(f"{'arm':10}{'mislabel (truth contradicts lock)':>38}{'switch runs moved / n':>24}{'  moved at turn (dist)':>26}{'post-reply ok':>16}{'hold runs kept / n':>22}")
    for arm in arms:
        rs = [r for r in rows if r["arm"] == arm]
        mis = tot = 0
        for r in rs:
            for t in r["turns"]:
                lb, tr = t["meta"]["lock_before"], t["truth"]
                if tr in RAW and lb and lb != lock_lang_of(tr):
                    tot += 1
                    mis += t["meta"]["llm_message_language"] not in RAW[tr]
        sw = [r for r in rs if r["expect"] in TARGET]
        moved, at, post_ok, post_n = 0, defaultdict(int), 0, 0
        for r in sw:
            tgt = TARGET[r["expect"]]
            idx = next((i for i, t in enumerate(r["turns"]) if t["meta"]["lock_after"] == tgt and (i == 0 or r["turns"][i - 1]["meta"]["lock_after"] != tgt)), None)
            if idx is None:
                at["never"] += 1
                continue
            moved += 1
            at[idx + 1] += 1
            for t in r["turns"][idx + 1:]:
                post_n += 1
                post_ok += family(t["label"]) == family(tgt)
        hd = [r for r in rs if r["expect"] == "hold_roman"]
        kept = sum(all(t["meta"]["lock_after"] == "ne_roman" for t in r["turns"]) and
                   all(family(t["label"]) == "roman" for t in r["turns"] if t["truth"] != "neutral") for r in hd)
        print(f"{arm:10}{mis:>26}/{tot:<11}{moved:>18}/{len(sw):<5}{str(dict(sorted(at.items(), key=lambda x: str(x[0])))):>26}{post_ok:>10}/{post_n:<5}{kept:>16}/{len(hd):<5}")
    print()
    for sid in dict.fromkeys(r["scenario"] for r in rows):
        line = []
        for arm in arms:
            rs = [r for r in rows if r["arm"] == arm and r["scenario"] == sid]
            seqs = [">".join(str(t["meta"]["lock_after"] or "-")[:2] for t in r["turns"]) for r in rs]
            line.append(f"{arm}: " + " | ".join(seqs))
        print(sid, *line, sep="\n   ")


if __name__ == "__main__":
    main(sys.argv[1:])
