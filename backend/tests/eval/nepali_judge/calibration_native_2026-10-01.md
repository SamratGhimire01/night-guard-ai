# Nepali judge calibration

Bars: correct picks ≥ 90%; same answer in both orders ≥ 85% (holistic pairwise only); native agreement κ ≥ 0.6 once ≥ 10 native verdicts exist. 'Trusted for' = defect types with ≥ 90% on at least 2 pairs.

| judge | pairs | picks the better reply | same answer both orders | native κ (n) | errors | trusted |
|---|---|---|---|---|---|---|
| lint | 30 | 100% | — | 0.72 (30) | 0 | **yes** |
| hybrid:gemini/gemini-3.1-flash-lite | 56 | 98% | — | 0.86 (30) | 0 | **yes** |

## Trusted for

- **lint**: bookish, english_date, hindi, stock_ending, timi, wrong_language
- **hybrid:gemini/gemini-3.1-flash-lite**: asks_twice, bookish, cold, english_date, hindi, native, robotic, stock_ending, timi, wrong_language

## By defect (right / pairs)

| defect | lint | hybrid:gemini/gemini-3.1-flash-lite |
|---|---|---|
| asks_twice | — | 2/2 |
| bookish | 7/7 | 7/7 |
| cold | — | 3/3 |
| english_date | 3/3 | 3/3 |
| hindi | 6/6 | 6/6 |
| mixed_script | 1/1 | 1/1 |
| monologue | 1/1 | 1/1 |
| native | — | 13/13 |
| repeat | 1/1 | 1/1 |
| robotic | — | 4/4 |
| spelling | 1/1 | 1/1 |
| spelling_style | 1/1 | 1/1 |
| stock_ending | 3/3 | 3/3 |
| timi | 3/3 | 3/3 |
| unhelpful | — | 3/4 |
| wrong_language | 2/2 | 2/2 |
| wrong_script | 1/1 | 1/1 |
