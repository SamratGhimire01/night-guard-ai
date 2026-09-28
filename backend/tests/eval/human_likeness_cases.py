"""Phase 3 (cut down) — fixed test set for the before/after human-likeness eval
(live_human_likeness_before_after.py).

39 single-turn cases across the 3 style-exemplar seeded tenants (Samaj Dental
Clinic/dental, Himalayan Trails Trekking Co./trekking, Everest Pathways
Consultancy/study_abroad), spanning greeting/general_question/service_question/
pricing_question/booking/complaint/off_topic and en/ne_deva/ne_roman/mixed.

Most messages are pulled verbatim from this project's own real conversation
logs (scripts/pull_real_conversations.py output), with any email/phone
digits redacted -- marked "real" below. Where the real logs had no clean
example for a given tenant/intent/language combination (trekking and
study_abroad have far fewer real conversations than the dental tenant, and
some categories like complaint/off_topic barely appear in either, or only in
a form too vulgar to be worth reproducing in an eval report), a short
scripted message fills the gap -- marked "scripted". Each case is a single
customer message into a fresh, empty conversation; the actual intent/
language bucket used for reporting comes from what the live system itself
detects on the AFTER run, not from a hand-assigned label here.
"""

CASES: list[dict] = [
    # --- Samaj Dental Clinic (dental) ---
    {"id": "dental-01", "business": "Samaj Dental Clinic", "source": "real", "message": "Hello"},
    {"id": "dental-02", "business": "Samaj Dental Clinic", "source": "real", "message": "k xa"},
    {"id": "dental-03", "business": "Samaj Dental Clinic", "source": "real", "message": "Do you take walk-ins?"},
    {
        "id": "dental-04", "business": "Samaj Dental Clinic", "source": "real",
        "message": "malai payment garna man cha kasri garni ho",
    },
    {"id": "dental-05", "business": "Samaj Dental Clinic", "source": "real", "message": "What service do you provide"},
    {
        "id": "dental-06", "business": "Samaj Dental Clinic", "source": "real",
        "message": "हेलो तपाईँको सर्भिस के के छ",
    },
    {
        "id": "dental-07", "business": "Samaj Dental Clinic", "source": "real",
        "message": "hlo, malai teeth cleaning ko barema janna man cha",
    },
    {"id": "dental-08", "business": "Samaj Dental Clinic", "source": "real", "message": "How much is a cleaning?"},
    {
        "id": "dental-09", "business": "Samaj Dental Clinic", "source": "real",
        "message": "रूट क्यानल गर्न कति लाग्छ?",
    },
    {
        "id": "dental-10", "business": "Samaj Dental Clinic", "source": "real",
        "message": "Hi, I'd like to book a Teeth Cleaning on Thursday September 17 2026. What times are available?",
    },
    {
        "id": "dental-11", "business": "Samaj Dental Clinic", "source": "real",
        "message": "सुन्नु न मलाई यो द तुथ क्लिनिङको लागि भोलि दस बजेको अपोइन्टमेन्ट बुक गरिदिनु न",
    },
    {
        "id": "dental-12", "business": "Samaj Dental Clinic", "source": "real",
        "message": "Don't you know my name? Why are you saying the website visitor?",
    },
    {
        "id": "dental-13", "business": "Samaj Dental Clinic", "source": "scripted",
        "message": "Yesto huna hudaina thyo, mero appointment miss vayo — I'm not happy about this.",
    },
    {
        "id": "dental-14", "business": "Samaj Dental Clinic", "source": "real",
        "message": "Random question — how was America discovered?",
    },

    # --- Himalayan Trails Trekking Co. (trekking) ---
    {
        "id": "trekking-01", "business": "Himalayan Trails Trekking Co.", "source": "scripted",
        "message": "Hey, is this the trekking company?",
    },
    {
        "id": "trekking-02", "business": "Himalayan Trails Trekking Co.", "source": "scripted",
        "message": "Namaste! Trek ko bare ma sodhna man lagyo.",
    },
    {
        "id": "trekking-03", "business": "Himalayan Trails Trekking Co.", "source": "scripted",
        "message": "Do you guys help with permits too?",
    },
    {
        "id": "trekking-04", "business": "Himalayan Trails Trekking Co.", "source": "scripted",
        "message": "Trek suru garnu agadi k k tayari garnu parcha?",
    },
    {
        "id": "trekking-05", "business": "Himalayan Trails Trekking Co.", "source": "real",
        "message": "What's the best season to trek Langtang Valley?",
    },
    {
        "id": "trekking-06", "business": "Himalayan Trails Trekking Co.", "source": "real",
        "message": "Namaste, trek season kahile best huncha, monsoon ma jana milxa?",
    },
    {
        "id": "trekking-07", "business": "Himalayan Trails Trekking Co.", "source": "real",
        "message": "gear rental ma k k items milxa, tent samet huncha ki hudaina?",
    },
    {
        "id": "trekking-08", "business": "Himalayan Trails Trekking Co.", "source": "real",
        "message": "How much does the Everest Base Camp trek cost and how long does it take?",
    },
    {
        "id": "trekking-09", "business": "Himalayan Trails Trekking Co.", "source": "real",
        "message": "गाइड बुकिङको लागि कति खर्च लाग्छ?",
    },
    {
        "id": "trekking-10", "business": "Himalayan Trails Trekking Co.", "source": "real",
        "message": "I'd like to reserve a spot on the Annapurna Circuit trek. How do I do that?",
    },
    {
        "id": "trekking-11", "business": "Himalayan Trails Trekking Co.", "source": "scripted",
        "message": "The guide never showed up on time for our last trek, that's not okay.",
    },
    {
        "id": "trekking-12", "business": "Himalayan Trails Trekking Co.", "source": "scripted",
        "message": "Can you recommend a good phone plan for international roaming?",
    },

    # --- Everest Pathways Consultancy (study_abroad) ---
    {"id": "study-01", "business": "Everest Pathways Consultancy", "source": "real", "message": "Hlo"},
    {"id": "study-02", "business": "Everest Pathways Consultancy", "source": "real", "message": "hlo maya k xa"},
    {
        "id": "study-03", "business": "Everest Pathways Consultancy", "source": "real",
        "message": "Just passed out +2 so I want to go abroad, so please can you tell me the best countries",
    },
    {
        "id": "study-04", "business": "Everest Pathways Consultancy", "source": "real",
        "message": "Mro tai bachelor sakina 1 Barsa matari xa Kun subject Lida hunxa master ko lagi UK ma padhna",
    },
    {
        "id": "study-05", "business": "Everest Pathways Consultancy", "source": "real",
        "message": "Hi, I want to study in Australia. What should I do first?",
    },
    {
        "id": "study-06", "business": "Everest Pathways Consultancy", "source": "scripted",
        "message": "भिसा इन्टरभ्यूको लागि कस्तो तयारी गर्नुपर्छ?",
    },
    {
        "id": "study-07", "business": "Everest Pathways Consultancy", "source": "real",
        "message": "SOP लेख्न कति समय लाग्छ, aru kehi documents chai chaine ho?",
    },
    {
        "id": "study-08", "business": "Everest Pathways Consultancy", "source": "scripted",
        "message": "What's the total cost for a US student visa application package?",
    },
    {
        "id": "study-09", "business": "Everest Pathways Consultancy", "source": "real",
        "message": "भिसा इन्टरभ्यू तयारीको शुल्क कति हो?",
    },
    {
        "id": "study-10", "business": "Everest Pathways Consultancy", "source": "real",
        "message": "Can I book a document evaluation session for next Monday at 11am?",
    },
    {
        "id": "study-11", "business": "Everest Pathways Consultancy", "source": "real",
        "message": "huncha book garidnus",
    },
    {
        "id": "study-12", "business": "Everest Pathways Consultancy", "source": "scripted",
        "message": "I paid the counseling fee but no one followed up with me for two weeks.",
    },
    {
        "id": "study-13", "business": "Everest Pathways Consultancy", "source": "real",
        "message": "What's Ace Institute of Management's overview and admission process?",
    },
]
