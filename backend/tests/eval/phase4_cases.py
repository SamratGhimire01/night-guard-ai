"""Phase 4 — expanded fixed test set for the multi-judge before/after eval
(live_phase4_multijudge.py). Measurement only.

= the 39 Phase 3 cases (human_likeness_cases.CASES, unchanged, ids kept) +
151 new single-turn cases across the same 3 tenants, weighted toward the
languages Phase 3 had least data on (ne_roman 11 -> ~60, ne_deva 7 -> ~57)
and covering every customer-facing intent except follow_up/unknown (both
only make sense mid-conversation, and every case here is a first message
into a fresh conversation).

"real" = verbatim customer message from data/regression/real_conversations
(messages with phone/email/names excluded; only clean single-turn ones
kept); "scripted" = hand-written to fill a tenant/language/intent gap the
real logs don't cover (trekking/study_abroad and Devanagari are thin there).
`lang`/`intent` are the INTENDED bucket (a coverage aid); reporting still
uses what the live system detects, same as Phase 3.
"""

from tests.eval.human_likeness_cases import CASES as PHASE3_CASES

_D, _T, _S = "Samaj Dental Clinic", "Himalayan Trails Trekking Co.", "Everest Pathways Consultancy"

_NEW = [
    # ---------------- Samaj Dental Clinic ----------------
    # en
    ("d-101", _D, "real", "en", "greeting", "Hyy"),
    ("d-102", _D, "real", "en", "business_hours", "What are your opening hours?"),
    ("d-103", _D, "real", "en", "location", "Is that the only location? Don’t you have branches?"),
    ("d-104", _D, "real", "en", "location", "Hi, where exactly is your clinic located? I'm coming from Kalanki and don't know the area at all, is there a landmark nearby I should look for, and is parking easy to find right there or should I plan for that?"),
    ("d-105", _D, "real", "en", "cancellation", "I want to cancel it now"),
    ("d-106", _D, "real", "en", "appointment_status", "what appointmet do i have"),
    ("d-107", _D, "real", "en", "resend_confirmation", "i did not get email"),
    ("d-108", _D, "real", "en", "human_handoff", "I want a rea person give me the number"),
    ("d-109", _D, "real", "en", "off_topic", "write a c program of finding odd and even number"),
    ("d-110", _D, "real", "en", "pricing_question", "roughly how much does stuff usually cost here and how long does a typical visit take?"),
    ("d-111", _D, "real", "en", "service_question", "I want to come in for some dental work soon, not totally sure what I need done though -- whenever you have an opening works for me, what would you suggest?"),
    ("d-112", _D, "scripted", "en", "rescheduling", "Something came up — can I move my appointment to next week?"),
    ("d-113", _D, "scripted", "en", "complaint", "I waited 45 minutes past my appointment time last week and nobody even apologized."),
    ("d-114", _D, "scripted", "en", "booking", "Can I get a braces consultation this Saturday afternoon?"),
    # ne_roman
    ("d-115", _D, "real", "ne_roman", "greeting", "K cha halkabar"),
    ("d-116", _D, "real", "ne_roman", "business_hours", "kati baje dekhi kati baje samma available cha appoiment"),
    ("d-117", _D, "real", "ne_roman", "location", "tapai ko clinic kata cha"),
    ("d-118", _D, "real", "ne_roman", "location", "location ani parking available cha ki nai"),
    ("d-119", _D, "real", "ne_roman", "pricing_question", "Hajur, teeth cleaning ko price kati ho, aru kunai discount xa?"),
    ("d-120", _D, "real", "ne_roman", "pricing_question", "Implant ko price kati ho ek tooth ko lagi?"),
    ("d-121", _D, "real", "ne_roman", "booking", "Root Canal garnu parla appoiment book garnu ta"),
    ("d-122", _D, "real", "ne_roman", "booking", "bholi ko lagi appoiment book garnu paryo chaidai garnu paryo"),
    ("d-123", _D, "real", "ne_roman", "cancellation", "i am very very sorry hai mero out of vally janu paryo plz cancel gardenu hola  sorry next time pakka"),
    ("d-124", _D, "real", "ne_roman", "rescheduling", "reshudule garnu na k last emergency vayo tuesday lai"),
    ("d-125", _D, "real", "ne_roman", "appointment_status", "ea sachhi mero appointment ko time kati re kasto yad vayana"),
    ("d-126", _D, "real", "ne_roman", "resend_confirmation", "mero qr yeta pathau na milxa"),
    ("d-127", _D, "real", "ne_roman", "service_question", "Mero daath dukheko cha k garnu sakvhu"),
    ("d-128", _D, "real", "ne_roman", "complaint", "Kasto eautai kura repeat gareko hola"),
    ("d-129", _D, "real", "ne_roman", "human_handoff", "Plz tell you team to call me"),
    ("d-130", _D, "real", "ne_roman", "off_topic", "Who is the president of nepal"),
    ("d-131", _D, "real", "ne_roman", "service_question", "sunnu na mero teeth ali ali dukhay ko 2 din vayo check garau nai parxara?"),
    # ne_deva
    ("d-132", _D, "real", "ne_deva", "greeting", "नमस्ते"),
    ("d-133", _D, "real", "ne_deva", "general_question", "हेलो हामी नेपालीमा बोल्न सक्छौँ"),
    ("d-134", _D, "real", "ne_deva", "pricing_question", "नमस्ते, तपाईंको क्लिनिकमा क्लिनिङको लागि कति लाग्छ?"),
    ("d-135", _D, "real", "ne_deva", "booking", "ल छिटो अब अपोइन्टमेन्ट लिदिनुस न"),
    ("d-136", _D, "real", "ne_deva", "booking", "तपाईसँग कुन कुन समय चाहिँ अभलेबल छ यसो भन्न मिल्छ त"),
    ("d-137", _D, "real", "ne_deva", "booking", "मलाई आइतबार बिहान ११ बजे अपोइन्टमेन्ट बुक गर्नु छ।"),
    ("d-138", _D, "real", "ne_deva", "appointment_status", "मेरो अपोइन्टमेन्ट कतिको छ अरे"),
    ("d-139", _D, "real", "ne_deva", "cancellation", "होइन मेरो अपोइन्टमेन्ट क्यान्सल गरिदिनु क्या मलाई चाहिएन"),
    ("d-140", _D, "real", "ne_deva", "service_question", "मलाई नि कतिवटा सर्भिस छ सबै यसो लिस्टेड गरिदिनु न"),
    ("d-141", _D, "scripted", "ne_deva", "business_hours", "तपाईंको क्लिनिक शनिबार खुल्छ?"),
    ("d-142", _D, "scripted", "ne_deva", "location", "क्लिनिक कहाँ पर्छ? नजिकै कुनै चिनिने ठाउँ छ?"),
    ("d-143", _D, "scripted", "ne_deva", "rescheduling", "मेरो भोलिको अपोइन्टमेन्ट पर्सि सार्न मिल्छ?"),
    ("d-144", _D, "scripted", "ne_deva", "resend_confirmation", "मेरो अपोइन्टमेन्टको QR कोड फेरि पठाइदिनुस् न"),
    ("d-145", _D, "scripted", "ne_deva", "complaint", "गएको पटक दाँत सफा गरेपछि धेरै दुख्यो, कसैले ध्यान दिएन।"),
    ("d-146", _D, "scripted", "ne_deva", "human_handoff", "म कुनै मान्छेसँग कुरा गर्न चाहन्छु, डाक्टरसँग सिधै कुरा गराइदिनुस्।"),
    ("d-147", _D, "scripted", "ne_deva", "off_topic", "आज काठमाडौंमा मौसम कस्तो छ?"),
    ("d-148", _D, "scripted", "ne_deva", "service_question", "दाँत सेतो बनाउने सेवा छ? कति समय लाग्छ?"),
    ("d-149", _D, "scripted", "ne_deva", "pricing_question", "ब्रेसेस लगाउन जम्मा कति खर्च लाग्छ?"),
    # mixed
    ("d-150", _D, "real", "mixed", "cancellation", "cancel garau hai"),
    ("d-151", _D, "real", "mixed", "general_question", "Namaste, ma appointment ko barema sodhna chahanchu"),
    ("d-152", _D, "real", "mixed", "booking", "Bholi 10 baje available xa?"),
    ("d-153", _D, "scripted", "mixed", "service_question", "Mero wisdom tooth ekdam dukhirako cha, is it an emergency? Aaja nai herna milcha?"),

    # ---------------- Himalayan Trails Trekking Co. ----------------
    # en
    ("t-101", _T, "scripted", "en", "greeting", "Hi there!"),
    ("t-102", _T, "scripted", "en", "business_hours", "What time is your office open on Saturdays?"),
    ("t-103", _T, "scripted", "en", "location", "Where is your office? Can I just walk in?"),
    ("t-104", _T, "scripted", "en", "pricing_question", "How much is a private guide per day?"),
    ("t-105", _T, "real", "en", "service_question", "Do I need a guide for a short trek or can I go on my own?"),
    ("t-106", _T, "scripted", "en", "booking", "Can I book a free trek consultation for tomorrow at 2pm?"),
    ("t-107", _T, "scripted", "en", "rescheduling", "I need to push my gear pickup to Friday instead, is that possible?"),
    ("t-108", _T, "scripted", "en", "cancellation", "Please cancel my guide consultation, our plans changed."),
    ("t-109", _T, "scripted", "en", "appointment_status", "When is my trek consultation again?"),
    ("t-110", _T, "scripted", "en", "resend_confirmation", "I didn't receive the confirmation email for my consultation, can you resend it?"),
    ("t-111", _T, "scripted", "en", "complaint", "The sleeping bag we rented was torn and smelled awful."),
    ("t-112", _T, "scripted", "en", "human_handoff", "Can I talk to an actual person who has done the Manaslu trek?"),
    ("t-113", _T, "scripted", "en", "off_topic", "What's the exchange rate for dollars to rupees today?"),
    ("t-114", _T, "scripted", "en", "general_question", "Is it safe for a solo female traveler to trek with your company?"),
    # ne_roman
    ("t-115", _T, "scripted", "ne_roman", "greeting", "Namaste dai, k cha?"),
    ("t-116", _T, "scripted", "ne_roman", "business_hours", "office kati baje khulcha?"),
    ("t-117", _T, "scripted", "ne_roman", "location", "tapai ko office kata ho, Thamel ma ho?"),
    ("t-118", _T, "scripted", "ne_roman", "pricing_question", "private guide ko ek din ko kati parcha?"),
    ("t-119", _T, "scripted", "ne_roman", "pricing_question", "Everest base camp jana jamma kati kharcha lagcha?"),
    ("t-120", _T, "scripted", "ne_roman", "service_question", "Mardi Himal trek garna milcha? kati din lagcha?"),
    ("t-121", _T, "scripted", "ne_roman", "service_question", "sleeping bag ra down jacket rent ma paincha?"),
    ("t-122", _T, "scripted", "ne_roman", "booking", "bholi consultation ko lagi aauna milcha? 11 baje tira"),
    ("t-123", _T, "scripted", "ne_roman", "rescheduling", "mero gear pickup parsi lai sarna milcha?"),
    ("t-124", _T, "scripted", "ne_roman", "cancellation", "guide consultation cancel garidinu na, plan change bhayo"),
    ("t-125", _T, "scripted", "ne_roman", "appointment_status", "mero consultation kahile ho, birsiye"),
    ("t-126", _T, "scripted", "ne_roman", "resend_confirmation", "confirmation email aayena, feri pathaunu na"),
    ("t-127", _T, "scripted", "ne_roman", "complaint", "guide le ekdam rude behave garyo, yesto ta hunu bhayena ni"),
    ("t-128", _T, "scripted", "ne_roman", "human_handoff", "kunai staff sanga direct kura garna milcha?"),
    ("t-129", _T, "scripted", "ne_roman", "off_topic", "Nepal ko sabai vanda aglo jhil kun ho?"),
    ("t-130", _T, "scripted", "ne_roman", "general_question", "altitude sickness lagyo bhane k garne?"),
    # ne_deva
    ("t-131", _T, "scripted", "ne_deva", "greeting", "नमस्ते, ट्रेकको बारेमा सोध्न सक्छु?"),
    ("t-132", _T, "scripted", "ne_deva", "business_hours", "तपाईंको अफिस कति बजे खुल्छ?"),
    ("t-133", _T, "scripted", "ne_deva", "location", "तपाईंको अफिस कहाँ छ?"),
    ("t-134", _T, "scripted", "ne_deva", "pricing_question", "एभरेस्ट बेस क्याम्प ट्रेकको कति पर्छ?"),
    ("t-135", _T, "scripted", "ne_deva", "pricing_question", "गियर भाडामा लिन कति लाग्छ?"),
    ("t-136", _T, "scripted", "ne_deva", "service_question", "अन्नपूर्ण बेस क्याम्प ट्रेक कति दिनको हुन्छ?"),
    ("t-137", _T, "scripted", "ne_deva", "service_question", "पहिलो पटक ट्रेक गर्दैछु, कुन ट्रेक सजिलो होला?"),
    ("t-138", _T, "scripted", "ne_deva", "booking", "भोलि बिहान ट्रेक परामर्शको लागि समय मिल्छ?"),
    ("t-139", _T, "scripted", "ne_deva", "rescheduling", "मेरो परामर्श अर्को हप्तामा सार्न मिल्छ?"),
    ("t-140", _T, "scripted", "ne_deva", "cancellation", "मेरो गाइड बुकिङ परामर्श रद्द गरिदिनुस्।"),
    ("t-141", _T, "scripted", "ne_deva", "appointment_status", "मेरो परामर्श कहिले छ?"),
    ("t-142", _T, "scripted", "ne_deva", "resend_confirmation", "मेरो बुकिङको पुष्टि फेरि पठाइदिनुस्।"),
    ("t-143", _T, "scripted", "ne_deva", "complaint", "गाइड समयमा आएनन्, हामी दुई घण्टा कुर्यौं।"),
    ("t-144", _T, "scripted", "ne_deva", "human_handoff", "मलाई कुनै कर्मचारीसँग फोनमा कुरा गर्नु छ।"),
    ("t-145", _T, "scripted", "ne_deva", "off_topic", "नेपालको राजधानी कुन हो?"),
    ("t-146", _T, "scripted", "ne_deva", "general_question", "के हिउँदमा ट्रेक गर्न सुरक्षित हुन्छ?"),
    # mixed
    ("t-147", _T, "scripted", "mixed", "service_question", "Langtang trek ko lagi permit chahincha? How many days total?"),
    ("t-148", _T, "scripted", "mixed", "service_question", "Hi, ma first time trekking garna lageko, beginner friendly trek suggest garnu na"),
    ("t-149", _T, "scripted", "mixed", "location", "Gear pickup kaha bata garne? Office mai ho?"),

    # ---------------- Everest Pathways Consultancy ----------------
    # en
    ("s-101", _S, "scripted", "en", "greeting", "Good morning"),
    ("s-102", _S, "scripted", "en", "business_hours", "Are you open on Saturday?"),
    ("s-103", _S, "scripted", "en", "location", "Where is your office? Is it near Putalisadak?"),
    ("s-104", _S, "scripted", "en", "pricing_question", "How much does the university application review cost?"),
    ("s-105", _S, "scripted", "en", "service_question", "Do you help with scholarships for Canada?"),
    ("s-106", _S, "scripted", "en", "booking", "I'd like to book a free counseling session this Friday."),
    ("s-107", _S, "scripted", "en", "rescheduling", "Can I move my visa interview prep to next Tuesday?"),
    ("s-108", _S, "scripted", "en", "cancellation", "Please cancel my document evaluation appointment."),
    ("s-109", _S, "real", "en", "appointment_status", "When is my appointment"),
    ("s-110", _S, "scripted", "en", "resend_confirmation", "Can you resend my appointment QR code?"),
    ("s-111", _S, "scripted", "en", "complaint", "My counselor gave me the wrong IELTS requirement and now I missed the deadline."),
    ("s-112", _S, "scripted", "en", "human_handoff", "I want to speak with a senior counselor, not a bot."),
    ("s-113", _S, "real", "en", "off_topic", "What is the fee for BBA at Kathmandu Model College?"),
    ("s-114", _S, "scripted", "en", "general_question", "Is IELTS mandatory for Australia or can I use PTE?"),
    # ne_roman
    ("s-115", _S, "real", "ne_roman", "greeting", "k xa ho hal khabar"),
    ("s-116", _S, "real", "ne_roman", "general_question", "visa bala  k"),
    ("s-117", _S, "scripted", "ne_roman", "business_hours", "office kati baje samma khulla huncha?"),
    ("s-118", _S, "scripted", "ne_roman", "location", "tapai ko office kata cha? Putalisadak tira ho?"),
    ("s-119", _S, "scripted", "ne_roman", "pricing_question", "document evaluation ko kati lagcha?"),
    ("s-120", _S, "scripted", "ne_roman", "pricing_question", "visa interview preparation ko fee kati ho?"),
    ("s-121", _S, "scripted", "ne_roman", "service_question", "Canada ko lagi scholarship ma help garnu huncha?"),
    ("s-122", _S, "scripted", "ne_roman", "service_question", "IELTS 6 aayo, UK ma masters garna milcha?"),
    ("s-123", _S, "scripted", "ne_roman", "booking", "counseling session book garna milcha bholi 2 baje?"),
    ("s-124", _S, "scripted", "ne_roman", "rescheduling", "mero appointment arko hapta sarna milcha?"),
    ("s-125", _S, "real", "ne_roman", "cancellation", "Cancel it sorry mero bau le marna lagyo"),
    ("s-126", _S, "scripted", "ne_roman", "appointment_status", "mero counseling kahile ho hai?"),
    ("s-127", _S, "scripted", "ne_roman", "resend_confirmation", "mero appointment ko email aayena, feri pathaunu na"),
    ("s-128", _S, "scripted", "ne_roman", "complaint", "2 hapta bhayo kasaile phone gareko chaina, yo ke ho?"),
    ("s-129", _S, "scripted", "ne_roman", "human_handoff", "counselor sanga direct kura garna paryo"),
    ("s-130", _S, "scripted", "ne_roman", "off_topic", "cricket ko score kati bhayo aaja?"),
    # ne_deva
    ("s-131", _S, "scripted", "ne_deva", "greeting", "नमस्ते दाइ"),
    ("s-132", _S, "scripted", "ne_deva", "business_hours", "तपाईंको अफिस शनिबार खुल्छ?"),
    ("s-133", _S, "scripted", "ne_deva", "location", "तपाईंको अफिस कहाँ छ?"),
    ("s-134", _S, "scripted", "ne_deva", "pricing_question", "कागजात मूल्याङ्कनको शुल्क कति हो?"),
    ("s-135", _S, "scripted", "ne_deva", "pricing_question", "विश्वविद्यालय आवेदन समीक्षाको कति पर्छ?"),
    ("s-136", _S, "scripted", "ne_deva", "service_question", "अष्ट्रेलियामा नर्सिङ पढ्न के के चाहिन्छ?"),
    ("s-137", _S, "scripted", "ne_deva", "service_question", "क्यानडाको भिसा प्रक्रिया कति समय लाग्छ?"),
    ("s-138", _S, "scripted", "ne_deva", "booking", "निःशुल्क परामर्शको लागि भोलि आउन मिल्छ?"),
    ("s-139", _S, "scripted", "ne_deva", "rescheduling", "मेरो अपोइन्टमेन्ट अर्को हप्ता सार्न सकिन्छ?"),
    ("s-140", _S, "scripted", "ne_deva", "cancellation", "मेरो भिसा अन्तर्वार्ता तयारी रद्द गरिदिनुस्।"),
    ("s-141", _S, "scripted", "ne_deva", "appointment_status", "मेरो परामर्श कति बजे हो?"),
    ("s-142", _S, "scripted", "ne_deva", "resend_confirmation", "मलाई इमेल आएन, फेरि पठाइदिनुस्।"),
    ("s-143", _S, "scripted", "ne_deva", "complaint", "मैले शुल्क तिरें तर कसैले सम्पर्क गरेन।"),
    ("s-144", _S, "scripted", "ne_deva", "human_handoff", "मलाई कुनै काउन्सेलरसँग सिधै कुरा गर्नु छ।"),
    ("s-145", _S, "scripted", "ne_deva", "off_topic", "नेपालको प्रधानमन्त्री को हुनुहुन्छ?"),
    ("s-146", _S, "scripted", "ne_deva", "general_question", "IELTS बिना बेलायत जान मिल्छ?"),
    # mixed
    ("s-147", _S, "real", "mixed", "general_question", "hola kasto yo truth website ho"),
    ("s-148", _S, "scripted", "mixed", "service_question", "Hi, ma +2 science sakera Australia ma nursing padhna chahanchu, k k documents chaincha?"),
    ("s-149", _S, "scripted", "mixed", "service_question", "UK ma study gap 2 years cha, visa reject huncha ki?"),
]

CASES: list[dict] = [dict(c, lang=None, intent=None) for c in PHASE3_CASES] + [
    {"id": i, "business": b, "source": src, "lang": lang, "intent": intent, "message": msg}
    for i, b, src, lang, intent, msg in _NEW
]

if __name__ == "__main__":
    from collections import Counter

    assert len({c["id"] for c in CASES}) == len(CASES), "duplicate case id"
    print(len(CASES), Counter(c["business"] for c in CASES))
    print(Counter(c["lang"] for c in CASES), Counter(c["intent"] for c in CASES))
