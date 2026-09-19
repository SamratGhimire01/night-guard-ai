"""Eval inputs = the customer turn of every group in the two held-out sets (#1 = dev, #2 = still clean), mapped onto
sandbox businesses so EVERY arm sees identical structured facts. Group-level 'facts' strings that are situational
(booking draft, slot list...) become Item.note; business-description facts map to a business config."""
import re

import lab.heldout_set as H1
import lab.heldout_set_2 as H2
from lab.items import Item

_BIZ = {  # group id -> business config (everything not listed here: derived from which facts constant it used)
    "thanks-verbose-closing": "dental", "complaint-callback": "dental", "readiness-loop": "dental",
    "confirmation-ignored": "dental", "clarifying-with-false-handoff": "dental",
    "slot-pick-date-lost": "dental", "contradictory-booking": "dental",
}
_BY_FACTS = {H1.RIVERSIDE: "riverside", H1.SALON: "salon", H1.TREK: "trek"}


def _history(conv: str):
    out = []
    for line in filter(None, (conv or "").split("\n")):
        m = re.match(r"(Customer|Assistant): (.*)", line)
        if m:
            out.append((m.group(1), m.group(2)))
    return out


def _items(mod, tag):
    items = []
    for g in mod.GROUPS:
        facts = g.get("facts", "")
        biz = _BIZ.get(g["id"]) or _BY_FACTS.get(facts) or ("riverside" if "Business hours: Monday-Saturday" in facts else "dental")
        situational = facts if facts not in _BY_FACTS and not facts.startswith("Business hours:") else ""
        items.append(Item(id=f"{tag}:{g['id']}", biz=biz, customer=g["customer"], history=_history(g.get("conversation", "")),
                          note=situational, prov=f"{tag} group {g['id']}"))
    return items


HELDOUT1 = _items(H1, "h1")   # dev set (spent on the scope-gap finding)
HELDOUT2 = _items(H2, "h2")   # clean held-out
