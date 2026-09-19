"""Print score + no_reflexive_question for chosen result files (used to compare before/after the criterion refinement)."""
import json, sys
for f in sys.argv[1:]:
    rs = json.load(open(f))["results"]
    print("##", f.split("/")[-1])
    for r in rs:
        print(f"  {r['group'][:28]:28}{r['label']:5} score {r['score']:5.1f}  no_reflexive {r['criteria']['no_reflexive_question']:.1f}  {r['text'][:52]!r}")
