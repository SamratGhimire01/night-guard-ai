"""Summarize judged replies (lang_judge_run.py output): mean judge total + language_match per arm x type, split by turn kind
because the judge is only VALIDATED for language_match on turns with real language signal (see judge_check_v1.txt: it fails
on neutral 'thanks' after Roman Nepali -- it rewards answering an English word in English). Paired prod-vs-hybrid comparison
on identical (scenario, rep, turn) cells with a cluster bootstrap over scenarios (turns within a scenario are correlated).
  python scripts/lang_judge_report.py results/lang/judged_main.jsonl [results/lang/judged_ctl.jsonl]"""
import json
import random
import sys
from collections import defaultdict
from statistics import mean

SIGNAL = {"signal", "switch", "explicit", "mix"}


def load(paths):
    rows = [json.loads(l) for p in paths for l in open(p) if l.strip()]
    for r in rows:
        r["lm"], r["tot"] = r["criteria"]["language_match"], r["score"]
    return rows


def table(rows):
    print(f"{'arm':10}{'type':5}{'n':>5}{'judge total':>13}{'lang_match (signal turns)':>27}{'lang_match (neutral turns)*':>29}")
    for arm in dict.fromkeys(r["arm"] for r in rows):
        for ty in ("A", "B", "C", "D", "ALL"):
            rs = [r for r in rows if r["arm"] == arm and (ty == "ALL" or r["type"] == ty)]
            if not rs:
                continue
            sg = [r["lm"] for r in rs if r["kind"] in SIGNAL]
            ne = [r["lm"] for r in rs if r["kind"] == "neutral"]
            f = lambda x: f"{mean(x):.2f} (n={len(x)})" if x else "-"
            print(f"{arm:10}{ty:5}{len(rs):>5}{mean(r['tot'] for r in rs):>13.1f}{f(sg):>27}{f(ne):>29}")
        print()
    print("* neutral-turn language_match is NOT trusted (judge rewards English replies to an English 'thanks'); use the flip metric.")


def paired(rows, a, b, key, only=None):
    cells = defaultdict(dict)
    for r in rows:
        if only is None or r["kind"] in only:
            cells[(r["scenario"], r["rep"], r["turn"])][r["arm"]] = r[key]
    d = [(s, v[b] - v[a]) for (s, _, _), v in cells.items() if a in v and b in v]
    by = defaultdict(list)
    for s, x in d:
        by[s].append(x)
    scen = list(by)
    boots = []
    rnd = random.Random(0)
    for _ in range(2000):
        pick = [x for s in (rnd.choice(scen) for _ in scen) for x in by[s]]
        boots.append(mean(pick))
    boots.sort()
    return mean(x for _, x in d), boots[50], boots[1949], len(d)


if __name__ == "__main__":
    rows = load(sys.argv[1:])
    table(rows)
    print("\nPaired hybrid - prod (same scenario/rep/turn), 95% cluster-bootstrap CI over scenarios:")
    for key, only, lab in (("tot", None, "judge total, all turns"), ("lm", SIGNAL, "language_match, signal turns"),
                           ("tot", {"neutral"}, "judge total, neutral turns")):
        m, lo, hi, n = paired(rows, "prod", "hybrid", key, only)
        print(f"  {lab:34} {m:+.2f}  [{lo:+.2f}, {hi:+.2f}]  n={n}")
