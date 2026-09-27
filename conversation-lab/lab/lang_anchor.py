"""Phase L8 (conversation-lab only): the production language-lock ANCHORING bug (found in L7) and its candidate fix.

The bug (L7, traced in a real run): production tells the model "This conversation's locked language: X ... write `response` in
X regardless of drift", and asks the same JSON object for `message_language` (an honest read of the CUSTOMER's message) AFTER
`response`. The model reports what it just wrote / what it was told, not what the customer typed -> plain English in a
Romanized-Nepali conversation comes back as message_language='ne_roman' -> streak reset -> the 3-message switch never completes.

Arms (all use the REAL orchestrator lock functions via lab.lang_mech, and the pre-fix production template read from git rev
b7b62b3 so the baseline does not move when the fix is ported):
  prod       pre-fix production (baseline)
  prod_fix   fix A + fix B
  prod_fixA  ablation: JSON key order only (message_language / language_switch_request first, before `response`; rule-7 sentence
             + the 4 lock few-shots reordered to match)
  prod_fixB  ablation: user-prompt lock line only ("this lock decides ONLY `response`; `message_language` still reports the
             customer's own words")
  prod_fixBN fixB + a NEUTRAL-TOKEN GUARD: while a lock exists, a message with no language evidence (no Devanagari, <=2 Latin
             words, <2 Nepali word-list hits) resolves to "no signal" and so never counts toward a switch streak. Added after
             L8 run 1: fixB alone fixed the anchoring but, because "Friday"/"3pm"/"yes" are literally English, three neutral
             tokens in a row then completed an English streak and flipped the lock (neutral-turn flips 4/223 -> 13/221). The old
             anchoring had been masking that by echoing the lock on exactly those turns.
Backend files are READ ONLY here. The fix is expressed as string surgery on the evaluated template (apply_fix); the production
port must produce an identical template (checked by `python -m lab.lang_anchor`, which compares the CURRENT backend template with
apply_fix(PRE))."""
import ast
import re
import subprocess

from lab import lang_mech as M
from lab.lang_mech import LABELS, ConvState, _call, _item, resolve_locked_language, resolve_message_language
from lab.production_prompt import _BACKEND, system_prompt, user_prompt

PRE_REV = "b7b62b3"  # last commit before the fix (production as of the booking-loop phase)


def _template_at(rev: str) -> str:
    src = subprocess.run(["git", "-C", str(M._REPO), "show", f"{rev}:backend/app/services/conversation/intent.py"],
                         capture_output=True, text=True, check=True).stdout
    return next(n.value.value for n in ast.parse(src).body
                if isinstance(n, ast.Assign) and getattr(n.targets[0], "id", "") == "_SYSTEM_PROMPT_TEMPLATE")


PRE_TEMPLATE = _template_at(PRE_REV)

# ---------------------------------------------------------------- the fix (single source of truth for the wording)
RULE7_OLD = ("if you truly can't tell (e.g. a bare number, emoji, or appointment id). This is just an "
             "honest observation of THIS message")
RULE7_NEW = ("if you truly can't tell (e.g. a bare number, emoji, or appointment id). Work out `message_language` FIRST -- "
             "it is the first field of the JSON, filled in before you write `response` -- from the customer's own words in "
             "THIS message alone: the language they typed, never the language the conversation is locked to and never the "
             "language you are about to reply in. A plain English message is \"en\" even when the conversation is locked to "
             "Nepali and your reply will be Nepali (and the reverse for Nepali in an English conversation): the lock decides "
             "only the language of `response`, never this field. This is just an honest observation of THIS message")

LOCK_LINE_OLD = ("Write `response` in this exact language/script regardless of minor drift in "
                 "the customer's current message.")
LOCK_LINE_NEW = ("Write `response` in this exact language/script regardless of minor drift in "
                 "the customer's current message. This lock decides ONLY the language of `response`: report "
                 "`message_language` from the customer's own words alone (plain English is \"en\" even here).")


def _apply_order(t: str) -> str:
    """Fix A: observations before the reply. JSON schema head + the rule-7 sentence + the 4 few-shots that show the fields."""
    t = t.replace(RULE7_OLD, RULE7_NEW, 1)
    old_schema = ('{{"intent": "<one of the intents above>", "response": "<your reply to the customer>", ')
    new_schema = ('{{"message_language": "<one of en, ne_deva, ne_roman, mixed, unclear>", '
                  '"language_switch_request": null or "<one of en, ne_deva, ne_roman, mixed>", '
                  '"intent": "<one of the intents above>", "response": "<your reply to the customer>", ')
    assert t.count(old_schema) == 1
    t = t.replace(old_schema, new_schema, 1)
    tail_old = ('"needs_human_handoff": true or false, "message_language": "<one of en, ne_deva, ne_roman, mixed, unclear>", '
                '"language_switch_request": null or "<one of en, ne_deva, ne_roman, mixed>"}}')
    assert t.count(tail_old) == 1
    t = t.replace(tail_old, '"needs_human_handoff": true or false}}', 1)
    # the 4 few-shots: move message_language / language_switch_request in front of "intent"
    def move(m):
        intent, response, ml, rest = m.group(1), m.group(2), m.group(3), m.group(4)
        lead = f'"message_language": "{ml}", '
        sw = re.search(r'"language_switch_request": (null|"[a-z_]+"), ?', rest)
        if sw:
            lead += sw.group(0)
            rest = re.sub(r",\s*$", "", rest.replace(sw.group(0), "", 1))
        return f'Assistant: {{{{{lead}"intent": {intent}, "response": {response}{rest}}}}}'
    pat = re.compile(r'Assistant: \{\{"intent": ("[a-z_]+"), "response": ("(?:[^"\\]|\\.)*"), "message_language": "([a-z_]+)"(.*?)\}\}\n', re.S)
    t, n = pat.subn(lambda m: move(m) + "\n", t)
    assert n == 4, f"expected 4 lock few-shots, found {n}"
    return t


def apply_fix(t: str, order: bool = True) -> str:
    return _apply_order(t) if order else t


def lock_line(fixB: bool) -> str:
    return (f"This conversation's locked language: {{label}}. " + (LOCK_LINE_NEW if fixB else LOCK_LINE_OLD)) + "\n\n"


FIX_TEMPLATE = apply_fix(PRE_TEMPLATE, order=True)
FIXA_TEMPLATE = FIX_TEMPLATE  # order-only ablation uses the same template, but the OLD lock line

TEMPLATES = {"prod": PRE_TEMPLATE, "prod_fix": FIX_TEMPLATE, "prod_fixA": FIX_TEMPLATE, "prod_fixB": PRE_TEMPLATE,
             "prod_fixBN": PRE_TEMPLATE}
FIXB_LINE = {"prod": False, "prod_fix": True, "prod_fixA": False, "prod_fixB": True, "prod_fixBN": True}
NEUTRAL_GUARD = {"prod_fixBN"}


def is_language_neutral(content: str) -> bool:
    """LAB COPY of the production helper (orchestrator._is_language_neutral, added when the fix is ported; the two are compared
    by `python -m lab.lang_anchor` once ported). No Devanagari, at most 2 Latin words, and fewer than 2 Nepali word-list hits."""
    ns = M._PROD
    if ns["_DEVANAGARI_RE"].search(content):
        return False
    words = ns["_WORD_RE"].findall(content)
    return len(words) <= 2 and sum(w.lower() in ns["_ROMAN_NEPALI_WORDS"] for w in words) < 2
ARMS = tuple(TEMPLATES)


def step(arm: str, state: ConvState, history, customer: str, biz: str, lm) -> dict:
    """Same as lang_mech.step's `prod` arm (real lock functions), parameterised by template + lock-line wording."""
    it = _item(biz, history, customer)
    up = user_prompt(it)
    if state.detected_language in LABELS:
        up = lock_line(FIXB_LINE[arm]).format(label=LABELS[state.detected_language]) + up
    lock_before = state.detected_language
    d = _call(lm, system_prompt(biz, TEMPLATES[arm]), up)
    msg_lang = resolve_message_language(customer, d.get("message_language"))
    if arm in NEUTRAL_GUARD and state.detected_language and is_language_neutral(customer):
        msg_lang = None  # no language evidence: never counts toward (or against) a switch streak
    used = resolve_locked_language(state, msg_lang, d.get("language_switch_request"))
    return {"reply": d["response"], "meta": {"lock_before": lock_before, "lock_after": state.detected_language,
                                             "streak": state.language_switch_streak, "resolved_msg_lang": msg_lang,
                                             "llm_message_language": d.get("message_language"),
                                             "switch_request": d.get("language_switch_request"), "lock_used": used}}


# ---------------------------------------------------------------- scenarios (written BEFORE any run)
# turn = (text, truth). truth = the language the customer's own words are in, fixed by construction:
#   en    plain English, no Nepali words     roman  Romanized Nepali (>=2 word-list hits, so also caught deterministically)
#   deva  Devanagari                         neutral bare "ok"/number/weekday (no language evidence; not scored for mislabel)
# expectation per conversation (`expect`): "switch_to_en" | "hold_roman" | "switch_to_roman" (streak semantics: 3 consecutive
# differing messages move the lock for the NEXT turn; fewer, or one interrupted by a message in the lock language, never do).
ANCHOR = [
    # -- the bug: Romanized-Nepali lock, then 3+ plain English messages -> must switch
    dict(id="AN1-roman-to-en-dental", biz="dental", expect="switch_to_en", turns=[
        ("namaste, teeth cleaning ko price kati ho?", "roman"),
        ("ani root canal ko kati parcha?", "roman"),
        ("Okay. Do you accept eSewa or Khalti for payment?", "en"),
        ("And what are your hours on Friday?", "en"),
        ("Can I book for next Tuesday afternoon?", "en"),
        ("Is there parking near the clinic?", "en"),
        ("Great, and how long does a cleaning usually take?", "en")]),
    dict(id="AN2-roman-to-en-salon", biz="salon", expect="switch_to_en", turns=[
        ("hlo, haircut ko price kati ho?", "roman"),
        ("ani beard trim pani garchau ki chaina?", "roman"),
        ("I see. Do you take walk-ins on weekends?", "en"),
        ("What time do you open on Saturday?", "en"),
        ("Could I get a haircut around noon tomorrow?", "en"),
        ("Do I need to bring anything with me?", "en"),
        ("Perfect, is there somewhere to leave my bag?", "en")]),
    # AN2 (salon) is rejected by Azure's content filter for EVERY arm (a false positive, same as L7's HB3 salon prompt), so it yields
    # no data. AN2b is its post-hoc replacement (written after seeing that failure, before seeing any AN2b result; nothing tuned).
    dict(id="AN2b-roman-to-en-riverside", biz="riverside", expect="switch_to_en", turns=[
        ("namaste, cleaning ko price kati ho?", "roman"),
        ("ani kati din ma hunchha?", "roman"),
        ("Okay. Is there a discount for families?", "en"),
        ("What are your opening hours on weekdays?", "en"),
        ("Can I come in on Wednesday morning?", "en"),
        ("Do I need to bring anything with me?", "en"),
        ("Great, thanks for the details.", "en")]),
    dict(id="AN3-roman-to-en-trek", biz="trek", expect="switch_to_en", turns=[
        ("namaste, Poon Hill trek ko price kati ho?", "roman"),
        ("ani kati din lagcha jana ra aauna?", "roman"),
        ("Understood. What is the best season to go?", "en"),
        ("Do you provide the gear or do I need to bring my own?", "en"),
        ("Is it suitable for someone who has never trekked before?", "en"),
        ("How large are your groups usually?", "en"),
        ("Thanks, and can you arrange a guide who speaks English?", "en")]),
    # -- the real transcript of 2026-09-20 (roman opener, 3 substantial English messages incl. a booking ask)
    dict(id="AN4-real-transcript-dental", biz="dental", expect="switch_to_en", turns=[
        ("hlo, malai teeth cleaning ko barema janna man cha", "roman"),
        ("kati ho price", "roman"),
        ("ok thik cha, ma bholi aauna sakchu", "roman"),
        ("Actually, can you tell me what time you open on weekends?", "en"),
        ("I think I'll come on Monday morning instead, does that work?", "en"),
        ("Great, can you book that for me?", "en"),
        ("Thanks, and is there parking near the clinic?", "en")]),
    dict(id="AN5-deva-to-en-dental", biz="dental", expect="switch_to_en", turns=[
        ("नमस्ते, दाँत सफा गर्ने कति पर्छ?", "deva"),
        ("अनि खुल्ने समय कति बजे हो?", "deva"),
        ("Alright. Do you have any openings next week?", "en"),
        ("What about Wednesday morning?", "en"),
        ("Can you tell me how much the whitening costs?", "en"),
        ("And is there a discount for students?", "en"),
        ("Great, thank you for the information.", "en")]),
    # -- do-no-harm: the lock must still HOLD against passive drift
    dict(id="AN6-single-stray-english-hold", biz="dental", expect="hold_roman", turns=[
        ("namaste, teeth whitening kati parcha?", "roman"),
        ("ani weekend ma khula huncha ki chaina?", "roman"),
        ("ok thanks, what time works tomorrow?", "en"),
        ("malai bholi bihana 10 baje ko slot chahiyo, milcha?", "roman"),
        ("ani parking cha ki chaina?", "roman"),
        ("ok", "neutral")]),
    dict(id="AN7-two-english-then-roman-hold", biz="salon", expect="hold_roman", turns=[
        ("namaste, haircut ko price kati ho?", "roman"),
        ("ani facial jasto kehi cha ki chaina?", "roman"),
        ("Okay, and what are your opening hours?", "en"),
        ("Can I come in on Friday afternoon?", "en"),
        ("hunxa, tyo bela ma aauchu ni", "roman"),
        ("ani price ma discount cha ki chaina?", "roman"),
        ("thanks", "neutral")]),
    dict(id="AN8-two-english-then-roman-trek-hold", biz="trek", expect="hold_roman", turns=[
        ("namaste, Everest Base Camp ko price kati ho?", "roman"),
        ("ani deposit kati dinu parcha?", "roman"),
        ("Sorry, one more thing: what is the cancellation policy?", "en"),
        ("And do you offer travel insurance?", "en"),
        ("ramro, malai tyo kura bujhe, dhanyabad", "roman"),
        ("ani kati din agadi book garna parcha?", "roman"),
        ("ok", "neutral")]),
    # -- regression direction: English lock, then sustained Romanized Nepali (already handled by the word list; must not break)
    dict(id="AN9-en-to-roman-dental", biz="dental", expect="switch_to_roman", turns=[
        ("Hi, how much is a teeth cleaning?", "en"),
        ("Ok and do you have a slot tomorrow?", "en"),
        ("malai bholi bihana 10 baje ko slot chahiyo, milcha?", "roman"),
        ("ani parking cha ki chaina?", "roman"),
        ("hamro family ko lagi pani milcha ki?", "roman"),
        ("kati din agadi book garna parcha?", "roman"),
        ("dhanyabad, ma bholi aauchu", "roman")]),
]
ANCHOR_BY_ID = {s["id"]: s for s in ANCHOR}

if __name__ == "__main__":  # smallest checks: the surgery applies cleanly, and the CURRENT backend template matches once ported
    assert is_language_neutral("Friday") and is_language_neutral("3pm") and is_language_neutral("yes") and is_language_neutral("thank you")
    assert is_language_neutral("") and not is_language_neutral("malai xa") and not is_language_neutral("Can I book Monday?")
    assert not is_language_neutral("धन्यवाद") and is_language_neutral("kati?")  # one Nepali word alone is not evidence
    assert FIX_TEMPLATE != PRE_TEMPLATE and "Work out `message_language` FIRST" in FIX_TEMPLATE
    assert FIX_TEMPLATE.index('"message_language": "<one of') < FIX_TEMPLATE.index('"response": "<your reply to the customer>"')
    FIX_TEMPLATE.format(business_name="x", business_description="", tone="t", intent_list="a")
    assert "message_language" not in FIX_TEMPLATE[FIX_TEMPLATE.rindex('"needs_human_handoff": true or false'):]
    live = M.TEMPLATE
    print("backend template state:", "FIXED (== apply_fix(PRE))" if live == FIX_TEMPLATE else
          "PRE-FIX (== git b7b62b3)" if live == PRE_TEMPLATE else "DIFFERENT from both -- port is not equivalent!")
    assert all(len(s["turns"]) == 7 or s["id"].startswith("AN6") for s in ANCHOR)
    print("lang_anchor checks ok; scenarios:", len(ANCHOR))
