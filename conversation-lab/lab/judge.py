"""LLM-as-judge for Night Guard conversation style.

One real gpt-5-mini call per sample rates a candidate reply 1-5 on each rubric
criterion; the 0-100 score is computed deterministically in Python (weighted
mean) so the model never does arithmetic. Two objective checks (emoji count,
scripted corporate phrases) act as hard caps so a lenient judge can't wave them
through."""
from dataclasses import dataclass, field
from concurrent.futures import ThreadPoolExecutor
from statistics import mean

import dspy

from lab.rubric import CRITERIA, WEIGHT_TOTAL, objective_metrics, rubric_text


class JudgeReply(dspy.Signature):
    """You are a strict, consistent quality judge for a receptionist chatbot of a small business in
    Nepal (clinic, salon, agency, shop...; customers write English, Devanagari Nepali, Romanized Nepali, or a mix). Rate ONE candidate reply
    against each rubric criterion from 1 (clearly violates) to 5 (exemplary). Judge only the candidate reply
    itself, in light of the conversation and the facts the assistant had. Be harsh on real violations and give 5
    only when the reply is genuinely what a good human receptionist would send. Do not reward length or
    politeness for their own sake."""

    rubric: str = dspy.InputField(desc="criteria with their meaning")
    facts_available_to_assistant: str = dspy.InputField(desc="business facts the assistant had (may be empty)")
    conversation_so_far: str = dspy.InputField(desc="earlier turns, oldest first (may be empty)")
    customer_message: str = dspy.InputField()
    candidate_reply: str = dspy.InputField()

    length_fit: int = dspy.OutputField(desc="1-5")
    language_match: int = dspy.OutputField(desc="1-5")
    natural_tone: int = dspy.OutputField(desc="1-5")
    no_reflexive_question: int = dspy.OutputField(desc="1-5")
    focused_no_dump: int = dspy.OutputField(desc="1-5")
    helpful_honest: int = dspy.OutputField(desc="1-5")
    stays_in_scope: int = dspy.OutputField(desc="1-5")
    emoji_name_policy: int = dspy.OutputField(desc="1-5")


@dataclass
class Judgement:
    score: float  # 0-100
    criteria: dict[str, float]
    objective: dict
    reasoning: str = ""
    weighted_score: float = 0.0  # v1 plain weighted mean, kept for comparison
    samples: int = 1
    per_sample_scores: list[float] = field(default_factory=list)


def _clamp(x) -> int:
    try:
        return max(1, min(5, int(x)))
    except (TypeError, ValueError):
        return 1


def _weighted_score(criteria: dict[str, float]) -> float:
    weighted = sum(c.weight * criteria[c.name] for c in CRITERIA) / WEIGHT_TOTAL
    return round((weighted - 1) / 4 * 100, 1)


def _score(criteria: dict[str, float]) -> float:
    """v2 aggregation: half weighted mean, half weakest-link. v1 (plain weighted
    mean) let one serious violation be diluted by six perfect criteria -- e.g.
    a reflexive 'want me to check times?' after 'thank you' still scored 76.
    A receptionist reply is only as good as its worst real flaw."""
    weakest = (min(criteria.values()) - 1) / 4 * 100
    return round(0.5 * _weighted_score(criteria) + 0.5 * weakest, 1)


class ReplyJudge:
    def __init__(self, *, samples: int = 1, lm=None):
        """lm: optional LM override (e.g. a low-reasoning-effort LM for interactive use); None = the configured LM."""
        self.samples = samples
        self.lm = lm
        self._predict = dspy.ChainOfThought(JudgeReply)

    def __call__(
        self, customer_message: str, reply: str, *, conversation: str = "", facts: str = ""
    ) -> Judgement:
        objective = objective_metrics(reply)
        def one(_):
            return self._predict(
                rubric=rubric_text(),
                facts_available_to_assistant=facts or "(none given)",
                conversation_so_far=conversation or "(start of conversation)",
                customer_message=customer_message,
                candidate_reply=reply,
                lm=self.lm,
            )

        if self.samples > 1:
            with ThreadPoolExecutor(self.samples) as ex:
                outs = list(ex.map(one, range(self.samples)))
        else:
            outs = [one(0)]
        runs: list[dict[str, int]] = [{c.name: _clamp(getattr(o, c.name)) for c in CRITERIA} for o in outs]
        reasoning = next((getattr(o, "reasoning", "") for o in outs if getattr(o, "reasoning", "")), "")

        per_sample = []
        for r in runs:
            r = self._apply_caps(r, objective)
            per_sample.append(_score(r))
        avg = {c.name: mean(self._apply_caps(r, objective)[c.name] for r in runs) for c in CRITERIA}
        return Judgement(
            score=round(mean(per_sample), 1),
            weighted_score=_weighted_score(avg),
            criteria={k: round(v, 2) for k, v in avg.items()},
            objective=objective,
            reasoning=reasoning,
            samples=self.samples,
            per_sample_scores=per_sample,
        )

    @staticmethod
    def _apply_caps(criteria: dict[str, int], objective: dict) -> dict[str, int]:
        capped = dict(criteria)
        if objective["corporate_phrase_hits"]:
            capped["natural_tone"] = min(capped["natural_tone"], 1)
        if objective["emoji_count"] > 1:
            capped["emoji_name_policy"] = min(capped["emoji_name_policy"], 1)
        return capped
