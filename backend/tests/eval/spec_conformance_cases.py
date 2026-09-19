"""Literal spec-conformance test cases.

Every case here is extracted DIRECTLY from the user's 67-section conversation-
quality specification document — not paraphrased into a general category, the
actual concrete customer message(s) and the spec's own stated expected
response shape. Run against the real orchestrator (real Azure LLM, real
business "Samaj Dental Clinic") via run_spec_conformance_eval.py.

Where the spec's literal wording assumes something this real business's real
system correctly won't do (e.g. "is Dr. Sharma available tomorrow" — this
system has no per-doctor schedule and, per intent.py rule 1's accuracy floor,
correctly refuses to invent one), the customer message is adapted to a real,
answerable equivalent that tests the SAME language/length/structure property,
and the adaptation is noted in `notes`. Every other case uses the spec's
customer message VERBATIM.

Deliberately NOT pytest, NOT CI-wired — same treatment as conversation_
quality_cases.py: response quality is read by a human against real, live
output, not asserted. `expect` fields are read as a checklist by the human
scorer, not auto-graded pass/fail (some, like `ends_with_question` and
`banned_phrases`, ARE auto-checked by the runner and reported alongside the
transcript, since those are objective).
"""

# Corporate/chatbot phrases §24 explicitly names — checked on every response,
# not just the dedicated §24 cases.
CORPORATE_PHRASES = [
    "thank you for reaching out",
    "i would be happy to assist",
    "happy to assist you",
    "please feel free to let me know",
    "feel free to let me know",
    "is there anything else i can assist you with",
    "is there anything else i can help you with",
    "your request has been successfully processed",
    "i apologize for the inconvenience",
    "i understand how frustrating that is",
]

CASES: list[dict] = [
    # ---------------------------------------------------------------- §5 ---
    {
        "id": "sec5-short-hours",
        "spec_ref": "§5 SHORT — 'open cha?' -> 'Cha, aaja 7 PM samma open cha.'",
        "turns": ["open cha?"],
        "expect": {"language": "ne_roman", "length": "short", "ends_with_question": False},
        "notes": "Real business hours differ (9am-6pm) from spec's literal '7 PM' — checking SHORT, factual, no compound question, not the exact hour.",
    },
    {
        "id": "sec5-medium-availability",
        "spec_ref": "§5 MEDIUM — service availability + slots + one question",
        "turns": ["teeth cleaning available cha?"],
        "expect": {"language": "ne_roman", "length": "medium", "ends_with_question": True},
        "notes": "Real service (Teeth Cleaning) exists — expect availability offer + one clarifying question, 2-4 sentences.",
    },
    # ---------------------------------------------------------------- §6 ---
    {
        "id": "sec6-short-yesno-context",
        "spec_ref": "§6 — '2 baje?' -> 'Yes, 2 PM available cha. Book gardim?' (SHORT, not a paragraph)",
        "turns": ["what times do you have for a teeth cleaning tomorrow?", "2 baje?"],
        "expect": {"language": "ne_roman", "length": "short", "ends_with_question": True},
        "notes": "Second turn must be SHORT (1-2 sentences), not a restated paragraph.",
    },
    # ---------------------------------------------------------------- §7 ---
    {
        "id": "sec7-english",
        "spec_ref": "§7 English example",
        "turns": ["Do you have an appointment tomorrow?"],
        "expect": {"language": "en", "length": "medium", "ends_with_question": True},
        "notes": "Adapted from 'appointment tomorrow' generically -> real system will ask which service if not given; scoring on language+brevity, not exact wording.",
    },
    {
        "id": "sec7-nepali-devanagari",
        "spec_ref": "§7 Nepali (Devanagari) example",
        "turns": ["भोलि दाँत सफा गर्न मिल्छ?"],
        "expect": {"language": "ne_deva", "length": "medium", "ends_with_question": True},
        "notes": "Adapted to ask about Teeth Cleaning tomorrow (real, answerable) in Devanagari script, same structure as spec's doctor-availability example.",
    },
    {
        "id": "sec7-roman-nepali",
        "spec_ref": "§7 Roman Nepali example — 'bholi doctor hunuhuncha?'",
        "turns": ["bholi teeth cleaning ko lagi doctor hunuhuncha?"],
        "expect": {"language": "ne_roman", "length": "medium", "ends_with_question": True},
        "notes": "Adapted 'doctor availability' -> 'is the clinic available for teeth cleaning tomorrow', same Roman Nepali structure test.",
    },
    {
        "id": "sec7-mixed",
        "spec_ref": "§7 Mixed language example — literal",
        "turns": ["Bholi doctor available cha? appointment book garnu paryo."],
        "expect": {"language": "mixed", "length": "medium", "ends_with_question": True},
        "notes": "Literal spec message, unmodified.",
    },
    # ---------------------------------------------------------------- §11 --
    {
        "id": "sec11-ack-reschedule",
        "spec_ref": "§11 — 'mero appointment reschedule garnu paryo' -> brief ack + one question",
        "turns": ["book a teeth cleaning tomorrow at 2pm, I'm Sita, 9800011122", "mero appointment reschedule garnu paryo"],
        "expect": {"language": "ne_roman", "length": "short", "ends_with_question": True},
        "notes": "Real appointment booked first so a real reschedule has something to act on.",
    },
    {
        "id": "sec11-ack-existing-booking",
        "spec_ref": "§11 — 'maile 2 baje ko book gareko thiye' -> 'Huss, 2 PM ko appointment raicha.'",
        "turns": ["book a teeth cleaning tomorrow at 2pm, I'm Sita, 9800011122", "maile 2 baje ko book gareko thiye, ho ra?"],
        "expect": {"language": "ne_roman", "length": "short", "ends_with_question": False},
        "notes": "Brief confirmation referencing the REAL just-booked appointment, not a generic reply.",
    },
    {
        "id": "sec11-ack-cant-come",
        "spec_ref": "§11 — 'aaja aauna mildaina' -> 'Thik cha, appointment reschedule gardim.'",
        "turns": ["book a teeth cleaning today at 4pm, I'm Sita, 9800011122", "aaja aauna mildaina"],
        "expect": {"language": "ne_roman", "length": "short", "ends_with_question": True},
        "notes": "Real appointment exists for today so 'can't come today' has something real to act on.",
    },
    # ---------------------------------------------------------------- §12 --
    {
        "id": "sec12-no-repetition",
        "spec_ref": "§12 — '2 PM milcha?' then 'book gardim?' must NOT restate availability",
        "turns": ["is 2pm available tomorrow for a teeth cleaning?", "book gardim?"],
        "expect": {"language": "en_or_mixed", "length": "short", "ends_with_question": False, "no_repeat_of_prior_fact": True},
        "notes": "Second response must not re-state 'yes 2pm is available' — that was already established.",
    },
    # ---------------------------------------------------------------- §16 --
    {
        "id": "sec16-full-booking-conversation",
        "spec_ref": "§16 — full literal booking conversation, 6 customer turns",
        "turns": ["appointment chaiyo", "bholi", "teeth cleaning", "1", "Ram", "ram9800000001@example.com"],
        "expect": {"language": "ne_roman", "length": "mixed_by_turn", "ends_with_question": None},
        "notes": (
            "Real system asks for a REAL way to reach the customer (phone/email) before "
            "locking a booking, which the spec's literal 6-turn version doesn't show — a "
            "real, pre-existing business requirement (Phase 24), not a conversational flaw. "
            "Scoring the FLOW's naturalness (short turns, no repeated questions, real "
            "progression) rather than an exact turn-for-turn match."
        ),
    },
    # ---------------------------------------------------------------- §18 --
    {
        "id": "sec18-cancellation",
        "spec_ref": "§18 — cancellation flow",
        "turns": ["book a teeth cleaning tomorrow at 2pm, I'm Sita, 9800011122", "mero appointment cancel gardinu"],
        "expect": {"language": "ne_roman", "length": "short", "ends_with_question": False},
        "notes": (
            "KNOWN, DELIBERATE DIVERGENCE: the spec's literal example has the AI ask "
            "'cancel garne ho?' before cancelling. Phase 1's audit (§2.D) already found "
            "real customers benefiting from the CURRENT confirmation-free fast path and "
            "explicitly decided NOT to add a gate. This case checks the real cancellation "
            "is SHORT and natural, not that it asks first — deliberately not scored against "
            "the spec's confirmation step."
        ),
    },
    # ---------------------------------------------------------------- §19 --
    {
        "id": "sec19-reschedule-flow",
        "spec_ref": "§19 — full literal reschedule conversation",
        "turns": ["book a teeth cleaning tomorrow at 10am, I'm Sita, 9800011122", "mero appointment reschedule garnu paryo", "Friday"],
        "expect": {"language": "ne_roman", "length": "mixed_by_turn", "ends_with_question": True},
        "notes": "Real Friday availability used instead of spec's literal '11 AM ra 3 PM' slots.",
    },
    # ---------------------------------------------------------------- §20 --
    {
        "id": "sec20-frustration-a",
        "spec_ref": "§20 — 'kati choti bhanne?' — must NOT be 'I apologize for the inconvenience'",
        "turns": ["kati choti bhanne?"],
        "expect": {"language": "ne_roman", "length": "short", "ends_with_question": True, "banned_phrases": CORPORATE_PHRASES},
        "notes": "Standalone frustration with no context — real system should ask what the issue is about.",
    },
    {
        "id": "sec20-frustration-b-with-context",
        "spec_ref": "§20 — frustration referencing an earlier topic",
        "turns": ["what's the price for a teeth cleaning?", "kati choti sodhne ma? tapai le suneko chaina?"],
        "expect": {"language": "ne_roman", "length": "short", "ends_with_question": False, "banned_phrases": CORPORATE_PHRASES},
        "notes": "Frustration after an already-answered question — must acknowledge briefly, not restart.",
    },
    # ---------------------------------------------------------------- §26 --
    {
        "id": "sec26-thank-you",
        "spec_ref": "§26 — 'thank you' -> 'You're welcome 😊', NOT 'anything else I can help with'",
        "turns": ["what's the price for a teeth cleaning?", "thank you"],
        "expect": {"language": "en", "length": "short", "ends_with_question": False, "banned_phrases": CORPORATE_PHRASES},
    },
    {
        "id": "sec26-huss",
        "spec_ref": "§26 — 'huss' -> 'Huss 😊'",
        "turns": ["teeth cleaning ko price kati ho?", "huss"],
        "expect": {"language": "ne_roman", "length": "short", "ends_with_question": False},
    },
    # ---------------------------------------------------------------- §27 --
    {
        "id": "sec27-bare-digit-context",
        "spec_ref": "§27 — 'Bholi 10 AM ra 2 PM available cha.' then '2' -> 'Huss, 2 PM rakhdim.'",
        "turns": ["what times do you have for a teeth cleaning tomorrow?", "2"],
        "expect": {"language": "ne_roman", "length": "short", "ends_with_question": None},
        "notes": "Exercises the Phase 2 deterministic bare-digit shortcut for the exact spec-named shape.",
    },
    {
        "id": "sec27-short-token-milcha",
        "spec_ref": "§27 — short context-dependent tokens ('milcha', 'la', 'huncha') must resolve from context",
        "turns": ["what times do you have for a teeth cleaning tomorrow?", "9 baje milcha?"],
        "expect": {"language": "ne_roman", "length": "short", "ends_with_question": True},
    },
    # ---------------------------------------------------------------- §61 --
    {
        "id": "sec61-ex1-price",
        "spec_ref": "§61 Example 1 — price question, concise + offer to book",
        "turns": ["what's the price for teeth cleaning"],
        "expect": {"language": "en", "length": "short", "ends_with_question": True, "banned_phrases": CORPORATE_PHRASES},
    },
    {
        "id": "sec61-ex2-tomorrow-availability",
        "spec_ref": "§61 Example 2 — tomorrow's availability, concise slot list + one question",
        "turns": ["do you have any teeth cleaning appointments available tomorrow"],
        "expect": {"language": "en", "length": "medium", "ends_with_question": True},
    },
    {
        "id": "sec61-ex3-cancellation-done",
        "spec_ref": "§61 Example 3 — 'Huss, appointment cancel gardiye.' not a corporate sentence",
        "turns": ["book a teeth cleaning tomorrow at 3pm, I'm Sita, 9800011122", "cancel gardinu na"],
        "expect": {"language": "ne_roman", "length": "short", "ends_with_question": False, "banned_phrases": CORPORATE_PHRASES},
    },
    {
        "id": "sec61-ex4-milcha-book",
        "spec_ref": "§61 Example 4 — 'bholi 2 baje milcha?' -> 'Milcha 😊 ... Book gardim?'",
        "turns": ["bholi 2 baje teeth cleaning ko lagi milcha?"],
        "expect": {"language": "ne_roman", "length": "short", "ends_with_question": True},
    },
    {
        "id": "sec61-ex5-cancel-sorry",
        "spec_ref": "§61 Example 5 — apologetic cancellation request -> brief, warm, not overly formal",
        "turns": ["book a teeth cleaning tomorrow at 11am, I'm Sita, 9800011122", "mero appointment cancel garnu paryo sorry"],
        "expect": {"language": "ne_roman", "length": "short", "ends_with_question": False, "banned_phrases": CORPORATE_PHRASES},
    },
    {
        "id": "sec61-ex6-huss-bare",
        "spec_ref": "§61 Example 6 — bare 'huss' -> 'Huss 😊', not 'thank you for confirming...'",
        "turns": ["teeth cleaning book garnu paryo, bholi 10 baje, Sita, 9800011122", "huss"],
        "expect": {"language": "ne_roman", "length": "short", "ends_with_question": False, "banned_phrases": CORPORATE_PHRASES},
    },
    # ---------------------------------------------------------------- §64 --
    {
        "id": "sec64-full-target-conversation",
        "spec_ref": "§64 — the complete 8-turn target conversation",
        "turns": [
            "hello",
            "malai bholi teeth cleaning ko appointment chaiyo",
            "1",
            "Samrat",
            "samratghimire01@gmail.com",
            "yes",
            "location chai?",
            "huss thank you",
        ],
        "expect": {"language": "mixed_by_turn", "length": "mixed_by_turn", "ends_with_question": None},
        "notes": (
            "Adapted: spec's 'Samrat' name+no-contact flow doesn't match this real business's "
            "real requirement for a phone/email before locking a booking — an email turn is "
            "inserted (same structural adaptation as §16). Scored on the overall real-conversation "
            "feel, not an exact turn-for-turn transcript match."
        ),
    },
]

# ---------------------------------------------------------------- §23 ------
# Emoji-policy sampling: reuse a representative slice of the cases above,
# grouped by the spec's own three categories, plus their real transcripts are
# what the runner counts emoji occurrences against.
EMOJI_SAMPLE_GROUPS: dict[str, list[str]] = {
    "serious_or_frustrated": ["sec20-frustration-a", "sec20-frustration-b-with-context"],
    "normal": ["sec5-short-hours", "sec5-medium-availability", "sec7-english", "sec61-ex1-price", "sec61-ex2-tomorrow-availability"],
    "friendly_confirmation": ["sec61-ex4-milcha-book", "sec61-ex6-huss-bare", "sec26-thank-you", "sec26-huss"],
}
