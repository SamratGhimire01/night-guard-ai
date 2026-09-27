"""Tiny shared helper (kept out of scripts/lang_report.py so importing it does not run that script's CLI)."""


def family(label):
    return {"en": "en", "ne_deva": "deva", "ne_roman": "roman", "mixed": "roman"}.get(label, "?")
