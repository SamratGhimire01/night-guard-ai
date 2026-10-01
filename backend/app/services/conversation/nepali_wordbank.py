"""Romanized Nepali word bank -- the ONE vocabulary source for how this assistant texts in Romanized Nepali.

Built from the 653 real conversations in data/regression/real_conversations (what customers actually type: xa, vayo,
hunxa, milxa, voli, k, kati, plz, ali, ta, na) plus everyday chat Nepali. Used in three places:

1. intent.py's system prompt (`prompt_word_guide`): the short "write like this, never like that" guide.
2. `polish_reply`, run on every Romanized-Nepali / mixed reply right before it's sent (orchestrator._finalize_reply):
   clear-cut swaps of Hindi or textbook words for what a Nepali person actually types, plus spelling that mirrors the
   customer's own (xa/vayo vs cha/bhayo). Every swap is logged.
3. Tests and scripts/nepali_naturalness_report.py, so no template or exemplar can slip back.

Only WORD-level swaps live here, never a rewrite: a swap must be safe in any sentence it can appear in. Anything that
needs a rewrite of the whole sentence (e.g. "maile thik sanga bujhna chahanchu") is listed in FLAG_ONLY instead -- it's
counted and steers the prompt, and the templates themselves were rewritten so they never produce it.
"""

import logging
import re

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------------------------------------------------
# 1. Natural words and phrases, grouped by situation. This is the "arsenal": the prompt shows a sample of each group,
#    and tests check templates/exemplars only use this register. Spelled in the default (cha/bhayo) style;
#    `mirror_spelling` converts to x/v style when the customer writes that way.
# ---------------------------------------------------------------------------------------------------------------------
NATURAL: dict[str, list[str]] = {
    "greet": [
        "namaste", "namaskar", "hello", "hi", "k cha", "sanchai hunuhuncha", "kasto cha", "ramro cha",
        "swagat cha", "aaunus", "bhannus", "bhannus na", "k help garum", "k garna sakchu",
    ],
    "acknowledge": [
        "huss", "hunchha", "huncha", "la", "la huncha", "thik cha", "thikai cha", "hajur", "ho", "hoina",
        "pakka", "pakka pani", "milcha", "mildaina", "bujhe", "bujhyo", "ok", "okay", "sure", "done",
        "bhayo", "bhaihalyo", "sabai milyo", "ramro", "ekdam ramro", "thik chha ta", "ho ni", "hajur ho",
        "la thik cha", "noted", "set bhayo", "fix bhayo", "garidiye", "ok ta",
    ],
    "thanks": [
        "dhanyabad", "thank you", "thanks", "khusi lagyo", "welcome", "swagat cha", "kehi chaina",
        "jaile pani", "pheri bhetaula", "ramro sanga aaunus", "take care",
    ],
    "sorry": [
        "sorry", "sorry hai", "ali bujhina", "ali confuse bhaye", "maile miss gare", "galti bhayo",
        "dukha lagyo", "pir nagarnus", "tension nalinus", "kehi chaina", "ma herchu",
    ],
    "time": [
        "aaja", "bholi", "parsi", "aile", "aile nai", "bholi bihana", "aaja beluka", "kaile", "kati baje",
        "bihana", "diuso", "beluka", "raati", "sadhe 10 baje", "dedh baje", "adhai baje", "sawa 11",
        "10 baje", "11 baje tira", "chadai", "chito", "ali pachi", "ek chin", "ek chin hai", "pahile",
        "pachi", "yo hapta", "arko hapta", "aune hapta", "mahina", "din", "ghanta", "minute", "samma",
        "dekhi", "agadi", "bhanda agadi", "bhitra", "ahilelai", "jaile", "kunai bela",
    ],
    "days": [
        "Aaitabar", "Sombar", "Mangalbar", "Budhbar", "Bihibar", "Sukrabar", "Sanibar", "hijo", "aaja",
        "bholi", "parsi", "weekend",
    ],
    "question": [
        "k", "kati", "kun", "kaha", "kata", "kasari", "kina", "kaile", "ko", "kasko", "kunai", "k ho",
        "kati ho", "kati parcha", "kati lagcha", "kun chai", "kun din", "kun time", "milcha?", "huncha?",
        "cha?", "ho?", "mildaina?", "ki", "ki kasto", "tike",
    ],
    "booking": [
        "book garidinchu", "book garum", "book bhayo", "booking", "appointment", "slot", "time",
        "milaidinchu", "milaidiye", "sardinchu", "sardiye", "sarnu", "cancel garidinchu", "cancel garidiye",
        "cancel bhayo", "confirm bhayo", "pakka bhayo", "reserve garidiye", "khali cha", "khali chaina",
        "booked cha", "bharieko cha", "available cha", "available chaina", "kun time milcha", "check garchu",
        "herdinchu", "check garera bhanchu", "number pathaidinus", "naam ra number", "pathaidinus",
        "bhanidinus", "dinus na", "pathaidinchu", "QR pathaidiye", "link pathaidiye",
    ],
    "softeners": [
        "hai", "ni", "ta", "na", "ali", "ali kati", "khali", "matra", "pani", "nai", "chai", "re",
        "rahecha", "raicha", "hola", "jasto cha", "hunu parcha", "garnu parcha",
    ],
    "money": [
        "Rs", "NPR", "rupaiya", "paisa", "price", "rate", "kati parcha", "charge", "free", "deposit",
        "advance", "baki", "tirnu", "tirnus", "eSewa", "Khalti", "cash", "online", "QR", "scan garnus",
    ],
    "empathy": [
        "ouch", "dukhda dherai garo huncha", "pir nagarnus", "hami herchau", "aaja nai herna milcha ki check garum",
        "ekdam garo bhayo hola", "chinta nagarnus", "ma help garchu", "sorry, yesto hunu bhayena",
        "turuntai herchau", "ramro bhayo", "khusi lagyo sunera",
    ],
    "actions": [
        "garchu", "garidinchu", "gardinchu", "herchu", "herdinchu", "bhanchu", "pathauchu", "pathaidinchu",
        "milauchu", "milaidinchu", "sodhchu", "bujhchu", "jodidinchu", "team sanga kura garchu",
        "team lai bhanchu", "call garnus", "phone garnus", "aaunus", "sidhai aaunus", "message garnus",
    ],
}

# ---------------------------------------------------------------------------------------------------------------------
# 2. Never use -> use this instead. Applied as whole-word, case-insensitive swaps (the replacement keeps the original
#    word's capitalization). Ordered: multi-word phrases first so "maaf garnuhos" is swapped before "garnuhos".
#    Each entry: (pattern, replacement, kind). kind is "hindi", "bookish" or "error" -- for logging and the report.
# ---------------------------------------------------------------------------------------------------------------------
SWAPS: list[tuple[str, str, str]] = [
    # --- multi-word phrases ------------------------------------------------------------------------------------------
    (r"maaf garnuhos|maaf garnuhola|maf garnuhos|maaf garnus|kshama garnuhos|chhama garnuhos", "sorry", "bookish"),
    (r"bhanera batauna sakinu ?huncha|batauna sakinu ?huncha|batauna saknuhuncha", "bhanidinus na", "bookish"),
    (r"bhanera batauna sakinu ?hunchha|batauna sakinu ?hunchha", "bhanidinus na", "bookish"),
    (r"prapta bhayo", "aayo", "bookish"),
    (r"prapta bhayepachi", "aaye pachi", "bookish"),
    (r"prapta huncha|prapta hunechha|prapta hunecha", "aaihalcha", "bookish"),
    (r"theek hai|thik hai", "thik cha", "hindi"),
    (r"ke liye|ka liye", "ko lagi", "hindi"),
    (r"tyo sambandhi|yo sambandhi", "tyo barema", "bookish"),
    (r"sahayog garna", "help garna", "bookish"),
    (r"madat garna chu", "help garna yaha chu", "error"),
    (r"gari diye", "garidiye", "error"),
    (r"gari dinchu", "garidinchu", "error"),
    (r"gari dinu", "garidinu", "error"),
    (r"sabaibhanda haile ka", "bhakhar ka", "error"),
    (r"aru kehi sahayog chahiyo bhane bhanuhos", "aru kehi chahiyo bhane bhannus", "bookish"),
    # --- Hindi words that never belong in Nepali ---------------------------------------------------------------------
    (r"kahan", "kaha", "hindi"),
    (r"dhanyavaad|dhanyavad|dhanyawad", "dhanyabad", "hindi"),
    (r"bilkul", "pakka", "hindi"),
    (r"zaroor|zarur", "pakka", "hindi"),
    (r"abhi", "aile", "hindi"),
    (r"aapka|aapki|aapke", "tapaiko", "hindi"),
    (r"aapko", "tapailai", "hindi"),
    (r"aap", "tapai", "hindi"),
    (r"bahut", "dherai", "hindi"),
    (r"samay", "time", "hindi"),
    (r"kripaya|kripya|kirpaya", "", "bookish"),
    # --- textbook / government-office words --------------------------------------------------------------------------
    (r"samaya", "time", "bookish"),
    (r"janakari|jaankari|jankari", "info", "bookish"),
    (r"sahayog", "help", "bookish"),
    (r"upalabdha|uplabdha|upalabdh", "available", "bookish"),
    (r"aagami|agami", "aune", "bookish"),
    (r"vyakti|byakti|byakti", "jana", "bookish"),
    (r"samasya", "problem", "bookish"),
    (r"sunischit|sunishchit", "pakka", "bookish"),
    (r"anurodh", "request", "bookish"),
    (r"byabastha|vyavastha|byawastha", "setup", "bookish"),
    (r"pratiksha", "wait", "bookish"),
    (r"sampark", "contact", "bookish"),
    (r"prayog", "use", "bookish"),
    (r"(\w+na) sakinu ?huncha", r"\1 milcha", "bookish"),
    (r"(\w+na) chahanu ?huncha", r"\1 man cha", "bookish"),
    (r"chahanu ?huncha", "chahiyo", "bookish"),
    (r"chahanuhuncha", "chahiyo", "bookish"),
    # --- polite-imperative: texting form, not the letter-writing form --------------------------------------------------
    (r"garnuhos", "garnus", "bookish"),
    (r"dinuhos|dinuhosh", "dinus", "bookish"),
    (r"bhannuhos|bhanuhos|bhanuhosh", "bhannus", "bookish"),
    (r"tirnuhos", "tirnus", "bookish"),
    (r"dekhaunuhos", "dekhaunus", "bookish"),
    (r"aaunuhos|aunuhos", "aaunus", "bookish"),
    (r"pathaunuhos", "pathaunus", "bookish"),
    (r"herunuhos|hernuhos", "hernus", "bookish"),
    (r"([a-z]+)nuhos", r"\1nus", "bookish"),
    # --- plain spelling errors seen in real replies -------------------------------------------------------------------
    (r"bhena", "bhayena", "error"),
    (r"aera", "aaera", "error"),
    (r"saknchu", "sakchu", "error"),
    (r"garchhu", "garchu", "error"),
    (r"chahinchha", "chahincha", "error"),
    (r"bandha", "banda", "error"),
    (r"budhabar", "Budhbar", "error"),
]

# Seen in real replies and always wrong, but no word swap fixes them safely -- counted by the report, named in the
# prompt, and never produced by a template. (Each is a regex, whole-word, case-insensitive.)
FLAG_ONLY: list[tuple[str, str]] = [
    (r"bujhna chahanchu", "bookish"),
    (r"garna chahanchu", "bookish"),
    (r"madhyam", "bookish"),
    (r"nahi|nahin", "hindi"),
    (r"kya", "hindi"),
    (r"hoga|hogi", "hindi"),
    (r"kaunsa|kaunsi", "hindi"),
    (r"karna|karenge|karunga|karungi", "hindi"),
    (r"accha|achha", "hindi"),
    (r"mera|meri", "hindi"),
    (r"aadi", "bookish"),
    (r"awastha|avastha", "bookish"),
    (r"adhyavadhik|adyavadhik", "bookish"),
]

# (?:...) matters: without it the word boundaries bind to the first and last alternative only, and "aunuhos" would
# match inside "btaunuhos".
_SWAP_RES = [(re.compile(rf"(?<![\w/@.])(?:{p})(?![\w@])", re.IGNORECASE), r, k) for p, r, k in SWAPS]
_FLAG_RES = [(re.compile(rf"(?<![\w/@.])(?:{p})(?![\w@])", re.IGNORECASE), k) for p, k in FLAG_ONLY]

# ---------------------------------------------------------------------------------------------------------------------
# 3. Spelling mirror. Real customers mostly write the "x" style (xa 80 vs cha 63, hunxa 42 vs huncha 9, vayo 33 vs
#    bhayo 3) -- the assistant wrote cha/huncha/bhayo every time. Only these listed Nepali word forms are ever
#    converted, never a pattern over all "ch" (check, chat, change...).
# ---------------------------------------------------------------------------------------------------------------------
_CH_STEMS = [
    "", "hun", "mil", "par", "lag", "gar", "din", "gardin", "garidin", "sak", "aau", "jaan", "jaa", "bhan", "her",
    "pathau", "pathaidin", "chahin", "bas", "khul", "lin", "dekhin", "milaidin", "sardin", "herdin", "jodidin",
    "sodh", "bujh", "pug", "rah", "bhai", "aaihal", "hudai", "gardai", "aaudai", "jaandai", "bhaihal", "lagau",
    "milaidi", "garidi", "pathaidi",
]
_CH_ENDINGS = {"cha": "xa", "chha": "xa", "chu": "xu", "chhu": "xu", "chau": "xau", "chan": "xan", "chaina": "xaina",
               "chhaina": "xaina", "chhan": "xan", "chhau": "xau"}
_TO_X: dict[str, str] = {}
for _stem in _CH_STEMS:
    for _ch, _x in _CH_ENDINGS.items():
        _TO_X[_stem + _ch] = _stem + _x
_TO_X.update({
    "chito": "xito", "chhito": "xito", "chadai": "xadai", "bhayo": "vayo", "bhaisakyo": "vaisakyo",
    "bhaihalyo": "vaihalyo", "bhanera": "vanera", "bhannus": "vannus", "bhane": "vane", "bhayena": "vayena",
    "bhaena": "vayena", "ahile": "aile", "kahile": "kaile", "ke": "k", "chaina": "xaina",
    "bhanchu": "vanxu", "bhanidinus": "vanidinus", "bhaneko": "vaneko", "bhaye": "vaye", "bhayeko": "vayeko",
})
# "bh" -> "v" stays consistent inside a converted word: bhaihalcha -> vaihalxa, not bhaihalxa.
_TO_X = {k: ("v" + v[2:] if v.startswith("bh") else v) for k, v in _TO_X.items()}
_X_RE = re.compile(r"\b(" + "|".join(sorted(map(re.escape, _TO_X), key=len, reverse=True)) + r")\b", re.IGNORECASE)

# Customer-side signals: words that only an x/v-style writer types.
_X_STYLE_WORDS = {"xa", "xaina", "hunxa", "vayo", "milxa", "parxa", "garxu", "vanera", "xu", "voli", "xito", "lagxa",
                  "garxa", "sakxu", "vannus", "xan", "xau", "vaneko", "dinxu", "hunxaina", "vaisakyo", "vane"}
_CH_STYLE_WORDS = {"cha", "chha", "chaina", "huncha", "bhayo", "milcha", "parcha", "garchu", "bhanera", "chu", "bholi",
                   "chito", "lagcha", "garcha", "sakchu", "bhannus", "bhaneko", "dinchu", "bhaisakyo", "bhane"}
_WORD_RE = re.compile(r"[A-Za-z]+")


def customer_spelling_style(customer_texts: list[str]) -> str:
    """"x" when the customer writes xa/vayo/hunxa more than cha/bhayo/huncha, else "ch" (the default)."""
    x = ch = 0
    for text in customer_texts:
        for w in _WORD_RE.findall(text.lower()):
            x += w in _X_STYLE_WORDS
            ch += w in _CH_STYLE_WORDS
    return "x" if x > ch else "ch"


def _keep_case(original: str, replacement: str) -> str:
    if not replacement:
        return replacement
    if original.isupper() and len(original) > 1:
        return replacement.upper()
    if original[0].isupper():
        return replacement[0].upper() + replacement[1:]
    return replacement


def mirror_spelling(text: str, style: str) -> str:
    if style != "x":
        return text
    return _X_RE.sub(lambda m: _keep_case(m.group(0), _TO_X[m.group(0).lower()]), text)


# ---------------------------------------------------------------------------------------------------------------------
# Protected spans: URLs, emails, booking refs, and any caller-supplied names (services, the business, the customer)
# are never touched -- "Samaya Dental" or a link containing "abhi" must come through byte-for-byte.
# ---------------------------------------------------------------------------------------------------------------------
_PROTECT_RE = re.compile(r"https?://\S+|\S+@\S+\.\S+|\b[A-Z0-9]{5,}\b|\{[A-Z_]+\}")
# A Roman word with a Devanagari suffix glued on ("Hamiले"): the suffix is transliterated.
_MIXED_SCRIPT_SUFFIX = {"ले": "le", "लाई": "lai", "को": "ko", "मा": "ma", "हरू": "haru", "सँग": "sanga", "बाट": "bata"}
_MIXED_SCRIPT_RE = re.compile(r"([A-Za-z]+)(" + "|".join(_MIXED_SCRIPT_SUFFIX) + r")")


def _mask(text: str, names: list[str]) -> tuple[str, list[str]]:
    spans: list[str] = []

    def keep(m: re.Match) -> str:
        spans.append(m.group(0))
        return f"\x00{len(spans) - 1}\x00"

    for name in sorted({n for n in names if n and len(n) > 2}, key=len, reverse=True):
        text = re.sub(re.escape(name), keep, text)
    return _PROTECT_RE.sub(keep, text), spans


def _unmask(text: str, spans: list[str]) -> str:
    return re.sub(r"\x00(\d+)\x00", lambda m: spans[int(m.group(1))], text)


def _tidy(text: str) -> str:
    text = re.sub(r"[ \t]{2,}", " ", text)
    text = re.sub(r" +([,.?!])", r"\1", text)
    text = text.strip()
    text = re.sub(r"(^|[.!?]\s+)([a-z])", lambda m: m.group(1) + m.group(2).upper(), text)
    return text


def polish_reply(text: str, *, style: str = "ch", protected: list[str] | None = None) -> tuple[str, list[str]]:
    """Clear-cut word swaps (Hindi/textbook -> natural), spelling mirror, mixed-script fix. Returns (text, changes),
    `changes` a list of "old->new (kind)" strings for the log. Only call on a Romanized-Nepali or mixed reply."""
    masked, spans = _mask(text, protected or [])
    changes: list[str] = []

    def mixed(m: re.Match) -> str:
        changes.append(f"{m.group(0)}->{m.group(1)}{_MIXED_SCRIPT_SUFFIX[m.group(2)]} (error)")
        return m.group(1) + _MIXED_SCRIPT_SUFFIX[m.group(2)]

    masked = _MIXED_SCRIPT_RE.sub(mixed, masked)
    for regex, replacement, kind in _SWAP_RES:
        def swap(m: re.Match, replacement=replacement, kind=kind) -> str:
            new = m.expand(replacement) if "\\" in replacement else replacement
            new = _keep_case(m.group(0), new)
            changes.append(f"{m.group(0)}->{new or '∅'} ({kind})")
            return new
        masked = regex.sub(swap, masked)
    before_mirror = masked
    masked = mirror_spelling(masked, style)
    if masked != before_mirror:
        changes.append("spelling mirrored to x/v style")
    result = _unmask(_tidy(masked), spans)
    return result, changes


def find_issues(text: str) -> list[tuple[str, str]]:
    """Every never-use word in `text` as (word, kind) -- swappable or flag-only. Used by tests and the report."""
    masked, _ = _mask(text, [])
    found = [(m.group(0), k) for regex, _, k in _SWAP_RES for m in regex.finditer(masked)]
    found += [(m.group(0), k) for regex, k in _FLAG_RES for m in regex.finditer(masked)]
    found += [(m.group(0), "error") for m in _MIXED_SCRIPT_RE.finditer(masked)]
    # "(\w+na) sakinu huncha" and its bare cousin can both hit the same words; count each span once.
    seen, unique = set(), []
    for word, kind in found:
        if word.lower() not in seen:
            seen.add(word.lower())
            unique.append((word, kind))
    return unique


def prompt_word_guide() -> str:
    """The word-bank section of intent.py's system prompt: short on purpose (shorter instructions get followed)."""
    return (
        "ROMANIZED NEPALI WORD BANK — how Nepali people actually text. Use: huss, hunchha/huncha, la, thik cha, "
        "pakka, milcha?, k, kati, kun, kaile, kaha, kasari; aaja, bholi, parsi, aile, bihana, diuso, beluka, "
        "sadhe 10 baje, dedh baje; book garidinchu, milaidinchu, sardinchu, cancel garidiye, check garchu; "
        "softeners ni, ta, na, ali, hai; dinus, garnus, bhannus, pathaidinus (never dinuhos/garnuhos). "
        "Never use Hindi (kya, aap, nahi, abhi, kal, bilkul, zaroor, bahut, kahan, samay, ke liye, theek hai) "
        "and never textbook/office words (kripaya, prapta, madhyam, janakari, sahayog, upalabdha, aagami, vyakti, "
        "samasya, maaf garnuhos, sakinu huncha, chahanu huncha, bujhna chahanchu) — say sorry, info, help, "
        "available, aune, jana, problem, milcha?, chahiyo? instead. Mirror the customer's spelling: if they write "
        "xa/vayo/hunxa/voli, write xa/vayo/hunxa/voli; if they write cha/bhayo, write that."
    )
