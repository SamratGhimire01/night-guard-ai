"""Item-level before/after between two judge result files (same set), optionally filtered to group-id substrings."""
import json, sys
b, a, *pat = sys.argv[1:]
B = {(r["group"], r["label"], r["text"]): r for r in json.load(open(b))["results"]}
for r in json.load(open(a))["results"]:
    k = (r["group"], r["label"], r["text"])
    if pat and not any(p in r["group"] for p in pat):
        continue
    o = B[k]
    print(f"{r['group'][:26]:26}{r['label']:5} {o['score']:5.1f} -> {r['score']:5.1f}   no_reflexive {o['criteria']['no_reflexive_question']:.1f} -> {r['criteria']['no_reflexive_question']:.1f}   {r['text'][:44]!r}")
