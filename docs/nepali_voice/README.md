# Natural Nepali voice (2026-10-01)

The business assistant's Romanized Nepali sounded like a textbook (kripaya, janakari, maaf garnuhos, sakinu huncha),
leaked Hindi (kahan, bilkul), re-sent the same fixed text in one chat (93 times across 653 real chats), and put
"Monday, October 5 at 10:00 AM" in the middle of Nepali sentences. Maya (the companion) is not touched.

## What changed

| Piece | File |
|---|---|
| Word bank: 255 natural words/phrases by situation, 118 never-use spellings (73 rules: 60 auto-swaps, 13 flag-only), 428 x/v spelling-mirror forms | `backend/app/services/conversation/nepali_wordbank.py` |
| Reply finalizer: word bank + drop filler endings, repeated stock offers, same opener twice in a row | `backend/app/services/conversation/reply_polish.py` |
| All fixed replies rewritten in natural Nepali (Romanized + Devanagari), 2–4 wordings each, never the same fixed text twice in one chat | `backend/app/services/conversation/response_templates.py` |
| Dates/times the Nepali way: "Sombar (Oct 5), bihana sadhe 10 baje", dedh/adhai/sawa | same file (`format_when`, `format_slot_list`) |
| A slot list already shown is pointed back at ("Mathi ko time haru madhye kunai milcha?") instead of pasted again | `orchestrator._propose_available_slots` |
| AI instructions: "tapai by default, hajur as a warm yes, never timi"; word-bank section; broken examples fixed; 16 natural Romanized/mixed examples | `backend/app/services/conversation/intent.py` |
| Style examples: 41 → 134 Romanized/mixed (Hindi "है"/"abhi" rows fixed) | `backend/data/style_exemplars/seed_v1.csv` |
| Judge prompt: Nepali naturalness guidance | `backend/tests/eval/live_human_likeness_before_after.py` |
| Measurement + native review sheet | `backend/scripts/nepali_naturalness_report.py` |

English first wordings are unchanged byte for byte; English only gained extra wordings for the no-repeat rule.

## Measured on the 653 real conversations (`naturalness_report_2026-10-01.json`)

| Measure | Before | After (code guards) | After (guards + new templates) |
|---|---|---|---|
| Never-use words per Romanized reply | 1.15 | 0.06 | 0.001 |
| Exact repeat of an earlier reply in the same chat | 93 | 87 | 24 |
| Same opener twice in a row | 60 | 0 | 0 |
| Replies ending in a stock filler/offer (not counting the first greeting) | 5.2% | 3.3% | 3.5% |
| Never-use words in the fixed Romanized wordings | 87 (in 59) | — | 0 (in 96) |

"After" re-runs the same sent replies through today's code; the LLM's own new wording (new prompt + examples) is not
in these numbers and needs the live 3-judge run. The 24 remaining repeats are mostly long test chats where every
wording of a template was used up, and repeated "what's my appointment?" answers.

## To go live

1. `docker compose up -d --force-recreate backend` (CLAUDE.md rule — the running server keeps old code otherwise).
2. `docker exec night_guard_ai-backend-1 python scripts/seed_style_exemplars.py --prune` — adds the new examples and
   retires the reworded old ones (only shared seed rows; tenant-specific rows are never touched).
3. Native review: fill in `native_review_sheet.md` (30 real replies, before → after) and skim the word bank.
4. Live scoring (needs Azure): `docker exec night_guard_ai-backend-1 python -m tests.eval.live_phase4_multijudge` (see its docstring for stages).

Re-measure any time: `python scripts/nepali_naturalness_report.py --old-templates <old response_templates.py>`.
