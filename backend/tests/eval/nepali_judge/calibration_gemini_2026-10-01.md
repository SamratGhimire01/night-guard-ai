# Nepali judge calibration

Bars: correct picks ≥ 90%; same answer in both orders ≥ 85% (holistic pairwise only); native agreement κ ≥ 0.6 once ≥ 10 native verdicts exist. 'Trusted for' = defect types with ≥ 90% on at least 2 pairs.

| judge | pairs | picks the better reply | same answer both orders | native κ (n) | errors | trusted |
|---|---|---|---|---|---|---|
| lint | 25 | 100% | — | — (0) | 0 | **yes** |
| hybrid:gemini/gemini-3.1-flash-lite | 34 | 97% | — | — (0) | 0 | **yes** |
| check:gemini/gemini-3.1-flash-lite | 34 | 41% | — | — (0) | 0 | no |

## Trusted for

- **lint**: bookish, english_date, hindi, stock_ending, timi, wrong_language
- **hybrid:gemini/gemini-3.1-flash-lite**: bookish, cold, english_date, hindi, robotic, stock_ending, timi, wrong_language
- **check:gemini/gemini-3.1-flash-lite**: cold, robotic, stock_ending

## By defect (right / pairs)

| defect | lint | hybrid:gemini/gemini-3.1-flash-lite | check:gemini/gemini-3.1-flash-lite |
|---|---|---|---|
| asks_twice | — | 1/1 | 1/1 |
| bookish | 6/6 | 6/6 | 2/6 |
| cold | — | 2/2 | 2/2 |
| english_date | 2/2 | 2/2 | 0/2 |
| hindi | 5/5 | 5/5 | 0/5 |
| mixed_script | 1/1 | 1/1 | 0/1 |
| monologue | 1/1 | 1/1 | 0/1 |
| repeat | 1/1 | 1/1 | 1/1 |
| robotic | — | 3/3 | 3/3 |
| spelling | 1/1 | 1/1 | 0/1 |
| spelling_style | 1/1 | 1/1 | 0/1 |
| stock_ending | 2/2 | 2/2 | 2/2 |
| timi | 2/2 | 2/2 | 1/2 |
| unhelpful | — | 2/3 | 2/3 |
| wrong_language | 2/2 | 2/2 | 0/2 |
| wrong_script | 1/1 | 1/1 | 0/1 |
