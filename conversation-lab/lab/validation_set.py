"""Labeled replies for proving the judge is trustworthy BEFORE anything is
built on it. `real` groups use ONLY verbatim text (customer name/phone/email redacted to placeholders) recorded in PHASE_STATUS.md
from today's real work (real customer message, real assistant reply, label =
the project's own verdict at the time: pre-fix = bad, post-fix/target = good).
`synthetic` groups are clearly labeled and exist only to probe criteria that
have no recorded real bad example (scripted corporate phrasing, emoji while
frustrated, wrong language)."""

HOURS = "Business hours: Monday-Friday 9:00 AM-6:00 PM; closed Saturday and Sunday."
SLOTS = (
    "Service: Teeth Cleaning (Scaling & Polishing). Real open slots for it: Thursday, September 17 at 9:30 AM, "
    "9:45 AM, 10:00 AM, 10:15 AM, 10:30 AM."
)

GROUPS: list[dict] = [
    {
        "id": "greeting-hlo",
        "kind": "real",
        "customer": "hlo",
        "facts": "Samaj Dental Clinic, New Baneshwor. Services: general dentistry, orthodontics, oral surgery, cosmetic.",
        "replies": [
            ("bad", "Hello! Welcome to Samaj Dental Clinic. How can I help you today? We offer general dentistry, orthodontics (braces), oral surgery, and cosmetic treatments — on-site parking is available.", "Phase 3, live run #3 (pre-fix)"),
            ("bad", "Hello! Welcome to Samaj Dental Clinic in New Baneshwor — we offer general dentistry, orthodontics, oral surgery, and cosmetic treatments, and on-site parking is available. How can I help you today — an appointment, question about a service, or directions?", "Phase 3, live run #5 (pre-fix)"),
            ("bad", "Hi — welcome to Test Chat Biz! How can I help you today? I can assist with appointments, services, pricing, hours, location, or policies.", "Phase 7, stale-container live reply"),
            ("good", "Namaste! Kasari sahayog garna sakchu?", "Phase 4, post-fix live run #1"),
            ("good", "Hi! Welcome to Samaj Dental Clinic — how can I help you today?", "Phase 4, post-fix live run #2"),
            ("good", "Hi! K ma madat garna sakchu?", "Phase 4, post-fix live run #3"),
            ("good", "Namaste! K ma madat garna sakchu? 😊", "Phase 7, live after container recreate"),
            ("good", "Hi — welcome to Samaj Dental Clinic. How can I help you today?", "Phase 8, live after recreate"),
        ],
    },
    {
        "id": "greeting-yo",
        "kind": "real",
        "customer": "Yo",
        "facts": "Samaj Dental Clinic, New Baneshwor. Services: appointments, general dentistry, directions, on-site parking.",
        "replies": [
            ("bad", "Hi! Welcome to Samaj Dental Clinic in New Baneshwor. How can I help you today — would you like to book an appointment, get directions, or hear more about a specific service?", "Phase 1 audit §2.A, real transcript 3db7b0b2"),
            ("bad", "Hi! Welcome to Samaj Dental Clinic. How can I help — would you like to book an appointment, get directions to our New Baneshwor clinic (we have on-site parking), or learn about a specific service?", "Phase 1 audit §2.A, real transcript 3db7b0b2"),
            ("good", "Hi! How can I help you today?", "Phase 4, eval-set re-run"),
        ],
    },
    {
        "id": "hours-open-cha",
        "kind": "real",
        "customer": "open cha?",
        "facts": HOURS,
        "replies": [
            ("bad", "Maile yaha hamro opening hours ko info paudina. Ke ma team sanga connect garera confirm garera dinu?", "Phase 6 baseline (pre-fix, hours not given to LLM)"),
            ("good", "Ho — hami Somabar dekhi Sukrabar samma, 9:00 AM dekhi 6:00 PM samma khula chau. Sanibar ra Aitabar bandha huncha.", "Phase 6, post-fix live run"),
            ("good", "Ho — hamro clinic Somabar dekhi Shukrabar 9:00 AM–6:00 PM samma khula cha. Saturday ra Sunday bandha huncha.", "Phase 8, live re-verification"),
        ],
    },
    {
        "id": "thanks-closing",
        "kind": "real",
        "customer": "thank you",
        "facts": "Earlier in the conversation the assistant already answered the customer's question about cleaning prices.",
        "replies": [
            ("bad", "You're welcome — would you like me to check available times for a cleaning?", "Phase 6 baseline (pre-fix)"),
            ("good", "You're welcome!", "Phase 6, post-fix live run"),
        ],
    },
    {
        "id": "availability-no-contact-gate",
        "kind": "real",
        "customer": "teeth cleaning available cha?",
        "facts": SLOTS,
        "replies": [
            ("bad", "Bujhe — Teeth Cleaning (Scaling & Polishing). Lock garna malai tapaiko naam ra phone number wa email chahincha.", "Phase 6 baseline (contact gate fired first)"),
            ("good", "Teeth Cleaning (Scaling & Polishing) ko lagi yi samaya haru khali chan: Thursday, September 17 at 9:30 AM, Thursday, September 17 at 9:45 AM, Thursday, September 17 at 10:00 AM, Thursday, September 17 at 10:15 AM, Thursday, September 17 at 10:30 AM. Kun milcha?", "Phase 8, live re-verification"),
        ],
    },
    {
        "id": "reask-loop-whatsapp",
        "kind": "real",
        "customer": "Tooth cleaning Ani tei what app number ma pathaunu k",
        "conversation": "[earlier turns, verbatim text not preserved in the status file: the customer had already named WhatsApp as the delivery channel twice, and twice been asked 'WhatsApp, email, or SMS?' again]",
        "facts": "Customer phone on file 98XXXXXXXX. Service: Teeth Cleaning (Scaling & Polishing), NPR 1500.",
        "replies": [
            ("bad", "Thik cha — yo dui jana ko Teeth Cleaning ho bhanera bujhe. E‑Sewa QR kun method ma pathaun? WhatsApp 98XXXXXXXX, email sita@example.com, or SMS 98XXXXXXXX — kun ma pathaun bhanera confirm garnuhos. Ra eSewa QR dui ota pathaun huncha ho?", "Rule-16 phase, real BEFORE turn 11 (loop reproduced)"),
        ],
    },
    {
        "id": "reask-fixed",
        "kind": "real",
        "customer": "Ho whatsapp ma nai pathaun na, tei number ho",
        "conversation": "[earlier: 24 real messages in which the agent repeatedly asked WhatsApp vs email vs SMS]",
        "facts": "Customer phone on file 98XXXXXXXX. Service: Teeth Cleaning (Scaling & Polishing), NPR 1500.",
        "replies": [
            ("good", "Thik cha — WhatsApp ma nai pathaun. Yo QR Teeth Cleaning (Scaling & Polishing) ko payment NPR 1500 ko lagi ho, thik cha? Ma front desk sanga QR pathauna bhanera arrange garna sahayog garun?", "Rule-16 phase, real AFTER (post-fix; itself still a bit compound)"),
        ],
    },
    {
        "id": "cancel-it-transactional",
        "kind": "real",
        "customer": "cancel it",
        "facts": "The customer's one active appointment (Monday, September 7 at 10:00 AM) was just cancelled by the real system.",
        "replies": [
            ("good", "Done, Sita — your appointment on Monday, September 7 at 10:00 AM has been cancelled.", "Phase 1 audit §2.F, real transcript 32aea5c3 ('target quality bar')"),
        ],
    },
    # ---- synthetic probes (clearly NOT real transcripts) ----
    {
        "id": "frustrated-corporate",
        "kind": "synthetic",
        "customer": "This is the third time I've called about this and no one's called me back!",
        "facts": "",
        "replies": [
            ("bad", "I apologize for the inconvenience. I understand how frustrating that is. Thank you for reaching out to us, and please feel free to let me know if there is anything else I can assist you with.", "synthetic: scripted phrases named in intent.py rule 4"),
            ("bad", "So sorry about that 😊😊 we'll fix it right away 🙏", "synthetic: emoji while frustrated"),
            ("good", "Three times with no callback — that shouldn't happen. Let's get this sorted now. What's the issue, and what's the best number to reach you?", "verbatim few-shot example from intent.py"),
        ],
    },
    {
        "id": "wrong-language-devanagari",
        "kind": "synthetic",
        "customer": "भोलि दाँत सफा गर्न मिल्छ?",
        "facts": "Service: Teeth Cleaning. Open Monday-Friday 9:00 AM-6:00 PM.",
        "replies": [
            ("bad", "Yes, we can do a teeth cleaning tomorrow. Which time would you prefer?", "synthetic: English reply to a Devanagari message (customer msg is verbatim spec §7)"),
            ("good", "मिल्छ — भोलि दाँत सफा गर्न कुन समय मिल्छ तपाईंलाई?", "synthetic: same content in the customer's script"),
        ],
    },
]
