"""Nepali-aware reply judge: a deterministic native-language lint plus an LLM ensemble scored on an analytic rubric.

Why a new judge: generic LLM judges are measurably weak on low-resource and romanized languages (lower consistency,
over-trusted verdicts), and Romanized Nepali has no standard spelling. So:

- lint.py     what a native reader always notices, checked by rule (Hindi, textbook words, timi, English dates mid-Nepali,
              mixed script, wrong language, repeats, stock endings, monologues). Free, offline, never drifts. Its
              findings CAP the LLM scores: an LLM can't award 5/5 to a reply with a Hindi word in it.
- rubric.py   five criteria with 1-5 anchors, scored separately; the judge first reads a Romanized reply back into
              Devanagari and glosses it (comprehension before scoring), and must quote the words it penalises.
- engine.py   absolute scoring and pairwise comparison (both orders: a verdict that flips with the order is a tie),
              ensembled over judges from different model families.
- gold.py     minimal pairs: two replies that differ in exactly one known defect, so the right answer is known
              without an annotator. Plus native labels from docs/nepali_voice/native_review_sheet.md when filled in.
- calibrate.py  measures every judge against the gold set and marks it trusted only above fixed bars.

    python -m tests.eval.nepali_judge.calibrate --judges lint,claude,azure   # needs the judges' API keys
"""
