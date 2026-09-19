"""Deterministic, channel-neutral reply formatting for LLM-drafted text.

`format_service_list` exists because the service list is composed by the LLM, and live testing (PHASE_STATUS.md,
Phase 14) showed it is inconsistent: for the same business, "what services do you offer?" came back as one long
";"-separated line, a ","-separated line, or (for a different phrasing) a proper one-per-line list. A prompt rule alone
would be "instructed, not guaranteed" — the same lesson as the rule-3/greeting work — so the guarantee lives here, in
plain code that reads the REAL service names from the database.

Output uses a plain "\\n" and a "- " bullet: WhatsApp, Messenger and Instagram render a newline natively, and the website
widget / /test-chat bubbles use `white-space: pre-wrap` (verified live for each channel, see PHASE_STATUS.md)."""
import re

_CONJUNCTIONS = ("and", "ani", "ra", "तथा", "र")
_SENTENCE_END_CHARS = ".!?।"
# A list-entry "detail" (price/duration after the service name) is short and mostly numbers/parentheses. Anything
# wordier is prose ("... are our most popular"), which must never be mangled into a bullet.
_MAX_DETAIL_CHARS = 60
_MAX_DETAIL_WORDS_OUTSIDE_PARENS = 3


def _balanced(text: str) -> bool:
    return text.count("(") == text.count(")")


def _has_sentence_break(text: str) -> bool:
    return bool(re.search(r"[.!?।](?=\s|$)", text))


def _looks_like_entry_detail(detail: str) -> bool:
    if len(detail) > _MAX_DETAIL_CHARS or not _balanced(detail) or _has_sentence_break(detail):
        return False
    outside_parens = re.sub(r"\([^()]*\)", " ", detail)
    words = re.findall(r"[^\W\d_]+", outside_parens)
    return len(words) <= _MAX_DETAIL_WORDS_OUTSIDE_PARENS


def _find_service_mentions(text: str, names: list[str]) -> list[tuple[int, int, str]]:
    """Non-overlapping, case-insensitive whole-word occurrences of the real service names, longest name first so
    "Teeth Cleaning" wins over "Cleaning"."""
    taken: list[tuple[int, int, str]] = []
    for name in sorted({n for n in names if n}, key=len, reverse=True):
        for match in re.finditer(rf"(?<!\w){re.escape(name)}(?!\w)", text, re.IGNORECASE):
            if not any(match.start() < end and start < match.end() for start, end, _ in taken):
                taken.append((match.start(), match.end(), name.lower()))
    return sorted(taken)


def _detail_before_separator(gap: str) -> str | None:
    """`gap` is the text between one service mention and the next. It must be exactly: that entry's short detail, then
    a separator (";" or "," and/or a conjunction). Returns the detail, or None if the gap is anything else."""
    g = gap.rstrip()
    conjunction_stripped = False
    for conj in _CONJUNCTIONS:
        if re.search(rf"(?<!\w){conj}$", g, re.IGNORECASE):
            g = g[: -len(conj)].rstrip()
            conjunction_stripped = True
            break
    if g.endswith((";", ",")):
        detail = g[:-1]
    elif conjunction_stripped:
        detail = g
    else:
        return None
    return detail if _looks_like_entry_detail(detail) else None


def _last_entry_end(text: str, start: int) -> int:
    """Index just past the sentence-ending punctuation that closes the list (skipping "." inside parentheses or inside
    numbers like 1500.00), or len(text) if the list runs to the end."""
    depth = 0
    for i in range(start, len(text)):
        ch = text[i]
        if ch == "(":
            depth += 1
        elif ch == ")":
            depth = max(0, depth - 1)
        elif depth == 0 and ch in _SENTENCE_END_CHARS and (i + 1 == len(text) or text[i + 1].isspace()):
            return i + 1
    return len(text)


def format_service_list(text: str, service_names: list[str]) -> str:
    """If `text` lists two or more of the business's real services inline (";"- or ","-separated, or "A and B"),
    put each on its own "- " line. Returns `text` unchanged when it already contains a newline, doesn't clearly
    have the shape of a list (a comparison sentence, a question, prose after an entry), or names fewer than two
    distinct real services — never guesses."""
    if not text or "\n" in text or len({n.lower() for n in service_names if n}) < 2:
        return text
    mentions = _find_service_mentions(text, service_names)
    if len({m[2] for m in mentions}) < 2:
        return text

    run = [mentions[0]]
    details: list[str] = []
    for nxt in mentions[1:]:
        detail = _detail_before_separator(text[run[-1][1] : nxt[0]])
        if detail is None:
            break
        details.append(detail)
        run.append(nxt)
    if len(run) < 2 or len({m[2] for m in run}) < 2:
        return text

    end = _last_entry_end(text, run[-1][1])
    closing = text[end - 1] if end <= len(text) and text[end - 1] in _SENTENCE_END_CHARS else ""
    if closing in ("?", "!"):
        return text  # a question or exclamation that happens to name services is not a list
    last_detail = text[run[-1][1] : end - 1 if closing else end]
    if not _looks_like_entry_detail(last_detail):
        return text
    details.append(last_detail)

    lead_in = text[: run[0][0]].rstrip()
    if lead_in and not lead_in.endswith(":"):
        lead_in += ":"
    lines = [f"- {text[start:stop]}{detail}".rstrip() for (start, stop, _), detail in zip(run, details)]
    tail = text[end:].strip()
    return "\n".join(([lead_in] if lead_in else []) + lines) + (f"\n\n{tail}" if tail else "")
