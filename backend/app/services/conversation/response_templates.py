import re
import string
from collections.abc import Iterator
from contextlib import contextmanager
from contextvars import ContextVar
from datetime import date, datetime

from app.schemas.conversation import ConversationLanguage
from app.services.conversation.nepali_wordbank import mirror_spelling

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


# Natural-voice rewrite (2026-10-01): every Romanized-Nepali string below is written the way a Nepali receptionist
# actually texts -- the vocabulary comes from nepali_wordbank.NATURAL, never a word on its never-use list (enforced by
# tests/unit/test_nepali_naturalness.py). A template whose value is a LIST has several wordings of the same facts:
# render() picks the first one this conversation hasn't already seen (see `reply_history`), so the same fixed text is
# never sent twice in one chat. Every wording of one template in one language carries the same {placeholders}. The
# FIRST wording is the default (used on first need, and by every caller with no conversation history); the later ones
# are deliberately shorter -- a second ask reads like a person nudging, not a form re-printing itself.
# booking_unavailable_*: the booking system's own reason ("Requested time is not available (outside business hours, on
# a closed date, ...)") is internal English and never goes in front of a customer -- a native reviewer flagged it
# leaking into Nepali replies. The alternatives list says everything the customer needs.
TEMPLATES: dict[str, dict[str, str | list[str]]] = {
    "booking_success": {
        "en": [
            "You're all set{who}! I've booked {service} for {when} ({duration} min). Your booking ID is {id}.",
            "Done{who}, {service} is booked for {when} ({duration} min). Your booking ID is {id}.",
            "Booked{who}! {service}, {when} ({duration} min). Booking ID: {id}",
        ],
        "ne_deva": [
            "सबै मिल्यो{who}! {when} मा {service} ({duration} मिनेट) बुक गरिदिएँ। बुकिङ आईडी: {id}",
            "भइहाल्यो{who}, {when} को {service} ({duration} मिनेट) पक्का भयो। बुकिङ आईडी {id} हो।",
            "बुक भयो{who}! {service}, {when} ({duration} मिनेट)। बुकिङ आईडी: {id}",
        ],
        "ne_roman": [
            "Booking confirm bhayo{who}! {when} ma {service} ({duration} min) — bhetaula 😊 Booking ID: {id}",  # sheet #21
            "Sabai milyo{who}! {when} ma {service} book garidiye ({duration} min). Booking ID: {id}",
            "Book bhayo{who}! {service}, {when} ({duration} min). Tapaiko booking ID {id} ho.",
            "La done{who}, {when} ko {service} pakka bhayo ({duration} min). Booking ID: {id}",
        ],
    },
    "booking_unavailable_with_alts": {
        "en": [
            "That time isn't available anymore{who}. Here are some other openings for {service}: {options}. Would any of those work?",
            "That time isn't free{who}. For {service} I can do {options}. Any of those work?",
            "Sorry{who}, that one's gone. Still open for {service}: {options}. Which suits you?",
        ],
        "ne_deva": [
            "त्यो समय चाहिँ खाली रहेनछ{who}। {service} को लागि यी समय खाली छन्: {options}। कुन चाहिँ मिल्छ?",
            "सरी{who}, त्यो समय गइसक्यो। {service} को लागि अझै खाली: {options}। कुन चाहिँ मिल्छ?",
        ],
        "ne_roman": [
            "Tyo time chai bharkhar book bhaisakyo{who}. {service} ko lagi {options} khali cha — kun milcha?",  # sheet #22
            "Tyo time chai khali chaina raicha{who}. {service} ko lagi yo time haru khali cha: {options}. Tapailai kun chai milcha?",
            "Sorry{who}, tyo time gaisakyo. {service} ko lagi aile khali: {options}. Kun chai milcha?",
        ],
    },
    "booking_unavailable_no_alts": {
        "en": [
            "That time isn't available anymore{who}. I don't see any other openings for {service} in the next week — would you like me to connect you with our team instead?",
            "That time's not available anymore{who}. I don't see another opening for {service} this week — want me to get the team to sort out a time with you?",
            "Sorry{who}, that slot's gone, and {service} is full for the next week. Should I ask the team to find you a time?",
        ],
        "ne_deva": [
            "त्यो समय अब खाली छैन{who}। यो हप्ता {service} को अर्को खाली समय देखिँदैन — टिमलाई तपाईंसँग समय मिलाउन भनिदिऊँ?",
            "सरी{who}, त्यो समय गइसक्यो, र अर्को एक हप्ता {service} भरिएको छ। टिमलाई समय खोज्न भनूँ?",
        ],
        "ne_roman": [
            "Tyo time aile khali chaina{who}. Yo hapta {service} ko arko khali time dekhina — team lai tapai sanga time milauna bhanidiu?",
            "Sorry{who}, tyo slot gaisakyo, ani arko ek hapta {service} full cha. Team lai time khojna bhanum?",
        ],
    },
    "group_intro_success": {
        "en": "You're all set{who}! Here's what I booked:",
        "ne_deva": "सबैको बुकिङ भयो{who}! यस्तो छ:",
        "ne_roman": "Sabai ko booking bhayo{who}! Yesto cha:",
    },
    "group_intro_all_or_nothing_fail": {
        "en": "I wasn't able to get everyone in{who}, and since you wanted it all together, I didn't book anyone yet:",
        "ne_deva": "सबैलाई एकैचोटि मिलाउन सकिनँ{who}, र तपाईंले सँगै चाहनुभएकोले अहिले कसैको पनि बुक गरिनँ:",
        "ne_roman": "Sabai lai sangai milauna sakina{who}, tapai le sangai bhannu bhayeko le aile kasaiko pani book gareko chaina:",
    },
    "group_intro_partial": {
        "en": "Here's where things stand{who} — some went through, some didn't:",
        "ne_deva": "अहिलेसम्म यस्तो भयो{who} — केही बुक भयो, केही भएन:",
        "ne_roman": "Yesto bhayo{who} — kehi book bhayo, kehi bhayena:",
    },
    "group_line_success": {
        "en": "{people}: {service_name} on {when} ({duration} min, booking ID {id})",
        "ne_deva": "{people}: {when} मा {service_name} ({duration} मिनेट, बुकिङ आईडी {id})",
        "ne_roman": "{people}: {when} ma {service_name} ({duration} min, booking ID {id})",
    },
    "group_line_fail": {
        "en": "{people}: not booked — {message}",
        "ne_deva": "{people}: बुक भएन — {message}",
        "ne_roman": "{people}: book bhayena — {message}",
    },
    "cancellation_success": {
        "en": [
            "Done{who} — your appointment on {when} has been cancelled.",
            "Done{who} — your {when} appointment is cancelled.",
            "Cancelled{who}. Your {when} appointment is off the books.",
        ],
        "ne_deva": [
            "भइहाल्यो{who} — {when} को अपोइन्टमेन्ट क्यान्सल गरिदिएँ।",
            "क्यान्सल भयो{who}। {when} को अपोइन्टमेन्ट हटाइदिएँ।",
        ],
        "ne_roman": [
            "Bhaihalyo{who} — {when} ko appointment cancel garidiye.",
            "Cancel bhayo{who}. {when} ko appointment hataidiye.",
        ],
    },
    "cancellation_fail": {
        "en": "I couldn't cancel that{who} — {message}.",
        "ne_deva": "त्यो क्यान्सल गर्न मिलेन{who} — {message}।",
        "ne_roman": "Tyo cancel garna milena{who} — {message}.",
    },
    "reschedule_success": {
        "en": [
            "All set{who} — your appointment has been moved to {when}.",
            "All set{who} — moved to {when}.",
            "Done{who}, your appointment is now {when}.",
        ],
        "ne_deva": [
            "भइहाल्यो{who} — {when} मा सारिदिएँ।",
            "मिल्यो{who}, अब तपाईंको अपोइन्टमेन्ट {when} मा छ।",
        ],
        "ne_roman": [
            "Bhaihalyo{who} — {when} ma sardiye.",
            "Milyo{who}, aba tapaiko appointment {when} ma cha.",
        ],
    },
    "reschedule_fail": {
        "en": "I couldn't reschedule that{who} — {message}.",
        "ne_deva": "त्यो सार्न मिलेन{who} — {message}।",
        "ne_roman": "Tyo sarna milena{who} — {message}.",
    },
    "status_none": {
        "en": [
            "You don't have any appointments on file with us right now{who}.",
            "I don't see any appointments under your name yet{who}.",
            "Nothing booked under your name right now{who}.",
        ],
        "ne_deva": [
            "तपाईंको नाममा अहिले कुनै अपोइन्टमेन्ट देखिँदैन{who}।",
            "अहिले तपाईंको नाममा केही बुक छैन{who}।",
        ],
        "ne_roman": [
            "Tapaiko naam ma aile kunai appointment dekhina{who}.",
            "Aile tapaiko naam ma kehi book chaina{who}.",
        ],
    },
    "status_no_active": {
        "en": [
            "You don't have any upcoming appointments right now{who}.",
            "You don't have anything coming up right now{who}.",
            "No upcoming appointments at the moment{who}.",
        ],
        "ne_deva": [
            "अहिले तपाईंको कुनै आउने अपोइन्टमेन्ट छैन{who}।",
            "अहिलेलाई आउने अपोइन्टमेन्ट केही छैन{who}।",
        ],
        "ne_roman": [
            "Aile tapaiko kunai aune appointment chaina{who}.",
            "Ahilelai aune appointment kehi chaina{who}.",
        ],
    },
    # Real conversation-quality spec-conformance finding (PHASE_STATUS.md, §11 — a simple "is my 2pm still on?"
    # confirmation should read as brief as "Huss, 2 PM ko appointment raicha", not a formal status readout).
    "status_one_active": {
        "en": "{desc}{who} — {status}.",
        "ne_deva": "{desc}{who} — {status}।",
        "ne_roman": "{desc}{who} — {status}.",
    },
    "status_multi_active": {
        "en": "You have {n} upcoming appointments{who}: {lines}.",
        "ne_deva": "तपाईंका {n} वटा अपोइन्टमेन्ट आउँदैछन्{who}: {lines}।",
        "ne_roman": "Tapaiko {n} wota appointment aaudai cha{who}: {lines}.",
    },
    "status_recent_past": {
        "en": "Also on file (most recent): {lines}.",
        "ne_deva": "योभन्दा अघिका: {lines}।",
        "ne_roman": "Yo bhanda agadi ka: {lines}.",
    },
    "status_describe": {
        "en": "{service} on {when} (booking ID {id})",
        "ne_deva": "{when} मा {service} (बुकिङ आईडी {id})",
        "ne_roman": "{when} ma {service} (booking ID {id})",
    },
    "off_topic": {
        "en": [
            "I'm just here to help with things related to {name} — appointments, services, hours, and the like. Is there something about that I can help with?",
            "I'll have to pass on that one — I only handle {name} stuff. Need anything for a visit?",
            "Not something I can help with, sorry — I'm {name}'s assistant. Anything about our services?",
        ],
        "ne_deva": [
            "त्यो कुरामा म सहयोग गर्न सक्दिनँ — म {name} को बुकिङ, सेवा, मूल्य र समयको लागि मात्र हुँ। यसबारे केही चाहियो?",
            "सरी, त्यो मेरो काम बाहिरको कुरा हो — म {name} को कुरा मात्र हेर्छु। केही बुक गर्नु छ?",
            "त्यसमा म मद्दत गर्न सक्दिनँ — म {name} को सहायक हुँ। हाम्रो सेवाबारे केही सोध्नु छ?",
        ],
        "ne_roman": [
            # situation sheet #39/#40 (2026-10-01)
            "Tyo chai exact thaha bhayena hajur 😅 {name} ko service wa booking ko barema kei sodhnuhuncha?",
            "Tyo chai mildaina hajur 😊 {name} ko service ko barema k janna man cha bhannus na.",
            "Tyo kura ma ta help garna sakdina — ma {name} ko booking, service, price ra time ko lagi matra hu. Yesko barema kehi chahiyo?",
            "Sorry, tyo mero kaam bahira ko kura bhayo — ma {name} ko kura matra herchu. Kehi book garnu cha?",
            "Tyo ma ta help garna mildaina — ma {name} ko assistant hu. Hamro service ko barema kehi sodhnu cha?",
        ],
    },
    "booking_no_contact": {
        "en": [
            "Before I can get that booked, I'll need a way to reach you to confirm it — could you give me your name and a phone number or email?",
            "Just send me your name and number and I'll lock it in.",
            "Only your name and number left, then it's booked.",
            "Whenever you're ready, just a name and number and you're in.",
        ],
        "ne_deva": [
            "बुक गर्न तपाईंको नाम र फोन नम्बर (वा इमेल) चाहिन्छ, कन्फर्म गर्न।",
            "नाम र नम्बर मात्र पठाइदिनुस् न, अनि तुरुन्तै बुक गरिदिन्छु।",
            "नाम र नम्बर मात्र बाँकी छ, अनि बुक भइहाल्छ।",
            "जहिले तयार हुनुहुन्छ, नाम र नम्बर पठाउनुस् — अनि पक्का।",
        ],
        "ne_roman": [
            "Huss milcha! Booking pakka garna tapaiko naam ra phone number pathaidinus na.",  # situation sheet #20
            "Book garna tapaiko naam ra phone number (wa email) chahincha, confirm garna.",
            "Naam ra number matra pathaidinus na, ani turuntai book garidinchu.",
            "Naam ra number matra baki cha, ani book bhaihalcha.",
            "Jaile ready hunuhuncha, naam ra number pathaunus — ani pakka.",
        ],
    },
    "booking_clarify": {
        "en": [
            "Sorry, I want to make sure I get this right — could you tell me exactly which service, and the date and time you'd like?",
            "Just so I get it right — which service, and when would you like to come in?",
            "Which service is it for, and when works for you?",
        ],
        "ne_deva": [
            "सरी, अलि बुझिनँ — कुन सेवा हो, र कहिले आउन मिल्छ?",
            "ठीकसँग गर्न — कुन सेवा, र कुन दिन कति बजे आउने?",
            "कुन सेवाको लागि हो, र कहिले मिल्छ?",
        ],
        "ne_roman": [
            "Sorry, ali bujhina — kun service ho, ra kaile aauna milcha?",
            "Thik sanga milauna — kun service, ani kun din kati baje aaune?",
            "Kun service ko lagi ho, ani kaile milcha?",
        ],
    },
    "group_booking_clarify": {
        "en": [
            "Sorry, I want to make sure I get everyone booked correctly — could you confirm the exact service, date, and time for each person?",
            "Just need the service, day and time for each person and I'll book them all.",
        ],
        "ne_deva": [
            "सबैको बुक गरिदिन्छु — हरेक जनाको सेवा, दिन र समय भनिदिनुस् न।",
            "हरेक जनाको सेवा, दिन र समय मात्र चाहियो, अनि सबैको बुक गरिदिन्छु।",
        ],
        "ne_roman": [
            "Sabai ko book garidinchu — harek jana ko service, din ra time bhanidinus na.",
            "Harek jana ko service, din ra time matra chahiyo, ani sabai ko book garidinchu.",
        ],
    },
    "cancellation_clarify": {
        "en": [
            "Sorry, I want to make sure I cancel the right one — could you tell me which appointment (service and date) you'd like to cancel?",
            "Which appointment is it — the service and day?",
        ],
        "ne_deva": [
            "हुन्छ — कुन चाहिँ क्यान्सल गर्ने (सेवा र दिन)?",
            "कुन अपोइन्टमेन्ट हो — सेवा र दिन भनिदिनुस् न।",
        ],
        "ne_roman": [
            "Huss, cancel garidinchu. Kun din ko appointment thiyo, bhandinus na.",  # situation sheet #24
            "Huncha — kun chai cancel garne (service ra din)?",
            "Kun appointment ho — service ra din bhanidinus na.",
        ],
    },
    "reschedule_clarify": {
        "en": [
            "Sorry, I want to make sure I get this right — which appointment would you like to move, and to what new date and time?",
            "Which one are we moving, and what day and time instead?",
        ],
        "ne_deva": [
            "हुन्छ — कुन अपोइन्टमेन्ट सार्ने, र कहिले?",
            "कुन चाहिँ सार्ने, र कुन दिन कति बजे?",
        ],
        "ne_roman": [
            "Huncha — kun appointment sarne, ani kaile?",
            "Kun chai sarne, ani kun din kati baje?",
        ],
    },
    "contact_updated": {
        "en": "I've updated your contact info on file.",
        "ne_deva": "तपाईंको सम्पर्क विवरण अपडेट गरिदिएँ।",
        "ne_roman": "Tapaiko contact details update garidiye.",
    },
    "contact_resent": {
        "en": "I also resent your appointment confirmation — you should receive it shortly.",
        "ne_deva": "अपोइन्टमेन्टको कन्फर्मेसन पनि फेरि पठाइदिएँ — छिट्टै आइपुग्छ।",
        "ne_roman": "Appointment ko confirmation pani feri pathaidiye — chadai aaihalcha.",
    },
    # A customer's explicit "(re)send my confirmation/QR" request (ResendConfirmationTool) -- deliberately separate
    # wording from contact_resent above, which fires as a side effect of a contact-info update.
    "resend_email_sent": {
        "en": [
            "Sent! Your appointment confirmation and QR code are on their way to {to} — the email we have on file.",
            "Done — your confirmation and QR are on the way to {to}.",
        ],
        "ne_deva": [
            "पठाइदिएँ! तपाईंको कन्फर्मेसन र QR कोड {to} मा जाँदैछ — हामीसँग भएको तपाईंको इमेल।",
            "भइहाल्यो — कन्फर्मेसन र QR {to} मा पठाइदिएँ।",
        ],
        "ne_roman": [
            "Pathaidiye! Tapaiko confirmation ra QR code {to} ma jaadai cha — hami sanga bhayeko tapaiko email.",
            "Bhaihalyo — confirmation ra QR {to} ma pathaidiye.",
        ],
    },
    # "QR in chat": a signed, expiring link to the QR page (qr_link_service). Deliberately just a URL on its own line --
    # WhatsApp/Messenger/Instagram auto-link it and the widget linkifies it, so every channel gets the same plain link.
    "resend_qr_link": {
        "en": [
            "Here's your check-in QR code — open the link and show it at the front desk:\n{url}",
            "Here it is again — show this at the front desk:\n{url}",
        ],
        "ne_deva": [
            "यो तपाईंको चेक-इन QR हो — लिङ्क खोलेर फ्रन्ट डेस्कमा देखाउनुस्:\n{url}",
            "यो फेरि — फ्रन्ट डेस्कमा देखाउनुस्:\n{url}",
        ],
        "ne_roman": [
            "Yo tapaiko check-in QR ho — link kholera front desk ma dekhaunus:\n{url}",
            "Yo feri — front desk ma dekhaunus:\n{url}",
        ],
    },
    # Appended on a resend turn when the customer's message ALSO carried a different email/phone: a resend only ever
    # goes to the contact details already on file; changing them is its own separate request.
    "resend_contact_change_ignored": {
        "en": (
            "For your security I can only send this to the contact details already on file, so I didn't use the new "
            "one. If you'd like to change them, tell me separately (for example \"update my email to …\")."
        ),
        "ne_deva": (
            "सुरक्षाको लागि यो पहिले नै भएको विवरणमा मात्र पठाउँछु, त्यसैले नयाँ प्रयोग गरिनँ। बदल्नु छ भने छुट्टै भन्नुस् "
            "(जस्तै \"मेरो इमेल … मा बदलिदिनुस्\")।"
        ),
        "ne_roman": (
            "Security ko lagi yo pahile dekhi bhayeko details ma matra pathauchu, tesaile naya wala use gareko chaina. "
            "Badalnu cha bhane chhuttai bhannus (jastai \"mero email … ma badalidinus\")."
        ),
    },
    "resend_no_recipient": {
        "en": "I don't have a {channels} on file for you yet — could you give me one?",
        "ne_deva": "मसँग तपाईंको {channels} छैन — एउटा पठाइदिनुस् न?",
        "ne_roman": "Ma sanga tapaiko {channels} chaina — euta pathaidinus na?",
    },
    "resend_not_connected": {
        "en": "WhatsApp sending isn't set up on our end right now — let me connect you with our front desk instead.",
        "ne_deva": "अहिले हाम्रोतर्फ WhatsApp बाट पठाउने सेटअप छैन — फ्रन्ट डेस्कलाई सहयोग गर्न भन्छु।",
        "ne_roman": "Aile hamro tira WhatsApp bata pathaune setup chaina — front desk lai help garna bhanchu.",
    },
    "resend_send_failed": {
        "en": [
            "Something went wrong sending that just now — let me connect you with our front desk instead.",
            "Something went wrong sending that just now — I'll get the front desk to help you instead.",
            "That didn't go through on my end — the front desk will sort it out for you.",
        ],
        "ne_deva": [
            "अहिले पठाउँदा केही गडबड भयो — फ्रन्ट डेस्कलाई सहयोग गर्न भन्छु।",
            "मेरोतर्फबाट गएन — फ्रन्ट डेस्कले मिलाइदिन्छ।",
        ],
        "ne_roman": [
            "Aile pathauda kehi gadbad bhayo — front desk lai help garna bhanchu.",
            "Mero tira bata gayena — front desk le milaidincha.",
        ],
    },
    "resend_rate_limited": {
        "en": "You've already received this several times — let me connect you with our front desk instead.",
        "ne_deva": "यो त धेरैपटक गइसकेको छ — फ्रन्ट डेस्कलाई सिधै सहयोग गर्न भन्छु।",
        "ne_roman": "Yo ta dherai choti gaisakeko cha — front desk lai sidhai help garna bhanchu.",
    },
    "resend_fail": {
        "en": "I couldn't do that — {message}.",
        "ne_deva": "त्यो गर्न मिलेन — {message}।",
        "ne_roman": "Tyo garna milena — {message}.",
    },
    "resend_clarify": {
        "en": [
            "Sorry, I want to make sure I send the right one — could you tell me which appointment (service and date) you mean?",
            "Which appointment should I send — the service and day?",
        ],
        "ne_deva": [
            "हुन्छ — कुन अपोइन्टमेन्टको हो (सेवा र दिन)?",
            "कुन अपोइन्टमेन्टको पठाउने — सेवा र दिन भनिदिनुस् न।",
        ],
        "ne_roman": [
            "Huncha — kun appointment ko ho (service ra din)?",
            "Kun appointment ko pathaune — service ra din bhanidinus na.",
        ],
    },
    # Real gap found live (PHASE_STATUS.md, "silent service switch"): the ONLY place a booking-draft field switch is
    # acknowledged. A brief factual statement, never a question -- see orchestrator._merge_booking_draft.
    "booking_draft_switch": {
        "en": "Switching to {new} instead of {old}.",
        "ne_deva": "{old} को सट्टा {new}।",
        "ne_roman": "{old} ko satta {new}.",
    },
    # Phase 47: a booking whose service requires a deposit. Reserved, NOT "confirmed" -- the definitive confirmation is
    # `payment_received`, sent only after the gateway itself confirms the deposit. `{qr}` is the QR page link.
    "booking_reserved_pay": {
        "en": (
            "Great{who}, I've reserved {service} for {when}. To lock it in, please complete your {currency} {amount} "
            "deposit here: {link}\nOr scan it with your phone: {qr}\nThe remaining {currency} {remaining} is due "
            "in person. I'll confirm everything once the deposit is received. (Ref: {id})"
        ),
        "ne_deva": (
            "हुन्छ{who}, {when} को लागि {service} रिजर्भ गरिदिएँ। पक्का गर्न {currency} {amount} डिपोजिट यहाँ "
            "तिर्नुस्: {link}\nवा फोनले स्क्यान गर्नुस्: {qr}\nबाँकी {currency} {remaining} आउँदा तिर्नुस्। डिपोजिट "
            "आएपछि कन्फर्म गरिदिन्छु। (Ref: {id})"
        ),
        "ne_roman": (
            "Huncha{who}, {when} ko lagi {service} reserve garidiye. Pakka garna {currency} {amount} deposit yaha "
            "tirnus: {link}\nWa phone le scan garnus: {qr}\nBaki {currency} {remaining} aauda tirnus. Deposit "
            "aaye pachi confirm garidinchu. (Ref: {id})"
        ),
    },
    # Same, when the business offers both eSewa and Khalti and the customer hasn't picked yet -- the answer is read by
    # orchestrator._payment_choice_turn, which replies with `payment_link_chosen`.
    "booking_reserved_choose": {
        "en": (
            "Great{who}, I've reserved {service} for {when}. To lock it in, a {currency} {amount} deposit is needed "
            "(the remaining {currency} {remaining} is due in person) — would you like to pay with eSewa or Khalti? "
            "I'll confirm everything once it's received. (Ref: {id})"
        ),
        "ne_deva": (
            "हुन्छ{who}, {when} को लागि {service} रिजर्भ गरिदिएँ। पक्का गर्न {currency} {amount} डिपोजिट चाहिन्छ "
            "(बाँकी {currency} {remaining} आउँदा तिर्ने) — eSewa कि Khalti? डिपोजिट आएपछि कन्फर्म गरिदिन्छु। (Ref: {id})"
        ),
        "ne_roman": (
            "Huncha{who}, {when} ko lagi {service} reserve garidiye. Pakka garna {currency} {amount} deposit chahincha "
            "(baki {currency} {remaining} aauda tirne) — eSewa ki Khalti? Deposit aaye pachi confirm garidinchu. "
            "(Ref: {id})"
        ),
    },
    # Richer booking confirmation lines appended under booking_success / booking_reserved_* by
    # orchestrator._confirmation_extras, each only when its real data exists. `{email}` is the MASKED on-file address.
    "booking_for": {
        "en": "Booked for: {customer}",
        "ne_deva": "बुकिङ: {customer} को नाममा",
        "ne_roman": "Naam: {customer}",
    },
    "booking_where": {
        "en": "Where: {place}",
        "ne_deva": "ठाउँ: {place}",
        "ne_roman": "Kaha: {place}",
    },
    "booking_checkin_qr": {
        "en": "Your check-in QR (show it at the front desk when you arrive): {url}",
        "ne_deva": "चेक-इन QR (आउँदा फ्रन्ट डेस्कमा देखाउनुस्): {url}",
        "ne_roman": "Check-in QR (aauda front desk ma dekhaunus): {url}",
    },
    "booking_email_note": {
        "en": "A copy of these details, with your check-in QR, is also in your email ({email}).",
        "ne_deva": "यी सबै विवरण र चेक-इन QR तपाईंको इमेल ({email}) मा पनि पठाइएको छ।",
        "ne_roman": "Yo sabai details ra check-in QR tapaiko email ({email}) ma pani pathaiyeko cha.",
    },
    # A QR of the same real payment link, for a customer reading this on a laptop.
    "payment_qr_line": {
        "en": "Or scan it with your phone: {qr}",
        "ne_deva": "वा फोनले स्क्यान गर्नुस्: {qr}",
        "ne_roman": "Wa phone le scan garnus: {qr}",
    },
    # The customer named a gateway; this is the real link (and QR) that gateway just produced.
    "payment_link_chosen": {
        "en": "Great, here's your {provider} link for the {currency} {amount} deposit: {link}",
        "ne_deva": "{currency} {amount} डिपोजिटको लागि तपाईंको {provider} लिङ्क: {link}",
        "ne_roman": "{currency} {amount} deposit ko lagi tapaiko {provider} link: {link}",
    },
    # The gateway request could not be created (the booking itself is still confirmed).
    "payment_link_failed": {
        "en": "Sorry, I couldn't set up the {provider} payment just now. Your appointment is still confirmed — you can pay in person instead.",
        "ne_deva": "सरी, अहिले {provider} पेमेन्ट तयार गर्न मिलेन। तपाईंको अपोइन्टमेन्ट भने पक्का छ — आउँदा तिर्न मिल्छ।",
        "ne_roman": "Sorry, aile {provider} payment ready garna milena. Tapaiko appointment chai pakka cha — aauda tirna milcha.",
    },
    # Sent by the system, unprompted, once the gateway's own independent lookup says the payment completed -- the ONE
    # definitive confirmation of a deposit booking.
    "payment_received": {
        "en": (
            "Payment received — you're all set{who}! Your {service} appointment on {when} is now confirmed. "
            "We got your {currency} {amount} deposit. Booking ID: {id}"
        ),
        "ne_deva": (
            "पेमेन्ट आयो — सबै मिल्यो{who}! {when} को तपाईंको {service} अब पक्का भयो। {currency} {amount} डिपोजिट "
            "पायौँ। बुकिङ आईडी: {id}"
        ),
        "ne_roman": (
            "Payment aayo — sabai milyo{who}! {when} ko tapaiko {service} ab pakka bhayo. {currency} {amount} deposit "
            "payau. Booking ID: {id}"
        ),
    },
    "handoff_addendum": {
        "en": [
            "Let me check with our senior team on this and get back to you shortly.",
            "Let me check this with our team and get back to you shortly.",
            "I'll ask the team about this and come back to you soon.",
            "I've passed this to the team — they'll get back to you shortly.",
        ],
        "ne_deva": [
            "यसबारे टिमसँग सोधेर छिट्टै भन्छु।",
            "म टिमलाई सोधेर तपाईंलाई खबर गर्छु।",
            "टिमलाई भनिसकेँ — उहाँहरूले छिट्टै सम्पर्क गर्नुहुन्छ।",
        ],
        "ne_roman": [
            "Ma team lai inform gardinchu — chhadai tapailai contact garnuhunchha hai.",  # situation sheet #50
            "Yo kura team sanga sodhera chadai bhanchu.",
            "Ma team lai sodhera tapailai khabar garchu.",
            "Team lai bhanisake — uniharu le chadai contact garnu huncha.",
        ],
    },
    # Root-cause fix for a confirmed missed_escalation bug (a stated 9/10 toothache with overnight swelling got a plain
    # contact-info request, no urgency at all) -- see orchestrator._emergency_response. `{phone}` is "" or " at <phone>".
    "emergency_handoff": {
        "en": "This sounds like it needs urgent attention — please call us{phone} or visit us right away rather than waiting on chat. I've also flagged this conversation for our team.",
        "ne_deva": "ओहो, यो त तुरुन्तै हेर्नुपर्ने जस्तो छ — च्याटमा नपर्खी हामीलाई{phone} फोन गर्नुस् वा सिधै आउनुस्। टिमलाई पनि खबर गरिसकेँ।",
        "ne_roman": "Ouch, yo ta turuntai herna parne jasto cha — chat ma naparkhi hamilai{phone} phone garnus wa sidhai aaunus. Team lai pani khabar garisake.",
    },
    # Urgent fix (real 500 found live): the ONLY message shown when the LLM/embedding provider failed after its own
    # retries -- fully static. Always followed by handoff_addendum, never shown alone.
    "provider_failure": {
        "en": "Sorry, I'm having trouble connecting on my end right now.",
        "ne_deva": "सरी, अहिले मेरोतर्फ अलि समस्या आयो।",
        "ne_roman": "Sorry, aile mero tira ali problem aayo.",
    },
    # Phase 25a: composed only when 1 or 2 of {service, date, time} are still missing from the persisted booking draft
    # -- see render_missing_slots. All three missing reuses "booking_clarify" above instead.
    "booking_ask_missing": {
        "en": [
            "Got it — could you tell me {missing}?",
            "And {missing}?",
            "Just need {missing}.",
        ],
        "ne_deva": [
            "हुन्छ — {missing}?",
            "अनि {missing}?",
            "{missing} मात्र भनिदिनुस् न।",
        ],
        "ne_roman": [
            "Huncha — {missing}?",
            "Ani {missing}?",
            "{missing} matra bhanidinus na.",
        ],
    },
    # Phase 25a-2: the contact-info gate when at least one of {service, date, time} is already known -- see
    # render_contact_gate. "booking_no_contact" above is used when NOTHING is known yet.
    "booking_gate_with_progress": {
        "en": [
            "Got it — {summary}. I just need your name and a phone number or email to lock that in.",
            "{summary} it is. Send me your name and number and it's booked.",
            "Only your name and number left for {summary}.",
            "{summary} is ready to go — just your name and number.",
        ],
        "ne_deva": [
            "हुन्छ — {summary}। पक्का गर्न तपाईंको नाम र फोन नम्बर (वा इमेल) चाहियो।",
            "{summary}, ठीक छ। नाम र नम्बर पठाइदिनुस् न, अनि बुक भइहाल्छ।",
            "{summary} को लागि नाम र नम्बर मात्र बाँकी छ।",
            "{summary} तयार छ — नाम र नम्बर मात्र चाहियो।",
        ],
        "ne_roman": [
            "Huss — {summary}. Pakka garna tapaiko naam ra phone number (wa email) chahiyo.",
            "{summary}, thik cha. Naam ra number pathaidinus na, ani book bhaihalcha.",
            "{summary} ko lagi naam ra number matra baki cha.",
            "{summary} ready cha — naam ra number matra chahiyo.",
        ],
    },
    # Phase 33: the customer wants to see real options rather than name a time -- `options` is a real, freshly-computed
    # get_available_slots list, never invented.
    "availability_options": {
        "en": [
            "Here's what's open for {service}: {options}. Which works for you?",
            "For {service} I've got {options}. Which one suits you?",
            "{service} — free times: {options}. Which one?",
        ],
        "ne_deva": [
            "{service} को लागि यी समय खाली छन्: {options}। कुन मिल्छ?",
            "{service}: {options} खाली छ। कुन चाहिँ?",
            "{service} को खाली समय: {options}। कुन ठीक हुन्छ?",
        ],
        "ne_roman": [
            "{service} ko lagi yo time haru khali cha: {options}. Kun milcha?",
            "{service}: {options} khali cha. Kun chai?",
            "{service} ko khali time: {options}. Kun thik huncha?",
        ],
    },
    # trekking-10: prepended to a slot list when the customer never named the service it's for. The tenant's
    # description is English-only, so the Nepali variants leave it out.
    "booking_service_bridge": {
        "en": "That's booked through our {service}. {description}",
        "ne_deva": "यो हाम्रो {service} बाट बुक हुन्छ।",
        "ne_roman": "Yo hamro {service} bata book huncha.",
    },
    # Prepended to availability_options/availability_none_* when the customer named a specific time that turned out to
    # be already taken -- never silently pivot to alternatives without acknowledging the specific request failed.
    "requested_time_unavailable": {
        "en": ["That time isn't available anymore.",
            "That time's already taken.", "That one's gone, sorry.", "That slot's booked."],
        "ne_deva": ["त्यो समय बुक भइसक्यो।", "सरी, त्यो समय गइसक्यो।", "त्यो स्लट भरिएको छ।"],
        "ne_roman": ["Tyo time chai bharkhar book bhaisakyo.", "Sorry, tyo time gaisakyo.", "Tyo slot full cha."],
    },
    # The same slot list was shown in one of our last few replies: point back at it instead of pasting it again.
    "availability_refer_back": {
        "en": [
            "Those times above are still open — which one would you like? (Say the time, or \"the first one\".)",
            "Any of the times above work? Just tell me which.",
        ],
        "ne_deva": [
            "माथिका समय अझै खाली छन् — कुन चाहियो? (समय भन्नुस्, वा \"पहिलो\")",
            "माथिका समयमध्ये कुनै मिल्छ? कुन भन्नुस् न।",
        ],
        "ne_roman": [
            "Mathi ko time haru aile pani khali cha — kun chahiyo? (Time bhannus, wa \"pahilo\")",
            "Mathi ko time haru madhye kunai milcha? Kun bhannus na.",
        ],
    },
    # Phase 33: that specific day has nothing -- here's the real next opening (never a silent empty list).
    "availability_none_with_next_day": {
        "en": [
            "There's nothing open for {service} on {requested} — the next real opening is {options}. Would any of those work?",
            "Nothing left on {requested} for {service}, sorry. Next free: {options}. Any good?",
        ],
        "ne_deva": [
            "{requested} मा {service} भरिएको छ — अर्को खाली समय {options} हो। मिल्छ?",
            "सरी, {requested} मा {service} को समय छैन। अर्को खाली: {options}। मिल्छ?",
        ],
        "ne_roman": [
            "{requested} ma {service} full cha — arko khali time {options} ho. Milcha?",
            "Sorry, {requested} ma {service} ko time chaina. Arko khali: {options}. Milcha?",
        ],
    },
    # Phase 33: no real opening anywhere in the searched window -- an honest statement plus a handoff offer.
    "availability_none_no_alts": {
        "en": [
            "I don't see any openings for {service} in the next little while — would you like me to connect you with our team instead?",
            "{service} is fully booked for the next little while — want me to get the team to find you a time?",
            "No openings for {service} coming up, sorry. Should I ask the team to fit you in?",
        ],
        "ne_deva": [
            "केही दिनसम्म {service} भरिएको छ — टिमलाई तपाईंको लागि समय खोज्न भनूँ?",
            "सरी, {service} को खाली समय छैन। टिमलाई मिलाइदिन भनूँ?",
        ],
        "ne_roman": [
            "Kehi din samma {service} full cha — team lai tapai ko lagi time khojna bhanum?",
            "Sorry, {service} ko khali time chaina. Team lai milaidina bhanum?",
        ],
    },
    # Phase 16 ("ask upfront" language mode): confirmation once the customer has named a language.
    "language_chosen": {
        "en": "Great, we'll continue in English. How can I help you today?",
        "ne_deva": "हुन्छ, नेपालीमै कुरा गरौँ। भन्नुस्, के सहयोग गरूँ?",
        "ne_roman": "Huncha hajur, Nepali mai kura garaum 😊 Bhannus na, k help garum?",  # situation sheet #53
    },
    # The honest fallback for fact_validator.check_response_facts: the drafted reply stated a claim not backed by this
    # tenant's real config, and a regenerate still didn't fix it. Followed by a real handoff.
    "unconfirmed_fact_fallback": {
        "en": [
            "I don't want to guess on that one — let me get a real answer from the team and have them follow up with you.",
            "I'd rather not guess — I'll check with the team and they'll get back to you.",
        ],
        "ne_deva": [
            "त्यसमा म अड्कल काट्दिनँ — टिमबाट सही कुरा बुझेर तपाईंलाई खबर गर्न लगाउँछु।",
            "अड्कल गर्नुभन्दा टिमसँग सोधेर भन्छु — उहाँहरूले तपाईंलाई खबर गर्नुहुन्छ।",
        ],
        "ne_roman": [
            "Yo kura chai ma team sanga bujhera tapailai chhitto khabar garchu hai.",  # situation sheet #49
            "Yo kura chai team sanga bujhera tapailai chhitto bhandinchu hai.",
            "Exact kura record ma bhetiyena — team sanga bujhera tapailai bhandinchu hai.",
        ],
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


# The replies this conversation has already sent, oldest first -- set once per turn by
# orchestrator.handle_incoming_message (`reply_history`). None outside a conversation turn (tests, scripts, the
# payment webhook), where render() always gives the first wording.
_reply_history: ContextVar[tuple[str, ...] | None] = ContextVar("reply_history", default=None)


@contextmanager
def reply_history(previous_replies: list[str]) -> Iterator[None]:
    token = _reply_history.set(tuple(previous_replies))
    try:
        yield
    finally:
        _reply_history.reset(token)


def recent_replies(n: int) -> list[str]:
    """The last `n` replies this conversation sent, newest first ([] outside a turn)."""
    history = _reply_history.get() or ()
    return list(reversed(history[-n:]))


def _comparable(text: str) -> str:
    # The reply polisher may have mirrored cha->xa or swapped a word after render(); compare on the same footing.
    return mirror_spelling(" ".join(text.lower().split()), "x")


def already_sent(text: str, within: int | None = None) -> bool:
    """True when `text` appears verbatim (modulo spelling mirror/whitespace) inside one of our earlier replies."""
    history = _reply_history.get() or ()
    if within is not None:
        history = history[-within:]
    needle = _comparable(text)
    return any(needle in _comparable(h) for h in history)


def variants(template_name: str, language: str | None) -> list[str]:
    value = TEMPLATES[template_name][_key(language)]
    return list(value) if isinstance(value, list) else [value]


def render(template_name: str, language: str | None, **kwargs: str) -> str:
    """Never the same fixed text twice in one chat: the first wording this conversation hasn't seen yet, or -- once
    every wording has been used -- the one used longest ago. Deterministic (no randomness), so the first wording is
    always what a fresh conversation or a caller outside a turn gets."""
    formats = variants(template_name, language)
    rendered = [v.format(**kwargs) for v in formats]
    history = _reply_history.get()
    if not history or len(rendered) == 1:
        return rendered[0]
    seen = [_comparable(h) for h in history]

    def last_used(i: int) -> int:
        # A wording counts as used when its FIXED text was sent, whatever data filled it: "Cleaning, 10 baje ...
        # naam ra number chahiyo" and "Cleaning, 11 baje ... naam ra number chahiyo" are the same sentence to a person.
        pieces = _fixed_pieces(formats[i]) or [_comparable(rendered[i])]
        return max((j for j, h in enumerate(seen) if all(p in h for p in pieces)), default=-1)

    return rendered[min(range(len(rendered)), key=last_used)]


def _fixed_pieces(fmt: str) -> list[str]:
    """The literal text of a wording between its {placeholders}, normalized; tiny joiners ("ko", " — ") ignored."""
    pieces = [_comparable(literal).strip(" .,!?—-:") for literal, _, _, _ in _FORMATTER.parse(fmt)]
    return [p for p in pieces if len(p) >= 8]


_FORMATTER = string.Formatter()


# Phase 25a: natural-language labels for the three booking-draft slots, and
# the joining word between them, used ONLY to compose the "what's still
# missing" question (render_missing_slots) — never anything else, so this
# stays a tiny, self-contained table rather than growing into a second
# translation system.
_MISSING_SLOT_LABELS: dict[str, dict[str, str]] = {
    "en": {"service": "which service", "date": "what date", "time": "what time"},
    "ne_deva": {"service": "कुन सेवा", "date": "कुन दिन", "time": "कति बजे"},
    "ne_roman": {"service": "kun service", "date": "kun din", "time": "kati baje"},
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
    return _capitalize(render("booking_ask_missing", language, missing=joined))


def _capitalize(text: str) -> str:
    return text[0].upper() + text[1:] if text and text[0].islower() else text


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
    return _capitalize(render("booking_gate_with_progress", language, summary=known_summary))


_HOURS_WEEKDAY_NAMES: dict[str, list[str]] = {
    "en": ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"],
    "ne_deva": ["सोमबार", "मंगलबार", "बुधबार", "बिहीबार", "शुक्रबार", "शनिबार", "आइतबार"],
    "ne_roman": ["Sombar", "Mangalbar", "Budhbar", "Bihibar", "Sukrabar", "Sanibar", "Aaitabar"],
}
_HOURS_CLOSED_LABEL = {"en": "Closed", "ne_deva": "बन्द", "ne_roman": "Banda"}
_HOURS_INTRO = {
    "en": "Our hours are: {days}",
    "ne_deva": "हाम्रो खुल्ने समय: {days}",
    "ne_roman": "Hamro khulne time: {days}",
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
    "ne_deva": "खुल्ने समय मसँग अहिले छैन — टिमलाई तपाईंलाई भन्न लगाउँछु।",
    "ne_roman": "Khulne time ma sanga aile chaina — team lai tapailai bhanna lagauchu.",
}


_RANGE = {"ne_deva": "{open}देखि {close}सम्म", "ne_roman": "{open} dekhi {close} samma"}

# ---------------------------------------------------------------------------------------------------------------------
# Dates and times, the way a Nepali person texts them: "Sombar (Oct 5), bihana 10 baje", "sadhe 10", "dedh baje" --
# never "Monday, October 5 at 10:00 AM" in the middle of a Nepali sentence. English keeps its original format.
# ---------------------------------------------------------------------------------------------------------------------
_PERIODS = {
    "ne_roman": ("raati", "bihana", "diuso", "beluka"),
    "ne_deva": ("राति", "बिहान", "दिउँसो", "बेलुका"),
}
_CLOCK_WORDS = {
    "ne_roman": {"baje": "baje", "half": "sadhe {h}", "1:30": "dedh", "2:30": "adhai", "quarter": "sawa {h}"},
    "ne_deva": {"baje": "बजे", "half": "साढे {h}", "1:30": "डेढ", "2:30": "अढाई", "quarter": "सवा {h}"},
}


def _period_index(hour: int) -> int:
    if hour < 4 or hour >= 20:
        return 0
    if hour < 12:
        return 1
    if hour < 16:
        return 2
    return 3


def format_clock(t, language: str | None, *, with_period: bool = True) -> str:
    """`t`: a datetime or time. "bihana 10 baje", "sadhe 10 baje", "diuso dedh baje", "beluka 5:45 baje"."""
    lang_key = _key(language)
    if lang_key == "en":
        return t.strftime("%-I:%M %p")
    words = _CLOCK_WORDS[lang_key]
    h12 = t.hour % 12 or 12
    if t.minute == 0:
        core = str(h12)
    elif t.minute == 30 and h12 in (1, 2):
        core = words[f"{h12}:30"]
    elif t.minute == 30:
        core = words["half"].format(h=h12)
    elif t.minute == 15:
        core = words["quarter"].format(h=h12)
    else:
        core = f"{h12}:{t.minute:02d}"
    clock = f"{core} {words['baje']}"
    return f"{_PERIODS[lang_key][_period_index(t.hour)]} {clock}" if with_period else clock


def format_day(d: date | datetime, language: str | None) -> str:
    lang_key = _key(language)
    if lang_key == "en":
        return d.strftime("%A, %B %-d")
    return f"{_HOURS_WEEKDAY_NAMES[lang_key][d.weekday()]} ({d.strftime('%b')} {d.day})"


def format_when(dt: datetime, language: str | None) -> str:
    """A local datetime: "Monday, October 5 at 10:00 AM" / "Sombar (Oct 5), bihana 10 baje"."""
    if _key(language) == "en":
        return dt.strftime("%A, %B %-d at %-I:%M %p")
    return f"{format_day(dt, language)}, {format_clock(dt, language)}"


def format_slot_list(local_slots: list[datetime], language: str | None) -> str:
    """Slots on one day state the day once: "Sombar (Oct 5) — bihana 9 baje, sawa 9 baje, sadhe 9 baje" (the
    bihana/diuso/beluka word only when it changes); several days are grouped per day, "; "-separated. English keeps
    its original format (a shared day once, otherwise every slot with its own day)."""
    if _key(language) == "en":
        if len({s.date() for s in local_slots}) != 1:
            return ", ".join(format_when(s, language) for s in local_slots)
        return f"{local_slots[0].strftime('%A, %B %-d')} at " + ", ".join(s.strftime("%-I:%M %p") for s in local_slots)
    days: list[list[datetime]] = []
    for s in local_slots:
        if days and days[-1][0].date() == s.date():
            days[-1].append(s)
        else:
            days.append([s])
    groups = []
    for day_slots in days:
        clocks, last_period = [], None
        for s in day_slots:
            period = _period_index(s.hour)
            clocks.append(format_clock(s, language, with_period=period != last_period))
            last_period = period
        groups.append(f"{format_day(day_slots[0], language)} — " + ", ".join(clocks))
    return "; ".join(groups)


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
        if lang_key == "en":
            return f"{h.open_time.strftime('%-I:%M %p')} - {h.close_time.strftime('%-I:%M %p')}"
        return _RANGE[lang_key].format(open=format_clock(h.open_time, language), close=format_clock(h.close_time, language))

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
