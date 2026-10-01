"""Gold set for calibrating judges.

1. MINIMAL PAIRS (below): the same customer message with two replies that differ in ONE known defect, so which reply
   is better is known by construction -- no annotator needed. A judge that can't pick the good one on a defect type
   can't be trusted to measure that defect. `lint` says whether the deterministic lint is expected to catch the
   defect (the rest -- tone, warmth, helpfulness -- is exactly what the LLM judges are for).
   Constructed from the real customer vocabulary in data/regression/real_conversations; flagged for native review
   in docs/nepali_voice/ before the numbers are quoted as final.

2. NATIVE LABELS: docs/nepali_voice/native_review_sheet.md, once a native speaker fills in "Your verdict:" -- "OK"
   means the 'after' reply is good; any other text is how a Nepali receptionist would really write it, which becomes
   a pair (native rewrite > our reply). See native_pairs().
"""

import re
from pathlib import Path

PAIRS: list[dict] = [
    # --- Hindi words leaking into Romanized Nepali --------------------------------------------------------------
    {"id": "hindi-1", "defect": "hindi", "lint": True, "customer": "cleaning ko price kati ho?",
     "good": "Cleaning ko 1500 rupaiya ho, 30 minute jati lagcha.",
     "bad": "Cleaning ko price 1500 rupaiya ho, abhi book garna milcha."},
    {"id": "hindi-2", "defect": "hindi", "lint": True, "customer": "aaja khulla cha?",
     "good": "Cha, aaja beluka 6 baje samma khulla cha.",
     "bad": "Haan, aaja khulla cha, kya tapai aaunu huncha?"},
    {"id": "hindi-3", "defect": "hindi", "lint": True, "customer": "bholi ko lagi slot cha?",
     "good": "Bholi bihana 10 baje ra diuso 2 baje khali cha — kun milcha?",
     "bad": "Bholi ko lagi slot nahi cha, parsi milcha."},
    {"id": "hindi-4", "defect": "hindi", "lint": True, "customer": "clinic kaha cha?",
     "good": "Hami Baneshwor ma chau, Everest Bank ko chheu ma.",
     "bad": "Hamro clinic kahan cha bhanda, Baneshwor ma."},
    {"id": "hindi-5", "defect": "hindi", "lint": True, "customer": "booking cancel garna milcha?",
     "good": "Milcha, kun din ko booking cancel garne?",
     "bad": "Bilkul milcha, kun din ko booking cancel garne?"},
    # --- textbook / office Nepali -----------------------------------------------------------------------------------
    {"id": "bookish-1", "defect": "bookish", "lint": True, "customer": "naam ra number chahiyo?",
     "good": "Ho, naam ra phone number pathaidinus na.",
     "bad": "Ho, kripaya tapaiko naam ra phone number pathaunuhos."},
    {"id": "bookish-2", "defect": "bookish", "lint": True, "customer": "payment kasari garne?",
     "good": "eSewa ki Khalti bata tirna milcha, ki clinic mai aayera.",
     "bad": "Payment ko janakari: eSewa wa Khalti madhyam bata bhuktani garna saknuhuncha."},
    {"id": "bookish-3", "defect": "bookish", "lint": True, "customer": "mero booking confirm bhayo?",
     "good": "Bhayo, bholi 11 baje ko booking pakka cha 😊",
     "bad": "Tapaiko booking ko janakari prapta bhayo, bholi 11 baje pakka cha."},
    {"id": "bookish-4", "defect": "bookish", "lint": True, "customer": "k bhaneko bujhina",
     "good": "Sorry, ali clear bhanena — kun service chahiyo ra kaile aauna milcha?",
     "bad": "Maaf garnuhos, kun service ra kun miti chahanu huncha bhanera batauna sakinu huncha?"},
    {"id": "bookish-5", "defect": "bookish", "lint": True, "customer": "ma aaja aauna sakdina",
     "good": "Hunchha, arko din milaidinchu — kaile aauna milcha?",
     "bad": "Thik cha, kripaya arko upayukta samaya batauna sakinu huncha?"},
    {"id": "bookish-6", "defect": "bookish", "lint": True, "customer": "thank you",
     "good": "Hajur, dhanyabad! 😊",
     "bad": "Dhanyabad! Aru kehi sahayog chahiyo bhane kripaya bhanuhos."},
    # --- register: timi -------------------------------------------------------------------------------------------
    {"id": "timi-1", "defect": "timi", "lint": True, "customer": "timi ko ho?",
     "good": "Ma yaha ko assistant ho — booking, price, time jasta kura ma help garchu.",
     "bad": "Ma yaha ko assistant ho — timilai booking ma help garchu."},
    {"id": "timi-2", "defect": "timi", "lint": True, "customer": "mero appointment kati baje ho",
     "good": "Tapaiko appointment bholi 10 baje cha.",
     "bad": "Timro appointment bholi 10 baje cha."},
    # --- English date in the middle of Nepali ---------------------------------------------------------------------
    {"id": "date-1", "defect": "english_date", "lint": True, "customer": "kaile khali cha?",
     "good": "Sombar (Oct 5) bihana sadhe 10 baje khali cha — milcha?",
     "bad": "Monday, October 5 at 10:30 AM khali cha — milcha?"},
    {"id": "date-2", "defect": "english_date", "lint": True, "customer": "mero booking kaile ho",
     "good": "Tapaiko booking Bihibar (Oct 8) diuso 2 baje cha.",
     "bad": "Tapaiko booking Thursday, October 8 at 2:00 PM ma cha."},
    # --- wrong language / script ---------------------------------------------------------------------------------
    {"id": "lang-1", "defect": "wrong_language", "lint": True, "customer": "bholi aauna milcha?",
     "good": "Milcha, bholi kati baje aaune?",
     "bad": "Sure, what time would you like to come tomorrow?"},
    {"id": "lang-2", "defect": "wrong_language", "lint": True, "customer": "price kati ho root canal ko",
     "good": "Root canal ko 8000 rupaiya jati parcha, daat herera final huncha.",
     "bad": "A root canal costs around NPR 8000, depending on the tooth."},
    {"id": "lang-3", "defect": "wrong_script", "lint": True, "customer": "aaja kati baje samma khulla cha?",
     "good": "Aaja beluka 6 baje samma khulla cha.",
     "bad": "आज बेलुका ६ बजेसम्म खुल्ला छ।"},
    # --- spelling and mixed script --------------------------------------------------------------------------------
    {"id": "spell-1", "defect": "spelling", "lint": True, "customer": "booking bhayo?",
     "good": "Bhayena, tyo time ma arko booking cha. 2 baje milcha?",
     "bad": "Bhena, tyo time ma arko booking cha. 2 baje milcha?"},
    {"id": "spell-2", "defect": "mixed_script", "lint": True, "customer": "doctor kaha baschan?",
     "good": "Hamro doctor le Baneshwor ko clinic ma herchan.",
     "bad": "Hamro doctorले Baneshwor ko clinic ma herchan."},
    {"id": "spell-3", "defect": "spelling_style", "lint": True, "customer": "voli milxa? price kati xa?",
     "good": "Milxa, voli 11 baje khali xa. Price 1500 ho.",
     "bad": "Milcha, bholi 11 baje khali cha. Price 1500 ho."},
    # --- human-likeness: repeat, stock ending, monologue ---------------------------------------------------------
    {"id": "repeat-1", "defect": "repeat", "lint": True, "customer": "ok number 9800000000",
     "history": [{"role": "customer", "text": "book garna paryo"},
                 {"role": "assistant", "text": "Booking garna tapaiko naam ra phone number chahincha."},
                 {"role": "customer", "text": "Sita"}],
     "good": "La, Sita ji, number paye — aba kun din aaune?",
     "bad": "Booking garna tapaiko naam ra phone number chahincha."},
    {"id": "stock-1", "defect": "stock_ending", "lint": True, "customer": "parking cha?",
     "good": "Cha, clinic agadi nai 4-5 wota gaadi rakhne thau cha.",
     "bad": "Cha, clinic agadi nai parking cha. Aru kehi chahiyo bhane bhannus."},
    {"id": "stock-2", "defect": "stock_ending", "lint": True, "customer": "do you open on saturday?",
     "good": "No, we're closed on Saturdays — open Sunday to Friday, 9 to 6.",
     "bad": "No, we're closed on Saturdays. Let me know if there's anything else I can help with!"},
    {"id": "mono-1", "defect": "monologue", "lint": True, "customer": "hours?",
     "good": "Aaitabar dekhi Sukrabar, bihana 9 dekhi beluka 6 samma.",
     "bad": "Hamro clinic Aaitabar dekhi Sukrabar samma bihana 9 baje dekhi beluka 6 baje samma khulla huncha, "
            "Sanibar banda huncha, ra public holiday haru ma pani prayah banda huncha, tara emergency ko lagi tapai "
            "hamilai phone garna saknu huncha ani hamro team le sakdo chadai help garcha, appointment liyera aaunu "
            "bhayo bhane wait garnu pardaina, walk-in pani accept garchau tara ali wait garnu parna sakcha."},
    # --- LLM-only: tone, warmth, helpfulness (lint can't and shouldn't decide these) -----------------------------
    {"id": "warm-1", "defect": "cold", "lint": False, "customer": "mero daat dherai dukhyo, aaja nai dekhaunu paryo",
     "good": "Ouch, dukhda dherai garo huncha 😕 aaja diuso 3 baje khali cha — aauna milcha?",
     "bad": "Aaja diuso 3 baje khali cha."},
    {"id": "warm-2", "defect": "cold", "lint": False, "customer": "3 choti phone gare kasaile uthaena",
     "good": "3 choti ma pani kasaile nauthaunu ramro bhayena, sorry. Aile nai herchu — k ko lagi phone garnu bhako?",
     "bad": "Hamro phone line busy huna sakcha. K ko lagi phone garnu bhako?"},
    {"id": "help-1", "defect": "unhelpful", "lint": False, "customer": "whitening ko price kati ho?",
     "good": "Whitening ko 5000 rupaiya ho, ek ghanta jati lagcha.",
     "bad": "Whitening ekdam ramro service ho, dherai jana le garaunu huncha."},
    {"id": "help-2", "defect": "unhelpful", "lint": False, "customer": "bholi 10 baje milcha?",
     "good": "10 baje bhari bhayo, 11 baje ra 2 baje khali cha — kun milcha?",
     "bad": "Hami bihana 9 baje dekhi beluka 6 baje samma khulla chau."},
    {"id": "help-3", "defect": "unhelpful", "lint": False, "customer": "ma mero booking sarna chahanchu",
     "good": "Huss, kun din ma sarne?",
     "bad": "Booking garna kun service chahiyo?"},
    {"id": "help-4", "defect": "asks_twice", "lint": False, "customer": "Sita, 9800000000",
     "history": [{"role": "customer", "text": "bholi 10 baje cleaning book garidinus"},
                 {"role": "assistant", "text": "Huss! Book garna naam ra phone number pathaidinus na."}],
     "good": "La Sita ji, bholi 10 baje cleaning book bhayo 😊",
     "bad": "Thanks! Tapaiko naam ra number feri pathaidinus na."},
    {"id": "robot-1", "defect": "robotic", "lint": False, "customer": "hello",
     "good": "Namaste! K help garum?",
     "bad": "Namaste! Samaj Dental Clinic ma tapailai swagat cha. Ma tapailai appointment, service, price ra time ko "
            "barema help garna sakchu. Tapailai k chahiyo?"},
    {"id": "robot-2", "defect": "robotic", "lint": False, "customer": "ok thanks",
     "good": "Hunchha, aaunus hai 😊",
     "bad": "Tapaiko sandesh ko lagi dhanyabad. Tapaiko anurodh safal bhayo."},
    {"id": "en-1", "defect": "robotic", "lint": False, "customer": "can I bring my kid along?",
     "good": "Of course — kids are welcome. If they need a check-up too, I can book them in.",
     "bad": "Thank you for reaching out to us. I would be happy to assist you. Children are permitted on the premises."},
]


_ENTRY_RE = re.compile(
    r"^## (?P<n>\d+)\s*\n- Customer: (?P<customer>.*?)\n- Before: (?P<before>.*?)\n- After: (?P<after>.*?)\n"
    r"- Your verdict:(?P<verdict>.*?)(?=^## |\Z)",
    re.DOTALL | re.MULTILINE,
)
REVIEW_SHEET = Path(__file__).resolve().parents[4] / "docs" / "nepali_voice" / "native_review_sheet.md"


def native_labels(path: Path = REVIEW_SHEET) -> list[dict]:
    """Filled-in entries of the native review sheet: {"customer", "before", "after", "verdict", "ok", "rewrite"}."""
    if not path.exists():
        return []
    out = []
    for m in _ENTRY_RE.finditer(path.read_text(encoding="utf-8")):
        verdict = m["verdict"].strip()
        if not verdict:
            continue
        ok = verdict.lower().rstrip(".!") in {"ok", "okay", "thik", "thik cha", "good"}
        out.append({
            "id": f"native-{m['n']}", "customer": m["customer"].strip(), "before": m["before"].strip(),
            "after": m["after"].strip(), "verdict": verdict, "ok": ok, "rewrite": None if ok else verdict,
        })
    return out


def native_pairs(path: Path = REVIEW_SHEET) -> list[dict]:
    """A native rewrite of our reply is, by definition, better than our reply."""
    return [
        {"id": e["id"], "defect": "native", "lint": False, "customer": e["customer"], "good": e["rewrite"], "bad": e["after"]}
        for e in native_labels(path) if e["rewrite"]
    ]
