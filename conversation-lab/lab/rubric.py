"""The quality rubric, taken from the real production rules (backend/app/
services/conversation/intent.py rules 3-7, 13, 16, 17 and the greeting example)
and the real spec-conformance cases (backend/tests/eval/spec_conformance_cases.py).

The backend files are READ ONLY from here (CORPORATE_PHRASES is loaded by path);
nothing under backend/ is modified or imported as a package."""
import importlib.util
import re
from dataclasses import dataclass
from pathlib import Path

_BACKEND_EVAL = Path(__file__).resolve().parents[2] / "backend" / "tests" / "eval"


def _load_spec_cases():
    spec = importlib.util.spec_from_file_location("_spec_conformance_cases", _BACKEND_EVAL / "spec_conformance_cases.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


_spec_cases = _load_spec_cases()
CORPORATE_PHRASES: list[str] = _spec_cases.CORPORATE_PHRASES
SPEC_CASES: list[dict] = _spec_cases.CASES


@dataclass(frozen=True)
class Criterion:
    name: str
    weight: int
    source: str
    description: str


# Each is scored 1-5 by the LLM judge. Weights: honesty/helpfulness counts most
# (a pretty but wrong or evasive answer must not win), the rest are style.
CRITERIA: list[Criterion] = [
    Criterion(
        "length_fit", 2, "intent.py rule 17",
        "Length matches what prompted it. SHORT (one sentence, sometimes two) for greetings, a single known fact, "
        "a yes/no, a plain acknowledgment or a completed action. MEDIUM (2-4 sentences) for a few real options or "
        "one necessary question. LONG only for genuine complexity. Penalize padding, restated greetings, "
        "monologues; also penalize being too curt to be useful.",
    ),
    Criterion(
        "language_match", 2, "intent.py rule 7",
        "Written in the SAME language and script the customer is using (English / Devanagari Nepali / Romanized "
        "Nepali / natural code-mix) and stays there. Romanized Nepali must read like spoken text messages "
        "('cha', 'huncha', 'gardim', 'milcha'), not stiff formal Nepali. English service names/numbers mixed into "
        "a Nepali sentence are fine and natural. When the customer's message is language-ambiguous (a bare greeting "
        "like 'hlo', 'hi', 'yo', a bare number -- rule 7 allows 'unclear'), a reply in English OR natural Romanized "
        "Nepali is fine: score 4-5, do not penalize either choice.",
    ),
    Criterion(
        "natural_tone", 2, "intent.py rule 4",
        "Sounds like a real receptionist texting, not software. Penalize scripted customer-service phrasing "
        "('Thank you for reaching out', 'I would be happy to assist', 'Is there anything else I can assist you "
        "with', 'I understand how frustrating that is'), stiff over-apology, and mail-merge stock openers.",
    ),
    Criterion(
        "no_reflexive_question", 2, "intent.py rule 3 (+ its 'genuine next step' carve-out and rule 0's decline wording)",
        "Does NOT tack on a question or an offer of more help the customer did not need. Penalize (1-2): (i) a GENERIC "
        "content-free tail that could be pasted after any reply ('Is there anything else I can help you with?', 'Let "
        "me know if you need anything else', 'Feel free to ask', 'Anything else today?'); (ii) an UNPROMPTED offer or "
        "sales-style re-offer after the customer's message was already complete -- a thank-you/closing, or a question "
        "that has just been fully answered -- EVEN WHEN it sounds specific ('would you like me to check available "
        "times?', 'if you need anything else (an appointment, service info, or hours), just say the word'). After a "
        "thank-you or a complete answer the correct reply simply stops ('thank you' -> 'You're welcome!'). "
        "A question is FINE (score 4-5) in exactly these cases: (a) it is the one thing genuinely needed to resolve "
        "what the customer themselves opened or left unfinished ('Which day works for you?' after they asked to book); "
        "(b) ONE simple 'how can I help?' in reply to a bare greeting; (c) the redirect that follows a polite DECLINE "
        "of an off-topic request -- e.g. \"I'm just here to help with things related to <business> -- appointments, "
        "services, hours, and the like. Is there something about that I can help with?\" -- because the customer was "
        "just told no, and the question turns that no into a concrete way forward by naming what the business does. "
        "Test: (1) Was something left open by the customer, or did the assistant just decline and need to steer them "
        "back? If yes, a specific question is a real next step or redirect (fine). (2) Was the customer's message "
        "already complete and answered? Then ANY trailing offer/question is reflexive, however specific it sounds.",
    ),
    Criterion(
        "focused_no_dump", 2, "intent.py rules 16-17 + greeting example",
        "Answers only what was asked. No unprompted summary of what the business offers, no stacked list of 2-3 "
        "options in reply to a bare greeting, no compound multi-part questions (one question at a time), no "
        "unrequested extra sentences.",
    ),
    Criterion(
        "helpful_honest", 3, "intent.py rules 1, 13, 16",
        "Actually moves the customer forward using the FACTS the assistant had. Does not claim 'I don't have that "
        "information' when the facts contain it; does not invent facts; does not claim an action was completed "
        "without proof; does NOT re-ask something the customer already answered earlier in the conversation; does "
        "not demand personal details before answering a purely informational question.",
    ),
    Criterion(
        "stays_in_scope", 2, "intent.py rule 0 (off_topic)",
        "The assistant only does a receptionist's job: business questions and receptionist small talk (greetings, "
        "thanks, 'are you a bot'). A message CLEARLY unrelated to the business (trivia, history, weather, politics, "
        "current events, other companies, 'write me a poem', advice unrelated to the business) must be politely "
        "declined and redirected in one short sentence, WITHOUT answering it or using the model's own knowledge, and "
        "NOT phrased as 'I don't have that information' or escalated to a human (it is not a knowledge gap). "
        "Business-adjacent questions ('do you take insurance', 'is there parking', 'do I need travel insurance for "
        "the trek') are NOT off-topic: they must be answered from the facts or honestly escalated; wrongly refusing "
        "them is a violation. Score 5 whenever the reply handles its kind of message correctly -- for an ordinary "
        "in-scope message that is simply 5. Score 1 for answering an off-topic request or for over-refusing a "
        "business question.",
    ),
    Criterion(
        "emoji_name_policy", 1, "intent.py rules 4-5",
        "At most ONE emoji, and only in a genuinely warm moment (first greeting, thanks, a just-succeeded "
        "booking); none in a frustrated/serious conversation; none is fine. Doesn't open with the customer's "
        "name out of habit.",
    ),
]

WEIGHT_TOTAL = sum(c.weight for c in CRITERIA)

_EMOJI_RE = re.compile("[\U0001F300-\U0001FAFF\U00002600-\U000027BF\U0001F1E6-\U0001F1FF]")
_SENTENCE_SPLIT_RE = re.compile(r"[.!?।]+")


def objective_metrics(response: str) -> dict:
    """Deterministic checks (same definitions as the real runner's _metrics)."""
    lower = response.lower()
    sentences = [s for s in _SENTENCE_SPLIT_RE.split(response) if s.strip()]
    return {
        "word_count": len(response.split()),
        "sentence_count": max(len(sentences), 1),
        "ends_with_question": response.strip().endswith("?"),
        "emoji_count": len(_EMOJI_RE.findall(response)),
        "corporate_phrase_hits": [p for p in CORPORATE_PHRASES if p in lower],
    }


def rubric_text() -> str:
    return "\n".join(f"- {c.name} (weight {c.weight}; from {c.source}): {c.description}" for c in CRITERIA)
