"""Does a narrow prompt fix stop the 'thanks -> unsolicited upsell' violation, without hurting anything else?
Arms = current production template | variant A (example-only) | variant B (A + rule-3 sentence), all via the
in-memory patched template (intent.py is never modified).
 1. CLOSING SET: 10 fresh closing scenarios x 4 gens x 3 arms. Mechanical check (no judge): does the reply carry an
    unsolicited offer/tail? + judge score x3.
 2. REGRESSION: every non-closing item of the seed set (train+val) x 1 gen, production vs the winning variant; paired
    judge diff with bootstrap CI (the fix must not move unrelated replies).
Checkpointed + rate-limit backoff like eval_arms."""
import json, random, re, sys, time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from statistics import mean, median

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from lab.items import Item
from lab.judge import ReplyJudge
from lab.llm import configure
from lab.production_prompt import TEMPLATE, production_reply
from lab.seed_set import TRAIN, VAL
from lab.thanks_patch import variant_a, variant_b, variant_c

GENS, JS = 4, 3
lm = configure()
judge = ReplyJudge(samples=JS)
T = {"current": TEMPLATE, "A": variant_a(), "B": variant_b(), "C": variant_c()}
h = lambda q, a: [("Customer", q), ("Assistant", a)]
CLOSINGS = [  # fresh scenarios (h1:trek-thanks, the real failing case, is included as the first one)
    Item("c-trek-thanks", "trek", "thanks!", h("Everest Base Camp kati din ko ho?", "Everest Base Camp Trek 14 din ko ho.")),
    Item("c-trek-deposit", "trek", "thank you", h("How much is the deposit for Poon Hill?", "30% deposit — USD 135 for Poon Hill.")),
    Item("c-trek-deva", "trek", "धन्यवाद", h("permit ko lagi alag paisa lagcha?", "Permit price ma nai included cha.")),
    Item("c-dental-thanks", "dental", "thank you", h("teeth cleaning ko price kati ho?", "Teeth Cleaning NPR 1500 ho, 30 minute lagcha.")),
    Item("c-dental-dhanyabad", "dental", "dhanyabad", h("open cha?", "Cha — Somabar dekhi Sukrabar, 9:00 AM–6:00 PM.")),
    Item("c-dental-okthanks", "dental", "ok thanks", h("location chai?", "New Baneshwor, Kathmandu ma cha.")),
    Item("c-dental-huss", "dental", "huss", h("cancel garna paryo bhane kati agadi bhannu parcha?", "Kam se kam 4 ghanta agadi.")),
    Item("c-salon-thanks", "salon", "thanks!", h("facial ko price kati ho?", "Facial NPR 1800 ho, 60 minute lagcha.")),
    Item("c-salon-soMuch", "salon", "thank you so much", h("walk-in milcha?", "Milcha, stylist free bhaye.")),
    Item("c-salon-huss", "salon", "huss dhanyabad", h("esewa le tirna milcha?", "Milcha, cash ra eSewa dubai.")),
]
CLOSINGS_EN = [  # English exchanges (run 1's real failure was English); first one = the exact failing case (h1:trek-thanks)
    Item("e-trek-ebc", "trek", "thanks!", h("how long is the Everest Base Camp trek?", "14 days.")),
    Item("e-trek-price", "trek", "thank you", h("How much is the Poon Hill trek?", "Poon Hill Trek is USD 450.")),
    Item("e-salon-time", "salon", "thanks!", h("How long does a haircut take?", "About 30 minutes.")),
    Item("e-salon-price", "salon", "thank you so much", h("How much is a facial?", "A facial is NPR 1800.")),
    Item("e-dental-hours", "dental", "thank you", h("What are your hours?", "Monday to Friday, 9:00 AM–6:00 PM.")),
    Item("e-dental-price", "dental", "thanks", h("how much is a root canal?", "A root canal is NPR 9000.")),
]
GENS_EN = 6
TAIL = re.compile(r"if you(?:'d| would) like|let me know|anything else|need anything|feel free|would you like|do you want|want me to|"
                  r"\bbook|availab|more (?:details|information|info)|sahayog chahiyo|bhanuhos|any other|else|\?", re.I)
ckpt = Path(__file__).resolve().parents[1] / "results" / "thanks_experiment_ckpt.jsonl"
done = {(r["exp"], r["arm"], r["item"], r["gen"]): r for r in map(json.loads, ckpt.read_text().splitlines())} if ckpt.exists() else {}


def one(job):
    exp, arm, it, g = job
    key = (exp, arm, it.id, g)
    if key in done:
        return done[key]
    for attempt in range(10):
        try:
            reply = production_reply(it, lm, T[arm])
            j = judge(it.customer, reply, conversation=it.convo(), facts=it.facts())
            break
        except Exception as e:  # noqa: BLE001
            if "RateLimit" in type(e).__name__ or "429" in str(e):
                time.sleep(15 * (attempt + 1)); continue
            if "content management policy" in str(e):  # Azure prompt filter: record + exclude the item from both arms
                r = {"exp": exp, "arm": arm, "item": it.id, "gen": g, "customer": it.customer, "reply": "", "score": None,
                     "words": 0, "tail": False, "filtered": True}
                with open(ckpt, "a") as f:
                    f.write(json.dumps(r, ensure_ascii=False) + "\n")
                return r
            raise
    r = {"exp": exp, "arm": arm, "item": it.id, "gen": g, "customer": it.customer, "reply": reply, "score": j.score,
         "words": len(reply.split()), "tail": bool(TAIL.search(reply))}
    with open(ckpt, "a") as f:
        f.write(json.dumps(r, ensure_ascii=False) + "\n")
    return r


def boot(d, n=5000):
    rnd = random.Random(0); ms = sorted(mean(rnd.choices(d, k=len(d))) for _ in range(n)); return ms[int(.025 * n)], ms[int(.975 * n)]


def run(jobs):
    with ThreadPoolExecutor(3) as ex:
        return list(ex.map(one, jobs))


rows = run([("closing", a, it, g) for a in T for it in CLOSINGS for g in range(GENS)])
print(f"\nCLOSING SET ({len(CLOSINGS)} scenarios x {GENS} gens per arm). Mechanical: reply carries an unsolicited offer/tail/question (regex).")
print(f"{'arm':9}{'replies w/ tail':>17}{'mean words':>12}{'judge mean':>12}{'judge median':>14}")
for a in T:
    rs = [r for r in rows if r["arm"] == a]
    print(f"{a:9}{sum(r['tail'] for r in rs):>12}/{len(rs)}{mean(r['words'] for r in rs):>12.1f}{mean(r['score'] for r in rs):>12.1f}{median(r['score'] for r in rs):>14.1f}")
print("per scenario, replies with tail (of 4): " + "  ".join(f"{it.id[2:]}: " + "/".join(str(sum(r['tail'] for r in rows if r['arm'] == a and r['item'] == it.id)) for a in T) for it in CLOSINGS) + "   (current/A/B)")
rows_en = run([("closing_en", a, it, g) for a in T for it in CLOSINGS_EN for g in range(GENS_EN)])
print(f"\nENGLISH CLOSING SET ({len(CLOSINGS_EN)} scenarios x {GENS_EN} gens per arm; first scenario = run 1's real failing case)")
print(f"{'arm':9}{'replies w/ tail':>17}{'mean words':>12}{'judge mean':>12}{'judge median':>14}   tails on the exact failing case (of {GENS_EN})")
for a in T:
    rs = [r for r in rows_en if r["arm"] == a]
    ex = [r for r in rs if r["item"] == "e-trek-ebc"]
    print(f"{a:9}{sum(r['tail'] for r in rs):>12}/{len(rs)}{mean(r['words'] for r in rs):>12.1f}{mean(r['score'] for r in rs):>12.1f}{median(r['score'] for r in rs):>14.1f}   {sum(r['tail'] for r in ex)}/{len(ex)}")
for a in T:
    for r in [r for r in rows_en if r["arm"] == a and r["tail"]][:2]:
        print(f"   e.g. [{a}] {r['customer']!r} -> {r['reply'][:120]!r}")
_tails = {a: sum(r["tail"] for r in rows_en + rows if r["arm"] == a) for a in ("A", "B")}  # regression check stays on A/B (C is diagnostic)
best = "C"  # narrowest variant that fully fixes the English closings (rule-3 sentence only); B regression was run first
print(f"\nREGRESSION check uses variant {best}: all NON-closing seed items x 1 gen, current vs {best}")
reg = [i for i in TRAIN + VAL if not any(i.id.endswith(x) for x in ("thanks", "huss"))]
rr = run([("regress", a, it, 0) for a in ("current", best) for it in reg])
bad = {r["item"] for r in rr if r.get("filtered")}
print("items rejected by Azure's content filter (excluded from both arms):", sorted(bad) or "none")
P = {r["item"]: r["score"] for r in rr if r["arm"] == "current" and r["item"] not in bad}; Q = {r["item"]: r["score"] for r in rr if r["arm"] == best and r["item"] not in bad}
d = [Q[k] - P[k] for k in P]; lo, hi = boot(d)
print(f"{len(d)} items: current {mean(P.values()):.1f} vs {best} {mean(Q.values()):.1f} | paired diff mean {mean(d):+.1f} median {median(d):+.1f} 95% CI [{lo:+.1f}, {hi:+.1f}] | better>5: {sum(x > 5 for x in d)} worse>5: {sum(x < -5 for x in d)}")
for k in sorted(P, key=lambda k: Q[k] - P[k])[:4]:
    print(f"   biggest drops: {k:16} {P[k]:.0f} -> {Q[k]:.0f}")
