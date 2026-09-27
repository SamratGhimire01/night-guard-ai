import re

from app.schemas.conversation import ConversationLanguage

# Phase 25 urgent fix: real testing showed the agent inconsistently switching
# between English, Devanagari Nepali, and Roman Nepali within one conversation
# — including in the deterministic Python-composed sentences below, which were
# always hardcoded English regardless of the conversation's actual locked
# language (Conversation.detected_language, see orchestrator.py). This module
# is the ONLY place those sentences are translated — same discipline as every
# _format_*_result function never trusting the LLM to compose them: the
# scaffold text is chosen deterministically by lookup, never generated.
#
# "mixed" (genuinely code-mixed Nepali/English customers) deliberately reuses
# the ne_roman set rather than a hand-authored fourth variant: a customer who
# code-mixes already reads Romanized Nepali fluently by definition, and a
# scripted "genuinely code-mixed" template would just be an arbitrary,
# inconsistent blend a real receptionist wouldn't actually produce on purpose
# — documented judgment call, see PHASE_STATUS.md Phase 25.
#
# Known, deliberate simplification (documented, not hidden): only the fixed
# scaffold wording is translated. Data embedded inside it — service names,
# formatted dates/times (weekday/month names stay English), appointment/
# booking IDs, raw tool failure `message` strings from deeper service-layer
# exceptions, appointment status words (confirmed/cancelled/...), and
# customer-supplied group-booking labels ("my wife") — is passed through
# as-is. Real Nepali customers already got English service names/prices
# mixed into otherwise-Nepali sentences in Phase 9's own eval transcript
# (case #10/#11) without reading as broken; full localization of dates and
# tool-internal error strings is a much larger, separate task, not scoped
# here.


def _key(language: str | None) -> str:
    if language == ConversationLanguage.NE_DEVA.value:
        return "ne_deva"
    if language in (ConversationLanguage.NE_ROMAN.value, ConversationLanguage.MIXED.value):
        return "ne_roman"
    return "en"


TEMPLATES: dict[str, dict[str, str]] = {
    "booking_success": {
        "en": "You're all set{who}! I've booked {service} for {when} ({duration} min). Your booking ID is {id}.",
        "ne_deva": "तपाईंको बुकिङ भइसक्यो{who}! मैले {when} ({duration} मिनेट) को लागि {service} बुक गरिदिएँ। तपाईंको बुकिङ आईडी {id} हो।",
        "ne_roman": "Sabai milyo{who}! Maile {when} ({duration} minute) ko lagi {service} book gari diye. Tapaiko booking ID {id} ho.",
    },
    "booking_unavailable_with_alts": {
        "en": (
            "That time isn't available anymore{who} — {message}. Here are some other openings "
            "for {service}: {options}. Would any of those work?"
        ),
        "ne_deva": (
            "त्यो समय अब उपलब्ध छैन{who} — {message}। {service} का लागि अरू केही उपलब्ध समयहरू यी हुन्: "
            "{options}। यीमध्ये कुनै मिल्छ?"
        ),
        "ne_roman": (
            "Tyo samaya ahile available chaina{who} — {message}. {service} ko lagi aru kehi available "
            "samaya haru: {options}. Yi madhye kunai milcha?"
        ),
    },
    "booking_unavailable_no_alts": {
        "en": (
            "That time isn't available anymore{who} — {message}. I don't see any other openings for "
            "{service} in the next week — would you like me to connect you with our team instead?"
        ),
        "ne_deva": (
            "त्यो समय अब उपलब्ध छैन{who} — {message}। आगामी हप्तामा {service} का लागि अरू कुनै खाली समय "
            "देखिँदैन — के म तपाईंलाई हाम्रो टिमसँग जोडिदिऊँ?"
        ),
        "ne_roman": (
            "Tyo samaya ahile available chaina{who} — {message}. Aagami hapta ma {service} ko lagi aru "
            "kunai khali samaya dekhindaina — ma tapailai hamro team sanga jodidiu?"
        ),
    },
    "group_intro_success": {
        "en": "You're all set{who}! Here's what I booked:",
        "ne_deva": "तपाईंहरू सबैको बुकिङ भइसक्यो{who}! मैले यी बुक गरेँ:",
        "ne_roman": "Sabaiko booking bhaisakyo{who}! Maile yi book gare:",
    },
    "group_intro_all_or_nothing_fail": {
        "en": (
            "I wasn't able to get everyone in{who}, and since you wanted it all together, I didn't "
            "book anyone yet:"
        ),
        "ne_deva": (
            "मैले सबैलाई मिलाउन सकिनँ{who}, र तपाईंले सबैलाई सँगै चाहनुभएकोले, अहिलेसम्म कसैको पनि बुकिङ गरिनँ:"
        ),
        "ne_roman": (
            "Maile sabailai milauna sakina{who}, ra tapaile sabailai sangai chahanu bhayeko le, ahile "
            "samma kasaiko pani booking gariina:"
        ),
    },
    "group_intro_partial": {
        "en": "Here's where things stand{who} — some went through, some didn't:",
        "ne_deva": "अहिलेको अवस्था यस्तो छ{who} — केही भयो, केही भएन:",
        "ne_roman": "Ahileko awastha yasto cha{who} — kehi bhayo, kehi bhena:",
    },
    "group_line_success": {
        "en": "{people}: {service_name} on {when} ({duration} min, booking ID {id})",
        "ne_deva": "{people}: {when} मा {service_name} ({duration} मिनेट, बुकिङ आईडी {id})",
        "ne_roman": "{people}: {when} ma {service_name} ({duration} minute, booking ID {id})",
    },
    "group_line_fail": {
        "en": "{people}: not booked — {message}",
        "ne_deva": "{people}: बुक भएन — {message}",
        "ne_roman": "{people}: book bhaena — {message}",
    },
    "cancellation_success": {
        "en": "Done{who} — your appointment on {when} has been cancelled.",
        "ne_deva": "भइहाल्यो{who} — तपाईंको {when} को अपोइन्टमेन्ट रद्द गरियो।",
        "ne_roman": "Bhaihalyo{who} — tapaiko {when} ko appointment cancel gariyo.",
    },
    "cancellation_fail": {
        "en": "I couldn't cancel that{who} — {message}.",
        "ne_deva": "मैले त्यो रद्द गर्न सकिनँ{who} — {message}।",
        "ne_roman": "Maile tyo cancel garna sakina{who} — {message}.",
    },
    "reschedule_success": {
        "en": "All set{who} — your appointment has been moved to {when}.",
        "ne_deva": "भइहाल्यो{who} — तपाईंको अपोइन्टमेन्ट {when} मा सारियो।",
        "ne_roman": "Bhaihalyo{who} — tapaiko appointment {when} ma sariyo.",
    },
    "reschedule_fail": {
        "en": "I couldn't reschedule that{who} — {message}.",
        "ne_deva": "मैले त्यो सार्न सकिनँ{who} — {message}।",
        "ne_roman": "Maile tyo sarna sakina{who} — {message}.",
    },
    "status_none": {
        "en": "You don't have any appointments on file with us right now{who}.",
        "ne_deva": "अहिले तपाईंको हामीसँग कुनै अपोइन्टमेन्ट रेकर्डमा छैन{who}।",
        "ne_roman": "Ahile tapaiko hamisanga kunai appointment record chaina{who}.",
    },
    "status_no_active": {
        "en": "You don't have any upcoming appointments right now{who}.",
        "ne_deva": "अहिले तपाईंको कुनै आगामी अपोइन्टमेन्ट छैन{who}।",
        "ne_roman": "Ahile tapaiko kunai aagami appointment chaina{who}.",
    },
    # Real conversation-quality spec-conformance finding (PHASE_STATUS.md,
    # §11 — a simple "is my 2pm still on?" confirmation should read as brief
    # as "Huss, 2 PM ko appointment raicha," not a formal status readout):
    # shortened from "You have one upcoming appointment{who}: {desc}, status:
    # {status}." — same real facts (desc already includes service/time/id),
    # less wrapper.
    "status_one_active": {
        "en": "{desc}{who} — {status}.",
        "ne_deva": "{desc}{who} — {status}।",
        "ne_roman": "{desc}{who} — {status}.",
    },
    "status_multi_active": {
        "en": "You have {n} upcoming appointments{who}: {lines}.",
        "ne_deva": "तपाईंका {n} वटा आगामी अपोइन्टमेन्टहरू छन्{who}: {lines}।",
        "ne_roman": "Tapaika {n} wota aagami appointment haru chan{who}: {lines}.",
    },
    "status_recent_past": {
        "en": "Also on file (most recent): {lines}.",
        "ne_deva": "रेकर्डमा यी पनि छन् (सबैभन्दा हालैका): {lines}।",
        "ne_roman": "Record ma yi pani chan (sabaibhanda haile ka): {lines}.",
    },
    "status_describe": {
        "en": "{service} on {when} (booking ID {id})",
        "ne_deva": "{when} मा {service} (बुकिङ आईडी {id})",
        "ne_roman": "{when} ma {service} (booking ID {id})",
    },
    "off_topic": {
        "en": (
            "I'm just here to help with things related to {name} — appointments, services, hours, "
            "and the like. Is there something about that I can help with?"
        ),
        "ne_deva": (
            "म यहाँ {name} सँग सम्बन्धित कुराहरूमा मात्र मद्दत गर्न छु — जस्तै अपोइन्टमेन्ट, सेवाहरू, समय, आदि। "
            "के त्यससम्बन्धी केही सोध्नुहुन्छ?"
        ),
        "ne_roman": (
            "Ma yaha {name} sanga related kura haru ma matra madat garna chu — jasto appointment, "
            "service haru, time, aadi. Tyo sambandhi kehi sodhnu huncha?"
        ),
    },
    "booking_no_contact": {
        "en": (
            "Before I can get that booked, I'll need a way to reach you to confirm it — could you "
            "give me your name and a phone number or email?"
        ),
        "ne_deva": (
            "त्यो बुक गर्नुअघि, पुष्टि गर्न तपाईंलाई सम्पर्क गर्ने माध्यम चाहिन्छ — कृपया तपाईंको नाम र फोन नम्बर "
            "वा इमेल दिनुहोस्?"
        ),
        "ne_roman": (
            "Tyo book garnu aghi, confirm garna tapailai contact garne madhyam chahincha — kripaya "
            "tapaiko naam ra phone number wa email dinuhos?"
        ),
    },
    "booking_clarify": {
        "en": (
            "Sorry, I want to make sure I get this right — could you tell me exactly which service, "
            "and the date and time you'd like?"
        ),
        "ne_deva": (
            "माफ गर्नुहोस्, मैले ठीकसँग बुझ्न चाहन्छु — कुन सेवा, र कुन मिति र समय चाहनुहुन्छ भनेर बताउनुहुन्छ?"
        ),
        "ne_roman": (
            "Maaf garnuhos, maile thik sanga bujhna chahanchu — kun service, ra kun miti ra samaya "
            "chahanu huncha bhanera batauna sakinu huncha?"
        ),
    },
    "group_booking_clarify": {
        "en": (
            "Sorry, I want to make sure I get everyone booked correctly — could you confirm the "
            "exact service, date, and time for each person?"
        ),
        "ne_deva": (
            "माफ गर्नुहोस्, मैले सबैको बुकिङ ठीकसँग गर्न चाहन्छु — हरेक व्यक्तिको लागि सेवा, मिति र समय "
            "पुष्टि गरिदिनुहुन्छ?"
        ),
        "ne_roman": (
            "Maaf garnuhos, maile sabaiko booking thik sanga garna chahanchu — harek vyakti ko lagi "
            "service, miti ra samaya confirm garidinu huncha?"
        ),
    },
    "cancellation_clarify": {
        "en": (
            "Sorry, I want to make sure I cancel the right one — could you tell me which appointment "
            "(service and date) you'd like to cancel?"
        ),
        "ne_deva": (
            "माफ गर्नुहोस्, मैले सही अपोइन्टमेन्ट रद्द गर्न चाहन्छु — कुन अपोइन्टमेन्ट (सेवा र मिति) रद्द गर्ने हो "
            "भनी बताउनुहुन्छ?"
        ),
        "ne_roman": (
            "Maaf garnuhos, maile sahi appointment cancel garna chahanchu — kun appointment (service "
            "ra miti) cancel garne ho bhanera batauna sakinu huncha?"
        ),
    },
    "reschedule_clarify": {
        "en": (
            "Sorry, I want to make sure I get this right — which appointment would you like to move, "
            "and to what new date and time?"
        ),
        "ne_deva": (
            "माफ गर्नुहोस्, मैले ठीकसँग गर्न चाहन्छु — कुन अपोइन्टमेन्ट सार्ने हो, र कुन नयाँ मिति र समयमा?"
        ),
        "ne_roman": (
            "Maaf garnuhos, maile thik sanga garna chahanchu — kun appointment sarne ho, ra kun naya "
            "miti ra samaya ma?"
        ),
    },
    "contact_updated": {
        "en": "I've updated your contact info on file.",
        "ne_deva": "मैले तपाईंको सम्पर्क जानकारी अद्यावधिक गरेँ।",
        "ne_roman": "Maile tapaiko contact information update gare.",
    },
    "contact_resent": {
        "en": "I also resent your appointment confirmation — you should receive it shortly.",
        "ne_deva": "मैले तपाईंको अपोइन्टमेन्ट पुष्टि पनि फेरि पठाएँ — छिट्टै प्राप्त हुनेछ।",
        "ne_roman": "Maile tapaiko appointment confirmation feri pathaye — chittai prapta huncha.",
    },
    # A customer's explicit "(re)send my confirmation/QR" request
    # (ResendConfirmationTool) — deliberately separate wording from
    # contact_resent above, which fires as a side effect of a contact-info
    # update, not a direct request, and doesn't need to report per-channel
    # detail or a rate limit the way this one does.
    "resend_email_sent": {
        "en": "Sent! Your appointment confirmation and QR code are on their way to {to} — the email we have on file.",
        "ne_deva": "पठाइयो! तपाईंको अपोइन्टमेन्ट पुष्टि र QR कोड {to} मा जाँदैछ — हामीसँग रेकर्डमा भएको इमेल।",
        "ne_roman": "Pathaiyo! Tapaiko appointment confirmation ra QR code {to} ma jaandai cha — hamisanga record ma bhayeko email.",
    },
    # "QR in chat": a signed, expiring link to the QR page (qr_link_service). Deliberately just a URL on its own line —
    # WhatsApp/Messenger/Instagram auto-link it and the widget linkifies it, so every channel gets the same plain link.
    "resend_qr_link": {
        "en": "Here's your check-in QR code — open the link and show it at the front desk:\n{url}",
        "ne_deva": "यो तपाईंको चेक-इन QR कोड हो — लिङ्क खोलेर फ्रन्ट डेस्कमा देखाउनुहोस्:\n{url}",
        "ne_roman": "Yo tapaiko check-in QR code ho — link kholera front desk ma dekhaunuhos:\n{url}",
    },
    # Appended on a resend turn when the customer's message ALSO carried a different email/phone: a resend only ever
    # goes to the contact details already on file (never a destination typed into the chat); changing them is its own
    # separate request.
    "resend_contact_change_ignored": {
        "en": (
            "For your security I can only send this to the contact details already on file, so I didn't use the new "
            "one. If you'd like to change them, tell me separately (for example \"update my email to …\")."
        ),
        "ne_deva": (
            "सुरक्षाका लागि म यो रेकर्डमा भएको सम्पर्क विवरणमा मात्र पठाउन सक्छु, त्यसैले नयाँ विवरण प्रयोग गरिनँ। "
            "बदल्न चाहनुहुन्छ भने छुट्टै भन्नुहोस् (जस्तै \"मेरो इमेल … मा बदल्नुहोस्\")।"
        ),
        "ne_roman": (
            "Surakshako lagi ma yo record ma bhayeko contact details ma matra pathauna sakchu, tesaile naya details "
            "prayog garina. Badalna chahanu huncha bhane chhutte bhannuhos (jastai \"mero email … ma badalideu\")."
        ),
    },
    "resend_no_recipient": {
        "en": "I don't have a {channels} on file for you yet — could you give me one?",
        "ne_deva": "मसँग तपाईंको {channels} रेकर्डमा छैन — एउटा दिनुहुन्छ?",
        "ne_roman": "Masanga tapaiko {channels} record ma chaina — euta dinuhuncha?",
    },
    "resend_not_connected": {
        "en": "WhatsApp sending isn't set up on our end right now — let me connect you with our front desk instead.",
        "ne_deva": "अहिले हाम्रोतर्फ WhatsApp पठाउने व्यवस्था मिलेको छैन — म तपाईंलाई हाम्रो फ्रन्ट डेस्कसँग जोडिदिन्छु।",
        "ne_roman": "Ahile hamro tarfa WhatsApp pathaune byabastha mileko chaina — ma tapailai hamro front desk sanga jodidinchu.",
    },
    "resend_send_failed": {
        "en": "Something went wrong sending that just now — let me connect you with our front desk instead.",
        "ne_deva": "अहिले पठाउँदा केही समस्या भयो — म तपाईंलाई हाम्रो फ्रन्ट डेस्कसँग जोडिदिन्छु।",
        "ne_roman": "Ahile pathauda kehi samasya bhayo — ma tapailai hamro front desk sanga jodidinchu.",
    },
    "resend_rate_limited": {
        "en": "You've already received this several times — let me connect you with our front desk instead.",
        "ne_deva": "तपाईंले यो पहिले नै धेरैपटक पाउनुभएको छ — म तपाईंलाई हाम्रो फ्रन्ट डेस्कसँग जोडिदिन्छु।",
        "ne_roman": "Tapaile yo pahile nai dherai patak paunu bhayeko cha — ma tapailai hamro front desk sanga jodidinchu.",
    },
    "resend_fail": {
        "en": "I couldn't do that — {message}.",
        "ne_deva": "म त्यो गर्न सकिनँ — {message}।",
        "ne_roman": "Ma tyo garna sakina — {message}.",
    },
    "resend_clarify": {
        "en": (
            "Sorry, I want to make sure I send the right one — could you tell me which appointment "
            "(service and date) you mean?"
        ),
        "ne_deva": (
            "माफ गर्नुहोस्, मैले सही अपोइन्टमेन्टमा पठाउन चाहन्छु — कुन अपोइन्टमेन्ट (सेवा र मिति) हो "
            "भनी बताउनुहुन्छ?"
        ),
        "ne_roman": (
            "Maaf garnuhos, maile sahi appointment ma pathauna chahanchu — kun appointment (service "
            "ra miti) ho bhanera batauna sakinu huncha?"
        ),
    },
    # Real gap found live (PHASE_STATUS.md, "silent service switch"): the ONLY
    # place a booking-draft field switch (a genuinely NEW value replacing a
    # different, already-known one — never a first-time fill-in) is
    # acknowledged. A brief factual statement, never a question — see
    # orchestrator._merge_booking_draft's own docstring for why this must
    # never become a new blocking confirmation round-trip.
    "booking_draft_switch": {
        "en": "Switching to {new} instead of {old}.",
        "ne_deva": "{old} को सट्टा {new}।",
        "ne_roman": "{old} ko sattama {new}.",
    },
    # Phase 47: a booking whose service requires a deposit. The appointment IS reserved in the database at once (a
    # gateway problem must never block a real booking — Phase 44), but the customer hasn't paid, so this deliberately
    # does NOT say "you're all set"/"confirmed" and mentions the booking id once, low-key, as a reference. The
    # definitive confirmation is `payment_received` below, sent only after the gateway itself confirms the deposit.
    # Used INSTEAD of booking_success (no-deposit bookings keep booking_success untouched). `{qr}` is the QR page link.
    "booking_reserved_pay": {
        "en": (
            "Great{who}, I've reserved {service} for {when}. To lock it in, please complete your {currency} {amount} "
            "deposit here: {link}\nOr scan it with your phone: {qr}\nThe remaining {currency} {remaining} is due "
            "in person. I'll confirm everything once the deposit is received. (Ref: {id})"
        ),
        "ne_deva": (
            "ठीक छ{who}, मैले {when} को लागि {service} रिजर्भ गरिदिएँ। यसलाई पक्का गर्न कृपया {currency} {amount} "
            "डिपोजिट यहाँ तिर्नुहोस्: {link}\nवा फोनले स्क्यान गर्नुहोस्: {qr}\nबाँकी {currency} {remaining} "
            "आएर तिर्नुहोस्। डिपोजिट प्राप्त भएपछि म सबै पुष्टि गर्नेछु। (सन्दर्भ: {id})"
        ),
        "ne_roman": (
            "Huncha{who}, maile {when} ko lagi {service} reserve gari diye. Yo pakka garna kripaya {currency} {amount} "
            "deposit yaha tirnuhos: {link}\nYa phone le scan garnuhos: {qr}\nBaki {currency} {remaining} aera "
            "tirnuhos. Deposit prapta bhayepachi ma sabai confirm garchhu. (Ref: {id})"
        ),
    },
    # Same, when the business offers both eSewa and Khalti and the customer hasn't picked yet — the answer is read by
    # orchestrator._payment_choice_turn, which replies with `payment_link_chosen`.
    "booking_reserved_choose": {
        "en": (
            "Great{who}, I've reserved {service} for {when}. To lock it in, a {currency} {amount} deposit is needed "
            "(the remaining {currency} {remaining} is due in person) — would you like to pay with eSewa or Khalti? "
            "I'll confirm everything once it's received. (Ref: {id})"
        ),
        "ne_deva": (
            "ठीक छ{who}, मैले {when} को लागि {service} रिजर्भ गरिदिएँ। यसलाई पक्का गर्न {currency} {amount} डिपोजिट "
            "चाहिन्छ (बाँकी {currency} {remaining} आएर तिर्नुहोस्) — eSewa वा Khalti मध्ये कुनबाट तिर्न "
            "चाहनुहुन्छ? प्राप्त भएपछि म सबै पुष्टि गर्नेछु। (सन्दर्भ: {id})"
        ),
        "ne_roman": (
            "Huncha{who}, maile {when} ko lagi {service} reserve gari diye. Yo pakka garna {currency} {amount} deposit "
            "chahincha (baki {currency} {remaining} aera tirnuhos) — eSewa ki Khalti, kunbata tirna "
            "chahanuhuncha? Prapta bhayepachi ma sabai confirm garchhu. (Ref: {id})"
        ),
    },
    # Richer booking confirmation (same detail level as the confirmation email): lines appended under booking_success /
    # booking_reserved_* by orchestrator._confirmation_extras, each only when its real data exists. `{url}` is the signed
    # check-in QR page (qr_link_service — the same link a resend request returns), `{email}` the MASKED on-file address
    # (never the raw one, exactly like a resend) and only ever shown when the confirmation email was really sent.
    "booking_for": {
        "en": "Booked for: {customer}",
        "ne_deva": "बुकिङ गरिएको: {customer}",
        "ne_roman": "Tapaiko naam ma: {customer}",
    },
    "booking_where": {
        "en": "Where: {place}",
        "ne_deva": "कहाँ: {place}",
        "ne_roman": "Kahan: {place}",
    },
    "booking_checkin_qr": {
        "en": "Your check-in QR (show it at the front desk when you arrive): {url}",
        "ne_deva": "तपाईंको चेक-इन QR (आउँदा फ्रन्ट डेस्कमा देखाउनुहोस्): {url}",
        "ne_roman": "Tapaiko check-in QR (aauda front desk ma dekhaunuhos): {url}",
    },
    "booking_email_note": {
        "en": "A copy of these details, with your check-in QR, is also in your email ({email}).",
        "ne_deva": "यी विवरणहरू र तपाईंको चेक-इन QR को प्रतिलिपि तपाईंको इमेल ({email}) मा पनि पठाइएको छ।",
        "ne_roman": "Yi details ra tapaiko check-in QR ko copy tapaiko email ({email}) ma pani pathaiyeko cha.",
    },
    # A QR of the same real payment link, for a customer reading this on a laptop (scan it with a phone camera)
    # instead of tapping — a link to a small page showing it, same "QR in chat" delivery as resend_qr_link.
    "payment_qr_line": {
        "en": "Or scan it with your phone: {qr}",
        "ne_deva": "वा फोनले स्क्यान गर्नुहोस्: {qr}",
        "ne_roman": "Ya phone le scan garnuhos: {qr}",
    },
    # The customer named a gateway; this is the real link (and QR) that gateway just produced.
    "payment_link_chosen": {
        "en": "Great, here's your {provider} link for the {currency} {amount} deposit: {link}",
        "ne_deva": "हुन्छ, {currency} {amount} डिपोजिटका लागि तपाईंको {provider} लिङ्क: {link}",
        "ne_roman": "Huncha, {currency} {amount} deposit ko lagi tapaiko {provider} link: {link}",
    },
    # The gateway request could not be created (the booking itself is still confirmed).
    "payment_link_failed": {
        "en": "Sorry, I couldn't set up the {provider} payment just now. Your appointment is still confirmed — you can pay in person instead.",
        "ne_deva": "माफ गर्नुहोस्, अहिले {provider} भुक्तानी तयार गर्न सकिएन। तपाईंको अपोइन्टमेन्ट अझै पक्का छ — आएर तिर्न सक्नुहुन्छ।",
        "ne_roman": "Maaf garnuhos, ahile {provider} payment tayar garna sakiyena. Tapaiko appointment ajhai pakka cha — aera tirna saknuhuncha.",
    },
    # Sent by the system, unprompted, once the gateway's own independent lookup says the payment completed — the ONE
    # definitive confirmation of a deposit booking (booking_reserved_* above deliberately never says "confirmed"): the
    # strong "all set" wording, the time, the amount received and the booking id all live here.
    "payment_received": {
        "en": (
            "Payment received — you're all set{who}! Your {service} appointment on {when} is now confirmed. "
            "We got your {currency} {amount} deposit. Booking ID: {id}"
        ),
        "ne_deva": (
            "भुक्तानी प्राप्त भयो — तपाईंको बुकिङ भइसक्यो{who}! {when} को तपाईंको {service} अपोइन्टमेन्ट अब पक्का भयो। "
            "तपाईंको {currency} {amount} डिपोजिट प्राप्त भयो। बुकिङ आईडी: {id}"
        ),
        "ne_roman": (
            "Payment prapta bhayo — sabai milyo{who}! {when} ko tapaiko {service} appointment ab pakka bhayo. "
            "Tapaiko {currency} {amount} deposit prapta bhayo. Booking ID: {id}"
        ),
    },
    "handoff_addendum": {
        "en": "I've also let our team know, so a real person will follow up with you.",
        "ne_deva": "मैले हाम्रो टिमलाई पनि जानकारी दिएँ, त्यसैले एक जना साँच्चैको मान्छेले तपाईंलाई फलो-अप गर्नेछ।",
        "ne_roman": "Maile hamro team lai pani janakari diye, tyesaile euta sacchai ko manche le tapailai follow-up garnecha.",
    },
    # Root-cause fix for a confirmed missed_escalation bug (a stated 9/10 toothache with
    # overnight swelling got a plain contact-info request, no urgency at all) -- see
    # orchestrator._emergency_response's docstring. `{phone}` is either "" or
    # " at <business phone>", composed in code (never every language re-authoring the
    # conditional itself).
    "emergency_handoff": {
        "en": "This sounds like it needs urgent attention — please call us{phone} or visit us right away rather than waiting on chat. I've also flagged this conversation for our team.",
        "ne_deva": "यो त तुरुन्तै ध्यान दिनुपर्ने जस्तो देखिन्छ — कृपया चिया गफमा कुरा नगरी हामीलाई{phone} फोन गर्नुहोस् वा सीधै आउनुहोस्। मैले यो कुराकानी हाम्रो टिमलाई पनि जानकारी दिएको छु।",
        "ne_roman": "Yo ta turuntai dhyan dinu parne jasto dekhincha — kripaya chat ma nabasi hamilai{phone} phone garnuhos ya sidhai aaunuhos. Maile yo kurakani hamro team lai pani janakari diyeko chu.",
    },
    # Urgent fix (real 500 found live, PHASE_STATUS.md): the ONLY message ever
    # shown when the LLM/embedding provider call itself failed after its own
    # internal retries (app/llm/azure_openai.py) — no LLM call is available to
    # draft anything for this turn, so this is fully static, same discipline
    # as off_topic. Always followed by handoff_addendum (orchestrator always
    # creates a real HumanHandoff for this case), never shown alone.
    "provider_failure": {
        "en": "Sorry, I'm having trouble connecting on my end right now.",
        "ne_deva": "माफ गर्नुहोस्, अहिले मलाई जडान गर्न समस्या भइरहेको छ।",
        "ne_roman": "Maaf garnuhos, ahile malai connect garna samasya bhairaheko cha.",
    },
    # Phase 25a: composed only when 1 or 2 of {service, date, time} are still
    # missing from the persisted booking draft — see render_missing_slots.
    # All three missing reuses "booking_clarify" above instead (a fresh
    # "nothing known yet" opener reads more naturally than "Got it" with
    # nothing yet to have gotten).
    "booking_ask_missing": {
        "en": "Got it — could you tell me {missing}?",
        "ne_deva": "बुझें — कृपया मलाई {missing} बताउनुहुन्छ?",
        "ne_roman": "Bujhe — kripaya malai {missing} batauna sakinu huncha?",
    },
    # Phase 25a-2: composed only when the contact-info gate is holding AND at
    # least one of {service, date, time} is already known from the persisted
    # draft — see orchestrator._describe_known_booking_slots /
    # render_contact_gate. "booking_no_contact" above is still used verbatim
    # when NOTHING is known yet (turn 1, before any slot has been given).
    "booking_gate_with_progress": {
        "en": "Got it — {summary}. I just need your name and a phone number or email to lock that in.",
        "ne_deva": "बुझें — {summary}। लक गर्न मलाई तपाईंको नाम र फोन नम्बर वा इमेल चाहिन्छ।",
        "ne_roman": "Bujhe — {summary}. Lock garna malai tapaiko naam ra phone number wa email chahincha.",
    },
    # Phase 33: composed when the customer wants to see real options rather
    # than name a time themselves (orchestrator._propose_available_slots) —
    # `options` is a real, freshly-computed get_available_slots list, never
    # invented. Used when at least one real opening exists in the searched
    # window and (if the customer named a specific day) that day is one of
    # the ones actually on offer.
    "availability_options": {
        "en": "Here's what's open for {service}: {options}. Which works for you?",
        "ne_deva": "{service} का लागि यी समयहरू खाली छन्: {options}। कुन मिल्छ?",
        "ne_roman": "{service} ko lagi yi samaya haru khali chan: {options}. Kun milcha?",
    },
    # Prepended to availability_options/availability_none_with_next_day/
    # availability_none_no_alts when the customer named a specific time that
    # turned out to be already taken (the pre-flight same_day_slots check in
    # orchestrator.py caught it before ever attempting the booking) -- never
    # silently pivot straight to alternatives without acknowledging the
    # specific request failed, especially when the LLM's own drafted text may
    # have implied success.
    "requested_time_unavailable": {
        "en": "That time isn't available anymore.",
        "ne_deva": "त्यो समय अब उपलब्ध छैन।",
        "ne_roman": "Tyo samaya ahile available chaina.",
    },
    # The customer answered a slot list without naming a time ("does that work?", "book that for me") and the list
    # would have been repeated word for word -- ask for the one missing piece instead.
    "availability_pick_one": {
        "en": "Yes, that day works. Those are the times still open: {options}. Just tell me which one you'd like (say the time, or \"the first one\") and I'll book it.",
        "ne_deva": "हुन्छ, त्यो दिन मिल्छ। अझै खाली समयहरू: {options}। कुन समय चाहिन्छ भन्नुहोस् (समय वा \"पहिलो\") र म बुक गरिदिन्छु।",
        "ne_roman": "Huncha, tyo din milcha. Ajhai khali samaya haru: {options}. Kun samaya chahinchha bhanuhos (samaya ya \"pahilo\") ra ma book gari dinchu.",
    },
    # Phase 33: the honest "that specific day has nothing, here's the real
    # next opening" case — required so a fully-booked/closed day is never
    # answered with a silent empty list or an invented slot.
    "availability_none_with_next_day": {
        "en": "There's nothing open for {service} on {requested} — the next real opening is {options}. Would any of those work?",
        "ne_deva": "{requested} मा {service} को लागि केही खाली छैन — अर्को वास्तविक खाली समय {options} हो। यीमध्ये कुनै मिल्छ?",
        "ne_roman": "{requested} ma {service} ko lagi kehi khali chaina — arko real khali samaya {options} ho. Yi madhye kunai milcha?",
    },
    # Phase 33: no real opening at all anywhere in the searched window —
    # never shown as an empty list, always an honest statement plus a
    # human-handoff offer instead of inventing a slot.
    "availability_none_no_alts": {
        "en": "I don't see any openings for {service} in the next little while — would you like me to connect you with our team instead?",
        "ne_deva": "अहिलेलाई {service} को लागि कुनै खाली समय देखिँदैन — के म तपाईंलाई हाम्रो टिमसँग जोडिदिऊँ?",
        "ne_roman": "Ahile lai {service} ko lagi kunai khali samaya dekhindaina — ma tapailai hamro team sanga jodidiu?",
    },
    # Phase 16 ("ask upfront" language mode): confirmation once the customer has named a language.
    "language_chosen": {
        "en": "Great, we'll continue in English. How can I help you today?",
        "ne_deva": "हुन्छ, नेपालीमा कुरा गरौँ। म तपाईंलाई कसरी मद्दत गर्न सक्छु?",
        "ne_roman": "Huncha, Nepali ma kura garaun. Ma tapailai kasari madat garna sakchu?",
    },
    # The honest fallback for fact_validator.check_response_facts: the LLM's drafted
    # reply stated a specific price/policy/hours/contact claim not backed by this
    # tenant's real config, and a regenerate attempt still didn't fix it. Never a
    # freehand guess at that point -- this fixed, translated sentence plus a real
    # handoff (see orchestrator._handle_turn) is the only thing sent instead.
    "unconfirmed_fact_fallback": {
        "en": "I don't want to guess on that one — let me get a real answer from the team and have them follow up with you.",
        "ne_deva": "त्यसमा म अड्कल गर्न चाहन्न — म टिमबाट सही जानकारी लिएर तपाईंलाई फलो-अप गराउँछु।",
        "ne_roman": "Tyo ma guess garna chahanna — ma team bata sahi jankari lera tapailai follow-up garauchu.",
    },
}

# Human-readable label for the "this conversation's locked language" line
# injected into the LLM's user prompt each turn (see intent.py) — never shown
# to the customer, just steers the model's own drafted text.
LANGUAGE_LABELS: dict[str, str] = {
    "en": "English",
    "ne_deva": 'Nepali, written in Devanagari script (नेपाली)',
    "ne_roman": 'Nepali, written in Romanized/Latin letters (e.g. "Timro naam k ho?")',
    "mixed": "code-mixed Nepali/English, the same natural blended style the customer uses",
}


def render(template_name: str, language: str | None, **kwargs: str) -> str:
    return TEMPLATES[template_name][_key(language)].format(**kwargs)


# Phase 25a: natural-language labels for the three booking-draft slots, and
# the joining word between them, used ONLY to compose the "what's still
# missing" question (render_missing_slots) — never anything else, so this
# stays a tiny, self-contained table rather than growing into a second
# translation system.
_MISSING_SLOT_LABELS: dict[str, dict[str, str]] = {
    "en": {"service": "which service", "date": "what date", "time": "what time"},
    "ne_deva": {"service": "कुन सेवा", "date": "कुन मिति", "time": "कुन समय"},
    "ne_roman": {"service": "kun service", "date": "kun miti", "time": "kun samaya"},
}
_MISSING_SLOT_JOINER: dict[str, str] = {"en": "and", "ne_deva": "र", "ne_roman": "ra"}


def render_missing_slots(missing: list[str], language: str | None) -> str:
    """Phase 25a — the ONLY place the "what's still needed to book" question
    is composed. `missing` is an ordered subset of ["service", "date",
    "time"] computed deterministically by orchestrator._booking_draft_missing
    from the real persisted draft state (never from the LLM's own judgment of
    what it still needs) — this is the fix for the infinite confirmation
    loop: the customer is asked for EXACTLY the piece(s) still missing, never
    a vague readiness question, and never a slot that's already filled."""
    if len(missing) == 3:
        return render("booking_clarify", language)
    lang_key = _key(language)
    labels = _MISSING_SLOT_LABELS[lang_key]
    joiner = _MISSING_SLOT_JOINER[lang_key]
    parts = [labels[m] for m in missing]
    if len(parts) == 1:
        joined = parts[0]
    else:
        joined = f"{parts[0]} {joiner} {parts[1]}"
    return render("booking_ask_missing", language, missing=joined)


def render_contact_gate(known_summary: str | None, language: str | None) -> str:
    """Phase 25a-2 — the ONLY place the contact-info gate sentence is
    composed. `known_summary` is a deterministic, already-formatted
    description of whatever the persisted booking draft already has (built by
    orchestrator._describe_known_booking_slots), or None when nothing has
    been given yet. Fixes the "feels robotic" regression: the gate must
    visibly acknowledge real progress instead of repeating one identical
    sentence turn after turn while the customer keeps supplying new info."""
    if known_summary is None:
        return render("booking_no_contact", language)
    return render("booking_gate_with_progress", language, summary=known_summary)


_HOURS_WEEKDAY_NAMES: dict[str, list[str]] = {
    "en": ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"],
    "ne_deva": ["सोमबार", "मंगलबार", "बुधबार", "बिहीबार", "शुक्रबार", "शनिबार", "आइतबार"],
    "ne_roman": ["Sombar", "Mangalbar", "Budhabar", "Bihibar", "Sukrabar", "Sanibar", "Aitabar"],
}
_HOURS_CLOSED_LABEL = {"en": "Closed", "ne_deva": "बन्द", "ne_roman": "Bandha"}
_HOURS_INTRO = {
    "en": "Our hours are: {days}",
    "ne_deva": "हाम्रो खुल्ने समय: {days}",
    "ne_roman": "Hamro khulne samaya: {days}",
}
# One of these ends EVERY day-group (see describe_business_hours) -- confirmed regression
# (full 615-case live regression run): fact_validator.check_weekday_hours splits a reply
# into clauses on sentence-ending punctuation only (by design -- see its own docstring on
# why it must NOT split on a bare comma), so a single comma-joined sentence naming several
# days ("Monday-Friday: 9-6, Saturday: Closed, Sunday: 10-6") is ONE clause to it -- and it
# then (wrongly) attributes Saturday's "Closed" to every OTHER day named in that same
# clause too. Ending each day-group with real sentence punctuation makes each one its own
# clause, so the shared-checker function scopes "closed" to the day it actually describes.
_HOURS_SENTENCE_END = {"en": ".", "ne_deva": "।", "ne_roman": "."}
_HOURS_NOT_CONFIGURED = {
    "en": "I don't have our hours on file yet — let me connect you with our team for that.",
    "ne_deva": "हामीसँग अहिले खुल्ने समयको जानकारी दर्ता छैन — म तपाईंलाई हाम्रो टिमसँग जोड्छु।",
    "ne_roman": "Hamisanga ahile khulne samayako jankari darta chaina — ma tapailai hamro team sanga jodxu.",
}


def describe_business_hours(hours: list, language: str | None) -> str:
    """The ONLY place a customer-facing "what are your hours" answer is composed --
    deterministic, read straight off the real per-day `BusinessHours` rows, never LLM
    narration. Root-cause fix for a confirmed, reproduced live bug: handed the correct
    hours as plain context and left to draft its own sentence, the model stated "Saturday
    AND Sunday closed" for a tenant configured with Sunday OPEN (only Saturday closed) --
    its own "weekend = Sat+Sun" world knowledge overriding the real data it was given. Same
    principle as every other tool-backed intent in this module: a fact this deterministic is
    read out of the real row data directly, never left for the model to (mis)recall.
    `hours`: BusinessHours rows (day_of_week 0=Monday..6=Sunday, see business_hours_service).
    """
    lang_key = _key(language)
    if not hours:
        return _HOURS_NOT_CONFIGURED[lang_key]
    by_day = {h.day_of_week: h for h in hours}
    names = _HOURS_WEEKDAY_NAMES[lang_key]
    closed_label = _HOURS_CLOSED_LABEL[lang_key]

    def slot_for(day_index: int) -> str:
        h = by_day.get(day_index)
        if h is None or h.closed or h.open_time is None or h.close_time is None:
            return closed_label
        return f"{h.open_time.strftime('%-I:%M %p')} - {h.close_time.strftime('%-I:%M %p')}"

    sentence_end = _HOURS_SENTENCE_END[lang_key]
    slots = [slot_for(i) for i in range(7)]
    day_parts = []
    start = 0
    for i in range(1, 8):
        if i == 7 or slots[i] != slots[start]:
            label = names[start] if i - 1 == start else f"{names[start]}-{names[i - 1]}"
            day_parts.append(f"{label}: {slots[start]}{sentence_end}")
            start = i
    return _HOURS_INTRO[lang_key].format(days=" ".join(day_parts))


def render_language_question(business_name: str) -> str:
    """Phase 16 ("ask upfront" language mode) -- the first reply of a new conversation. Nothing is locked yet, so this is one
    fixed two-language line (English, then Devanagari Nepali) that every customer can read whichever they prefer."""
    return (
        f"Welcome to {business_name}! Which language would you like to chat in — English or Nepali?\n\n"
        f"{business_name} मा स्वागत छ! तपाईं कुन भाषामा कुरा गर्न चाहनुहुन्छ — English कि नेपाली?"
    )


_CHOICE_WORD_RE = re.compile(r"[A-Za-z]+|[ऀ-ॿ]+")
_ENGLISH_WORDS = ("english", "inglish", "angrezi", "angreji", "अंग्रेजी", "अङ्ग्रेजी", "अंग्रेज़ी", "इङ्लिश", "इंग्लिश")
_NEPALI_WORDS = ("nepali", "nepalese", "नेपाली")
_MAX_ANSWER_WORDS = 6


def parse_language_choice(text: str) -> str | None:
    """Phase 16 -- read the customer's answer to the language question: "en", "ne_deva" or "ne_roman", or None when the message
    is not a plain answer (a real question, both languages named, or no language named at all). Only a SHORT message that names
    exactly one of English / Nepali counts, so "English please" locks English while "what is the price of a cleaning in
    English?" is left for the normal flow. Nepali typed in Latin letters locks Romanized Nepali; Devanagari script (typed, or
    asked for by name) locks Devanagari."""
    words = [w.lower() for w in _CHOICE_WORD_RE.findall(text)]
    if not words or len(words) > _MAX_ANSWER_WORDS:
        return None
    english = any(w.startswith(e) for w in words for e in _ENGLISH_WORDS)
    nepali = any(w.startswith(n) for w in words for n in _NEPALI_WORDS)
    if english == nepali:
        return None
    if english:
        return "en"
    devanagari = bool(re.search(r"[ऀ-ॿ]", text)) or any(w.startswith(("devanagari", "देवनागरी")) for w in words)
    return "ne_deva" if devanagari else "ne_roman"
