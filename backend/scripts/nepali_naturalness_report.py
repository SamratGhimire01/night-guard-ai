"""Before/after naturalness numbers over the real conversations in data/regression/real_conversations.

    python scripts/nepali_naturalness_report.py            # print the table
    python scripts/nepali_naturalness_report.py --json out.json

What it measures, per assistant reply:
  - never-use words (Hindi / textbook / error, from nepali_wordbank) per Romanized-Nepali reply
  - exact repeats: a reply (20+ chars) identical to one we already sent earlier in the same chat
  - stock endings: the last sentence is a filler or stock offer ("let me know if…", "aru kehi… bhannus", "would you like…")
  - same opener twice in a row ("Got it —", "Bujhe —", "Thik cha," …)

"before" is the replies exactly as they were sent. "after_code_guards" runs the SAME replies through today's reply
finalizer (word bank + guards), in order, with the chat's own history. "after_code_guards_and_templates" (needs
--old-templates) additionally recognises every reply that was a fixed template and re-renders it with today's
wordings and no-repeat choice -- i.e. what these same chats would have sent today, minus the LLM's own drafts. The LLM's own wording change (new prompt + exemplars) can only be measured live
(tests/eval/live_phase4_multijudge.py) -- this script doesn't pretend to.
"""

import argparse
import glob
import json
import re
import sys
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.services.conversation import response_templates as rt  # noqa: E402
from app.services.conversation.nepali_wordbank import find_issues  # noqa: E402
from app.services.conversation.reply_polish import _FILLER_TAIL_RE, _OFFER_TAIL_RE, _opener, finalize_reply  # noqa: E402
from app.services.conversation.style_checks import split_sentences  # noqa: E402

DATA = Path(__file__).resolve().parent.parent / "data" / "regression" / "real_conversations"
_DEVANAGARI = re.compile(r"[ऀ-ॿ]")


def _stock_ending(text: str) -> bool:
    sentences = split_sentences(text)
    if not sentences:
        return False
    last = sentences[-1].strip()
    return bool(_FILLER_TAIL_RE.search(last) or _OFFER_TAIL_RE.search(last))


def _norm(text: str) -> str:
    return " ".join(text.lower().split())


def _template_matchers(old_templates: dict | None) -> list[tuple[str, str, re.Pattern, list[str]]]:
    """Each old fixed wording as a full-match regex, so a sent reply that WAS that template can be re-rendered with
    today's wordings (and today's no-repeat choice)."""
    matchers = []
    for name, langs in (old_templates or {}).items():
        if name not in rt.TEMPLATES:
            continue
        for lang, fmt in langs.items():
            fields: list[str] = []
            pattern = ""
            for literal, field, _, _ in __import__("string").Formatter().parse(fmt):
                pattern += re.escape(literal)
                if field:
                    pattern += "(.+?)"
                    fields.append(field)
            # A template that doesn't end in a placeholder may be followed by an appended line (handoff addendum,
            # booking details): match it as a prefix and keep the rest.
            tail = "$" if fmt.endswith("}") else "(?P<_rest>.*)$"
            literal_len = len(re.sub(r"\{[^}]*\}", "", fmt))
            if literal_len < 12:  # "{desc}{who} — {status}." would match almost any reply
                continue
            matchers.append((literal_len, name, lang, re.compile(rf"^{pattern}{tail}", re.S), fields))
    # most specific (longest fixed text) first
    return [m[1:] for m in sorted(matchers, key=lambda m: -m[0])]


_EN_DAY = (r"(?:Monday|Tuesday|Wednesday|Thursday|Friday|Saturday|Sunday), (?:January|February|March|April|May|June|"
           r"July|August|September|October|November|December) \d{1,2}")
_EN_TIME = r"\d{1,2}:\d{2} [AP]M"
# one run of "Day at T(, T)*" items, possibly several days: "Monday, Sep 7 at 9:00 AM, 9:15 AM, Monday, Sep 7 at 9:30 AM"
_EN_LIST_RE = re.compile(rf"{_EN_DAY} at {_EN_TIME}(?:, (?:{_EN_DAY} at )?{_EN_TIME})*")


def _nepali_dates(text: str, language: str, year: int) -> str:
    """The old replies carry English dates; today's code formats them the Nepali way (rt.format_when /
    format_slot_list) -- convert them so the 'after' text is what would really be sent."""
    def convert(m: re.Match) -> str:
        slots, day = [], None
        for item in m.group(0).split(", "):
            if item.endswith("day"):
                continue  # the weekday half of "Monday, September 7 at 9:00 AM"; the date comes next
            if re.fullmatch(_EN_TIME, item):
                slots.append(datetime.combine(day, datetime.strptime(item, "%I:%M %p").time()))
            else:
                month_day, clock = item.split(" at ")
                day = datetime.strptime(f"{month_day} {year}", "%B %d %Y").date()
                slots.append(datetime.combine(day, datetime.strptime(clock, "%I:%M %p").time()))
        return rt.format_slot_list(slots, language) if len(slots) > 1 else rt.format_when(slots[0], language)

    return _EN_LIST_RE.sub(convert, text)


def _rerender(text: str, matchers, history: list[str]) -> str:
    for name, lang, regex, fields in matchers:
        m = regex.match(text)
        if m:
            rest = m.groupdict().get("_rest") or ""
            values = m.groups()[: len(fields)]
            with rt.reply_history(history):
                try:
                    return rt.render(name, lang, **dict(zip(fields, values))) + rest
                except (KeyError, IndexError):
                    return text
    return text


def _measure(conversations: list[dict], *, polish: bool, matchers=None) -> dict:
    replies = rn_replies = issue_words = repeats = stock = same_opener = 0
    by_kind = {"hindi": 0, "bookish": 0, "error": 0}
    top: dict[str, int] = {}
    for conv in conversations:
        language = conv.get("detected_language")
        sent: list[str] = []
        customer: list[str] = []
        for m in conv["messages"]:
            if m["sender_type"] == "customer":
                customer.append(m["content"])
                continue
            if m["sender_type"] != "agent" or not m["content"]:
                continue
            text = m["content"]
            if matchers:
                text = _rerender(text, matchers, sent)
                if language in ("ne_roman", "mixed", "ne_deva"):
                    text = _nepali_dates(text, language, int(conv["created_at"][:4]))
            if polish:
                services = [s["name"] for s in (conv.get("business") or {}).get("services") or []]
                text, _ = finalize_reply(
                    text, language=language, previous_replies=sent, customer_texts=customer,
                    protected=services + [(conv.get("business") or {}).get("name") or ""],
                )
            replies += 1
            is_rn = language in ("ne_roman", "mixed") and not _DEVANAGARI.search(text)
            if is_rn:
                rn_replies += 1
                for word, kind in find_issues(text):
                    issue_words += 1
                    by_kind[kind] += 1
                    top[word.lower()] = top.get(word.lower(), 0) + 1
            if len(text) >= 20 and any(_norm(text) == _norm(s) for s in sent):
                repeats += 1
            if sent and _stock_ending(text):  # a first greeting's "how can I help?" is not a stock tail
                stock += 1
            if sent and _opener(text) and _opener(text) == _opener(sent[-1]):
                same_opener += 1
            sent.append(text)
    return {
        "replies": replies,
        "romanized_replies": rn_replies,
        "never_use_words_per_romanized_reply": round(issue_words / max(rn_replies, 1), 3),
        "never_use_words_by_kind": by_kind,
        "top_never_use_words": sorted(top.items(), key=lambda kv: -kv[1])[:15],
        "exact_repeats": repeats,
        "stock_ending_pct": round(100 * stock / max(replies, 1), 1),
        "same_opener_in_a_row": same_opener,
    }


def _template_report(old_templates: dict | None) -> dict:
    def count(templates: dict, getter) -> tuple[int, int]:
        n = issues = 0
        for name in templates:
            for text in getter(templates, name):
                n += 1
                issues += len(find_issues(text))
        return n, issues

    now_n, now_issues = count(rt.TEMPLATES, lambda t, name: rt.variants(name, "ne_roman"))
    report = {"after": {"ne_roman_wordings": now_n, "never_use_words": now_issues}}
    if old_templates:
        old_n, old_issues = count(old_templates, lambda t, name: [t[name]["ne_roman"]])
        report["before"] = {"ne_roman_wordings": old_n, "never_use_words": old_issues}
    return report


def _review_sheet(conversations: list[dict], matchers, n: int = 30) -> str:
    """`n` real Romanized-Nepali replies that today's code would send differently, before -> after, spread across
    chats (at most 2 per chat) -- the native-speaker review sheet."""
    picked: list[tuple[str, str, str]] = []
    per_conv: dict[str, int] = {}
    seen_before: set[str] = set()
    for conv in conversations:
        if conv.get("detected_language") not in ("ne_roman", "mixed"):
            continue
        sent: list[str] = []
        customer: list[str] = []
        last_customer = ""
        for m in conv["messages"]:
            if m["sender_type"] == "customer":
                customer.append(m["content"])
                last_customer = m["content"]
                continue
            if m["sender_type"] != "agent" or not m["content"]:
                continue
            new = _nepali_dates(_rerender(m["content"], matchers, sent), conv["detected_language"],
                                int(conv["created_at"][:4]))
            services = [s["name"] for s in (conv.get("business") or {}).get("services") or []]
            new, _ = finalize_reply(new, language=conv["detected_language"], previous_replies=sent,
                                    customer_texts=customer, protected=services)
            cid = conv["conversation_id"]
            if (
                new != m["content"] and per_conv.get(cid, 0) < 2 and not _DEVANAGARI.search(m["content"])
                and m["content"] not in seen_before
            ):
                seen_before.add(m["content"])
                picked.append((last_customer, m["content"], new))
                per_conv[cid] = per_conv.get(cid, 0) + 1
            sent.append(new)
    step = max(len(picked) // n, 1)
    sample = picked[::step][:n]
    lines = [
        "# Native review: 30 real Romanized-Nepali replies, before -> after",
        "",
        "From the real conversations in backend/data/regression/real_conversations. 'Before' is what was sent;",
        "'after' is what today's code sends for the same turn (new template wording + word bank + guards). LLM-drafted",
        "replies only show the word-bank/guard changes -- the new prompt's effect needs a live run.",
        "",
        "For each: mark OK, or write how a Nepali receptionist would actually text it.",
        "",
    ]
    for i, (cust, before, after) in enumerate(sample, 1):
        lines += [f"## {i}", f"- Customer: {cust}", f"- Before: {before}", f"- After: {after}", "- Your verdict: ", ""]
    return "\n".join(lines)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--json", help="also write the numbers to this file")
    parser.add_argument("--old-templates", help="path to a previous response_templates.py, for the template comparison")
    parser.add_argument("--review-sheet", help="write the 30-reply native review sheet (markdown) here")
    args = parser.parse_args()
    conversations = [json.loads(Path(f).read_text()) for f in sorted(glob.glob(str(DATA / "*.json")))]
    old_templates = None
    if args.old_templates:
        namespace: dict = {}
        source = Path(args.old_templates).read_text()
        exec(compile(source, args.old_templates, "exec"), namespace)  # a trusted local file the caller names
        old_templates = namespace["TEMPLATES"]
    result = {
        "conversations": len(conversations),
        "before": _measure(conversations, polish=False),
        "after_code_guards": _measure(conversations, polish=True),
        "after_code_guards_and_templates": _measure(
            conversations, polish=True, matchers=_template_matchers(old_templates)
        ) if old_templates else None,
        "templates": _template_report(old_templates),
    }
    print(json.dumps(result, indent=2, ensure_ascii=False))
    if args.review_sheet:
        Path(args.review_sheet).write_text(_review_sheet(conversations, _template_matchers(old_templates)))
    if args.json:
        Path(args.json).write_text(json.dumps(result, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
