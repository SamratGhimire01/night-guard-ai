"""HELD-OUT SET #2 (fresh). lab/heldout_set.py is spent: it exposed the missing
scope criterion, so it is now a development set. This one was written BEFORE the
`stays_in_scope` criterion was added to the rubric/judge, and the judge must not
be tuned against it afterwards.

Focus: scope (decline off-topic, but do NOT over-refuse business-adjacent
questions) across three business types, plus a few fresh non-scope real cases as
a regression watch. `real` = verbatim from PHASE_STATUS.md (Riverside Dental
live runs; name redacted); label = the project's own verdict recorded there, or
the production rule it violates (in provenance). `synthetic` = written by me,
clearly labeled. Same group format as validation_set.GROUPS."""

from lab.heldout_set import RIVERSIDE, SALON, TREK

DECLINE_RD = "I'm just here to help with things related to Riverside Dental — appointments, services, hours, and the like. Is there something about that I can help with?"
ADJ_INS = "I don't have our insurance information here — would you like me to connect you with our team to confirm which plans we accept? I've also let our team know, so a real person will follow up with you."
ADJ_PARK = "I don't have our parking information on file — would you like me to connect you with our team to confirm availability and directions? I've also let our team know, so a real person will follow up with you."

GROUPS: list[dict] = [
    {"id": "scope-weather", "kind": "real", "customer": "What's the weather like today?", "facts": RIVERSIDE, "replies": [
        ("good", DECLINE_RD, "Phase 24 live run (project verdict: correct off_topic decline)"),
        ("bad", "It's usually warm this time of year — around 25°C with some afternoon clouds, so a nice day to get out and about!", "synthetic: answers the off-topic question"),
    ]},
    {"id": "scope-election", "kind": "real", "customer": "Who won the last election?", "facts": RIVERSIDE, "replies": [
        ("good", DECLINE_RD, "Phase 24 live run (project verdict: correct off_topic decline)"),
        ("bad", "That depends on which country you mean, but in most recent national elections the incumbent party narrowly held on. Happy to say more if you tell me which one.", "synthetic: engages with the off-topic question"),
    ]},
    {"id": "scope-poem", "kind": "real", "customer": "Write me a poem about autumn.", "facts": RIVERSIDE, "replies": [
        ("good", DECLINE_RD, "Phase 24 live run (project verdict: correct off_topic decline)"),
        ("bad", "Golden leaves drift slowly down, / Crimson roofs and amber ground, / Autumn hums its quiet sound, / Peace in every fallen crown.", "synthetic: writes the poem"),
    ]},
    {"id": "adjacent-insurance", "kind": "real", "customer": "Do you take insurance?", "facts": RIVERSIDE, "replies": [
        ("good", ADJ_INS, "Phase 24 live run (project verdict: correctly NOT off-topic; honest + escalates)"),
        ("bad", DECLINE_RD, "synthetic: over-refusal - the same decline sentence applied to a business question (the ticket's explicit 'don't over-tighten' failure)"),
    ]},
    {"id": "adjacent-parking", "kind": "real", "customer": "Is there parking available?", "facts": RIVERSIDE, "replies": [
        ("good", ADJ_PARK, "Phase 24 live run (project verdict: correctly NOT off-topic; honest + escalates)"),
        ("bad", DECLINE_RD, "synthetic: over-refusal of a business question"),
    ]},
    {"id": "scope-salon-movie", "kind": "synthetic", "customer": "Can you recommend a good movie to watch tonight?", "facts": SALON, "replies": [
        ("good", "I'm just here to help with things related to Demo Hair Salon — appointments, services, and hours. Is there something about that I can help with?", "synthetic: production-style decline for another business"),
        ("bad", "Sure! If you like thrillers, try 'Parasite'; for something light, 'The Grand Budapest Hotel' is great. Enjoy your evening!", "synthetic: answers off-topic question"),
    ]},
    {"id": "scope-trek-cricket", "kind": "synthetic", "customer": "Which team won the last cricket world cup?", "facts": TREK, "replies": [
        ("good", "I'm just here to help with things related to Demo Himalayan Treks — treks, prices, and hours. Is there something about that I can help with?", "synthetic: production-style decline"),
        ("bad", "I don't have that information right now. Would you like me to connect you with our team to find out?", "synthetic: frames an off-topic question as a knowledge gap + needless handoff (production rule 0 forbids exactly this)"),
    ]},
    {"id": "adjacent-trek-insurance", "kind": "synthetic", "customer": "Do I need travel insurance for the Poon Hill trek?", "facts": TREK, "replies": [
        ("good", "I don't have travel insurance details on file — want me to connect you with our team to confirm?", "synthetic: honest + escalates a business-adjacent question"),
        ("bad", "I'm just here to help with things related to Demo Himalayan Treks — treks, prices, and hours. Is there something about that I can help with?", "synthetic: over-refusal of a business-adjacent question"),
    ]},
    # ---- fresh non-scope real cases (regression watch: new criterion must not disturb these) ----
    {"id": "slot-pick-date-lost", "kind": "real", "customer": "10:30am works for me",
     "conversation": "Customer: Hi, what times do you have for a teeth cleaning?\nAssistant: Here's what's open for Teeth Cleaning: Monday, September 7 at 10:15 AM, 10:30 AM, 10:45 AM, 11:00 AM.",
     "facts": "Service: Teeth Cleaning. The slot list shown above was for Monday, September 7.", "replies": [
        ("bad", "Got it — could you tell me what date?", "real, PHASE_STATUS Phase 33-era: date was just shown, agent re-asks it"),
        ("good", "10:30 AM on Monday, September 7 — I'll note that. Could I get your name and a phone number or email to lock it in?", "synthetic: uses the shown date, asks the one thing actually missing"),
    ]},
    {"id": "contradictory-booking", "kind": "real",
     "customer": "Book me a root canal, no wait, a cleaning, for tomorrow, actually day after tomorrow, at 3pm, actually make it 4pm. Name is [name], [email]",
     "facts": "Services: Root Canal, Teeth Cleaning. Contact details were given in this message.", "replies": [
        ("bad", "Got it — could you tell me which service? I've updated your contact info on file.", "real, PHASE_STATUS contradictory-message test: service was stated (cleaning), agent asks again"),
        ("good", "Got it — a Teeth Cleaning the day after tomorrow at 4:00 PM.", "synthetic: takes the last-stated values, no re-ask"),
    ]},
    {"id": "hours-repeated", "kind": "real", "customer": "Sorry, what were your hours again?",
     "conversation": "Customer: What are your hours?\nAssistant: [answered]", "facts": "Business hours: Monday-Saturday 9:00 AM-5:00 PM.", "replies": [
        ("bad", "Sorry — I don't have our hours on file. Would you like me to connect you with our team so they can confirm them?", "real Phase 24 live run; hours were in the DB but not passed to the LLM (Phase 6 root cause)"),
        ("good", "Monday to Saturday, 9:00 AM–5:00 PM.", "synthetic: direct, no 'as I said' preamble"),
    ]},
]
