# conversation-lab — status (lab-specific; PHASE_STATUS.md only gets a pointer)

## Phase L1 — sandbox environment, judge, and test UI (2026-09-19). No DSPy optimization run yet (by design).

### 1. Environment + real Azure connection — proven
DSPy 3.3.1 in `conversation-lab/.venv` only. Real friction hit and solved:
1. `dspy.LM(...)` refused gpt-5-mini: "reasoning models require temperature=1.0 and max_tokens >= 16000".
2. The Foundry resource (`*.services.ai.azure.com`) works via LiteLLM's `azure_ai/` route with `api_base=<endpoint>/models`.
Real hello-world (`scripts/hello_world.py`):
```
answer        : hello world from the conversation lab
model         : azure_ai/gpt-5-mini
response model: azure_ai/gpt-5-mini-2025-08-07      <- returned by Azure itself
usage         : prompt 146 / completion 218 tokens (192 reasoning)
```

### 2. Judge — built, found flawed, iterated three times, validated
Rubric = 7 criteria from real production rules (length_fit r17, language_match r7, natural_tone r4,
no_reflexive_question r3, focused_no_dump r16-17+greeting example, helpful_honest r1/13/16, emoji_name_policy r4-5),
scored 1-5 by a real gpt-5-mini call; the 0-100 score is computed in Python. Two objective checks (emoji count,
scripted phrases from the real `CORPORATE_PHRASES`) cap the relevant criterion.
Validation set: 24 real replies (verbatim from PHASE_STATUS.md: pre-fix = bad, post-fix = good; name/phone/email
redacted) + 3 clearly-labeled synthetic replies for criteria with no recorded real bad example. 26 replies total.

Iterations (all on the same 26 replies, so read the later numbers as optimistic):
| version | change | pairwise good>bad | mean good / bad | noise (stdev) |
|---|---|---|---|---|
| v1 | plain weighted mean, 3 samples | 24/24 | 94.8 / 62.7 | 3.4 |
| v2 | + weakest-link blend (v1 let one serious violation be diluted: reflexive "want me to check times?" after "thank you" still scored 76) | 24/24 | 87.0 / 39.7 | 6.5 |
| v3 | + two rubric anchors from the production text (bare greeting is language-ambiguous; a greeting's single "how can I help?" is not a tic), 5 samples | 24/24 | 94.4 / 36.3 | 4.9 |
| **final** (PII-redacted set, 5 samples) | same as v3 | **24/24 (real 21/21, synthetic 3/3)** | **94.1 / 34.7** | **5.5** |
(median-across-samples was tried offline on v2 and was worse; not adopted.)

Final real scores (mean of 5 judge samples; range in brackets):
| customer msg | reply (label, provenance) | score |
|---|---|---|
| hlo | BAD "Hello! Welcome... We offer general dentistry... parking" (Phase 3 pre-fix) | 32.1 [28-45] |
| hlo | BAD "...in New Baneshwor — we offer ... How can I help — an appointment, service, or directions?" | 32.3 [21-40] |
| hlo | BAD "Hi — welcome to Test Chat Biz! ... I can assist with appointments, services, pricing, hours..." (Phase 7 stale) | 23.6 [21-29] |
| hlo | GOOD "Namaste! Kasari sahayog garna sakchu?" | 94.3 [72-100] |
| hlo | GOOD "Hi! Welcome to Samaj Dental Clinic — how can I help you today?" | 100 |
| hlo | GOOD "Hi! K ma madat garna sakchu?" / "Namaste! K ma madat garna sakchu? 😊" / Phase 8 live | 100 |
| Yo | BAD x2 (Phase 1 audit, real transcript: compound 3-way question + business intro) | 52.5 / 48.9 |
| Yo | GOOD "Hi! How can I help you today?" | 100 |
| open cha? | BAD "Maile yaha hamro opening hours ko info paudina..." (pre-fix) | 16.8 |
| open cha? | GOOD x2 (real hours answers, Phase 6 + Phase 8) | 100 / 100 |
| thank you | BAD "You're welcome — would you like me to check available times...?" | 66.6 [29-100] |
| thank you | GOOD "You're welcome!" | 100 |
| teeth cleaning available cha? | BAD "Bujhe — ... Lock garna malai tapaiko naam ra phone number wa email chahincha." | 40.0 [27-64] |
| teeth cleaning available cha? | GOOD real slot list + "Kun milcha?" | 100 |
| (re-ask loop) | BAD real loop reply (WhatsApp/email/SMS asked again) | 19.6 |
| (re-ask, fixed) | "GOOD" post-fix reply (itself still asks two things) | 64.3 [49-86] |
| cancel it | GOOD "Done, Sita — ...has been cancelled." | 94.6 |
| synthetic | corporate-phrase reply 13.9; emoji-while-frustrated 33.6; English reply to Devanagari 36.1 | all < their good counterparts (88.6 / 88.6 / 75.7) |

**Verdict, stated honestly.** The judge ranks correctly: every good reply beat every bad reply for the same customer
message in every run (24/24). It is a trustworthy *relative* scorer. Limits found:
* Absolute thresholds are not perfectly clean: best single threshold classified 96% (v2 scale, 1 miss: the
  "good" re-ask reply at 64.3, which is itself compound - arguably my label was generous, the judge is right).
  Best-single-threshold accuracy across the four runs: v1 scale 92% / 92% / 96% / 100%, v2 scale 92% / 92% / 96% / 96% -
  within noise; v2 is not clearly better as a classifier (its gain is a wider good-vs-bad gap, ~59 vs ~47 pts).
* Per-sample noise is real (~5 pts avg; the "thank you" bad reply ranged 29-100 across 5 samples - one sample missed
  the reflexive offer). Use >=5 samples; ignore single-run differences under ~15 points.
* **Overfitting risk:** rubric anchors were added after seeing failures on this same set. A fresh held-out set
  should be gathered BEFORE the optimization phase so the optimizer is not scored by a judge tuned on its own examples.
* An unoptimized baseline exposed the same failure class we fixed in production (see UI run below) - so the judge
  has real signal to optimize against.

### 3. Test UI — working end to end
`python -m lab.webapp` -> http://127.0.0.1:8765 (stdlib server, own port/look, red "NON-PRODUCTION SANDBOX" banner,
fictional "Demo Dental Clinic"). Real bug found while testing in a browser: `let history` collided with the browser's
`window.history` and killed the page script (form reloaded silently) - renamed, fixed. Real session (baseline, judge x1):
```
customer: open cha?                     -> "Ho — Demo Dental Clinic ko samanya khulaune samaya Monday–Friday 9:00 AM–6:00 PM ho.
                                            Saturday ra Sunday hami band chhau. Tapai kun din/kun time aauna chahanu huncha? Ma upalabdhta
                                            herera madat garna sakchhu. (Note: yo chat matra ho ...)"  judge 67.8/100
                                            (length 4, lang 5, tone 5, no_reflexive 3, focused 4, helpful 5, emoji 5; words 46)
customer: teeth cleaning ko price kati ho? -> judge 48.2/100
```
API smoke ("hlo", judge x3): baseline reply was a 50-word welcome + hours + "services, directions, or appointment?" +
sandbox disclaimer -> **48.8**: the exact greeting failure fixed in production, now measurable - a real optimization target.
Screenshots (local, this session): /tmp/claude-chrome-screenshots-z5WbTy/screenshot-1789818225972-1.jpg and
screenshot-1789818273623-2.jpg (score breakdown expanded).

### 4. Isolation / secrets checks (real output)
* `find backend frontend -newer conversation-lab/.venv/pyvenv.cfg` (excluding caches/node_modules) -> **no files**:
  zero changes to backend/ or frontend/ during this phase. `backend/.env` mtime 16:53 (the earlier Gmail change) predates the lab.
* Scan of every file in conversation-lab (excl. .venv) for the real API key value and endpoint host -> **NONE**.
  Credentials are read read-only from `backend/.env` at runtime; no new secrets file exists.
* `git check-ignore`: `.venv/` and `__pycache__/` ignored via repo-root .gitignore (`.env`/`.env.*` too).
* Redaction: name/phone/email removed from the validation set; earlier result files containing them were deleted;
  grep for the phone/email/name across lab files -> none.
* Docker: the lab runs in a host venv, not Docker; the backend container was not touched, so the force-recreate rule
  did not apply to it.

## Phase L2 — generalization, interactive speed, held-out validation (2026-09-19). Still no DSPy optimization run, still no commit.

All numbers below are real Azure gpt-5-mini calls; raw outputs are in `results/`.

### 1. Generalization check (dental vs hair salon vs trekking agency)
`lab/businesses.py`: 3 fictional configs shaped like the real per-business data (name/address/currency, hours per day,
services with price+duration, policies) rendered to a facts block. The receptionist and web UI take a business key.
**Two dental leaks were found and removed first** - the baseline's instruction said "small dental clinic" and the judge's
said "a dental clinic in Nepal"; both now say "small business" (judge lists "clinic, salon, agency, shop" as examples).
Calibration re-run with the generic judge wording (26 replies, 5 samples): **24/24 pairwise, good 95.4 / bad 35.1, noise 4.0**
(before: 24/24, 94.1 / 34.7, 5.5) -> no regression.
* (a) **Own data used, not dental:** no dental words in the salon/trek facts text; 0 dental-word hits in 30 salon+trek baseline
  replies; replies cite the business's own facts (Jawalakhel, walk-ins, Thamel, permits, 30% deposit); the trek "Are you open on
  Saturday?" reply correctly said closed (its own hours), salon said open.
* (b) **Rubric is generic:** grep of `rubric_text()` + judge field descriptions for dental terms -> none; only "clinic" in the judge
  instruction's example list. Held-out synthetic salon/trek pairs: good replies 100 vs bad 18.9-42.9 (5/5 pairs right).
* (c) **Same baseline problems for every business** (45 baseline replies, 3 per cell, judge x3; mean score / mean words):
| scenario | dental | salon | trek |
|---|---|---|---|
| greeting "hlo" | 31.9 / 107w | 31.9 / 100w | 33.3 / 118w |
| hours (roman) | 46.0 / 72w | 49.7 / 79w | 54.3 / 72w |
| hours (english) | 49.4 / 74w | 43.7 / 93w | 55.4 / 65w |
| price | 36.3 / 76w | 43.0 / 63w | 52.9 / 83w |
| thanks (after a price answer) | 23.6 / 70w | 25.1 / 50w | 24.1 / 92w |
| overall mean | 37.5 | 38.7 | 44.0 |
Greeting ~100-118 words (a bare "hlo") and "thanks" answered with an offer/booking pitch score ~32 and ~24 in all three - the
failure is business-independent. Caveat: only 3 businesses, all Nepal-context, all mostly Roman-Nepali/English prompts.

### 2. Speed for interactive testing (real before/after)
| measurement | result |
|---|---|
| 16000-token cap vs 2000 (same prompt, 3 calls each) | **8.73s vs 8.78s - the cap is only a ceiling; it does not cost time.** Latency tracks *reasoning tokens generated*. |
| judge samples parallel? | **Already parallel** (ThreadPoolExecutor in `judge.py`). Measured judge latency x1 6.5s / x3 8.0s / x5 9.4s (sequential would be ~32s). |
| reply latency, default effort -> `reasoning_effort="low"` -> `"minimal"` | **10.4s -> 4.2s -> 2.5s** (mean of 12; completion tokens 620 -> 244 -> 115) |
| reply quality at each (default x3 judge as yardstick, n=12) | 36.2 / 36.1 / 42.9 - low is no different; minimal changes reply behaviour (shorter), so not used |
| judge x1 latency, default -> low -> minimal | 6.5s -> 4.6s -> 3.8s |
Does a low-effort judge hurt? Validated on BOTH sets (x1 accuracy = mean over the 5 independent draws of each 5-sample run):
| judge effort | calibration pairwise x1 (x5) | held-out pairwise x1 (x5) | good/bad mean (cal.) | draw-vs-mean deviation |
|---|---|---|---|---|
| default | 100% (24/24) | 94.7% (14/15) | 95.4 / 35.1 | 3.6-4.7 |
| **low** | 100% (24/24) | 94.7% (14/15) | 96.9 / 35.3 | 3.6-4.4 |
| minimal | 100% (24/24) | 94.7% (14/15) | 94.4 / 40.2 (gap narrower) | 3.9-4.1 |
(minimal's first attempt hit an Azure 429 rate limit after retries; re-run with 3 workers.)
**Adopted for the UI only** (`lab/webapp.py`): reply `low`, quick judge `low`, **default 1 sample**, plus a per-reply
**"re-score x5 (calibrated judge)"** button (default effort, 5 samples, no regeneration - new `/api/judge`). UI shows reply/judge seconds.
Real browser test (salon, "hlo"): **8.0s per turn** (reply 2.9s + judge 4.4s) vs ~24s before; the x5 re-score took 11s.
It also showed the noise trade-off: x1 scored 50, the x5 re-score 31.2 for the same reply - x1 is for iteration, not for conclusions.
Calibration/validation/optimization scripts are unchanged and keep default effort + 5 samples (`--effort` flag is opt-in).
Caveat: because the UI replies at `low` and the baseline was calibrated at default, any optimizer run must pin its effort explicitly.
The effort choice was made looking at both sets (a config choice, not a rubric change, but say so).

### 3. Held-out validation (`lab/heldout_set.py`, written BEFORE the judge ran on it; judge NOT tuned afterwards)
29 replies, none in the calibration set: 9 groups from real transcripts in PHASE_STATUS.md (off-topic, verbose thanks,
complaint, "are you a bot", language switch, hours-not-given, rule-9 loop, confirmation ignored, false handoff) + 5 synthetic
groups for salon/trek. Some goods/bads inside real groups are synthetic counterparts written by me (labeled in provenance).
| result (5 samples, default effort) | value |
|---|---|
| pairwise good>bad | **14/15 (93%)** - real 9/10, synthetic 5/5 (calibration was 24/24) |
| threshold 87.5 fitted on calibration, NOT refit | **25/29 = 86%** (calibration best-fit was 96%) |
| mean good / bad, noise | 94.3 / 35.6, 5.6 |
Misses, honestly:
1. **REAL RUBRIC GAP (the important one):** off-topic "how was America discovered?" - the real history essay a dental bot gave
   scored **94.3** (bad), *above* the correct decline (84.6). The rubric has no scope/off-topic criterion (production rule 0 /
   intent `off_topic`), so the essay got 5/5 on helpful_honest. Not fixed here on purpose: patching it now would contaminate this
   held-out set. Next phase: add a `stays_in_scope` criterion, then gather a fresh held-out set that includes scope cases.
2. Three "good" labels scored 69-75 (below the 87.5 threshold, still above their bad pair): the bot-question reply ends "What can I help you
   with today?" (reflexive-question 3/5), the complaint reply promises a callback ("helpful_honest" 3.4). These are arguable
   labels (the labels are the project's verdicts, not ground truth), so treat the 86% as a lower bound on a label-noisy set.
So: the judge generalizes to unseen replies and new businesses for what it measures, but its blind spot (scope) is real,
and calibration numbers overstated it - use held-out-style numbers (93% pairwise / 86% threshold) as the honest expectation.

### Isolation / secrets (real output)
`find backend frontend -newer .venv/pyvenv.cfg` (excl. caches/node_modules) -> no files. Scan for the API key value and endpoint host in
conversation-lab (excl. .venv) -> NONE. No real PII (only placeholder `sita@example.com` from the calibration set). The old lab server from
L1 (pid 15728) was stopped and restarted with the new code on :8765 (host venv, not Docker; the backend container was not touched).
New/changed files (all in conversation-lab/): `lab/businesses.py`, `lab/heldout_set.py`, `scripts/baseline_by_business.py`,
`scripts/latency_bench.py`; edited `lab/{receptionist,judge,llm,webapp}.py`, `scripts/validate_judge.py` (`--set`, `--effort`, `--threshold-from`).

## Phase L3 — scope criterion + fresh held-out set (2026-09-19). No DSPy optimization run, no commit.

**Change:** new rubric criterion `stays_in_scope` (weight 2, from production rule 0 / `off_topic`) in `lab/rubric.py` + `lab/judge.py`.
Off-topic requests must be declined without answering (and not framed as a knowledge gap/handoff); business-ADJACENT questions
(insurance, parking, travel insurance) must be answered/escalated, and over-refusing them is a violation. Ordinary in-scope replies = 5.
`lab/heldout_set.py` is now marked SPENT (it exposed the gap). `lab/heldout_set_2.py` (22 replies, 11 groups: 3 real off-topic
declines, 2 real business-adjacent, 3 synthetic salon/trek scope cases, 3 real non-scope regression cases) was written BEFORE
the criterion was added and the judge was not tuned on it afterwards.

| check (5 samples, default effort) | result |
|---|---|
| calibration set (regression) | **24/24**, good 97.3 / bad 40.1, noise 4.8 (before: 24/24, 95.4 / 35.1, 4.0) |
| spent held-out #1 (development now, not held-out) | **15/15** - the America essay that scored 94.3 is now caught (was 14/15). Threshold acc 90% (was 86%). |
| **fresh held-out #2** pairwise good>bad | **11/11** (real 8/8, synthetic 3/3) |
| held-out #2 good / bad mean, noise | 79.3 / 23.7, 7.1 |
| held-out #2 threshold 79.9 fitted on calibration, NOT refit | **16/22 = 73%** (see below) |
| held-out #2 best possible single threshold | 100% (cutoff 46.6) |
| held-out #2 at `low` effort (UI quick judge) | pairwise 11/11, good/bad 82.4 / 21.6, noise 6.0 |
Scope behaviour on held-out #2 (default effort): `stays_in_scope` = 1 for answered off-topic (weather, election, poem, movie, and the
"I don't have that information / connect you to the team" framing of a cricket question); 1 / 2.4 for over-refusals of insurance/parking/
travel-insurance; correct declines and honest escalations are not flagged on it. At `low` effort all off-topic bads were caught, but one
over-refusal scored 4 (default: 1) - ranking still held via other criteria, so the quick UI judge is weaker on over-refusal; use the x5 button.

**Honest caveats (found, not fixed - fixing would spend held-out #2):**
1. **Absolute cutoffs do not transfer.** 73% at the calibration threshold vs 100% at its own best cutoff: the new criterion + stricter
   grading of these reply types shifted good scores down. Use the judge for RANKING/relative improvement (what an optimizer needs),
   not for a fixed pass/fail line.
2. **Honest "I don't have that" escalations are graded harshly** (good replies scored 46.6 parking / 58.3 insurance / 74.7 travel-insurance;
   helpful_honest 2.2-3.2, length/tone 3-3.8): the real production wording ("...I've also let our team know, so a real person will follow up
   with you.") is long. Still far above their over-refusal bads (11-17), so ordering is right.
3. **Rubric vs production tension:** the production decline sentence itself ends "Is there something about that I can help with?", which
   `no_reflexive_question` marks down (3-4/5; correct declines scored 69-83). An optimizer could learn to drop that redirect question.
   Decide whether the spec's decline sentence or rule 3 wins before optimizing.
4. Labels are still the project's verdicts + my synthetic counterparts (roughly half of the replies in held-out #2 are synthetic-written).
The lab server on :8765 was restarted with the new judge (host process, not the Docker backend, so the force-recreate rule does not apply).
Isolation: no files changed under backend/ or frontend/ (find -newer check).

## Phase L4 — no_reflexive_question refinement + FIRST REAL DSPy OPTIMIZATION RUN (2026-09-19). No commit; NOTHING exported to backend/.

### A. Judge fix: `no_reflexive_question` (decision: production decline sentence stays exactly as-is)
Reworded (lab/rubric.py): a question is FINE when it is (a) the one thing needed to resolve what the customer left open, (b) one "how can I help?" to a bare greeting,
or (c) the redirect after a polite decline (the real decline sentence is the positive example); it is reflexive when generic/content-free
("anything else I can help you with?") OR an unprompted re-offer after a complete customer message (thank-you/closing/fully answered question), *even if it sounds specific*.
Iterated ONLY on: a new dev probe set (`lab/dev_set_reflexive.py`: 10 declines x 3 businesses + 4 generic-tail bads), calibration, held-out #1. Held-out #2 was run ONCE at the end.
**v1 wording was rejected**: it said "specific + connected to the moment = fine" and the real production negative example ("You're welcome — would you like me to check available times?") scored 100
(calibration 23/24; "If you need anything else (an appointment, service info, or hours)..." scored 91.6). v2 added the "complete message => any tail is reflexive, however specific" test.
| check (5 samples, default effort) | before | after (v2) |
|---|---|---|
| dev probe: real-shape decline sentences (n=10) | score 85.1, no_reflexive 4.6 (min 4) | **92.6, no_reflexive 5.0** |
| dev probe: generic-tail bads (n=4) | 27.6, no_reflexive 1.05 | 29.4, no_reflexive 1.1 (**still caught**) |
| calibration pairwise / good-bad | 24/24, 97.3 / 40.1 | 24/24, 97.7 / 40.2 (noise 4.8 -> 3.6) |
| calibration real "thank you" reflexive bad ("...check available times?") | 65.5 | **31.7** |
| held-out #1 (dev) pairwise; real decline (America) score | 15/15; 60.1 | 15/15; **97.2**; thanks-verbose bad 63.1 -> **34.7** |
| **held-out #2 (clean, run once)** pairwise | 11/11 | **11/11** |
| held-out #2 real decline sentences (weather/election/poem/movie/cricket) | 79.1 / 76.3 / 94.4 / 69.4 / 82.8 | **94.1 / 100 / 100 / 100 / 100** (no_reflexive 3.2-4.6 -> 5.0) |
| held-out #2 good mean; threshold acc (calibration threshold, not refit) | 79.3; 73% | 90.7; 86% |
Confirmed: the real decline sentence is no longer penalized, generic tails are still caught. Left alone (not a decline, so outside the fix): "Are you a bot?" answered with a trailing
"What can I help you with today?" still scores 67-75. Known judge blind spot seen in the smoke test: "kati choti bhanne?" (frustrated repeat-asker) got 100 for a "which service? [list]" reply -
the rubric has no "acknowledges frustration" criterion, so an optimizer can't be steered there.

### B. Setup for the optimization run
* **Production baseline arm** (`lab/production_prompt.py`): the CURRENT working-tree `intent.py` `_SYSTEM_PROMPT_TEMPLATE` (5,961 words; the working tree has earlier phases' uncommitted edits) read with `ast`
  (read-only, nothing from backend/ imported/executed), formatted per sandbox business, plus a user prompt laid out like `_build_user_prompt`; JSON `response` parsed like production. NOT replicated:
  the orchestrator's deterministic templates/overrides (booking confirmations, contact gate, static off_topic decline, handoff addenda), language lock, real knowledge retrieval, tools. So this measures the LLM's free-text reply only.
* **Optimizer start point** (`RULES_INSTRUCTION`, 1,777 words): production reply-style rules 0-6, 13, 16, 17 verbatim + rule 7 condensed by me (booking/JSON-extraction rules dropped). **Harness bug found afterwards:** I replaced
  `{business_name}` with "this business" (a static DSPy instruction has no per-item name), which changed rule 0's decline example - see results.
* **Seed set** (`lab/seed_set.py`): 39 train + 13 val items, dental/salon/trek (dental 20, salon 16, trek 16). Provenance: 15 real customer messages (backend eval cases, live transcripts incl. the pricing-fix
  "Root Canal cost and how long", contact-gate slot question, typo/toothache cases), 16 adapted from real patterns, 21 written by me (real transcripts only cover dental). 4 REAL recorded good replies attached as `gold`
  but NOT used as demos (MIPRO would show gold-less examples as broken demos; `max_labeled_demos=0`). Riverside Dental (held-out business) is absent. Import-time assertion: no seed customer message equals any held-out message.
  Honest limit: categories (greeting/hours/price/thanks/scope) exist in both seed and held-out sets by design - they are the failure classes - only messages and one business differ.
* **Optimizer: MIPROv2 (light)**, not BootstrapFewShot. Why: the failure modes are instruction-level style rules (length/tail/scope) and BootstrapFewShot can only add demos, never change instructions; the metric is a
  continuous judge score (BootstrapFewShot's pass/fail demo filter is crude - I still set `metric_threshold=0.9` for MIPRO's bootstrapped demos); and MIPRO always keeps the ORIGINAL instruction as candidate 0, so it can honestly
  return "no better instruction". Metric = calibrated judge, default effort, 3 samples (effort pinned). Risk acknowledged: small trainset -> overfit; hence a separate val split + held-out sets.
* Friction: MIPROv2 needs `optuna` (missing in the venv; discovered only after ~7 min of bootstrapping - lost run; installed in lab venv, listed in lab `requirements.txt`, never in backend); the first eval run died on Azure 429 (the 10k-token production prompt
  eats tokens/min) and lost its results - `scripts/eval_arms.py` now checkpoints every reply (resumable), backs off on 429, 3 workers.

### C. Result of the MIPROv2 run (`results/optimize_20260919_191615/`, 17.7 min, 11 trials)
* All 2 model-proposed instructions scored LOWER than the original (85-89 vs ~93 on val). The "best" trial (97.8 on val = original instruction + few-shot set 4) was noise: the same configuration re-scored 92.2 later and 90.7 in the final check
  (val n=13; identical program scored 92.8/93.8/92.95 in three baseline evals; trial scores ranged 85-98). **The optimized program = the UNCHANGED production-rules instruction + 2 self-generated demos** ("esewa le tirna milcha?" -> "Cha, eSewa le tirna milcha. Cash pani chalcha."; "huss" -> "Thik cha.").
  Val 92.8 -> 90.7 (not a held-out number, and slightly down).

### D. Held-out before/after (`scripts/eval_arms.py`, results/eval_arms_20260919_201247.json; same 25 inputs for every arm, 3 generations each, default effort, judge x5; run ONCE)
| arm | held-out #2 (clean, 11) | held-out #1 (dev, 14) | all 25 | mean words | ends in "?" |
|---|---|---|---|---|---|
| minimal DSPy baseline (L1) | 49.6 | 48.3 | 48.9 | 82 | 39% |
| **production prompt (current intent.py)** | **91.8** | **88.5** | **89.9** | 20 | 56% |
| production rules as DSPy instruction (optimizer start) | 95.4 | 89.5 | 92.1 | 22 | 60% |
| **optimized (rules + 2 demos)** | **96.9** | **95.3** | **96.0** | 18 | 59% |
Paired vs production (per-item means, bootstrap 95% CI over items): optimized **+5.1 on clean #2 [-0.0, +13.0]**, +6.8 on #1 [-0.2, +17.0], **+6.1 on all 25 [+0.9, +12.5]**; items better/worse by >5 pts: 5 / 1 of 25.
Optimized vs its own start (rules): +1.5 on #2 [-1.3, +4.0] (no evidence), +3.9 all [+0.3, +7.9]. Rules vs production: +2.2 [-3.0, +7.8] (no evidence - the reply-style subset is about as good as the full prompt here).
Per-reply (75 paired generations): mean +6.1 but **median 0.0**; optimized better by >5 in 22, worse in 7, 46 ties; replies scoring <60: production 8, optimized 2.
**Where the gain comes from** (read the replies): a handful of items where production sometimes misbehaves - closing "thanks!" (production tacked on "If you'd like to book the Everest Base Camp Trek..." in 3/3 generations: 35 vs 100, even though rule 3 forbids it -
i.e. rule text alone did not stop it, the demo did), "10:30am works for me" (production: "checking availability..."; optimized asks the one missing thing, the name), "Huncha", trek deposit. Criterion means: length_fit 4.73 -> 4.92, no_reflexive 4.78 -> 4.88, focused 4.75 -> 4.90.
**Costs / regressions the judge cannot see:**
1. **Protected decline wording drifted.** Exact production decline (business name + closing question) on the 6 off-topic items x 3 gens: production 17/18, rules 3/18, **optimized 0/18** (14/18 say "this clinic"/"this business").
   Mostly my harness bug ({business_name} -> "this business" in the start instruction), not necessarily the optimizer - but it means the optimized arm as built would violate your keep-the-decline-as-is decision. Judge still scored them 94-100 (it doesn't check wording).
2. "yes" after a confirmation prompt (`h1:confirmation-ignored`): optimized replies dumped payment/cancellation policy + a reminder offer (57-73) - production said "Great!" (42-68); both weak, neither is a fix.
3. Replies promise callbacks ("clinic manager to call you back") - same as production.
Caveats: judge is near ceiling (all real arms >88) and noisy (~4-5 pts/reply); production arm lacks the orchestrator, so per-item production scores like 35-57 may not occur in the real system (templates handle bookings; but the closing tail is pure LLM text); labels/eval inputs partly synthetic; 3 gens/item.

**Verdict, stated plainly: NOT a clear improvement, and not export-ready.** The optimizer found no better instruction; the ~+6 point gain (borderline CI, zero median) is attributable to two short few-shot demos that teach brevity on closings, it is
concentrated in a few items, it sits at the judge's ceiling, and the built arm drifts from the protected decline sentence. Useful findings regardless: (1) production's rule-3 text alone did not stop "thanks!" from getting a booking pitch - demos did; (2) the reply-style rules subset performs like the whole prompt.
**Nothing exported.** Suggested next steps for your review (none done): fix the instruction so the decline uses the exact business name from `business_facts`, add a decline-wording adherence check to the eval, re-run optimization + eval once (held-out #2 would then have been evaluated twice - disclose),
and, if the demo effect holds, propose the smallest production change (e.g. 1-2 closing few-shots) as a reviewed diff.
Isolation: `find backend frontend -newer .venv/pyvenv.cfg` -> nothing; no secrets in lab files; `intent.py` was only READ (its git diff vs HEAD is earlier phases' uncommitted work). Lab server on :8765 restarted with the refined judge.
New files: `lab/{items,eval_items,seed_set,programs,production_prompt,dev_set_reflexive}.py`, `scripts/{optimize,eval_arms,compare_runs,show_reflexive}.py`; edited `lab/{rubric,businesses}.py`.

## Phase L5 — harness fix, decline-wording fidelity check, optimization re-run, narrow "thanks" fix proposal (2026-09-19). No commit; intent.py NOT touched.

### 1. Harness bug fixed
The start instruction had `{business_name}` replaced by the literal "this business". Now `business_name` is a real per-item INPUT of the DSPy signature (`lab/programs.py`), and the instruction says
"wherever the rules say <business_name>, write the exact value of `business_name` ... never 'this business'/'the clinic'" (`lab/production_prompt.py`). Result: **0/18 replies say "this clinic/business"** in every arm (was 5/18 rules, 16/18 optimized).

### 2. Mechanical decline-wording fidelity (`lab/fidelity.py`, self-check via `python -m lab.fidelity`)
The expected sentence is read LIVE from intent.py rule 0 ("I'm just here to help with things related to {business_name} — appointments, services, hours, and the like. Is there something about that I can help with?") and each reply on the
6 clear off-topic items (x3 gens = 18) is string-compared: exact / typography-only (dash spacing) / drift / no decline; plus over-refusals (a decline on any of the 57 in-scope replies).
| arm | exact | typography | drift | no decline | says "this clinic/business" | over-refusals |
|---|---|---|---|---|---|---|
| minimal baseline | 0/18 | 0 | 0 | 18/18 (answers the off-topic question) | 0 | 0/57 |
| production (current intent.py) | 16/18 | 1 | 1 | 0 | 0 | 0/57 |
| rules (optimizer start) - run 1 (bugged) -> **run 2** | 3/18 -> **15/18** | 0 | 14 -> **3** | 1 -> 0 | 5 -> **0** | 0/57 |
| optimized - run 1 (bugged) -> **run 2** | 0/18 -> **11/18** | 0 | 17 -> **7** | 1 -> 0 | 16 -> **0** | 0/57 |
Run-2 optimized drift (7/18), read line by line: 2 dropped the closing redirect question entirely ("...hours, and the like."), 3 reworded it ("Can I help with any of those?"), 2 only adapted the service list for the trek business
("bookings, trips" - production did this once too). So the "colder decline" risk is real but small: a decline with NO redirect in 2/18; the judge scored all of these 97-100, i.e. it cannot see this.

### 3. Optimization re-run (once, bug fixed) - ⚠ held-out #2 has now been evaluated TWICE
Run 1 (bugged harness) and run 2 (fixed) both scored the same 25 held-out inputs. **Run 2's numbers are the ones that matter; they are not averaged with run 1.** Note the `production` and `minimal` arms were NOT regenerated in run 2 (nothing about
them changed): their 150 replies are the same ones as run 1, so production's numbers are one 3-generation sample per item, not two independent samples.
* MIPROv2 (light, same seed set/split/config, `results/optimize_20260919_202621/`, 16.6 min): 11 trials; **again the original instruction + the same two self-generated demos** ("esewa le tirna milcha?" -> "Ho, eSewa le tirna milcha. Cash pani chalcha."; "huss" -> "Thik cha."); the 2 proposed instructions scored lower (79-90).
* **Best-trial stability check (the run-1 lesson):** the winning config scored 98.5 (trial 7), 97.8 (an independent repeat, trial 11), then 98.1 / 97.0 / 97.1 in three final re-scores (mean 97.4, sd 0.5). The START program: 95.4, 95.8 (two baseline evals) and 92.5 / 95.2 / 96.7 re-scores (mean of the 3 = 94.8, sd 1.7).
  So unlike run 1 (97.8 -> 92.2 -> 90.7) this val gain (~+2.6) is stable across 5 scorings - but val (n=13) is what MIPRO selected on, so it is NOT evidence of a held-out gain.
* **Held-out, run 2** (`results/eval_arms_20260919_210244.json`; 25 inputs x 3 gens, default effort, judge x5):
| arm | #2 clean | #1 dev | all 25 | mean words |
|---|---|---|---|---|
| minimal | 49.6 | 48.3 | 48.9 | 82 |
| **production** | **91.8** | **88.5** | **89.9** | 20 |
| rules (start) | 94.3 | 90.1 | 92.0 | 22 |
| **optimized** | **95.4** | **93.6** | **94.4** | 20 |
Paired vs production (per-item means, bootstrap 95% CI over items): optimized **+3.6 on #2 [-2.2, +12.3]**, +5.2 on #1 [-2.5, +15.8], **+4.5 on all 25 [-0.8, +11.2] - the interval now includes zero** (run 1 showed +6.1 [+0.9, +12.5]; that did not replicate as significant).
Optimized vs its own start: +2.5 [-0.6, +6.1]. Rules vs production: +2.0 [-3.3, +8.6].
Per-reply (75 paired generations): optimized mean +4.5, **median +0.0**; better by >5 in 18, worse by >5 in 14, 43 ties; replies scoring <60: optimized 1 vs production 8.
Gains concentrate in a few items (closing "thanks!" 36 -> 100, "10:30am works" 57 -> 100, "Huncha" 76 -> 99); one loss (trek deposit 89 -> 79). Criterion means: no_reflexive 4.78 -> 4.84, length_fit 4.73 -> 4.89, helpful 4.67 -> 4.93.
**Verdict (run 2): not a clear improvement.** No better instruction was found, the held-out gain is +4.5 with an interval that includes zero and a zero median, and the demos cost decline fidelity (11/18 exact vs production 16/18; 2/18 with the redirect dropped).
It still isn't a reason to export the optimized program; it IS a reason to look at the specific closing behavior below.

### 4. The narrow "thanks -> no unsolicited upsell" fix (proposal only - `results/thanks_fix_PROPOSAL.diff`, intent.py NOT modified)
**Finding:** the real violation reproduces in this harness (English exchange "how long is the Everest Base Camp trek?" / "14 days." -> "thanks!"): the current template tacks on "If you'd like to book the Everest Base Camp Trek..." **5/6** times on that exact case.
A likely contributing cause: the prompt's own few-shot example for "thanks!" (intent.py ~line 306) ends "Dhanyabad! Aru kehi sahayog chahiyo bhane bhanuhos." - a generic "tell me if you need more help" tail, i.e. the prompt demonstrates what rule 3 forbids. (The project's own spec §26 already states the target: "thank you" -> "You're welcome 😊", not "anything else I can help with".)
Tested as in-memory edits of the extracted template (`lab/thanks_patch.py`, `scripts/thanks_experiment.py`; ckpt `results/thanks_experiment_ckpt.jsonl`), judge x3, mechanical tail regex:
| variant | English closings: replies with a tail (6 scenarios x 6 gens) | the exact failing case | judge mean | Romanized-Nepali closings (10 x 4) |
|---|---|---|---|---|
| current template | **9/36** | 5/6 | 83.7 | 0/40 |
| A: fix only the contradictory example | 7/36 | 2/6 | 87.8 | 1/40 |
| B: A + rule-3 sentence | 0/36 | 0/6 | 100 | 0/40 |
| **C: rule-3 sentence ONLY** | **0/36** | **0/6** | **100** | 0/40 |
Fisher exact: 9/36 vs 0/36 p=0.002; 5/6 vs 0/6 p=0.015. **The rule-3 sentence alone (C) is sufficient; the example edit alone (A) is not** -> proposal = C, a single hunk, nothing else.
Regression check (45 non-closing seed items x 1 gen; 1 item, `s-price`, was rejected by Azure's content filter and excluded from both arms): current 90.1 vs C 90.9, paired diff **+0.8 [-2.0, +3.8], median 0** (B: +1.1 [-2.5, +4.7]) - no measurable effect on unrelated replies.
Caveats: prompt-only harness (no orchestrator/templates); only 6 English scenarios; the regex counts any "?" as a tail; my first closing set (10 Romanized-Nepali scenarios) had no headroom - it never reproduced the violation - which is why the English set exists; not tested against the real backend
(after any approved edit: pytest + `docker compose up -d --force-recreate backend` + a live "thanks!" check, per CLAUDE.md). Not proposed, optional, separate: the line-306 example inconsistency (C works without it).
Isolation: `find backend frontend -newer .venv/pyvenv.cfg` -> nothing; `intent.py` mtime unchanged (2026-09-17); no secrets in lab files.
New/changed: `lab/{fidelity,thanks_patch}.py`; edited `lab/{production_prompt,programs}.py` (`business_name` input; `template=` what-if param); `scripts/{eval_arms,optimize,thanks_experiment}.py`.

## Phase L6 — the approved "thanks" fix is now APPLIED to the backend (2026-09-19). Not committed.
The single-hunk `results/thanks_fix_PROPOSAL.diff` was applied to `backend/app/services/conversation/intent.py` (line-306 example left untouched, per your instruction; optional separate future cleanup).
Verification: full backend suite **525 passed / 10 skipped / 0 failed** (= baseline); `docker compose up -d --force-recreate backend` + loaded-module check; **live check on the real backend: closings with an unsolicited tail 2/30 before -> 0/30 after**
(script `scripts/live_thanks_check.py`, results/live_thanks_{before,before2,after}.json). The live baseline rate (~7%) is much lower than the harness's (25%+), so the live sample alone is not statistically significant (Fisher p = 0.49);
the lab evidence in Phase L5 section 4 (p = 0.002) carries the significance. Full write-up: PHASE_STATUS.md, "Phase 12 (2026-09-19 series)".
Also learned: the lab's production-prompt arm over-states how often this violation occurs in the real system (it lacks the orchestrator's added context) - treat harness rates as an upper bound, not a live prediction.

### Not done / next
* (L1 note; held-out set now exists - see L2.) No DSPy optimization run (per instructions). Needs: add a scope criterion + fresh held-out cases, then a `dspy.MIPROv2`/`BootstrapFewShot`
  run over `lab/receptionist.py` scored by this judge (>=5 samples).
* Nothing committed. Files added: conversation-lab/ only (+ a pointer line in PHASE_STATUS.md).

## Phase L7 — hybrid per-message language matching vs the production language lock (2026-09-20). Lab only; NO production change; NOT committed.

### Verdict (read this first)
Honest summary: **the hybrid clearly wins on ONE thing (following a real language change immediately), ties production on stability, and is NOT
shown better at within-message code-mixing (and is worse on one such message: "ekdum ramro, thanks!", section 3a). It also has costs and untested areas (below). It is not a clear across-the-board win, so I am not
proposing a production change; I am proposing you review the evidence, and I list two much smaller production fixes I found on the way (untested).**
Combined dev+held-out, 3 reps per conversation, real Azure gpt-5-mini, reply generation at the deployment's default effort:

| measure (95% Wilson CI) | pre-Phase-25 (original) | **production lock (current)** | **hybrid v3** | hybrid, tiebreak removed (ablation) |
|---|---|---|---|---|
| **flip-flop**: neutral turn ("ok", "2", "Friday", "thanks"...) whose reply language differs from the previous reply | 40/223 (18%) [13-24] | **4/223 (2%) [1-5]** | **2/225 (1%) [0-3]** | 60/227 (26%) [21-33] |
| **real change, NO explicit request** (en->Roman, Roman->Devanagari, Devanagari->en, Roman->en...): reply follows AT the switch turn | 15/18 [61-94] | **0/18 [0-18]** | **18/18 [82-100]** | 18/18 [82-100] |
| explicit request ("English please", "talk in Nepali") honored at once | 6/9 (script choice, see B5) | 9/9 | 9/9 | 9/9 |
| replies right on turns with real language signal (A+B+C+D: signal/switch/mix/explicit) | 235/291 (81%) | 229/291 (79%) | **276/286 (97%)** | 284/297 (96%) |
Held-out alone (frozen before it ran; the honest number): flips prod 2/76, hybrid 1/78; implicit switch prod 0/6, hybrid 6/6; signal-turn match prod 70/90, hybrid 80/85.
Dev alone is optimistic for the hybrid (I iterated on it): 1/147 flips, 12/12, 196/201.

**Flip-flop risk, stated plainly:** it did NOT resurface on neutral turns at a rate above production's (2/225 vs 4/223; CIs overlap fully) - but it is not zero
and it is not free:
1. Without a guard, the model ignores the "keep the conversation's language" instruction on ~3% of short turns (7 of 228 short turns needed the
   verify-and-retry redraft: 3/144 dev, 4/84 held-out). The 2 flips that remain (see below) both survived that guard.
2. The tiebreak is what buys the stability. With it removed (same prompt otherwise) neutral turns flip 60/227 = 26% - the original bug at full strength, on the modern
   prompt too. So the stability is NOT "randomness dressed up as flexibility", and it is NOT the per-message design by itself; it is the tiebreak + retry.
3. A customer who genuinely alternates languages message to message (B7) gets alternating replies (that is mirroring by design, but to the customer it
   looks like flipping). Production would stay in one language for that customer. Whether that is better or worse is a product decision, not a metric.
4. Short messages (<=2 Latin words) can never change the language on their own (P1: "kati parcha?" in an English chat -> English reply, prod and hybrid alike;
   a 3-word Nepali message right after switches the hybrid immediately, prod stays English).
5. The 2 counted hybrid flips, inspected: (a) held-out HC1: "Yo" in a Roman-Nepali chat -> "Namaste!" (my labeler calls a bare "Namaste!" English; arguably consistent);
   (b) dev D3: a Devanagari reply that lists English service names was labelled "mixed" then the next reply "ne_deva". Both are labeler-boundary cases, but I counted them.

**What production's lock actually does wrong (new evidence, independent of the hybrid):**
* Its sustained-switch path is effectively dead for en<->Roman. Real traced run (B6, `prod`, rep 0): customer types 3 plain-English messages after Roman Nepali; lock state:
  `streak 1 -> 2 -> (LLM self-reports message_language='ne_roman' for "Can I book for next Tuesday afternoon?") -> streak reset to 0`. The model anchors to the lock it was just
  told about (Phase 25's documented "known limitation"), so the 3-message streak never completes. Result: 0/18 implicit switches followed, ever, even 2 turns later.
  Held-out example (HB2, prod): customer asks in full English "What are your office hours during the week?" -> "Hamro office Monday dekhi Friday samma 10:00 AM bata 6:00 PM samma khula huncha."
* Turn 1 is unprotected: nothing is locked yet, so a Roman-Nepali opener ("Namaste, tapaiko teeth cleaning ko lagi kati parcha?") got a **Devanagari** reply in 2/3 prod runs (and 3 turns
  in a row for pre25's D1). Prod's 4 "flips" are exactly these turn-1 script errors being corrected at turn 2, not language flip-flop.
* Where the hybrid gets this right: a deterministic per-message script note (Devanagari present -> reply Devanagari; Latin only -> reply Latin letters unless Devanagari is asked for).
  This is a few lines of Python, needs no lock, and could be added to production separately.

### 1. What was built (all in conversation-lab/; backend/ and frontend/ untouched)
* `lab/lang_mech.py` - four arms, one function `step(arm, state, history, customer, biz, lm)`:
  * `pre25` - the ORIGINAL pre-Phase-25 prompt read from git (`2456440:.../intent.py`, rule 7 = "match the customer", no lock). = reconstruction of the flip-flop.
  * `prod` - current production: the real `_SYSTEM_PROMPT_TEMPLATE` + the lock line injected into the user prompt + the REAL `_resolve_message_language` /
    `_resolve_locked_language` and the real word list, streak threshold (3) and Phase 25b explicit-switch path, **extracted from orchestrator.py with `ast` and executed** (nothing re-implemented; asserts in `python -m lab.lang_mech`).
  * `hybrid` (v3, frozen; copy in `results/lang/lang_mech_FROZEN_v3.py.txt`, sha1 in `frozen_hashes.txt`) - rule 7 rewritten (match THIS message; mix back a mix; follow a clear change at once; explicit requests
    honored and kept), the 4 lock few-shots replaced by 4 per-message ones, JSON gets `reply_language`. **No lock, no streak.** The only carried state is `strong_language`: the language of the last reply
    to a *substantive* message or explicit request (never a reply to a short turn, so one bad reply cannot poison it). Three deterministic helpers: (i) `is_short` = no Devanagari and <=2 Latin words;
    (ii) on short turns the model is told the conversation's language as a directive (only exception: the message explicitly asks to change language) and, if it still answers in another language family,
    redrafted once (the model reports what it wrote); (iii) on non-short turns a per-message script note. The word list is NOT used.
  * `hybrid_nt` - ablation: same as hybrid minus (ii) (no tiebreak line, no tiebreak rule sentence, no retry).
* `lab/lang_scenarios.py` - 19 DEV + 10 HELD-OUT + 3 PROBE scripted conversations (fictional dental/salon/trek businesses, fake names/phones), each turn with an expectation and a kind
  (signal / neutral / switch / explicit / mix) written BEFORE any run. Real material used: "What app ma vaya hunxa", "K xa", "malai euta tooth dukheko xa", the long real Roman-Nepali message,
  "hlo", "thanks!" after Roman Nepali, "Can we just switch to English please?", "Can we talk in Nepali from now on?" (PHASE_STATUS.md Phases 25/25b and the 2026-09-19 conversation-quality audit).
* `scripts/lang_run.py` (runs arms x scenarios x reps, labels every reply with an independent low-effort LLM labeler, 3 votes; Devanagari-bearing replies are labelled by a deterministic rule), `lang_report.py`
  (tables/transcripts), `lang_judge_check.py`, `lang_judge_run.py`, `lang_judge_report.py`. Outputs in `results/lang/`; human-readable transcripts in **`results/lang/TRANSCRIPTS.md`** (63 conversations).
* Metric definitions (fixed before results): *match* = reply label in the turn's accepted set; *flip-flop* = on a neutral turn the reply family (en / Roman-or-mixed / Devanagari) differs from the previous reply's;
  *switch latency* = turns until the reply is right after the first switch/explicit turn.

### 2. Iteration history and overfitting control (disclosed)
* Hybrid **v1** (soft "keep the previous language if the words don't clearly show one") failed in the first smoke test: a Devanagari chat, customer "thanks" -> "You're welcome!", and that reply then poisoned the carried state ("2" also English).
* **v2** (directive tiebreak; state updated only by substantive turns) on the dev set: 322/346 matches, 3/145 flips. Failures inspected one by one: Roman-Nepali openers answered in Devanagari (C1, D1), "Can we talk in Nepali?" answered in
  Devanagari (B5), a Devanagari+English message answered in Latin (A4), 2 tiebreak ignores. My labeler also mislabelled Devanagari replies containing English service names as "mixed" (fixed, applied to ALL arms).
* **v3** = v2 + per-message script note + verify-and-retry. Dev: 346/351, 1/147. **Frozen** (hashes recorded), then the held-out set (written before any hybrid run) was run once. Held-out came out consistent with dev (table above).
* One held-out scenario (HB3) was replaced (id HB3b): its "facials / how much?" prompt was rejected by Azure's content filter for EVERY arm (false positive, `violence: high`; a real risk for any business with a "Facial" service).
  No arm produced data for it, so nothing was tuned; topic changed to haircuts. Other content-filter/rate-limit failures left 1-2 of 30 conversation-runs missing per arm (28/28/28/29 held-out, 57 dev each). Counts are in the tables' `runs` column.
* The judge's language check (section 4) and the flip/latency/match metrics were fixed before the runs; the metric for "flip" was not changed afterwards.

### 3. Evidence for the four scenario types (numbers = combined turn-level match; transcripts in results/lang/TRANSCRIPTS.md)
**(a) Within-message code-switching (mirroring)** - A1-A4, HA1-HA2 (real code-mix lines). match: pre25 47/60, prod 48/60, hybrid 52/60. **No clear win** (differences inside noise). Both arms answer
"hello, malai teeth whitening garna man cha, price kati hola?" in natural Roman Nepali with English nouns ("Teeth Whitening ko price NPR 6000 ho, ra karib 45 minute lagcha"). The consistent miss, in every arm: an English-frame message with a Nepali
clause ("Hi, I'm interested in Poon Hill, kati din ko hunchha?") gets a mostly-Roman-Nepali reply (hybrid 3/3, prod 3/3, hybrid_nt 3/3; pre25 3/3 Nepali too, 1 of them in Devanagari) rather than an English-frame mix - my expectation for those may be too strict, but the proportion-mirroring is not
precise anywhere. **A regression against both baselines:** "ekdum ramro, thanks!" (a Nepali phrase + English "thanks", 3 words so not "short") -> hybrid answered in English 2/3 ("Welcome!", "You're welcome! 😊") and mixed 1/3, while prod AND pre25 answered in Roman Nepali 3/3 ("Swaagat cha! 😊"). The per-message design reads the English word and follows it; production's lock/older prompt happened to keep the Nepali. Devanagari+Latin message (A4): hybrid 9/9 Devanagari-with-English-words.
**(b) Deliberate mid-conversation change** - the clear win. en->Roman (B1), Roman->Devanagari (B2), Devanagari->en (B3), Roman->en without asking (B6, HB2), en->Devanagari (HB1): hybrid follows at the switch turn every time (18/18); prod never does (0/18).
B1 prod: after "malai bholi bihana 10 baje ko slot chahiyo, milcha?" -> "We're closed on Sundays, so we don't have any slots tomorrow..." (English, and stays English for 3 more turns);
B1 hybrid: "Bholi Sunday ho ra clinic bandha huncha, tesaile 10 baje mildaina. Ke Monday (2026-09-21) 10:00 baje milcha?" then "Cha - clinic ma on-site parking cha." then "ok" -> "Thik cha." Explicit requests (B4, B5, HB3b, P2): all honored at once by prod and hybrid.
B5 note: pre25 answered "Can we talk in Nepali from now on?" in Devanagari to a customer typing Latin (counted as a miss; it is a script-choice miss, NOT the false-handoff bug Phase 25b fixed - that bug did not reproduce on gpt-5-mini here: 0 of the 9 pre25 explicit-request replies (B4, B5, HB3b x3 reps) was handoff-like by a regex for team member/connect/human/staff, and all 9 honored the request).
B7 (alternating customer, stress): hybrid mirrors 14/15; prod holds one language (9/15 by the mirroring standard). See flip-flop point 3.
**(c) The original ambiguous-short-input flip-flop** - reconstructed with the real pre-25 prompt: 19/78 neutral turns flipped in type C and 6/39 in type D (dev), 8/51 and 3/13 (held-out); every scenario type showed it (e.g. C2 rep 1:
Devanagari chat, then "Friday" -> "Do you mean Friday, 2026-09-25 for a Teeth Cleaning?..." in English, "3pm" -> Devanagari, "thanks" -> "You're welcome - if you'd like to proceed..." in English, "2" -> Devanagari). Not regressed: hybrid 0/78 (dev C),
1/57 (held C: the "Yo"->"Namaste!" case), prod 2/78 and 2/51 (turn-1 script errors), hybrid without the tiebreak 25/78 and 11/51. Real openers: "hlo" -> "K xa" -> "malai euta tooth dukheko xa" -> "ok"/"2"/"thanks" stay Roman in prod 18/18 and hybrid 18/18 (pre25 11/18, 4/9 flips).
**(d) Long conversation, no real language change** - D1 (13 turns Roman), D2 (12 English), D3 (8 Devanagari), HD1, HD2: hybrid dev 98/99, held 30/30, identical reply-family sequence across all 3 reps in D1/D2 and HD1; prod 98/99 and 40/40. The ablation (no tiebreak) breaks it
(15/39 flips dev, 2/17 held), the original prompt breaks it (6/39, 3/13). So the stability comes from the mechanism, and production has it too. Not shown: any advantage of the hybrid here.

### 4. The judge (unchanged rubric) - what it can and cannot tell us
* Re-validated on 8 synthetic good/bad pairs for the new situations (`results/lang/judge_check_v1.txt`, x5 default effort): **7/8 pass** on language_match (switch en->Roman, Roman->en, Roman->Devanagari, neutral "ok" after Devanagari, within-message mix vs English,
  vs over-formal Devanagari, explicit request). **FAIL: neutral "thanks" after Roman Nepali** - it scored the English "You're welcome!" 5.0 and the Roman "Hunxa!" 2.0, because the customer's word literally is English and the rubric has no
  "very short/neutral turns keep the conversation's language" anchor. So the judge is blind to exactly the flip-flop case. I did NOT change the rubric mid-experiment; instead language_match is only trusted on turns with real signal, and neutral turns use the flip metric.
* Judge x3 low effort, prod vs hybrid on the same 338 cells (reps 0-1, dev+held): judge total **hybrid 94.2 vs prod 90.7**; paired diff **+3.78 [+0.70, +7.38]** (cluster bootstrap over scenarios); language_match on signal turns **4.94 vs 4.59**, paired **+0.38 [+0.14, +0.66]**;
  by type (total): A prod 97.4 / hybrid 94.5, B 84.0 / 97.0, C 90.4 / 92.8, D 95.8 / 92.7. Controls (rep 0): pre25 80.8 (older prompt, other criteria not comparable), hybrid_nt 94.4 - i.e. **the judge cannot see the 26% flip rate of hybrid_nt at all**.
* Side-observation, unresolved: the hybrid scores LOWER than prod in A (-2.9) and D (-3.1) on non-language criteria (mostly `no_reflexive_question`: e.g. bare "ok" -> "Okay - let me know if you'd like to book a time.", prod: "Okay - glad to help.");
  higher in B and C. Could be judge noise (single-cell noise is ~5) or a side effect of my prompt edit (I replaced the 4 lock examples and rule 7). Not investigated; it must be checked before any production port.

### 5. Limits of this evidence
* Prompt-only harness (same as earlier lab phases): NOT run - the orchestrator's deterministic templates (which render in the locked language; a production hybrid would render them from the reply language), booking tools, retrieval, conversation summaries. Production's own lock is
  therefore only partly reproduced (its deterministic sentences are the part of the lock that works by construction).
* Scripted, non-reactive customers; one model (gpt-5-mini); 3 reps per conversation; 3 fictional businesses; an LLM labeler (with a deterministic Devanagari rule) decides reply languages; the "accepted set" expectations for A2/HA2 (English frame + Nepali clause) and B5 (Roman rather than Devanagari) are my judgment calls.
* Dev numbers are optimistic (iterated); held-out is 10 conversations / 62 turns / ~28 runs per arm - CIs are wide (see Wilson intervals).
* The lab's prod arm was run on a business-facts-only prompt; the live system adds summaries and more context. Harness rates are best read as upper bounds on how often a failure occurs live (a caveat already established in L5).

### 6. If you decide to pursue this - not done, not proposed as-is
Cheaper things to consider first (untested, from the findings above): (1) a per-message deterministic script note in production (fixes the turn-1 Devanagari reply, needs no lock change); (2) stop telling the model the lock when it reports `message_language`
(or drop the anchored self-report) so the 3-message streak can actually complete. A full hybrid port would also need: reply-language-aware deterministic templates, persisting `strong_language`, the retry guard, the 3 open questions in sections 3-4 (alternating customers, non-language criteria dip, short distinctive messages),
a production-shaped end-to-end test with the real orchestrator, `pytest`, and (per CLAUDE.md) `docker compose up -d --force-recreate backend` before any live check. Nothing under backend/ was edited.

### 7. Isolation / secrets (real output)
`git status --short backend frontend` -> empty; `git diff --stat -- backend frontend` -> empty (the earlier `find -newer .venv/pyvenv.cfg` heuristic is now noisy: it lists files changed by the already-committed production phases 13/14 - mtimes 2026-09-19 23:41 and earlier, before this session).
`git status`: only untracked lab files (+ `.claude/settings.local.json`, modified before this session). Backend read-only use: `orchestrator.py`, `response_templates.py`, `schemas/conversation.py`, `intent.py` (via `ast`), and `git show 2456440:.../intent.py`; nothing imported as a package and nothing executed from backend/ beyond the `ast`-extracted pure functions.
Secrets: scan of all of conversation-lab (excl .venv) for the API key value and the endpoint host, CASE-INSENSITIVE: the host was found in two failure logs (litellm tracebacks; my first, case-sensitive scan missed it because .env spells it `Samrat-G01`) - scrubbed to `<azure-host>`, re-scan -> NONE. No customer PII (scenario names/phones are fake; real-transcript lines used contain none).
The backend container was not touched, so the force-recreate rule did not apply. Nothing committed.

### Reproduce
`python -m lab.lang_mech` (self-checks) - `python scripts/lang_run.py --set dev|held|probe --arms pre25,prod,hybrid,hybrid_nt --reps 3 --out results/lang/x.jsonl` - `python scripts/lang_report.py results/lang/*.jsonl` -
`python scripts/lang_judge_run.py ... && python scripts/lang_judge_report.py ...`. Azure rate limits bite above ~4 concurrent workers; the runners retry with backoff.
