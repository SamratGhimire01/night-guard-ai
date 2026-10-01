# Conversation simulator

Plays scripted customers against many kinds of business through the **real** conversation engine and scores
every reply the way a native reader would. Use it to get a real number before and after a change, instead of
guessing.

- **24 businesses** (`businesses.py`): dental, eye, vet and physio clinics, trekking, study abroad, salon, barber,
  restaurant, cafe, organic shop, gym, yoga, hotel, law firm, bike workshop, preschool, tuition, photo studio,
  laptop repair, real estate, driving school, tailor and party palace. Several have no business type and no example
  replies, on purpose. Three don't take bookings in chat. All of the data is made up.
- **30 scenarios** (`scenarios.py`): price, "what is X", two questions at once, comparisons, booking, "don't ask my
  name again", group booking, goodbye, complaint, problem after a service, haggling, "too expensive", "are you a bot?"
  (casual and pressed), small talk, off-topic, flirting, "hmm"/👍, typos, a rambling message, a prompt-injection
  attempt, "talk to staff", cancelling with no booking, an unknown fact, English, Devanagari, mixed, and switching
  language mid-chat.
- **Scoring:**
  - the native lint from `nepali_judge`, which knows the history (repeats, stock endings, the customer's spelling,
    the locked language);
  - scripted checks (`checks.py`): price stated, hours given, never claims to be human, doesn't volunteer "AI", no
    internals leaked, doesn't re-ask a name or phone it already has, short answer to "ok"/"bye", offers a person when
    asked;
  - optionally, the trusted yes/no checklist judge.
- **Headline numbers:** the share of OK replies, and the stricter share of conversations where every reply was OK
  (what the customer actually feels). Results are broken down by situation, business and language, with the worst
  replies and the reason for each.

## Run it (inside the backend container; real LLM, costs money)

```bash
# free judge: lint + scripted checks; each scenario on 3 businesses = 90 conversations
docker exec -e PYTHONPATH=/app night_guard_ai-backend-1 python -m tests.eval.simulator.run \
  --out tests/eval/simulator/results/lint_$(date +%F).json

# with the trusted checklist judge (needs GEMINI_API_KEY in backend/.env)
docker exec -e PYTHONPATH=/app night_guard_ai-backend-1 python -m tests.eval.simulator.run \
  --judges hybrid:gemini/gemini-3.1-flash-lite --out tests/eval/simulator/results/gemini_$(date +%F).json

# before/after for the voice pass: same run with it off, then on
docker exec -e PYTHONPATH=/app -e VOICE_PASS_MODE=off night_guard_ai-backend-1 python -m tests.eval.simulator.run \
  --judges hybrid:gemini/gemini-3.1-flash-lite --out tests/eval/simulator/results/voice_off.json
docker exec -e PYTHONPATH=/app -e VOICE_PASS_MODE=auto night_guard_ai-backend-1 python -m tests.eval.simulator.run \
  --judges hybrid:gemini/gemini-3.1-flash-lite --out tests/eval/simulator/results/voice_auto.json
docker exec -e PYTHONPATH=/app night_guard_ai-backend-1 python -m tests.eval.simulator.run compare \
  tests/eval/simulator/results/voice_off.json tests/eval/simulator/results/voice_auto.json

# where one defect comes from: template vs model text, per intent, with examples
docker exec -e PYTHONPATH=/app night_guard_ai-backend-1 python -m tests.eval.simulator.run analyze \
  tests/eval/simulator/results/voice_auto.json --defect not_template
```

`compare` also pairs the same scenario, business and turn across the two runs, then counts bad → OK and OK → bad
replies and runs a sign test. Per-business percentages built from 5–12 replies swing 8–33 points when a single reply
flips, so only trust a difference the sign test calls real (p < 0.05).

Options:
- `--scenarios identity,complaint` and `--businesses trek,salon`: run only these.
- `--per-scenario 0`: every scenario on every business (720 conversations).
- `--workers 4`: conversations run in parallel.
- `--no-knowledge`: puts the FAQ into the description, so no embedding calls are made.
- `cleanup`: removes leftover SIM businesses.

Each run creates its businesses as `SIM <name>` and deletes them, with everything under them, when it ends, even
after an error. Raw run JSON is git-ignored. Commit the `.md` reports you want to keep.

**Read the numbers honestly:**
- The scripts were written by a non-native author.
- The checklist judge is calibrated against 30 native verdicts (κ 0.86, an optimistic figure).
- A higher score is real progress, but the native blind review is still the final word.
