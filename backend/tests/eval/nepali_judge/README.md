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

## v3 (after the first live calibration)

The first live run (2026-10-01, on the owner's machine) confirmed the research: **Azure 74%, Groq gpt-oss-120b 68%**
correct picks, Groq also position-biased (74% same answer in both orders), both missing exactly the language defects
the lint gets 100% right. So v3 splits the work:

- **Language defects** (Hindi, textbook words, timi, script, spelling, repeats, English dates): the lint decides. No
  LLM is asked.
- **Everything else** (answers the question, one question at a time, doesn't re-ask, reacts to pain/frustration, not a
  template, no filler ending, right length, warm, would a receptionist send it): a **yes/no checklist**
  (`rubric.CHECKLIST`), each reply checked on its own, so there is no A/B order to be biased by. Binary checklists are
  far more consistent across judges than 1–5 scores ([CheckEval, EMNLP 2025](https://aclanthology.org/2025.emnlp-main.796/)).
- **Gemini 3.1 Flash-Lite** (free tier) added: in a 2026 Nepali benchmark it kept 89.5% reading comprehension in Nepali
  vs 97% in English, where small open models collapse. (gemini-3.5-flash is free only for 20 requests/day.)
- **Trusted for**: a judge that misses the overall bar can still be trusted for the defect types it gets right.
- Parallel (`--workers`), each judge paced to its own rate limit; everything cached.

Specs: `lint`, `<llm>` (old holistic pairwise), `check:<llm>+<llm>`, `hybrid:<llm>+<llm>` (recommended).

## Run it

```bash
# offline, free: the lint layer alone
python -m tests.eval.nepali_judge.calibrate gold --judges lint

# v3: lint + yes/no checklist (keys in backend/.env: GEMINI_API_KEY, AZURE_OPENAI_*, GROQ_API_KEY)
docker exec -e PYTHONPATH=/app night_guard_ai-backend-1 \
  python -m tests.eval.nepali_judge.calibrate gold \
  --judges lint,hybrid:gemini/gemini-3.1-flash-lite,hybrid:azure,hybrid:groq/qwen/qwen3.8-27b,hybrid:gemini/gemini-3.1-flash-lite+azure \
  --out tests/eval/nepali_judge/calibration_$(date +%F).md

# re-judge a saved before/after run with the trusted judges
python -m tests.eval.nepali_judge.calibrate rejudge tests/eval/phase4_results_2026-09-29.json --judges lint,claude
```

Results are cached in `cache.json` (git-ignored), so re-runs only pay for new comparisons. Only quote numbers from
judges the calibration marked trusted.

## Live result, v3 (2026-10-01, `calibration_gemini_2026-10-01.md`)

| judge | correct picks | trusted |
|---|---|---|
| lint | 100% (25 language pairs) | yes |
| **hybrid:gemini/gemini-3.1-flash-lite** | **97% (33/34)** | **yes** — for every defect type except `unhelpful` (2/3) |
| check:gemini/gemini-3.1-flash-lite (no lint) | 41% | no — 0/5 on Hindi, but 2/2 cold, 3/3 robotic |
| azure, holistic pairwise (v2 run) | 74% | no |
| groq/openai/gpt-oss-120b, holistic pairwise (v2 run) | 68% | no |

The split works: the lint covers what the LLM can't read reliably, the checklist covers tone. Use
`hybrid:gemini/gemini-3.1-flash-lite` (add `+azure` once Azure has been calibrated in checklist mode).

## Status (2026-10-01)

- Lint layer: 25/25 on its gold pairs, 0 false alarms on the 34 good gold replies (`calibration_lint_2026-10-01.md`).
  On the 30 native-review replies it flags 6, all real: four over-long answers and words the app's word bank doesn't
  swap yet (`yadi`, `rakta`, `swikarchhau`, `saadharan roopma`, `magincha`). Those are candidates for the word bank,
  pending native review.
- LLM judges: not yet calibrated — needs API keys (this sandbox has none). Run the command above.
- Native labels: 0 so far. Filling in `native_review_sheet.md` turns on the κ check and adds native pairs.
- The gold pairs were written from real customer vocabulary but by a non-native author: a native skim of `gold.py`
  (especially the `good` replies) is part of the review.
