"""Mechanical decline-wording fidelity: compares each reply with the ACTUAL production decline template read from
intent.py rule 0 (via lab.production_prompt, read-only). The judge cannot see wording/identity drift (it scored "this
clinic" declines 94-100), so this is a plain string check.

Classes for a reply on an item where a decline is correct:
  exact        - identical to the production sentence with the real business name (after whitespace/quote-mark normalisation only)
  typography   - identical once dash type/spacing is normalised (e.g. "Riverside Dental—appointments")
  drift        - is a decline (uses the production's opening, or another decline stem) but wording differs
  no_decline   - not a decline at all (answered, or something else)
and, separately, name drift: says "this clinic/business" instead of the real name. On items where a decline is WRONG
(business questions), any decline is an over-refusal."""
import re

from lab.production_prompt import _rules

TEMPLATE = re.search(r'"(I\'m just here to help with things related to \{business_name\}[^"]*)"', _rules()[0]).group(1)
OFFTOPIC_IDS = {"h1:offtopic-america", "h2:scope-weather", "h2:scope-election", "h2:scope-poem", "h2:scope-salon-movie",
                "h2:scope-trek-cricket"}


def expected(name: str) -> str:
    return TEMPLATE.format(business_name=name)


def _ws(s):
    return " ".join(s.replace("’", "'").replace("‘", "'").replace("“", '"').replace("”", '"').split())


def _dash(s):
    return re.sub(r"\s*[—–-]+\s*", " - ", _ws(s))


_DECLINE_STEMS = ("just here to help", "outside what i can help", "just the assistant for", "not something i can help",
                  "can only help with", "here to help with things related")


def is_decline(reply: str) -> bool:
    return any(stem in _ws(reply).lower() for stem in _DECLINE_STEMS)


def classify(reply: str, name: str) -> str:
    if _ws(reply) == _ws(expected(name)):
        return "exact"
    if _dash(reply) == _dash(expected(name)):
        return "typography"
    return "drift" if is_decline(reply) else "no_decline"


def name_drift(reply: str) -> bool:
    return bool(re.search(r"related to (this|the) (clinic|business|salon|agency|company)|assistant for (this|the) (clinic|business)", reply, re.I))


def report(rows: list[dict]) -> None:
    """rows: eval_arms rows (arm, item, reply). Prints decline-wording fidelity per arm."""
    from lab.businesses import BUSINESSES
    from lab.eval_items import HELDOUT1, HELDOUT2
    name = {i.id: BUSINESSES[i.biz]["name"] for i in HELDOUT1 + HELDOUT2}
    print(f"{'arm':12}{'exact':>8}{'typography':>12}{'drift':>7}{'no decline':>12}{'says this clinic/business':>27}   {'over-refusals (decline on an in-scope item)':>44}")
    for arm in dict.fromkeys(r["arm"] for r in rows):
        off = [r for r in rows if r["arm"] == arm and r["item"] in OFFTOPIC_IDS]
        ins = [r for r in rows if r["arm"] == arm and r["item"] not in OFFTOPIC_IDS]
        c = [classify(r["reply"], name[r["item"]]) for r in off]
        print(f"{arm:12}{c.count('exact'):>5}/{len(c)}{c.count('typography'):>9}/{len(c)}{c.count('drift'):>4}/{len(c)}{c.count('no_decline'):>9}/{len(c)}"
              f"{sum(name_drift(r['reply']) for r in off):>22}/{len(off)}   {sum(is_decline(r['reply']) for r in ins):>34}/{len(ins)}")


if __name__ == "__main__":  # smallest check that fails if the logic breaks
    n = "Riverside Dental"
    e = expected(n)
    assert e == "I'm just here to help with things related to Riverside Dental — appointments, services, hours, and the like. Is there something about that I can help with?", e
    assert classify(e, n) == "exact" and classify(e.replace(" — ", "—"), n) == "typography"
    assert classify(e.replace("Riverside Dental", "this clinic"), n) == "drift" and name_drift(e.replace("Riverside Dental", "this clinic"))
    assert classify("It's sunny today.", n) == "no_decline" and not is_decline("We're open 9-5.")
    print("fidelity checks ok;", "template:", TEMPLATE)
