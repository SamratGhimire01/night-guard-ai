"""The last step before a reply is sent: make it read like a person, not a script.

Runs on the final reply text of every main-flow turn (orchestrator._handle_turn), after the fact check and style
guard, so it only ever touches wording -- never a price, time, link, booking id or name (those are protected or
contain digits, and every guard below leaves a sentence with a digit or link alone).

1. Romanized Nepali / mixed replies go through nepali_wordbank.polish_reply: Hindi and textbook words swapped for
   what Nepali people actually type, spelling mirrored to the customer's own (xa/vayo vs cha/bhayo).
2. A filler ending ("let me know if…", "aru kehi chahiyo bhane bhannus") is dropped. An offer ending ("Would you like
   me to…?") is dropped when one of our last 3 replies already ended with one -- in the 653 real conversations, 17% of replies
   ended with a stock line, often several in a row.
3. The same opener ("Got it —", "Bujhe —", "Thik cha,") is never used twice in a row: the repeat is dropped.
4. A stock filler/offer sentence we already sent word for word earlier in this chat is dropped (never one with a
   digit or a link, never the reply's only sentence). A repeated real request is kept -- the customer still owes it.

Every change is returned for the log; nothing here can empty a reply.
"""

import re

from app.schemas.conversation import ConversationLanguage
from app.services.conversation.nepali_wordbank import customer_spelling_style, mirror_spelling, polish_reply
from app.services.conversation.style_checks import split_sentences

_NEPALI_ROMAN = {ConversationLanguage.NE_ROMAN.value, ConversationLanguage.MIXED.value}

# Pure filler: says nothing the customer needs. Matched against one sentence.
_FILLER_TAIL_RE = re.compile(
    r"^(please )?(let me know if|let me know when|feel free to|if you (need|have|want|would like|'d like) (anything|any|more)|"
    r"anything else|is there anything else|hope (this|that) helps|happy to help (with anything|further))"
    r"|(aru|aaru|arru) (kehi|kei|k)\b.*\b(bhane|vane)\b"
    r"|\b(kehi|kei) (chahiyo|chaiyo|xaiyo|paryo) (bhane|vane) (bhannus|vannus|bhanuhos|bhanuhola|bhannu hola|sodhnus)"
    r"|अरू केही .*भने|केही चाहियो भने",
    re.IGNORECASE,
)
# A stock offer / question tail: fine once, robotic every turn.
_OFFER_TAIL_RE = re.compile(
    r"^(would you like|do you want|want me to|shall i|should i|can i help|how can i help|what else can i)"
    r"|\b(garna|herna|check garna) man (cha|xa|chha)\b.*\?$"
    r"|\b(k|ke) (help|sahayog|madat) garna (sakchu|sakxu|sakchhu)\b"
    r"|\b(garum|garidiu|herdiu|milaidiu|check garum)\s*\?$"
    r"|गरूँ\?$|गरिदिऊँ\?$|चाहनुहुन्छ\?$",
    re.IGNORECASE,
)
# A detachable acknowledgment at the very start, followed by punctuation.
_OPENER_RE = re.compile(
    r"^(got it|okay|ok|sure|great|perfect|alright|no problem|of course|absolutely|noted|done|"
    r"bujhe|bujhyo|thik cha|thik xa|thik chha|thikai cha|huss|hus|hunchha|huncha|hunxa|la|hajur|sabai milyo|"
    r"ramro|pakka|ठीक छ|हुन्छ|बुझेँ|बुझें)\s*([,!.—–-]+|\s—)\s*",
    re.IGNORECASE,
)
_HELP_QUESTION_RE = re.compile(r"how can i help|what can i do for you|\bk help garum\b|\bk garna sakchu\b", re.IGNORECASE)
_HAS_FACT_RE = re.compile(r"\d|https?://|@")
_MIN_REPEAT_LEN = 25
# An offer ending is dropped when any of our last this-many replies already ended with a stock line.
_OFFER_WINDOW = 3


def _norm(text: str) -> str:
    return mirror_spelling(" ".join(text.lower().split()), "x")


def _last_sentence(text: str) -> str:
    sentences = split_sentences(text)
    return sentences[-1] if sentences else ""


def _is_stock_tail(sentence: str) -> bool:
    s = sentence.strip()
    return bool(_FILLER_TAIL_RE.search(s) or _OFFER_TAIL_RE.search(s))


def _opener(text: str) -> str | None:
    m = _OPENER_RE.match(text.strip())
    return _norm(m.group(1)) if m else None


def _capitalize(text: str) -> str:
    return text[0].upper() + text[1:] if text and text[0].islower() else text


def finalize_reply(
    text: str,
    *,
    language: str | None,
    previous_replies: list[str],
    customer_texts: list[str],
    protected: list[str],
    intent: str | None = None,
) -> tuple[str, list[str]]:
    """`previous_replies`: our earlier replies in this chat, oldest first. `customer_texts`: the customer's messages
    (any order). `protected`: names that must come through untouched (services, business, customer, persona)."""
    changes: list[str] = []
    if language in _NEPALI_ROMAN:
        text, word_changes = polish_reply(text, style=customer_spelling_style(customer_texts), protected=protected)
        changes += word_changes

    previous = previous_replies[-1] if previous_replies else None
    sentences = split_sentences(text)
    # Sentences are removed from the original string (never re-joined), so line breaks in a list survive.
    drop: list[str] = []

    # 2. stock endings
    if len(sentences) >= 2 and not _HAS_FACT_RE.search(sentences[-1]):
        tail = sentences[-1]
        previous_tail_stock = any(_is_stock_tail(_last_sentence(r)) for r in previous_replies[-_OFFER_WINDOW:])
        # A greeting's "how can I help?" IS the reply's point, never a tail to trim.
        offer_droppable = intent != "greeting" and not _HELP_QUESTION_RE.search(tail)
        if _FILLER_TAIL_RE.search(tail) or (_OFFER_TAIL_RE.search(tail) and previous_tail_stock and offer_droppable):
            changes.append(f"dropped stock ending: {tail!r}")
            drop.append(tail)

    # 4. a plain sentence already sent word for word
    if previous_replies:
        sent_before = [_norm(r) for r in previous_replies]
        for s in sentences:
            if s in drop or len(drop) >= len(sentences) - 1:
                continue
            n = _norm(s)
            # Only stock filler/offers: a repeated real request ("I just need your name and number") is still needed.
            if (
                len(n) >= _MIN_REPEAT_LEN and _is_stock_tail(s) and not _HAS_FACT_RE.search(s)
                and any(n in r for r in sent_before)
            ):
                changes.append(f"dropped repeated sentence: {s!r}")
                drop.append(s)

    for s in drop:
        i = text.find(s)
        if i >= 0:
            text = (text[:i].rstrip(" ") + (" " if text[i + len(s):].strip() else "") + text[i + len(s):].lstrip(" ")).strip()

    # 3. the same opener twice in a row
    opener = _opener(text)
    if opener and previous and _opener(previous) == opener:
        rest = _OPENER_RE.sub("", text.strip(), count=1)
        if len(rest.split()) >= 2:
            changes.append(f"dropped repeated opener: {opener!r}")
            text = _capitalize(rest)
    return text, changes
