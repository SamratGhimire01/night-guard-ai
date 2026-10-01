"""Importing the native situation sheet into style exemplars: parsing both layouts, and never importing a bad line."""

import importlib.util
from pathlib import Path

_spec = importlib.util.spec_from_file_location(
    "import_situation_sheet", Path(__file__).resolve().parents[2] / "scripts" / "import_situation_sheet.py"
)
imp = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(imp)

FILLED = """
### 1. First "hi"

* Customer: `hlo`
* Draft: Namaste! Bhannus na, k help garum?
* **Your version:** `OK`

### 2. Namaste
* Customer: `namaste didi`
* Draft: Namaste hajur.
* **Your version:** `Namaste hajur! 😊 Bhannus na, k help garum?`

### 8. Too expensive
* Draft: x
* **Your version:** `Ekpatak try गरेर hernus na`

### 13. What is X
* **Your version:** `{SERVICE} bhaneko ... (simple explanation).`

### 19. Wants to book
* **Your version:** `Kati baje tira aauna chahanuhuncha?`

### 34. Are you a bot
* **Your version:** `Ma yahan ko virtual assistant ho 😊`

### 37. Small talk
* **Your version:** `Ma AI ho, khana khadina`

### 42. Thumbs
* **Your version:** `SKIP - never happens`
"""

TEMPLATE = """
### 6. Plain price question
Customer: `{SERVICE} kati parcha?`
Draft: {SERVICE} ko {PRICE} parcha hajur.
Your version: OK

### 7. Unfilled
Draft: something
Your version:
"""


def test_parses_filled_layout_and_resolves_ok_and_skip():
    items = {i["n"]: i for i in imp.parse(FILLED)}
    assert items[1]["customer"] == "hlo" and imp.final_text(items[1]) == "Namaste! Bhannus na, k help garum?"
    assert imp.final_text(items[2]) == "Namaste hajur! 😊 Bhannus na, k help garum?"
    assert imp.final_text(items[42]) is None


def test_parses_blank_template_layout():
    items = {i["n"]: i for i in imp.parse(TEMPLATE)}
    assert imp.final_text(items[6]) == "{SERVICE} ko {PRICE} parcha hajur."
    assert imp.final_text(items[7]) is None


def test_bad_lines_are_rejected_with_reasons():
    rows, rejected = imp.build(imp.parse(FILLED))
    reasons = {n: " ".join(r) for n, _, r in rejected}
    assert "Devanagari" in reasons[8]
    assert "placeholder" in reasons[13]
    assert "bookish" in reasons[19]
    assert "mentions AI" in reasons[37]
    ids = {r["id"] for r in rows}
    assert ids == {"s01", "s02", "s34"}  # 34 may say "virtual assistant": the customer asked who they're talking to
    assert all(r["business_type"] == "shared" for r in rows)


def test_merge_replaces_old_sheet_rows_and_superseded_drafts():
    existing = [{"id": "g01"}, {"id": "s05"}, {"id": "id01"}, {"id": "n03"}]
    merged = imp.merge(existing, [{"id": "s01"}])
    assert [r["id"] for r in merged] == ["g01", "n03", "s01"]


def test_the_committed_sheet_imports_cleanly():
    rows, rejected = imp.build(imp.parse(imp.SHEET.read_text(encoding="utf-8")))
    assert len(rows) >= 50
    assert all(not imp.problems(int(r["id"][1:]), r["text"], r["language"]) for r in rows)
