"""Turns the filled docs/nepali_voice/situation_sheet.md into shared style exemplars (rows s01..s60 of seed_v1.csv).

Each situation's "Your version" becomes an example the assistant copies for every business ("OK" = keep the draft,
"SKIP" = leave it out). Before anything is written, every line goes through the same checks as the app's own replies;
a line that fails is NOT imported and is listed, so a slip in the sheet never becomes the bot's habit:
  - Hindi/textbook words and broken spelling (nepali_wordbank.find_issues)
  - Devanagari letters inside a Romanized line
  - an unfinished placeholder ("...", "(simple explanation)")
  - "AI"/"virtual assistant" outside the two "who are you" situations

    python scripts/import_situation_sheet.py            # show what would change
    python scripts/import_situation_sheet.py --write    # update seed_v1.csv (then run seed_style_exemplars.py --prune)
"""

import csv
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app.services.conversation.nepali_wordbank import find_issues  # noqa: E402

SHEET = ROOT.parent / "docs" / "nepali_voice" / "situation_sheet.md"
CSV_PATH = ROOT / "data" / "style_exemplars" / "seed_v1.csv"
PREFIX = "s"
# Rows this sheet replaces (the earlier drafts of the same identity answers).
SUPERSEDED = {"id01", "id02", "id03"}

# Situation number -> intent (the CSV's intent column; retrieval is semantic, the intent is for reading the CSV).
INTENTS = {
    **dict.fromkeys(range(1, 6), "greeting"),
    **dict.fromkeys(range(6, 13), "pricing_question"),
    11: "general_question",
    **dict.fromkeys(range(13, 17), "service_question"),
    17: "pricing_question", 18: "pricing_question",
    **dict.fromkeys(range(19, 24), "booking"),
    24: "cancellation", 25: "rescheduling", 26: "follow_up",
    **dict.fromkeys(range(27, 32), "complaint"),
    30: "follow_up",
    **dict.fromkeys(range(32, 38), "follow_up"),
    **dict.fromkeys(range(38, 41), "off_topic"),
    **dict.fromkeys(range(41, 46), "follow_up"),
    44: "pricing_question",
    46: "location", 47: "business_hours", 48: "general_question", 49: "general_question", 50: "human_handoff",
    51: "booking", 52: "general_question", 53: "follow_up", 54: "follow_up", 55: "pricing_question",
    56: "follow_up", 57: "follow_up", 58: "follow_up", 59: "booking", 60: "pricing_question",
}
LANGUAGES = {54: "en", 55: "mixed", 57: "mixed"}
IDENTITY = {34, 35}

_HEAD = re.compile(r"^###\s+(\d+)\.\s*(.+)$")
_FIELD = re.compile(r"^[*\-\s]*(\*\*)?(Customer|Draft|Your version)(\*\*)?\s*:\s*(\*\*)?\s*(.*)$", re.IGNORECASE)
_DEVANAGARI = re.compile(r"[ऀ-ॿ]")
_AI_WORD = re.compile(r"\b(ai|a\.i\.|artificial intelligence|chat ?bot|virtual assistant)\b", re.IGNORECASE)


def _unquote(text: str) -> str:
    text = text.strip().strip("*").strip()
    if len(text) >= 2 and text[0] == text[-1] == "`":
        text = text[1:-1].strip()
    return text


def parse(md: str) -> list[dict]:
    items, cur = [], None
    for line in md.splitlines():
        if m := _HEAD.match(line.strip()):
            cur = {"n": int(m.group(1)), "title": m.group(2).strip(), "customer": "", "draft": "", "version": ""}
            items.append(cur)
        elif cur and (m := _FIELD.match(line)):
            key = {"customer": "customer", "draft": "draft", "your version": "version"}[m.group(2).lower()]
            cur[key] = _unquote(m.group(5))
    return items


def final_text(item: dict) -> str | None:
    v = item["version"]
    if not v:
        return None
    if v.upper() == "OK":
        return item["draft"]
    if v.upper().startswith("SKIP"):
        return None
    return v


def problems(n: int, text: str, language: str) -> list[str]:
    out = []
    if language != "en":
        issues = find_issues(text)
        if issues:
            out.append("word check: " + ", ".join(f"{w} ({k})" for w, k in issues))
        if _DEVANAGARI.search(text):
            out.append("Devanagari letters inside a Romanized line: " + " ".join(_DEVANAGARI.findall(text)))
    if "..." in text or "…" in text or re.search(r"\((simple|e\.g\.|explanation)", text, re.I):
        out.append("unfinished placeholder")
    if n not in IDENTITY and _AI_WORD.search(text):
        out.append("mentions AI outside a 'who are you' situation")
    return out


def build(items: list[dict]) -> tuple[list[dict], list[tuple[int, str, list[str]]]]:
    rows, rejected = [], []
    for item in items:
        text = final_text(item)
        if not text:
            continue
        n = item["n"]
        language = LANGUAGES.get(n, "ne_roman")
        bad = problems(n, text, language)
        if bad:
            rejected.append((n, text, bad))
            continue
        rows.append({"id": f"{PREFIX}{n:02d}", "business_type": "shared", "intent": INTENTS.get(n, "follow_up"),
                     "language": language, "register": "warm", "text": text,
                     "notes": f"situation sheet 2026-10-01 #{n} {item['title']}; any business"})
    return rows, rejected


def merge(existing: list[dict], new_rows: list[dict]) -> list[dict]:
    keep = [r for r in existing if not re.fullmatch(rf"{PREFIX}\d\d", r["id"]) and r["id"] not in SUPERSEDED]
    return keep + new_rows


def main(argv: list[str]) -> None:
    rows, rejected = build(parse(SHEET.read_text(encoding="utf-8")))
    print(f"{len(rows)} situations ready to import")
    for n, text, bad in rejected:
        print(f"  NOT imported #{n}: {text}\n      -> {'; '.join(bad)}")
    if "--write" not in argv:
        print("dry run; add --write to update", CSV_PATH.name)
        return
    with CSV_PATH.open(encoding="utf-8", newline="") as f:
        reader = csv.DictReader(f)
        fields, existing = reader.fieldnames, list(reader)
    merged = merge(existing, rows)
    with CSV_PATH.open("w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=fields)
        w.writeheader()
        w.writerows(merged)
    print(f"wrote {CSV_PATH.name}: {len(merged)} rows ({len(rows)} from the sheet)")


if __name__ == "__main__":
    main(sys.argv[1:])
