"""Deterministic post-generation style check for a drafted customer-facing reply.

Same discipline and shape as fact_validator.py, one line over: intent.py's system prompt
already SPECIFIES this behavior in plain English (rule 4's banned-phrase list, rule 16's
one-question-per-turn rule, rule 17's per-category length budgets) -- this module is what
makes those rules a real guarantee instead of "instructed, not guaranteed" (see
fact_validator.py's own docstring and formatting.py's format_service_list for the same
lesson applied to service lists). It does not invent any new style policy; every check
below quotes or paraphrases wording already in intent.py's system prompt.

Called right after the existing fact-check block in orchestrator._handle_turn, on the same
`classification.response` those checks already validated -- skipped whenever that text has
already been replaced by a fixed, correct-by-construction template (fact_check_front_desk_
reason is not None), same skip condition the post-generation language check already uses.

Repair is deterministic and sentence-level only, never a mid-sentence/mid-word cut: a
sentence containing a banned phrase is dropped whole, a second-or-later question sentence is
dropped whole, and length trimming drops whole trailing sentences from the end. This avoids
the risk the outside style-review report itself flagged -- a hard word-count truncation can
slice a price or a booking id in half. If repair still leaves a violation (e.g. a single
sentence that alone exceeds its ceiling, with nothing left to trim), the caller regenerates
once, exactly like fact_validator's own regenerate-once pattern.
"""

import re

# Rule 4's own wording, verbatim (see intent.py _SYSTEM_PROMPT_TEMPLATE). Deliberately not
# expanded with guessed synonyms/variants -- ported straight from what's already banned by
# written policy, not a new judgment call about what else might sound robotic.
_BANNED_PHRASES = [
    "thank you for reaching out to us",
    "i would be happy to assist you",
    "please feel free to let me know",
    "your request has been successfully processed",
    "is there anything else i can assist you with",
    "i'm deeply sorry that you're experiencing this unfortunate inconvenience",
    "i understand how frustrating that is",
]

# Rule 17's own three-tier budget, mapped onto ConversationIntent values. Ceilings are
# deliberately generous (this is a backstop against genuine essay-mode drift, not a tight
# enforcement of the shortest possible reply) and intents whose real answer can legitimately
# list several services/prices/appointments get the more permissive tier rather than SHORT,
# so a correct multi-item answer is never mistaken for rambling.
_SHORT, _MEDIUM, _LONG = 45, 90, 160
_LENGTH_CEILINGS: dict[str, int] = {
    "greeting": _SHORT,
    "off_topic": _SHORT,
    "location": _SHORT,
    "follow_up": _SHORT,
    "business_hours": _MEDIUM,
    "appointment_status": _MEDIUM,
    "service_question": _MEDIUM,
    "pricing_question": _MEDIUM,
    "booking": _MEDIUM,
    "rescheduling": _MEDIUM,
    "cancellation": _MEDIUM,
    "resend_confirmation": _MEDIUM,
    "complaint": _MEDIUM,
    "human_handoff": _MEDIUM,
    "general_question": _LONG,
}
_DEFAULT_CEILING = _MEDIUM

# Splits after a sentence-ending mark followed by whitespace/end -- same simple, stdlib-regex
# approach as fact_validator._CLAUSE_SPLIT_RE and formatting._SENTENCE_END_CHARS, not a real
# sentence tokenizer. "।" is the Devanagari sentence-ending mark used throughout
# response_templates.py's ne_deva strings.
_SENTENCE_SPLIT_RE = re.compile(r"(?<=[.!?।])\s+")


def _normalize(text: str) -> str:
    return text.replace("’", "'")  # curly apostrophe -> straight, before phrase matching


def split_sentences(text: str) -> list[str]:
    """Public: also reused by split_into_bubbles below, so a long reply is only ever broken on
    the same sentence boundaries the style guard itself already trusts not to slice a price or
    booking id mid-word."""
    return [s for s in _SENTENCE_SPLIT_RE.split(text.strip()) if s]


# Message-bubble split: shared by every channel that wants a long reply delivered/rendered as
# up to this many separate messages instead of one wall of text (WhatsApp's real outbound
# sends, the widget's response_bubbles field) -- one splitting decision, reused, not
# reimplemented per channel. Voice deliberately never calls this at all.
MAX_BUBBLES = 3
# ponytail: fixed word count, not per-intent -- _LENGTH_CEILINGS above already keeps a SHORT
# reply well under this, so this only ever fires on a MEDIUM/LONG-budget reply that's actually
# using that budget. Tune if live traffic shows it firing too eagerly/rarely.
BUBBLE_SPLIT_WORD_THRESHOLD = 40


def split_into_bubbles(text: str) -> list[str]:
    """Splits an ALREADY fully fact-checked and style-guard-validated reply (see
    orchestrator._handle_turn, which runs both guards on the full joined text before any
    caller of this ever sees it) into up to `MAX_BUBBLES` fragments. Callers use these purely
    for delivery/rendering -- the persisted Message row always keeps the single, full,
    validated text, completely unaffected by whatever a caller does with a copy of it
    afterward.

    Sentence-bounded only, via `split_sentences` -- never a mid-sentence/mid-word cut. Below
    the word threshold, or with fewer than 2 sentences to split on (nothing to break without
    violating that rule), returns the text unchanged as one "bubble".

    Bubbles are balanced by SENTENCE COUNT, not word count -- e.g. 5 sentences into 3 bubbles
    is [2, 2, 1], in order. Simpler and just as effective as word-balancing, and avoids a real
    bug word-balancing hit here: greedily accumulating until a word-count target is crossed can
    dump every sentence into a single trailing bubble when the first sentence is much shorter
    than the target on its own.
    """
    if len(text.split()) <= BUBBLE_SPLIT_WORD_THRESHOLD:
        return [text]
    sentences = split_sentences(text)
    if len(sentences) < 2:
        return [text]
    bubble_count = min(MAX_BUBBLES, len(sentences))
    base, extra = divmod(len(sentences), bubble_count)
    bubbles, i = [], 0
    for k in range(bubble_count):
        size = base + (1 if k < extra else 0)
        bubbles.append(" ".join(sentences[i : i + size]))
        i += size
    return bubbles


def check_banned_phrases(reply: str) -> list[str]:
    lower = _normalize(reply).lower()
    return [f"reply uses a scripted phrase rule 4 bans: {phrase!r}" for phrase in _BANNED_PHRASES if phrase in lower]


def repair_banned_phrases(reply: str) -> str:
    sentences = split_sentences(reply)
    kept = [s for s in sentences if not any(p in _normalize(s).lower() for p in _BANNED_PHRASES)]
    # Never empty the reply outright (e.g. every sentence happened to contain a banned
    # phrase) -- leave it as-is and let the unresolved violation fall through to a regenerate.
    return " ".join(kept) if kept else reply


def check_question_count(reply: str) -> list[str]:
    count = reply.count("?")
    if count > 1:
        return [f"reply asks {count} questions in one turn, over rule 16's one-question-per-turn limit"]
    return []


def repair_question_count(reply: str) -> str:
    if reply.count("?") <= 1:
        return reply
    sentences = split_sentences(reply)
    kept = []
    seen_question = False
    for s in sentences:
        if "?" in s:
            if seen_question:
                continue
            seen_question = True
        kept.append(s)
    return " ".join(kept) if kept else reply


def check_length(reply: str, *, intent: str) -> list[str]:
    ceiling = _LENGTH_CEILINGS.get(intent, _DEFAULT_CEILING)
    word_count = len(reply.split())
    if word_count > ceiling:
        return [f"reply is {word_count} words, over the {ceiling}-word ceiling for a {intent!r} reply (rule 17)"]
    return []


def repair_length(reply: str, *, intent: str) -> str:
    ceiling = _LENGTH_CEILINGS.get(intent, _DEFAULT_CEILING)
    sentences = split_sentences(reply)
    # ponytail: whole-trailing-sentence trim only -- a single sentence that alone exceeds the
    # ceiling is left untouched rather than word-truncated (a hard cut risks slicing a price or
    # booking id mid-word). Upgrade to a required-fact-aware trim if that's ever observed live.
    while len(sentences) > 1 and len(" ".join(sentences).split()) > ceiling:
        sentences = sentences[:-1]
    return " ".join(sentences) if sentences else reply


def check_response_style(reply: str, *, intent: str) -> list[str]:
    return [*check_banned_phrases(reply), *check_question_count(reply), *check_length(reply, intent=intent)]


def repair_response_style(reply: str, *, intent: str) -> str:
    reply = repair_banned_phrases(reply)
    reply = repair_question_count(reply)
    reply = repair_length(reply, intent=intent)
    return reply


def _demo() -> None:
    # Confirmed-shape case: a banned rule-4 phrase in its own sentence, ahead of a real fact.
    scripted = "Thank you for reaching out to us! Teeth Cleaning is $90."
    assert check_banned_phrases(scripted)
    assert repair_banned_phrases(scripted) == "Teeth Cleaning is $90."
    # No banned phrase, nothing to repair.
    assert not check_banned_phrases("Teeth Cleaning is $90.")

    # Two questions in one turn violates rule 16; repair keeps only the first.
    two_questions = "What time works for you? Do you also want the whitening add-on?"
    assert check_question_count(two_questions)
    assert repair_question_count(two_questions) == "What time works for you?"
    # A single question, or none at all, is fine.
    assert not check_question_count("What time works for you?")
    assert not check_question_count("Done — you're all set.")

    # A rambling greeting (SHORT ceiling = 45 words) over budget gets trimmed
    # sentence-by-sentence from the end, never mid-sentence. Three sentences of 20, 20 and 6
    # words (46 total) -- dropping the last one brings it to 40, back under the ceiling.
    sentence_20a = "One two three four five six seven eight nine ten eleven twelve thirteen fourteen fifteen sixteen seventeen eighteen nineteen twenty."
    sentence_20b = "Twenty nineteen eighteen seventeen sixteen fifteen fourteen thirteen twelve eleven ten nine eight seven six five four three two one."
    sentence_6 = "This sentence has exactly five words."
    rambling_greeting = f"{sentence_20a} {sentence_20b} {sentence_6}"
    assert check_length(rambling_greeting, intent="greeting")
    repaired = repair_length(rambling_greeting, intent="greeting")
    assert repaired == f"{sentence_20a} {sentence_20b}"
    assert not check_length(repaired, intent="greeting")
    # The same length is fine for an intent with a higher ceiling.
    assert not check_length(rambling_greeting, intent="general_question")

    # A single sentence that alone exceeds its ceiling is left alone (never word-truncated) --
    # the residual violation is the intended signal for the caller to regenerate instead.
    one_giant_sentence = "This " + "very " * 60 + "long single sentence has no period in the middle at all"
    assert check_length(one_giant_sentence, intent="greeting")
    assert repair_length(one_giant_sentence, intent="greeting") == one_giant_sentence

    print("style_checks self-check: all assertions passed")


if __name__ == "__main__":
    _demo()
