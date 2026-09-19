"""Candidate narrow fixes for the real rule-3 violation (a closing "thanks!" answered with a booking/details offer), as
IN-MEMORY edits of the extracted production template -- intent.py is never touched. Two variants, tested in
scripts/thanks_experiment.py:
  A  example-only : the prompt's own few-shot for "thanks!" (intent.py ~l.306) ends "...Aru kehi sahayog chahiyo bhane
     bhanuhos." = a generic 'tell me if you need more help' tail, i.e. the prompt itself demonstrates what rule 3 forbids.
  B  A + one added sentence + example in rule 3 naming the SOFT versions of the tail (the actual observed violation)."""
from lab.production_prompt import TEMPLATE

EX_OLD = "Dhanyabad! Aru kehi sahayog chahiyo bhane bhanuhos."
EX_NEW = "Dhanyabad!"
R3_ANCHOR = 'not "You\'re welcome! Would you like me to check available times for anything else?"'
R3_ADD = (' The same goes for softer versions of that tail — "If you\'d like to book X or want more details, just let me '
          'know," "Let me know if you\'d like more information about X" — and for restating a service, price, or date '
          'the conversation already covered: after a "thank you," "thanks!," or "huss," say only a brief, warm '
          'acknowledgment and stop. Example: customer "thanks!" right after a price answer -> "You\'re welcome! 😊" — '
          'not "You\'re welcome! If you\'d like to book it or want more details, just let me know."')


def _once(t, old):
    assert t.count(old) == 1, (old, t.count(old))
    return t


def variant_a(t: str = TEMPLATE) -> str:
    return _once(t, EX_OLD).replace(EX_OLD, EX_NEW)


def variant_b(t: str = TEMPLATE) -> str:
    t = variant_a(t)
    return _once(t, R3_ANCHOR).replace(R3_ANCHOR, R3_ANCHOR + R3_ADD)


def variant_c(t: str = TEMPLATE) -> str:
    """rule-3 sentence ONLY (existing example left untouched) -- to see which hunk is actually necessary."""
    return _once(t, R3_ANCHOR).replace(R3_ANCHOR, R3_ANCHOR + R3_ADD)


if __name__ == "__main__":
    a, b = variant_a(), variant_b()
    assert len(b) > len(a) > len(TEMPLATE) - 60 and "kehi sahayog" not in a and "softer versions" in b and "softer" not in a
    print("patch variants apply cleanly: A", len(a) - len(TEMPLATE), "chars, B +", len(b) - len(TEMPLATE), "chars vs current template")
