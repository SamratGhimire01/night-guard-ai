"""The judge prompt: five criteria scored separately on fixed 1-5 anchors, comprehension before scoring, evidence
before scores. Absolute (one reply) and pairwise (two replies) forms, plus strict parsers for both.

Research behind the choices (see README.md): analytic rubrics beat a single holistic score; pairwise beats absolute
for subtle quality differences; judges are weakest on romanized low-resource languages, and reading the text back in
the native script first measurably helps; anchored examples reduce score drift between judges and runs."""

import json
import re

from tests.eval.nepali_judge.lint import CRITERIA

CRITERION_TEXT = {
    "language": (
        "Natural language for THIS customer. For Nepali: the words a Nepali receptionist actually texts (huss, la, "
        "pakka, milcha?/milxa?, k, kati, kaile, bholi, sadhe 10 baje, dinus, garnus), the customer's own spelling style "
        "(xa/vayo vs cha/bhayo), in the customer's language and script. 5 = indistinguishable from a native texter. "
        "3 = understandable but with textbook/office words (kripaya, prapta, janakari, sahayog, madhyam, maaf garnuhos, "
        "sakinu huncha) or an English date mid-Nepali. 1 = Hindi words (kya, aap, nahi, abhi, kahan, samay, bilkul) "
        "or the wrong language entirely. For English: natural, plain English."
    ),
    "register": (
        "Tone and formality. A friendly, respectful receptionist: 'tapai' by default, 'hajur' as a warm yes, never "
        "'timi'; warm but not gushing. 5 = exactly the warmth a good receptionist would use here. 3 = noticeably stiff "
        "('government office') or slightly too familiar. 1 = rude, cold, or 'timi'."
    ),
    "human": (
        "Reads like a person typing, not software. 5 = a real person. 3 = recognisably templated: stock openers "
        "('Got it —', 'Bujhe —'), a tacked-on offer ('Would you like…', 'aru kehi chahiyo bhane bhannus'), repeated "
        "word for word from earlier, or far longer than the message called for. 1 = obviously a bot."
    ),
    "helpful": (
        "Does it actually move the customer forward? 5 = answers exactly what was asked (or asks the ONE thing still "
        "needed), nothing missing, nothing extra. 3 = partly answers, or answers something else. 1 = ignores the question."
    ),
    "correct": (
        "Spelling, grammar and script. 5 = no mistakes a native reader would notice (Romanized Nepali has no standard "
        "spelling: xa and cha are both correct; 'bhena', 'madat garna chu', Devanagari letters inside a Romanized "
        "word are mistakes). 3 = one clear mistake. 1 = hard to read."
    ),
}

WEIGHTS = {"language": 0.25, "register": 0.15, "human": 0.25, "helpful": 0.25, "correct": 0.10}

# Fixed reference replies with agreed scores: they pin what a 5, a 3 and a 1 look like, so different judges (and the
# same judge on different days) use the same scale.
ANCHORS = [
    {
        "customer": "bholi bihana dant jachaune milxa?",
        "reply": "Milxa 😊 bholi bihana 9 baje ra sadhe 10 baje khali xa — kun time milxa?",
        "scores": {"language": 5, "register": 5, "human": 5, "helpful": 5, "correct": 5},
        "why": "Natural words, mirrors the customer's xa/milxa, offers real times, one question.",
    },
    {
        "customer": "bholi bihana dant jachaune milxa?",
        "reply": "Kripaya tapaiko naam ra phone number pradan garnuhos, tyaspachhi hami tapailai upalabdha samaya ko "
        "janakari dinechhau. Aru kehi sahayog chahiyo bhane bhanuhos.",
        "scores": {"language": 2, "register": 3, "human": 2, "helpful": 3, "correct": 4},
        "why": "Office Nepali (kripaya, pradan, upalabdha, janakari, sahayog), stock ending, never answers 'milxa?'.",
    },
    {
        "customer": "price kati ho cleaning ko?",
        "reply": "Aap cleaning ke liye 1500 rupaiya dena hoga, kya aap book karna chahte hain?",
        "scores": {"language": 1, "register": 3, "human": 3, "helpful": 4, "correct": 2},
        "why": "This is Hindi, not Nepali, even though the price is right.",
    },
    {
        "customer": "thank you!",
        "reply": "You're welcome! 😊",
        "scores": {"language": 5, "register": 5, "human": 5, "helpful": 5, "correct": 5},
        "why": "English customer, short warm close, no tacked-on offer.",
    },
]

_COMPREHENSION = (
    "Before scoring, show that you understood: if a text is Romanized Nepali or mixed, write it in Devanagari as a "
    "Nepali reader would read it, then a literal English gloss. Then list the concrete problems, quoting the exact "
    "words. Only then score. Judge the TEXT only: you are not told who or what wrote it, longer is not better, and a "
    "reply that is correct but sounds robotic is not a 5."
)


def _criteria_block() -> str:
    return "\n".join(f'- "{c}": {CRITERION_TEXT[c]}' for c in CRITERIA)


def _anchor_block() -> str:
    lines = []
    for a in ANCHORS:
        lines.append(f'Customer: "{a["customer"]}"\nReply: "{a["reply"]}"\nScores: {json.dumps(a["scores"])} — {a["why"]}')
    return "\n\n".join(lines)


def _context_block(customer: str, history: list[dict] | None, locked_language: str | None) -> str:
    parts = []
    if history:
        convo = "\n".join(f'{"Customer" if t["role"] == "customer" else "Business"}: {t["text"]}' for t in history[-6:])
        parts.append(f"Earlier in this chat:\n{convo}")
    if locked_language:
        parts.append(f"The business set this chat's language to: {locked_language}.")
    parts.append(f"Customer's latest message:\n{customer}")
    return "\n\n".join(parts)


ABSOLUTE_SYSTEM = (
    "You are a native Nepali speaker who has worked years as a clinic/travel-agency receptionist in Kathmandu and "
    "reviews how businesses text their customers on WhatsApp and website chat. You read English, Devanagari Nepali, "
    "Romanized Nepali in every spelling, and code-mixed Nepali/English. Score ONE business reply on five separate "
    f"criteria, each 1-5:\n{_criteria_block()}\n\n{_COMPREHENSION}\n\nReference scores (use the same scale):\n\n"
    f"{_anchor_block()}\n\n"
    'Respond with ONLY this JSON: {"devanagari": "<or empty if not Romanized>", "gloss": "<literal English>", '
    '"problems": ["<quoted words + why>", ...], "scores": {"language": n, "register": n, "human": n, "helpful": n, '
    '"correct": n}}'
)

PAIRWISE_SYSTEM = (
    "You are a native Nepali speaker who has worked years as a clinic/travel-agency receptionist in Kathmandu and "
    "reviews how businesses text their customers. You read English, Devanagari Nepali, Romanized Nepali in every "
    "spelling, and code-mixed Nepali/English. Compare two candidate replies, A and B, to the same customer message, on "
    f"each criterion:\n{_criteria_block()}\n\n{_COMPREHENSION} The order A/B is random and means nothing.\n\n"
    'Respond with ONLY this JSON: {"reading_a": "<Devanagari + gloss>", "reading_b": "<Devanagari + gloss>", '
    '"problems_a": [...], "problems_b": [...], "winner": {"language": "A"|"B"|"tie", "register": ..., "human": ..., '
    '"helpful": ..., "correct": ...}, "overall": "A"|"B"|"tie"}'
)


def absolute_messages(reply: str, customer: str, history=None, locked_language=None) -> list[dict]:
    user = f"{_context_block(customer, history, locked_language)}\n\nBusiness reply to score:\n{reply}"
    return [{"role": "system", "content": ABSOLUTE_SYSTEM}, {"role": "user", "content": user}]


def pairwise_messages(reply_a: str, reply_b: str, customer: str, history=None, locked_language=None) -> list[dict]:
    user = f"{_context_block(customer, history, locked_language)}\n\nReply A:\n{reply_a}\n\nReply B:\n{reply_b}"
    return [{"role": "system", "content": PAIRWISE_SYSTEM}, {"role": "user", "content": user}]


_THINK_RE = re.compile(r"<think>.*?</think>", re.DOTALL)
_JSON_RE = re.compile(r"\{.*\}", re.DOTALL)


class BadJudgeOutput(ValueError):
    pass


def _json(raw: str) -> dict:
    match = _JSON_RE.search(_THINK_RE.sub("", raw or ""))
    if not match:
        raise BadJudgeOutput(f"no JSON in {raw[:200]!r}")
    try:
        return json.loads(match.group(0))
    except json.JSONDecodeError as exc:
        raise BadJudgeOutput(f"bad JSON: {exc}") from None


def parse_absolute(raw: str) -> dict:
    """{"scores": {criterion: 1-5}, "problems": [...], "devanagari": str}. Raises BadJudgeOutput."""
    data = _json(raw)
    scores = data.get("scores") or {}
    try:
        parsed = {c: int(scores[c]) for c in CRITERIA}
    except (KeyError, TypeError, ValueError):
        raise BadJudgeOutput(f"missing/invalid scores: {scores!r}") from None
    if not all(1 <= v <= 5 for v in parsed.values()):
        raise BadJudgeOutput(f"score out of range: {parsed}")
    return {"scores": parsed, "problems": list(data.get("problems") or []), "devanagari": data.get("devanagari") or ""}


def parse_pairwise(raw: str) -> dict:
    """{"winner": {criterion: "A"|"B"|"tie"}, "overall": "A"|"B"|"tie"}. Raises BadJudgeOutput."""
    data = _json(raw)
    norm = lambda v: {"a": "A", "b": "B"}.get(str(v).strip().lower(), "tie")  # noqa: E731
    winner = data.get("winner") or {}
    if "overall" not in data or not isinstance(winner, dict):
        raise BadJudgeOutput(f"missing overall/winner: {data!r}"[:200])
    return {"winner": {c: norm(winner.get(c, "tie")) for c in CRITERIA}, "overall": norm(data["overall"])}
