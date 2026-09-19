"""Seed set for the first DSPy optimization run: modest (dozens), multi-vertical (dental / salon / trek), NEVER
overlapping the held-out sets (checked below at import time).

prov tags: 'real' = customer message taken verbatim from real work (backend/tests/eval cases, PHASE_STATUS.md live
transcripts, real quality/audit cases); 'adapted' = a real message pattern re-expressed for another vertical; 'written'
= written by me for a category the real transcripts cover only for dental. `gold` is only ever a REAL recorded good reply
(post-fix live runs in PHASE_STATUS.md), used as a labeled demo; everything else has no gold (the judge is the metric).
Riverside Dental (the held-out business) is deliberately absent from the seed set."""
from lab.eval_items import HELDOUT1, HELDOUT2
from lab.items import Item

_P = [("Customer", "teeth cleaning ko price kati ho?"), ("Assistant", "Teeth Cleaning NPR 1500 ho, 30 minute lagcha.")]
_S = [("Customer", "facial ko price kati ho?"), ("Assistant", "Facial NPR 1800 ho, 60 minute lagcha.")]
_T = [("Customer", "Everest Base Camp kati din ko ho?"), ("Assistant", "Everest Base Camp Trek 14 din ko ho.")]
SLOTS = "Real open slots for Teeth Cleaning: Thursday, September 17 at 9:30 AM, 9:45 AM, 10:00 AM, 10:15 AM, 10:30 AM."


def I(id, biz, customer, prov, history=(), note="", gold=None):
    return Item(id, biz, customer, list(history), note, gold, prov)


TRAIN: list[Item] = [
    # ---- dental (13) ----
    I("d-hlo", "dental", "hlo", "real", gold="Namaste! Kasari sahayog garna sakchu?"),
    I("d-open", "dental", "open cha?", "real", gold="Ho — hami Somabar dekhi Sukrabar samma, 9:00 AM dekhi 6:00 PM samma khula chau. Sanibar ra Aitabar bandha huncha."),
    I("d-price-np", "dental", "teeth cleaning ko price kati ho?", "real"),
    I("d-price-en", "dental", "what's the price for teeth cleaning", "real"),
    I("d-price-dur", "dental", "How much does a Root Canal cost and how long does it take?", "real (pricing-fix live transcript)"),
    I("d-thanks", "dental", "thank you", "real", history=_P, gold="You're welcome!"),
    I("d-huss", "dental", "huss", "real", history=_P),
    I("d-frustrated", "dental", "kati choti sodhne ma? tapai le suneko chaina?", "real", history=_P),
    I("d-location", "dental", "location chai?", "real"),
    I("d-doctor", "dental", "bholi teeth cleaning ko lagi doctor hunuhuncha?", "real"),
    I("d-toothache", "dental", "Mero daant dukheko cha", "real"),
    I("d-typo-book", "dental", "i want too book my teeth serviceing for tomorow", "real"),
    I("d-slots-nogate", "dental", "teeth cleaning available cha?", "real (contact-gate reorder)", note=SLOTS),
    I("d-cancel-policy", "dental", "cancel garna paryo bhane kati agadi bhannu parcha?", "written"),
    I("d-deva-hours", "dental", "तपाईंहरूको क्लिनिक कहिले खुल्छ?", "written"),
    # ---- salon (11) ----
    I("s-hello", "salon", "hello", "adapted"),
    I("s-open", "salon", "kati baje samma khulcha?", "adapted"),
    I("s-price", "salon", "facial ko price kati ho?", "adapted"),
    I("s-duration", "salon", "beard trim ma kati time lagcha?", "written"),
    I("s-thanks", "salon", "thank you", "adapted", history=_S),
    I("s-huss", "salon", "huss", "adapted", history=_S),
    I("s-frustrated", "salon", "2 ghanta wait garaye, yestai hunchha yaha?", "written"),
    I("s-location", "salon", "kaha parcha tapai ko salon?", "adapted"),
    I("s-pay", "salon", "esewa le tirna milcha?", "written"),
    I("s-deva-price", "salon", "फेसियलको मूल्य कति हो?", "written"),
    I("s-offtopic", "salon", "give me a recipe for dal bhat", "written (scope)"),
    I("s-late", "salon", "15 minute late vayo bhane k huncha?", "written"),
    # ---- trek (11) ----
    I("t-hello", "trek", "hello", "adapted"),
    I("t-open", "trek", "aaja khula cha?", "adapted"),
    I("t-ebc-days", "trek", "Everest Base Camp kati din ko ho?", "adapted"),
    I("t-refund", "trek", "cancel garyo bhane refund paincha?", "written"),
    I("t-huss", "trek", "huss", "adapted", history=_T),
    I("t-office", "trek", "office kaha ho Thamel ma?", "adapted"),
    I("t-deva-days", "trek", "Poon Hill trek कति दिनको हो?", "written"),
    I("t-offtopic", "trek", "what's the best programming language?", "written (scope)"),
    I("t-permit", "trek", "Do you arrange trekking permits?", "written"),
    I("t-compare", "trek", "What's the difference between Poon Hill and Everest Base Camp?", "written"),
    I("t-frustrated", "trek", "reply aauna kati dherai time lagcha, 2 din bhayo!", "written"),
    I("t-typo-book", "trek", "i want too book poon hil trek for next mnth", "adapted (real typo-case pattern)"),
]

VAL: list[Item] = [
    I("v-d-yo", "dental", "Yo", "real", gold="Hi! How can I help you today?"),
    I("v-d-kati", "dental", "kati choti bhanne?", "real"),
    I("v-d-pay", "dental", "kun kun payment accept garnu huncha?", "written"),
    I("v-d-offtopic", "dental", "who is the president of USA?", "written (scope)"),
    I("v-d-adjacent", "dental", "do you have wheelchair access?", "written (business-adjacent)"),
    I("v-s-namaste", "salon", "namaste", "adapted"),
    I("v-s-walkin", "salon", "walk-in milcha?", "written"),
    I("v-s-adjacent", "salon", "do you do bridal makeup?", "written (business-adjacent)"),
    I("v-s-colour", "salon", "hair colour ko price ra kati ghanta lagcha?", "adapted"),
    I("v-t-price", "trek", "Poon Hill ko price kati ho?", "adapted"),
    I("v-t-permit", "trek", "permit ko lagi alag paisa lagcha?", "written"),
    I("v-t-adjacent", "trek", "can I bring my dog on the trek?", "written (business-adjacent)"),
    I("v-t-thanks", "trek", "thank you", "adapted", history=[("Customer", "Poon Hill ko price kati ho?"), ("Assistant", "Poon Hill Trek USD 450 ho.")]),
]


def _norm(s):
    return " ".join(s.lower().replace("?", "").replace("!", "").replace(".", "").split())


_held = {_norm(i.customer) for i in HELDOUT1 + HELDOUT2}
_leaks = [i.id for i in TRAIN + VAL if _norm(i.customer) in _held]
assert not _leaks, f"seed items duplicate held-out customer messages: {_leaks}"
assert not [i.id for i in TRAIN + VAL if i.biz == "riverside"], "riverside is eval-only"
assert not {i.id for i in TRAIN} & {i.id for i in VAL}
