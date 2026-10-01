# Nepali-aware judge

Scores the business assistant's replies the way a native Nepali receptionist would read them, and proves how far
each judge can be trusted before its numbers are quoted.

## Why the old judge wasn't enough

The previous judge was one LLM giving one holistic 1–5 score with a paragraph of Nepali hints. Research on LLM judges
says that set-up is weakest exactly where we need it:

- Judges are much less consistent on low-resource languages, regardless of model size, and studies tend to over-trust
  them ([Fu et al., EMNLP Findings 2025](https://aclanthology.org/2025.findings-emnlp.587.pdf);
  [survey, 2026](https://arxiv.org/html/2607.02235v2)).
- Romanized Nepali has no standard spelling, and models understand it 10–20 points worse than Devanagari;
  transliterating to Devanagari first helps ([Romanized Nepali benchmark](https://arxiv.org/html/2604.14171);
  [NepaliXlit](https://aclanthology.org/2026.chipsal-1.12/)).
- Pairwise comparison agrees with humans more than absolute scoring; judges show strong position bias unless both
  orders are scored; analytic rubrics and calibration against labelled examples (target Cohen's κ > 0.6) are the
  standard practice ([best practices](https://futureagi.com/blog/llm-as-judge-best-practices-2026/);
  [pairwise vs rubric](https://ai-tldr.dev/learn/evaluation-safety/llm-as-judge/pairwise-vs-rubric-judging/)).

## How this judge works

| Layer | What it does | File |
|---|---|---|
| Native lint | Rule checks a native reader always notices: Hindi words, textbook/office words, `timi`, English dates mid-Nepali, Devanagari inside Romanized words, spelling errors, not mirroring the customer's xa/vayo style, wrong language/script, a reply repeated word for word, filler endings and repeated offers, monologues. Each finding **caps** a criterion (an LLM can't give 5/5 to a reply with a Hindi word). | `lint.py` |
| Rubric | Five criteria scored separately — language, register, human, helpful, correct — with fixed 1/3/5 anchors and four reference replies with agreed scores. The judge must first read a Romanized reply back in Devanagari and gloss it, then quote the words it penalises, then score. | `rubric.py` |
| Ensemble | Judges from different model families (Claude, Azure gpt — the bot's own family —, Groq open models). Scores: median per criterion, then lint caps. Comparisons: each judge sees A/B in both orders; a verdict that flips is position bias and counts as a tie; majority of the rest. | `engine.py`, `judges.py` |
| Gold set | 34 minimal pairs — two replies differing in exactly one known defect, so the right answer is known without an annotator (25 the lint must catch, 9 tone/warmth/helpfulness/robotic pairs only an LLM can judge). Plus native pairs from `docs/nepali_voice/native_review_sheet.md` once filled in. | `gold.py` |
| Calibration gate | A judge is **trusted** only at ≥ 90% correct picks, ≥ 85% same answer in both orders, and (once ≥ 10 native verdicts exist) κ ≥ 0.6 with the native speaker. | `calibrate.py` |

## Run it

```bash
# offline, free: the lint layer alone
python -m tests.eval.nepali_judge.calibrate gold --judges lint

# the LLM judges (keys in backend/.env; the Claude judge needs: pip install -r requirements-eval.txt)
docker exec -e PYTHONPATH=/app night_guard_ai-backend-1 \
  python -m tests.eval.nepali_judge.calibrate gold --judges lint,claude,azure,groq/openai/gpt-oss-120b \
  --out tests/eval/nepali_judge/calibration_$(date +%F).md

# re-judge a saved before/after run with the trusted judges
python -m tests.eval.nepali_judge.calibrate rejudge tests/eval/phase4_results_2026-09-29.json --judges lint,claude
```

Results are cached in `cache.json` (git-ignored), so re-runs only pay for new comparisons. Only quote numbers from
judges the calibration marked trusted.

## Status (2026-10-01)

- Lint layer: 25/25 on its gold pairs, 0 false alarms on the 34 good gold replies (`calibration_lint_2026-10-01.md`).
  On the 30 native-review replies it flags 6, all real: four over-long answers and words the app's word bank doesn't
  swap yet (`yadi`, `rakta`, `swikarchhau`, `saadharan roopma`, `magincha`). Those are candidates for the word bank,
  pending native review.
- LLM judges: not yet calibrated — needs API keys (this sandbox has none). Run the command above.
- Native labels: 0 so far. Filling in `native_review_sheet.md` turns on the κ check and adds native pairs.
- The gold pairs were written from real customer vocabulary but by a non-native author: a native skim of `gold.py`
  (especially the `good` replies) is part of the review.
