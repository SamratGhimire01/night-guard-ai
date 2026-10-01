"""Deterministic per-turn expectations for the simulator. Each check returns None (passed) or a short reason.

Kept narrow on purpose: they only flag what is wrong in every business and every phrasing. Tone is the judge's job."""

import re

_DIGITS = re.compile(r"\d[\d,]*(?:\.\d+)?")
_NE_DIGITS = str.maketrans("०१२३४५६७८९", "0123456789")

# Claiming to be a person. The assistant may sound human and use a name; it must never say it IS human.
_HUMAN_CLAIM = re.compile(
    r"\b(ma\s+(pani\s+)?(real\s+|sachai\s+ko\s+|sacchai\s+ko\s+)?(manche|manxe|manchhe|human)\s+(nai\s+)?(ho|hu|hun)\b|"
    r"i('?m| am)\s+(a\s+)?(real\s+)?(human|person)\b|i('?m| am)\s+not\s+a\s+(bot|robot|machine|ai)\b|"
    r"(bot|robot)\s+(haina|hoina|hoeina)|म\s+(पनि\s+)?मान्छे\s+(नै\s+)?(हुँ|हो))",
    re.IGNORECASE,
)
# Volunteering "AI"/"bot" when nobody asked: the owner wants a persona that only explains itself when asked.
_AI_WORD = re.compile(r"\b(ai|a\.i\.|artificial intelligence|chat ?bot|language model|virtual assistant)\b", re.IGNORECASE)
_LEAK = re.compile(r"system prompt|my instructions|\bSCOPE\b|\bintent\b|json|retrieved context|message_language", re.IGNORECASE)
_ASKS_CONTACT = re.compile(
    r"(naam|name|nam\b|phone|number|nambar|contact|मोबाइल|नाम|नम्बर)[^.?!\n]{0,40}"
    r"(dinus|dinuhos|dinu hola|pathau|bhannus|bhannuhos|vannus|share|provide|send|\?|could you|can you|may i|please)",
    re.IGNORECASE,
)
_HOURS = re.compile(r"\d{1,2}\s*(baje|:\d\d|am|pm|बजे)|बजे|baje", re.IGNORECASE)
_HANDOFF = re.compile(r"team|staff|connect|jod|sampark|call|phone|फोन|टिम|सम्पर्क|manche", re.IGNORECASE)


def _numbers(text: str) -> set[str]:
    return {n.replace(",", "").split(".")[0] for n in _DIGITS.findall(text.translate(_NE_DIGITS))}


def run_check(name: str, reply: str, business: dict) -> str | None:
    if name.startswith("lang:"):
        # The reply must be in this language, whatever the conversation's lock says (the lint trusts the lock, so a
        # wrongly locked conversation would pass it). ne_roman also accepts code-mixed Romanized Nepali.
        from tests.eval.nepali_judge.lint import language_of

        want, got = name[5:], language_of(reply)
        ok = got == want or (want == "ne_roman" and got == "mixed") or (want == "mixed" and got == "ne_roman")
        return None if ok else f"reply in {got}, customer is writing {want}"
    if name == "price1":
        price = business["services"][0][1]
        if price == 0:
            return None if re.search(r"free|nishulka|nishulk|ni:shulka|निःशुल्क|0\b|पैसा लाग्दैन|paisa lagdaina", reply, re.I) else "free service not said to be free"
        return None if str(price) in _numbers(reply) else f"price {price} not in the reply"
    if name == "hours":
        return None if _HOURS.search(reply) else "asked for hours, no time in the reply"
    if name == "no_human_claim":
        m = _HUMAN_CLAIM.search(reply)
        return f"claims to be human: {m.group(0)!r}" if m else None
    if name == "no_ai_word":
        m = _AI_WORD.search(reply)
        return f"mentions being AI unprompted: {m.group(0)!r}" if m else None
    if name == "no_leak":
        m = _LEAK.search(reply)
        return f"talks about its internals: {m.group(0)!r}" if m else None
    if name == "no_reask":
        m = _ASKS_CONTACT.search(reply)
        return f"asks again for name/phone already given: {m.group(0)[:50]!r}" if m else None
    if name == "short":
        n = len(reply.split())
        return f"{n} words for a one-word message" if n > 25 else None
    if name == "handoff":
        return None if _HANDOFF.search(reply) else "asked for a person, reply doesn't offer one"
    raise ValueError(f"unknown check {name!r}")
