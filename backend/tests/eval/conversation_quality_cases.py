"""Fixed, version-controlled conversation-quality evaluation set.

Seeded directly from real problems found in the conversation-quality audit
(PHASE_STATUS.md, "Phase 1 — Natural Conversation Engine: Audit + Proposed
Plan") and the real transcripts it pulled from the live database, plus the
spec's own harder categories it explicitly asked to be covered.

Deliberately NOT wired into pytest pass/fail — same treatment Phase 9 gave
its own tone eval: response quality (naturalness, length, "did it end with a
question it didn't need to") is read by a human, not asserted. Re-run this
same set with `run_conversation_quality_eval.py` (real DB, real Azure LLM —
costs real money/time, same reason Phase 6/7/9's real-API tests are never
auto-run) before/after any future conversation-quality change, and compare
the transcript to what's recorded here for each case's real BEFORE.

Each case is a fresh conversation. `turns` is the customer's messages, sent
one at a time in order. `real_before` records what the REAL system actually
said for this exact case before the fixes in this phase — pulled verbatim
from the live conversations DB (see PHASE_STATUS.md) where an exact real
transcript exists, or from this phase's own live before/after verification
scripts otherwise. `check_for` is a short list of red flags a human reviewer
should specifically look for in the new response — not an automated check.
"""

CASES: list[dict] = [
    {
        "id": "greeting-loop-repetition",
        "category": "repetition / dynamic length",
        "turns": ["Yo"],
        "real_before": (
            "Hi! Welcome to Samaj Dental Clinic in New Baneshwor. How can I help you "
            "today — would you like to book an appointment, get directions, or hear "
            "more about a specific service?"
            "  (real transcript 3db7b0b2 — the SAME ~30-word 3-question intro, barely "
            "reworded, sent 6 separate times over 4 days to the same customer's bare "
            "\"Yo\")"
        ),
        "check_for": [
            "should be SHORT for a bare greeting (rule 17)",
            "should not stack a 3-way compound question (rule 3 addition)",
            "wording should vary from a prior run of this same case, not repeat verbatim",
        ],
    },
    {
        "id": "rule-9-readiness-question-violation",
        "category": "booking readiness question (rule 9)",
        "turns": ["Mero daant dukheko cha", "Chahanchu", "Yes chahanchu"],
        "real_before": (
            "Turn 3 (real transcript f3242b3f): agent asked \"Ma tapai ko lagi Dental "
            "Consultation book garidinu?\" (a forbidden yes/no readiness question — "
            "rule 9 already forbade this) then, after the customer said yes, replied "
            "\"Maaf garnuhos, maile thik sanga bujhna chahanchu — kun service, ra kun "
            "miti ra samaya chahanu huncha bhanera batauna sakinu huncha?\" — twice in "
            "a row, never progressing."
        ),
        "check_for": [
            "must never contain a 'should I book that?' / 'shall I go ahead?' style question (rule 9 reinforcement)",
            "must acknowledge and move toward the one missing piece, not restart",
        ],
    },
    {
        "id": "confirmation-ignored-mid-booking-regression",
        "category": "state bug (§2.C) — now-fixed regression case",
        "turns": [
            "Teeth widening, you know, the talcumara.",
            "भोलिको एक गरेको भए हुन्छ",
            "Samrat Ghimire samratghimire01@gmail.com 9823045928",
            "yes",
        ],
        "real_before": (
            "Real transcript 4a0de7b9 AND this phase's own live pre-fix reproduction "
            "(2/2 runs): after the customer confirms with a bare \"yes\", the agent "
            "replies \"Bujhe — kripaya malai kun service batauna sakinu huncha?\" — "
            "asking which service, even though the customer named it (Teeth "
            "Whitening) three turns earlier and the agent's own second turn already "
            "committed to that service by name."
        ),
        "check_for": [
            "must NOT ask 'which service' again once it was named earlier, even on a non-booking-intent turn",
            "the booking should complete on turn 4, or ask only for whatever is genuinely still missing",
            "probabilistic, not guaranteed — the LLM must still confidently name the service on turn 1 for this to fully resolve; a hedge ('do you mean whitening?') on turn 1 is an acceptable, honest response, not a bug",
        ],
    },
    {
        "id": "bare-numeric-slot-selection",
        "category": "§50 — deterministic slot pick, now-fixed regression case",
        "turns": ["I'd like to book a teeth cleaning", "tomorrow", "2"],
        "real_before": (
            "This phase's own live before/after verification script (not a historical "
            "transcript — no real customer happened to reply with a bare digit in the "
            "15-conversation audit sample): forced through the old full-LLM path, a "
            "bare \"2\" took 9523ms and the model itself got confused — \"Sorry, I "
            "didn't catch that — what does \\\"2\\\" refer to? Are you selecting a "
            "service...\". The new deterministic path took 793ms and booked the "
            "correct (second) slot with zero LLM call."
        ),
        "check_for": [
            "must book the SECOND shown slot, not ask for clarification",
            "should be near-instant (no LLM round trip for this turn)",
        ],
    },
    {
        "id": "frustrated-customer-repeated-complaint",
        "category": "frustration handling + no corporate phrasing",
        "turns": ["kati choti bhanne ma same kura? kaile respond garne?"],
        "real_before": None,
        "check_for": [
            "brief, natural acknowledgment — not a repeated stock opener across runs (rule 4)",
            "must not contain scripted phrasing like 'I understand how frustrating that is' or 'I apologize for the inconvenience' (rule 4 corporate-phrasing addition)",
            "should move to being useful quickly, SHORT-to-MEDIUM length",
        ],
    },
    {
        "id": "typo_heavy_booking_request",
        "category": "typo tolerance",
        "turns": ["i want too book my teeth serviceing for tomorow", "docter Sharma vaye hunxa"],
        "real_before": None,
        "check_for": [
            "must not comment on or correct the customer's spelling",
            "should proceed with normal booking clarification",
        ],
    },
    {
        "id": "roman-nepali-common-spellings",
        "category": "language mirroring — Step 3 word-list extension",
        "turns": ["k xa aaja ko lagi slot?", "Bholi 2 baje huncha la, gardim hai"],
        "real_before": (
            "Before Step 3, neither 'xa' nor 'aaja'/'bholi'/'la'/'gardim' were in "
            "_ROMAN_NEPALI_WORDS — a conversation OPENING with either message got zero "
            "deterministic Roman-Nepali signal and could lock to the wrong "
            "script/language if the LLM's own self-report anchored elsewhere."
        ),
        "check_for": [
            "conversation should lock to Roman Nepali from these messages",
            "reply should stay in natural Roman Nepali contractions, not upgrade to formal Devanagari-style phrasing (rule 7 addition)",
        ],
    },
    {
        "id": "changed-mind-mid-booking",
        "category": "changing mind mid-flow",
        "turns": ["book me a teeth cleaning tomorrow at 2pm", "wait, actually 4pm instead"],
        "real_before": None,
        "check_for": [
            "must use the corrected time (4pm), not the original (2pm)",
            "must not re-ask for the service again",
        ],
    },
    {
        "id": "short-context-dependent-reply",
        "category": "short reply resolved from context",
        "turns": ["what times do you have for a cleaning tomorrow?", "2 baje"],
        "real_before": None,
        "check_for": [
            "'2 baje' must be understood as selecting the 2pm option from the just-shown list, not treated as a new, unrelated question",
        ],
    },
    {
        "id": "cancellation-stays-fast",
        "category": "cancellation confirmation-free path — confirmed unchanged by explicit decision",
        "turns": ["book me a teeth cleaning tomorrow at 2pm", "actually cancel it"],
        "real_before": (
            "Real transcripts 32aea5c3 and ecb33d1e: 'cancel it' -> immediate "
            "cancellation, no confirmation step. Explicitly confirmed to stay this way "
            "(audit §2.D decision) — this case exists to catch an ACCIDENTAL "
            "regression toward adding a confirmation gate, not to request one."
        ),
        "check_for": [
            "must cancel immediately, no 'are you sure?' step introduced",
        ],
    },
]
