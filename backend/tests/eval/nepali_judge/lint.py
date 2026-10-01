"""Deterministic native-language checks. Each finding names the rubric criterion it hurts and the highest score that
criterion can still get (a cap), so an LLM judge that misses the problem can't hide it.

Only flags things that are wrong in every context -- never a matter of taste. Taste is the LLM judges' job."""

import re
from dataclasses import dataclass

from app.services.conversation.nepali_wordbank import _CH_STYLE_WORDS, _X_STYLE_WORDS, customer_spelling_style, find_issues
from app.services.conversation.reply_polish import _FILLER_TAIL_RE, _OFFER_TAIL_RE
from app.services.conversation.style_checks import split_sentences

CRITERIA = ("language", "register", "human", "helpful", "correct")

_DEVANAGARI = re.compile(r"[ऀ-ॿ]")
_LATIN_WORD = re.compile(r"[A-Za-z]+")
# Words that only occur in Nepali, in either spelling style. Enough to tell Romanized Nepali from English.
_NE_MARKERS = _X_STYLE_WORDS | _CH_STYLE_WORDS | {
    "ho", "hola", "garna", "garne", "garnu", "garnus", "dinus", "bhannus", "vannus", "malai", "mero", "tapai", "tapaiko",
    "hajur", "hamro", "kati", "kun", "kasari", "kaha", "kaile", "kahile", "aaja", "aile", "ahile", "baje", "lagi", "sanga",
    "saga", "pani", "ani", "ra", "ko", "ma", "ni", "ta", "huss", "la", "pakka", "thik", "ramro", "bhayo", "vayo", "khali",
    "milaidinchu", "garidinchu", "chahiyo", "parcha", "parxa", "sakchu", "sakxu", "dherai", "ali", "aaune", "bihana",
    "beluka", "diuso", "sadhe", "dedh", "namaste", "dhanyabad", "k", "ke", "kina", "bata", "mai", "ki", "aayera",
    "garera", "bhane", "vane", "naam", "kripaya", "chahincha", "tirna", "aauna", "jana", "wota", "ota", "samma", "dekhi", "chau", "chan", "bhaneko",
}
# Nepali verb/postposition endings: catch words no list can hold (pathaidinus, garidinchu, milaunuhos, sakinchha).
_NE_ENDINGS = ("nus", "nuhos", "inchu", "inchha", "incha", "inxa", "chhu", "chha", "xau", "dainchu", "aunu", "ilai", "haru")
# English function words: an English sentence is full of them, a Nepali one with English nouns ("price", "booking",
# "slot") has almost none. Comparing the two is what separates code-mixed Nepali from English.
_EN_FUNCTION = {
    "the", "is", "are", "was", "you", "your", "we", "our", "to", "a", "an", "for", "and", "can", "i", "it", "of", "on",
    "in", "with", "will", "would", "what", "when", "do", "does", "have", "has", "be", "this", "that", "there", "please",
    "if", "or", "at", "how", "my", "me", "us", "they", "not", "no", "yes", "so", "but", "from", "just", "could",
}
# Formal/Sanskritised words the app's word bank doesn't swap yet (found by this judge in real replies). The judge flags
# them; adding them to nepali_wordbank is a separate, reviewed change.
_EXTRA_BOOKISH_RE = re.compile(
    r"\b(yadi|rakta|swikar\w*|saadharan|sadharan|roopma|rupma|prayah|anurodh|sandesh|safal|upayukta|pradan|bhuktani|"
    r"prakriya|aawashyak|awashyak|nirdesh|sunischit|nischit|uplabdha|upalabdha|sampark garnuhos|magincha|maginchha)\b",
    re.IGNORECASE,
)
# The customer asked for an explanation: a longer answer is the right answer, not a monologue.
_EXPLAIN_RE = re.compile(
    r"\b(what is|what's|what are|what does|means?|explain|why|kina|k ho|ke ho|bhaneko k|vaneko k|k k|ke ke|kun kun|"
    r"what services|which services?|list|barema|bare ma|janna)\b",
    re.IGNORECASE,
)
_GREETING_RE = re.compile(r"^\W*(hi+|hello+|hlo+|helo|hey|namaste|namaskar|k (cha|xa)|hajur)\W*$", re.IGNORECASE)
_TIMI_RE = re.compile(r"\b(timi|timro|timra|timilai|timle|timile|timisanga)\b", re.IGNORECASE)
_EN_DATE_RE = re.compile(
    r"\b(monday|tuesday|wednesday|thursday|friday|saturday|sunday),\s+(january|february|march|april|may|june|july|"
    r"august|september|october|november|december)\b|\bat \d{1,2}:\d{2}\s?(am|pm)\b",
    re.IGNORECASE,
)


@dataclass(frozen=True)
class Finding:
    code: str
    criterion: str
    cap: int
    detail: str


def language_of(text: str) -> str:
    """"ne_deva", "ne_roman", "mixed" (Romanized Nepali with English content words) or "en"."""
    if _DEVANAGARI.search(text) and len(_DEVANAGARI.findall(text)) > len(_LATIN_WORD.findall(text)):
        return "ne_deva"
    words = [w.lower() for w in _LATIN_WORD.findall(text)]
    if not words:
        return "en"
    ne = sum(w in _NE_MARKERS or (len(w) > 4 and w.endswith(_NE_ENDINGS)) for w in words)
    en = sum(w in _EN_FUNCTION for w in words)
    if ne == 0 or en > ne:
        return "en"
    return "ne_roman" if en == 0 or ne / len(words) >= 0.3 else "mixed"


def _nepali_reply(reply: str) -> bool:
    return language_of(reply) in ("ne_roman", "mixed")


def lint(reply: str, customer: str, history: list[dict] | None = None, *, locked_language: str | None = None) -> list[Finding]:
    """`history`: earlier turns as {"role": "customer"|"assistant", "text": ...}, oldest first.
    `locked_language`: the conversation's locked language when the system set one (then it, not this customer
    message, decides which language the reply must be in)."""
    history = history or []
    out: list[Finding] = []
    reply_lang, customer_lang = language_of(reply), language_of(customer)

    # --- language: wrong language, Hindi, textbook words, English dates mid-Nepali, spelling mismatch -------------
    expected = locked_language or customer_lang
    if expected in ("ne_roman", "mixed") and reply_lang == "en":
        out.append(Finding("wrong_language", "language", 2, "customer writes Romanized Nepali, reply is English"))
    elif expected == "ne_roman" and reply_lang == "ne_deva":
        out.append(Finding("wrong_script", "language", 3, "customer writes in Latin letters, reply is Devanagari"))
    elif expected == "en" and reply_lang in ("ne_roman", "ne_deva") and locked_language == "en":
        out.append(Finding("wrong_language", "language", 2, "conversation is locked to English, reply is Nepali"))

    if _nepali_reply(reply):
        issues = find_issues(reply)
        hindi = [w for w, k in issues if k == "hindi"]
        bookish = [w for w, k in issues if k == "bookish"] + _EXTRA_BOOKISH_RE.findall(reply)
        errors = [w for w, k in issues if k == "error"]
        if hindi:
            out.append(Finding("hindi", "language", 2 if len(hindi) > 1 else 3, ", ".join(hindi)))
        if bookish:
            out.append(Finding("bookish", "language", 2 if len(bookish) > 2 else 3, ", ".join(bookish)))
        if errors:
            out.append(Finding("spelling", "correct", 3, ", ".join(errors)))
        # An English sentence inside a Nepali reply (an internal system message leaking, e.g. "requested time is not
        # available (outside business hours, on a closed date, ...)"). English NOUNS are normal in code-mixed Nepali;
        # a run of English function words is not.
        en_function = [w for w in _LATIN_WORD.findall(reply.lower()) if w in _EN_FUNCTION]
        if len(en_function) >= 5:
            out.append(Finding("english_leak", "language", 3, " ".join(en_function[:6])))
        if _EN_DATE_RE.search(reply):
            out.append(Finding("english_date", "language", 3, _EN_DATE_RE.search(reply).group(0)))
        timi = _TIMI_RE.findall(reply)
        if timi:
            out.append(Finding("timi", "register", 2, ", ".join(timi)))
        if _DEVANAGARI.search(reply):
            out.append(Finding("mixed_script", "correct", 2, "Devanagari letters inside a Romanized reply"))
        customer_texts = [customer] + [t["text"] for t in history if t["role"] == "customer"]
        if customer_spelling_style(customer_texts) == "x":
            words = {w.lower() for w in _LATIN_WORD.findall(reply)}
            ch_words = sorted(words & _CH_STYLE_WORDS - _X_STYLE_WORDS)
            if len(ch_words) >= 2:
                out.append(Finding("spelling_style", "language", 4, f"customer writes xa/vayo, reply writes {', '.join(ch_words)}"))

    # --- human-likeness: verbatim repeats, stock endings, monologues ---------------------------------------------
    earlier = [t["text"].strip() for t in history if t["role"] == "assistant"]
    if len(reply.strip()) >= 20 and reply.strip() in earlier:
        out.append(Finding("repeat", "human", 2, "word-for-word the same as an earlier reply in this chat"))
    sentences = split_sentences(reply)
    last = sentences[-1].strip().lower() if sentences else ""
    # A filler tail ("let me know if…", "aru kehi chahiyo bhane bhannus") is always a tic. A single offer of a next
    # step ("booking garna man xa?") is what a person does too -- it only becomes robotic when the previous reply ended
    # the same way (the same policy reply_polish enforces).
    prev_last = (split_sentences(earlier[-1]) or [""])[-1].strip().lower() if earlier else ""
    prev_stock = bool(prev_last) and bool(_FILLER_TAIL_RE.search(prev_last) or _OFFER_TAIL_RE.search(prev_last))
    if last and len(sentences) > 1 and _FILLER_TAIL_RE.search(last):
        out.append(Finding("stock_ending", "human", 3 if prev_stock else 4, last[:60]))
    elif last and _OFFER_TAIL_RE.search(last) and prev_stock:
        out.append(Finding("stock_ending", "human", 3, "offers again, like the previous reply: " + last[:50]))
    customer_words, reply_words = len(customer.split()), len(reply.split())
    asked_to_explain = bool(_EXPLAIN_RE.search(customer))
    if customer_words <= 8 and reply_words > max(45, customer_words * 6) and not asked_to_explain and "\n-" not in reply and "\n•" not in reply:
        out.append(Finding("monologue", "human", 3, f"{reply_words} words for a {customer_words}-word message"))

    return out


def caps(findings: list[Finding]) -> dict[str, int]:
    """The highest score each criterion may get, given the findings (5 when nothing caps it)."""
    result = {c: 5 for c in CRITERIA}
    for f in findings:
        result[f.criterion] = min(result[f.criterion], f.cap)
    return result
