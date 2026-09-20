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
    # Phase 44: appended to booking_success ONLY when a real Payment row was
    # actually created for this booking (payment_service.
    # create_payment_for_appointment — Premium + payment collection enabled
    # + this specific service has deposit_enabled=true). Always states the
    # real percentage and both real amounts (deposit now, remainder at the
    # clinic) — never a bare number with no context, since only some
    # services require a deposit and a customer seeing this for the first
    # time has no other way to know why.
    "payment_deposit_required": {
        "en": (
            "A {percentage}% deposit of {currency} {amount} is required to confirm this appointment "
            "— the remaining {currency} {remaining} is due at the clinic. Pay here: {link}"
        ),
        "ne_deva": (
            "यो अपोइन्टमेन्ट पुष्टि गर्न {percentage}% डिपोजिट {currency} {amount} तिर्नुपर्छ — बाँकी "
            "{currency} {remaining} क्लिनिकमा तिर्नुहोस्। यहाँ भुक्तानी गर्नुहोस्: {link}"
        ),
        "ne_roman": (
            "Yo appointment confirm garna {percentage}% deposit {currency} {amount} tirnu parcha — baki "
            "{currency} {remaining} clinic ma tirnuhos. Yaha payment garnuhos: {link}"
        ),
    },
    "handoff_addendum": {
        "en": "I've also let our team know, so a real person will follow up with you.",
        "ne_deva": "मैले हाम्रो टिमलाई पनि जानकारी दिएँ, त्यसैले एक जना साँच्चैको मान्छेले तपाईंलाई फलो-अप गर्नेछ।",
        "ne_roman": "Maile hamro team lai pani janakari diye, tyesaile euta sacchai ko manche le tapailai follow-up garnecha.",
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
