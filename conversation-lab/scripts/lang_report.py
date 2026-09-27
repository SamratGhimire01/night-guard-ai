"""Aggregate lang_run.py output into per-arm x per-type tables, and print readable transcripts.
  python scripts/lang_report.py results/lang/a.jsonl [b.jsonl ...]            # tables
  python scripts/lang_report.py --transcripts SCENARIO_ID [--rep 0] files...  # side-by-side per arm
Definitions (all fixed BEFORE looking at results):
  match       reply label is in the accepted set for the turn's expectation (turns with exp=None always count)
  family      en | roman (ne_roman + mixed) | deva. 'flip-flop' = on a NEUTRAL turn (no language evidence in the customer message)
              the reply family differs from the previous reply's family. This is the original Phase 25 bug, measured directly.
  latency     for the first switch/explicit turn of a run: 0 = the very reply after it is already right; k = k turns late;
              never = no later turn ever got it right."""
import json
import sys
from pathlib import Path
from collections import defaultdict
from statistics import mean

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

ACCEPT = {"en": {"en"}, "roman": {"ne_roman", "mixed"}, "deva": {"ne_deva"}, "mix": {"mixed", "ne_roman"},
          "mix_en": {"en", "mixed"}, "deva_mix": {"ne_deva", "mixed"}}


def family(label):
    return {"en": "en", "ne_deva": "deva", "ne_roman": "roman", "mixed": "roman"}.get(label, "?")


def ok(turn):
    return turn["exp"] is None or turn["label"] in ACCEPT[turn["exp"]]


def _fix_deva(text, label):
    """Labeler fix applied to EVERY arm: a reply containing Devanagari is ne_deva unless Latin letters dominate (English service
    names inside a Devanagari reply are data, not a language switch). Deterministic; no LLM."""
    import re
    d, la = len(re.findall("[ऀ-ॿ]", text)), len(re.findall("[A-Za-z]", text))
    return label if not d else ("ne_deva" if d >= 0.3 * (d + la) else "mixed")


def load(paths):
    rows = []
    for p in paths:
        rows += [json.loads(l) for l in open(p) if l.strip()]
    from lab.lang_scenarios import ALL  # rows of retired scenarios (HB3: Azure content-filter false positive) are excluded
    rows = [r for r in rows if r["scenario"] in ALL]
    for r in rows:
        for t in r["turns"]:
            t["label"] = _fix_deva(t["reply"], t["label"])
    return rows


def run_stats(row):
    t = row["turns"]
    flips = [i for i in range(1, len(t)) if t[i]["kind"] == "neutral" and family(t[i]["label"]) != family(t[i - 1]["label"])]
    neutral = sum(1 for i in range(1, len(t)) if t[i]["kind"] == "neutral")
    lat = None
    sw = next((i for i, x in enumerate(t) if x["kind"] in ("switch", "explicit")), None)
    if sw is not None:
        lat = next((k for k in range(len(t) - sw) if ok(t[sw + k])), "never")
    return {"match": [ok(x) for x in t], "flips": len(flips), "neutral": neutral, "latency": lat,
            "seq": tuple(family(x["label"]) for x in t)}


def tables(rows):
    arms = list(dict.fromkeys(r["arm"] for r in rows))
    print(f"{'arm':10}{'type':5}{'runs':>5}{'turn match':>13}{'neutral flips':>16}{'switch latency (0 = immediate)':>34}")
    for arm in arms:
        for ty in "ABCD":
            rs = [r for r in rows if r["arm"] == arm and r["type"] == ty]
            if not rs:
                continue
            st = [run_stats(r) for r in rs]
            m = [x for s in st for x in s["match"]]
            fl, ne = sum(s["flips"] for s in st), sum(s["neutral"] for s in st)
            lats = [s["latency"] for s in st if s["latency"] is not None]
            never = sum(1 for x in lats if x == "never")
            nums = [x for x in lats if x != "never"]
            lat = (f"mean {mean(nums):.1f} (n={len(lats)}, never={never})" if nums else (f"never x{never}" if lats else "-"))
            print(f"{arm:10}{ty:5}{len(rs):>5}{sum(m):>7}/{len(m):<5}{fl:>9}/{ne:<6}{lat:>34}")
        rs = [r for r in rows if r["arm"] == arm]
        st = [run_stats(r) for r in rs]
        m = [x for s in st for x in s["match"]]
        print(f"{arm:10}{'ALL':5}{len(rs):>5}{sum(m):>7}/{len(m):<5}{sum(s['flips'] for s in st):>9}/{sum(s['neutral'] for s in st):<6}")
        print()


def stability(rows):
    print("Run-to-run stability (distinct reply-family sequences across reps of the same scenario; 1 = identical every time):")
    by = defaultdict(set)
    for r in rows:
        by[(r["arm"], r["scenario"])].add(run_stats(r)["seq"])
    for arm in dict.fromkeys(r["arm"] for r in rows):
        d = [(s, len(v)) for (a, s), v in by.items() if a == arm]
        print(f"  {arm:10} scenarios with 1 distinct sequence: {sum(1 for _, n in d if n == 1)}/{len(d)}   " +
              " ".join(f"{s.split('-')[0]}:{n}" for s, n in d if n > 1))


def transcripts(rows, sid, rep):
    for arm in dict.fromkeys(r["arm"] for r in rows):
        for r in rows:
            if r["arm"] == arm and r["scenario"] == sid and r["rep"] == rep:
                print(f"\n===== {sid} | arm={arm} | rep{rep} =====")
                for t in r["turns"]:
                    flag = "" if ok(t) else "   <-- MISMATCH"
                    print(f"C [{t['kind']:8} exp={t['exp']}]: {t['customer']}\nA [{t['label']:8}]: {t['reply']}{flag}")


if __name__ == "__main__":
    a = sys.argv[1:]
    rep = int(a[a.index("--rep") + 1]) if "--rep" in a else 0
    if "--rep" in a:
        del a[a.index("--rep"):a.index("--rep") + 2]
    if a and a[0] == "--transcripts":
        transcripts(load(a[2:]), a[1], rep)
    else:
        rows = load(a)
        tables(rows)
        stability(rows)
