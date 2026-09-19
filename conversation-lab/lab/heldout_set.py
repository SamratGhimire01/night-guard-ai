"""SPENT held-out set (now a development set): it exposed the missing scope criterion, so the judge was changed
after seeing it. Use lab/heldout_set_2.py for held-out numbers. Original note follows.

HELD-OUT validation set. Written BEFORE the judge was run on it and BEFORE
any judge change made in the same phase; the judge must NOT be tuned against
these groups (if it is, they stop being held out -- say so in LAB_STATUS.md).

None of these customer messages/replies appear in lab/validation_set.py (the set
the rubric was iterated on). `real` = verbatim text from PHASE_STATUS.md /
backend/tests/eval (customer name/booking id redacted); the label is the
project's own verdict recorded next to it -- or, where the verdict was only
made later, the project rule it violates (cited in provenance). `synthetic` =
written by me (Claude) for this phase, clearly labeled; they exist for the two
non-dental businesses and for criteria with no recorded real bad example.
Same group format as validation_set.GROUPS."""

RIVERSIDE = "Riverside Dental (a dental clinic). Business hours: Monday-Saturday 9:00 AM-5:00 PM. Service: Cleaning ($90, 30 min)."
SALON = (
    "Business: Demo Hair Salon (SANDBOX - fictional), Jawalakhel, Lalitpur. Hours: every day 9:00 AM-8:00 PM. "
    "Services: Haircut (NPR 600, 30 min); Hair Colour (NPR 3500, 120 min); Facial (NPR 1800, 60 min); Beard Trim (NPR 300, 15 min)."
)
TREK = (
    "Business: Demo Himalayan Treks (SANDBOX - fictional), Thamel, Kathmandu. Hours: Sunday-Friday 10:00 AM-6:00 PM; closed Saturday. "
    "Services: Poon Hill Trek (USD 450, 5 days); Everest Base Camp Trek (USD 1400, 14 days); Day Hike Nagarkot (USD 60, 1 day). "
    "Policy: 30% deposit to confirm; full refund if cancelled 14+ days before departure."
)

GROUPS: list[dict] = [
    # ---------------- real ----------------
    {
        "id": "offtopic-america",
        "kind": "real",
        "customer": "Random question — how was America discovered?",
        "facts": RIVERSIDE,
        "replies": [
            ("bad", "Short answer: Indigenous peoples lived in the Americas for many thousands of years before any European contact. Norse explorers (like Leif Erikson) reached parts of northeastern North America around 1000 CE, and Christopher Columbus's 1492 voyage led to sustained European exploration and colonization. Want a bit more detail on any part of that timeline?", "Phase 24-era live run, pre-fix: real history answer from a dental receptionist bot"),
            ("good", "I'm just here to help with things related to Riverside Dental — appointments, services, hours, and the like. Is there something about that I can help with?", "same phase, post-fix live run (project verdict: correct)"),
        ],
    },
    {
        "id": "thanks-verbose-closing",
        "kind": "real",
        "customer": "Thank you so much for the help!",
        "facts": "Earlier the assistant answered the customer's questions about services and hours.",
        "replies": [
            ("bad", "You're very welcome — glad I could help! If you need anything else (an appointment, service info, or hours), just say the word.", "Phase 24-era live run; the reflexive 'anything else' tail is what Phase 1 audit/rule 3 later banned"),
            ("good", "You're welcome!", "synthetic (minimal correct closing; real equivalent 'You're welcome!' is in the calibration set)"),
        ],
    },
    {
        "id": "complaint-callback",
        "kind": "real",
        "customer": "This is the third time I have called about this! No one ever calls me back. I am so frustrated with this clinic.",
        "facts": "",
        "replies": [
            ("good", "That shouldn't be happening — I'm sorry you've had that experience. Would you like me to connect you with our team to follow up?", "Phase 9/Phase 7 live regression check (project verdict: 'good bar')"),
            ("good", "I'm really sorry — three calls with no callback is not okay. I can connect you with our team to get this sorted. I've also let our team know, so a real person will follow up with you.", "Phase 24 live run, 'complaint' intent (project verdict: correct)"),
            ("bad", "I'm deeply sorry you're experiencing this unfortunate inconvenience. Thank you for bringing this to our attention, and please don't hesitate to reach out if there is anything else I can assist you with.", "synthetic: the boilerplate Phase 9's own text lists as the bad example"),
        ],
    },
    {
        "id": "bot-question",
        "kind": "real",
        "customer": "Are you a bot?",
        "facts": RIVERSIDE,
        "replies": [
            ("good", "I'm the virtual receptionist for Riverside Dental — here to help with appointments, services, hours, and the like. What can I help you with today?", "Phase 24 live run (project verdict: correct, self-answered)"),
            ("bad", "Yes, I am an AI language model developed to assist with a wide range of tasks, including answering general knowledge questions, writing essays, coding, and much more. How may I assist you today?", "synthetic: leaks generic-assistant identity, off-scope, corporate phrasing"),
        ],
    },
    {
        "id": "language-switch-request",
        "kind": "real",
        "customer": "English ma kura garam",
        "facts": RIVERSIDE,
        "replies": [
            ("good", "Of course — switching to English now. How can I help?", "Phase 24-era live run (project verdict: correct)"),
            ("bad", "Thik cha, ma Nepali ma nai kura garchu. Tapai lai kasari sahayog garna sakchu?", "synthetic: ignores the explicit request to switch"),
        ],
    },
    {
        "id": "hours-not-given-to-llm",
        "kind": "real",
        "customer": "What are your hours?",
        "facts": "Business hours: Monday-Saturday 9:00 AM-5:00 PM.",
        "replies": [
            ("bad", "I don't have our hours in my records. Would you like me to connect you with our team so they can confirm them for you?", "Phase 8/24 live run; hours WERE in the DB but not passed to the LLM (Phase 6 root cause)"),
            ("good", "We're open Monday to Saturday, 9:00 AM–5:00 PM.", "synthetic: the correct direct answer from the facts"),
        ],
    },
    {
        "id": "readiness-loop",
        "kind": "real",
        "customer": "Huncha",
        "conversation": "Assistant: ...Ma tapai ko lagi Dental Consultation book garidinu?\nCustomer: Huncha",
        "facts": "Service: Dental Consultation. Booking still needs a date and a time.",
        "replies": [
            ("bad", "Maaf garnuhos, maile thik sanga bujhna chahanchu — kun service, ra kun miti ra samaya chahanu huncha bhanera batauna sakinu huncha?", "real transcript f3242b3f (Phase 1 audit §2.B): re-asks a service the customer already picked, stacked with date+time"),
            ("good", "Thik cha — Dental Consultation ko lagi kun din aauna milcha?", "synthetic: acknowledges, asks the one missing piece"),
        ],
    },
    {
        "id": "confirmation-ignored",
        "kind": "real",
        "customer": "yes",
        "conversation": "Customer: Teeth widening, you know, the talcumara.\nCustomer: भोलिको एक गरेको भए हुन्छ\nAssistant: ...Ke yo thik cha bholi 8 Sept, 1:00 PM ko Teeth Whitening appointment confirm garna?...\nCustomer: yes",
        "facts": "Service: Teeth Whitening. Draft: tomorrow 1:00 PM. Contact details already given.",
        "replies": [
            ("bad", "Bujhe — kripaya malai kun service batauna sakinu huncha?", "real transcript 4a0de7b9 (Phase 1 audit §2.C)"),
            ("good", "You're all set, Sita! I've booked Teeth Whitening for tomorrow at 1:00 PM.", "real post-fix booking-confirmation shape (Phase 24 live: \"You're all set, <name>! I've booked ...\"), name redacted, booking id dropped"),
        ],
    },
    {
        "id": "clarifying-with-false-handoff",
        "kind": "real",
        "customer": "k garda thick hola",
        "facts": "Dental clinic; services: whitening, cleaning, consultation.",
        "replies": [
            ("bad", "Ke tapaile 'thick' bhanda gums (masu) ko thickness baddhaune kura bujhnu bhayo, ki daant lai mote/visal dekhine banaune kura ho? Maile hamro team lai pani janakari diye, tyesaile euta sacchai ko manche le tapailai follow-up garnecha.", "real transcript ac9079a1 (Phase 3): fine question, but false 'team notified' addendum"),
            ("good", "Ke tapai gums (masu) thick banaune kura bhanna khojnu bhayeko ho, ki daant safa/chamkilo banaune?", "synthetic: the same clarifying question without the false handoff claim"),
        ],
    },
    # ---------------- synthetic, non-dental businesses ----------------
    {
        "id": "salon-greeting",
        "kind": "synthetic",
        "customer": "hi",
        "facts": SALON,
        "replies": [
            ("bad", "Hello! Welcome to Demo Hair Salon in Jawalakhel. We offer haircuts, hair colour, facials and beard trims, and we're open every day from 9 AM to 8 PM. How can I help you today — book a service, check prices, or get directions?", "synthetic: verbose greeting dump, 3-way compound question"),
            ("good", "Hi! How can I help you today?", "synthetic: correct short greeting"),
        ],
    },
    {
        "id": "salon-price",
        "kind": "synthetic",
        "customer": "haircut ko price kati ho?",
        "facts": SALON,
        "replies": [
            ("bad", "Haircut ko price NPR 600 ho. Hami hair colour (NPR 3500), facial (NPR 1800) ra beard trim (NPR 300) pani garchau. Tapai kun service book garna chahanu huncha? Tapaiko naam ra phone number pani dinuhos.", "synthetic: answer buried in a service dump + contact demand before it is needed"),
            ("good", "Haircut NPR 600 ho, 30 minute lagcha.", "synthetic: direct answer from the facts"),
        ],
    },
    {
        "id": "trek-hours-english",
        "kind": "synthetic",
        "customer": "Are you open on Saturday?",
        "facts": TREK,
        "replies": [
            ("bad", "Ho, hami Saturday pani khula chau. Tapai kati baje aauna chahanu huncha?", "synthetic: wrong language (Romanized Nepali to an English message) AND wrong fact"),
            ("good", "No — we're closed on Saturdays. We're open Sunday to Friday, 10 AM–6 PM.", "synthetic: correct, from the facts"),
        ],
    },
    {
        "id": "trek-deposit-honesty",
        "kind": "synthetic",
        "customer": "How much deposit do I need for the Poon Hill trek?",
        "facts": TREK,
        "replies": [
            ("bad", "I'm sorry, I don't have information about deposits. Would you like me to connect you with our team to confirm?", "synthetic: claims not to know a fact that is in the facts"),
            ("good", "30% deposit to confirm — for Poon Hill (USD 450) that's USD 135.", "synthetic: correct, uses the facts"),
        ],
    },
    {
        "id": "trek-thanks",
        "kind": "synthetic",
        "customer": "thanks!",
        "conversation": "Customer: how long is the Everest Base Camp trek?\nAssistant: 14 days.",
        "facts": TREK,
        "replies": [
            ("bad", "You're most welcome! Would you like me to check available departure dates for Everest Base Camp, or is there anything else I can help you with? 😊😊", "synthetic: reflexive offer + two emoji"),
            ("good", "You're welcome!", "synthetic: plain closing"),
        ],
    },
]
