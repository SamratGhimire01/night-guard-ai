# Phase 4 multi-judge eval — 361 (case, sample) pairs, 181 cases, 2 judges

## Headline (consensus = mean of judges)

- before 3.40 → after 3.47, **Δ +0.07** (95% bootstrap CI over cases -0.04 … +0.19)
- cases improved/tied/regressed (consensus, averaged over samples): 63/65/53
- 108/361 pairs got byte-identical before/after replies (deterministic templates the Phase 1-3 pipeline never touches); Δ over only the 253 pairs that differ: +0.11

| judge | before | after | Δ | 95% CI (cases) |
|---|---|---|---|---|
| azure/gpt-5-mini | 3.68 | 3.63 | -0.05 | -0.17 … +0.08 |
| groq/qwen3.8-27b | 3.12 | 3.31 | +0.19 | +0.05 … +0.32 |

## Inter-judge agreement

Per reply score (both arms pooled) and per pair Δ (after − before):

| judge pair | score within ±1 | exact | Pearson r | Δ same sign | Δ within ±1 |
|---|---|---|---|---|---|
| azure/gpt-5-mini vs groq/qwen3.8-27b | 82% | 37% | 0.56 | 75% | 76% |

- all 2 judges within ±1 of each other on a reply: **82%**
- all judges agree on the direction of Δ (better/same/worse) for a pair: **75%**

Self-consistency (same judge, identical input, re-judged):

| judge | rechecks | exact | max abs diff |
|---|---|---|---|
| azure/gpt-5-mini | 32 | 64% | 2 |
| groq/qwen3.8-27b | 31 | 40% | 3 |

Generation noise (same case, sample 0 vs 1, consensus Δ): same sign 56%, mean |Δ0 − Δ1| 0.96 over 180 cases.

## By tenant

| slice | n pairs | before | after | Δ | 95% CI | Δ gpt-5-mini | Δ qwen3.8-27b | all-judges ±1 |
|---|---|---|---|---|---|---|---|---|
| Samaj Dental Clinic | 134 | 3.49 | 3.54 | +0.06 | -0.13 … +0.25 | -0.01 | +0.13 | 79% |
| Himalayan Trails Trekking Co. | 122 | 3.17 | 3.23 | +0.06 | -0.13 … +0.25 | -0.06 | +0.18 | 86% |
| Everest Pathways Consultancy | 105 | 3.54 | 3.66 | +0.11 | -0.07 … +0.30 | -0.07 | +0.30 | 80% |

## By language (detected, after arm)

| slice | n pairs | before | after | Δ | 95% CI | Δ gpt-5-mini | Δ qwen3.8-27b | all-judges ±1 |
|---|---|---|---|---|---|---|---|---|
| en | 126 | 3.24 | 3.50 | +0.26 | +0.07 … +0.45 | +0.11 | +0.41 | 85% |
| ne_roman | 122 | 3.55 | 3.52 | -0.02 | -0.20 … +0.15 | -0.17 | +0.12 | 78% |
| ne_deva | 101 | 3.43 | 3.37 | -0.05 | -0.27 … +0.15 | -0.11 | +0.00 | 85% |
| None | 10 | 3.20 | 3.30 | +0.10 | -0.60 … +0.70 | +0.20 | +0.00 | 75% |
| mixed | 2 | 3.50 | 4.25 | +0.75 | +0.00 … +1.50 | +0.00 | +1.50 | 100% |

## By intent (detected, after arm)

| slice | n pairs | before | after | Δ | 95% CI | Δ gpt-5-mini | Δ qwen3.8-27b | all-judges ±1 |
|---|---|---|---|---|---|---|---|---|
| service_question | 69 | 3.46 | 3.86 | +0.39 | +0.12 … +0.67 | +0.09 | +0.70 | 83% |
| pricing_question | 43 | 4.02 | 3.65 | -0.37 | -0.69 … -0.05 | -0.40 | -0.35 | 80% |
| booking | 38 | 3.09 | 3.03 | -0.07 | -0.16 … +0.00 | -0.08 | -0.05 | 84% |
| greeting | 26 | 3.50 | 4.37 | +0.87 | +0.37 … +1.31 | +0.88 | +0.85 | 79% |
| complaint | 23 | 4.09 | 3.83 | -0.26 | -0.70 … +0.17 | -0.61 | +0.09 | 83% |
| location | 22 | 3.27 | 3.48 | +0.20 | -0.23 … +0.64 | +0.27 | +0.14 | 70% |
| general_question | 20 | 3.83 | 3.60 | -0.23 | -0.90 … +0.42 | -0.25 | -0.20 | 85% |
| cancellation | 19 | 4.00 | 3.63 | -0.37 | -0.82 … +0.11 | -0.47 | -0.26 | 84% |
| off_topic | 18 | 2.03 | 2.03 | +0.00 | +0.00 … +0.00 | +0.00 | +0.00 | 72% |
| business_hours | 18 | 2.11 | 2.17 | +0.06 | -0.33 … +0.50 | +0.06 | +0.06 | 89% |
| rescheduling | 18 | 3.86 | 3.72 | -0.14 | -0.75 … +0.47 | -0.50 | +0.22 | 81% |
| human_handoff | 16 | 3.59 | 4.06 | +0.47 | +0.03 … +0.88 | +0.44 | +0.50 | 88% |
| appointment_status | 15 | 1.47 | 1.47 | +0.00 | +0.00 … +0.00 | +0.00 | +0.00 | 93% |
| resend_confirmation | 15 | 3.90 | 4.20 | +0.30 | -0.10 … +0.70 | +0.00 | +0.60 | 83% |
| follow_up | 1 | 5.00 | 3.50 | -1.50 | +nan … +nan | -2.00 | -1.00 | 100% |

## Biggest remaining gaps (consensus Δ most negative), with transcripts

**[t-128 s0]** Δ -3.00 (before 5.00 / after 2.00) — Himalayan Trails Trekking Co., general_question, ne_roman, scripted

- CUSTOMER: kunai staff sanga direct kura garna milcha?
- BEFORE: Sakinchha, hajur — kun bishaya ma kura garna chahanu huncha ra kun channel (phone/WhatsApp/email) milcha bhanera btaunuhos, ma team sanga connect garna help garchu? Ma yesbare hamro senior team sanga kura garera chadai tapailai update garne chu.
- AFTER: Tyo ma guess garna chahanna — ma team bata sahi jankari lera tapailai follow-up garauchu. Ma yesbare hamro senior team sanga kura garera chadai tapailai update garne chu.
  - azure/gpt-5-mini: before 5 (Natural, polite, asks clarifying questions and offers to connect you with the team, sounding like a helpful receptionist.) / after 2 (Awkward phrasing, presumptive and repetitive, feels scripted and less attentive to details like contact preference.)
  - groq/qwen3.8-27b: before 5 (It directly answers the customer's yes/no question affirmatively and proactively asks for specific details needed to make the connection, which is exactly what an attentive human receptionist would do.) / after 2 (It fails to answer the direct question, starts with a defensive 'I don't want to guess,' and contains awkward grammar that sounds more like a confused AI or a passive-aggressive script than a helpful human.)

**[t-135 s1]** Δ -3.00 (before 5.00 / after 2.00) — Himalayan Trails Trekking Co., pricing_question, ne_deva, scripted

- CUSTOMER: गियर भाडामा लिन कति लाग्छ?
- BEFORE: त्यसमा म अड्कल गर्न चाहन्न — म टिमबाट सही जानकारी लिएर तपाईंलाई फलो-अप गराउँछु। म यसबारे हाम्रो सिनियर टिमसँग कुरा गरेर चाँडै तपाईंलाई अपडेट गर्नेछु।
- AFTER: Gear Rental Pickup को शुल्क USD 0.00 हो, र करिब 20 मिनेट लाग्छ। बुक गर्न मन छ भने भन्नुहोस्।
  - azure/gpt-5-mini: before 5 (Feels like a real person—admits uncertainty, offers to check with the team and follow up, which is attentive and conversational.) / after 3 (Short and factual but a bit terse and formal (the 'USD 0.00' phrasing feels robotic).)
  - groq/qwen3.8-27b: before 5 (It sounds like a cautious human receptionist who honestly admits they need to check with the team rather than guessing or providing inaccurate data.) / after 1 (It sounds robotic and factually nonsensical, quoting a 'USD 0.00' fee and an arbitrary 20-minute duration without context.)

**[t-123 s0]** Δ -2.50 (before 4.50 / after 2.00) — Himalayan Trails Trekking Co., rescheduling, ne_roman, scripted

- CUSTOMER: mero gear pickup parsi lai sarna milcha?
- BEFORE: Thik cha, hajur — tara kun Gear Rental Pickup appointment sarnu bhannu bhayeko ho malaai thaha chhaina. Kripaya original pickup ko date ra time (or booking reference) dinuhos, ani confirm garnuhos ki "parsi" bhaneko 2026-10-01 ma sarnu ho?
- AFTER: Huss — ke yo tapaiko Gear Rental Pickup appointment ho?
  - azure/gpt-5-mini: before 4 (Polite and clarifying — asks for the original booking details and confirms what 'parsi' refers to, sounding like an attentive receptionist.) / after 2 (Very brief and abrupt, lacking confirmation steps or polite detail so it feels more like a curt scripted reply than a thoughtful human response.)
  - groq/qwen3.8-27b: before 5 (It naturally acknowledges the uncertainty of the specific date, asks for the necessary details (booking ref/date), and confirms the translation of 'parsi' to a specific date, showing genuine attentiveness.) / after 2 (The bizarre use of 'Huss' as a greeting instead of the standard Nepali 'Ho' makes it sound like a glitchy translation or AI error rather than a human.)

**[d-127 s1]** Δ -2.50 (before 5.00 / after 2.50) — Samaj Dental Clinic, service_question, ne_roman, real

- CUSTOMER: Mero daath dukheko cha k garnu sakvhu
- BEFORE: Dukhai bhayeko sunera afno laagi naramro lagyo. Pahila doctor le herera thik diagnosis garne parcha — Dental Consultation (NPR 500, 25 min) recommend garchu; tes pachi jaruri bhaye filling, extraction, or root canal jasto treatment salla garincha. Appointment book garna man cha hajur? Kun din/kun samaya milcha bhanera pathaunuhos, tara dherai dukha bhaye aaja chadhnu hola (Saturday banda cha, tara Sunday 10:00‑18:00 khula cha).
- AFTER: Dukhai ko lagi duchh, hajur. Daath ko pain ko lagi pahila Dental Consultation le herera exact karan thahaa garincha — hami ko Dental Consultation NPR 500 ho ra karib 25 minutes lagcha. Agar severe pain, gaalo sujeko, jor/fever cha bhane yo emergency jasto ho — chito aunuhos. Booking garna man cha hajur?
  - azure/gpt-5-mini: before 5 (Warmer and more empathetic, offers clear next steps and scheduling details, and invites a specific appointment time like a real receptionist would.) / after 2 (Short, a bit stilted with typos and blunt phrasing; reads like a scripted response rather than a warm receptionist.)
  - groq/qwen3.8-27b: before 5 (It reads like a knowledgeable and empathetic human receptionist because it proactively provides specific next-step treatments (filling, root canal) and detailed, date-aware availability context (mentioning Saturday is closed) rather than just stating a price.) / after 3 (It is polite and functional but feels more like a standard script because it relies on generic safety warnings and lacks the specific, context-rich details (like today's operational status) that would make it sound genuinely attentive.)

**[d-132 s0]** Δ -2.50 (before 5.00 / after 2.50) — Samaj Dental Clinic, greeting, ne_deva, real

- CUSTOMER: नमस्ते
- BEFORE: नमस्ते, हाजुर — म कसरि सहयोग गर्न सक्छु?
- AFTER: नमस्ते! म प्रिय — तपाईंलाई के सहयोग चाहियो, हजुर?
  - azure/gpt-5-mini: before 5 (Concise, polite and natural Nepali phrasing that reads like a real receptionist offering help.) / after 3 (Polite and attempts friendliness by introducing a name, but the name/word choice ('प्रिय' instead of 'प्रिया' or a clearer introduction) and slight awkward phrasing make it feel a bit off/scripted.)
  - groq/qwen3.8-27b: before 5 (It is a grammatically correct, polite, and concise standard opening that sounds completely natural for a Nepali-speaking receptionist.) / after 2 (The phrase 'म प्रिय' (I [am] love) is grammatically incorrect and nonsensical in this context, resembling a poor machine translation or hallucination rather than a human error.)

**[d-133 s1]** Δ -2.50 (before 5.00 / after 2.50) — Samaj Dental Clinic, general_question, ne_deva, real

- CUSTOMER: हेलो हामी नेपालीमा बोल्न सक्छौँ
- BEFORE: नमस्ते! पक्का — हामी नेपालीमै बोल्न सक्छौँ, हाजुर। म कसरी सहयोग गर्न सक्छु?
- AFTER: नमस्ते, म प्रिय हुँ — पक्कै, हामी नेपालीमै कुरा गर्न सक्छौं, हजुर। म कसरी सहयोग गर्न सक्छु?
  - azure/gpt-5-mini: before 5 (स्पष्ट, मिलनसार र स्वाभाविक स्वागत — मानव रिसेप्सनिस्टले बोले जस्तो लाग्छ।) / after 3 (सामान्यतया ठिक छ तर 'म प्रिय हुँ' भनाइ अलि असम्बद्ध/अनावश्यक छ र थोरै औपचारिकता बोटो देखिन्छ।)
  - groq/qwen3.8-27b: before 5 (The use of the respectful form 'हाजुर' combined with natural phrasing and a welcoming tone ('पक्का') reads exactly like a polite and attentive human receptionist in a Nepali-speaking context.) / after 2 (The phrase 'म प्रिय हुँ' ('I am dear') is semantically nonsensical and grammatically awkward in this context, reading more like a machine translation error or a typo for 'प्रियंका' (a name), which breaks the illusion of a human writer.)

**[trekking-09 s0]** Δ -2.00 (before 4.00 / after 2.00) — Himalayan Trails Trekking Co., pricing_question, ne_deva, real

- CUSTOMER: गाइड बुकिङको लागि कति खर्च लाग्छ?
- BEFORE: त्यसमा म अड्कल गर्न चाहन्न — म टिमबाट सही जानकारी लिएर तपाईंलाई फलो-अप गराउँछु। म यसबारे हाम्रो सिनियर टिमसँग कुरा गरेर चाँडै तपाईंलाई अपडेट गर्नेछु।
- AFTER: Private Guide Booking Consultation को खर्च USD 0.00 हुन्छ र करिब 30 मिनेट लग्छ। बुक गर्न चाहनुहुन्छ भने कुन मिति वा समय उपयुक्त होला?
  - azure/gpt-5-mini: before 4 (सिधा जवाफ नदिई पनि इमान्दारपूर्वक अनुमान नगर्ने र टिमसँग परामर्श गरेर फोलोअप गर्ने कुरा गर्नु भएको छ—ध्यानपूर्वक मान्छेले लेखेको जस्तो लाग्छ।) / after 3 (स्पष्ट र तुरुन्त जवाफ दिएको भएता पनि USD 0.00 जस्तो अचम्मको विवरण र थोरै औपचारिक टोनले थोरै साँचो-स्क्रिप्ट झल्किन्छ।)
  - groq/qwen3.8-27b: before 4 (The tone is respectful and natural, expressing a desire to be accurate rather than guessing, though the specific phrasing is slightly formal for a quick chat.) / after 1 (It awkwardly mixes English terms like 'Private Guide Booking Consultation' with Nepali and provides a suspiciously precise and likely incorrect detail of 'USD 0.00' cost, reading like a broken template.)

**[d-102 s0]** Δ -2.00 (before 4.00 / after 2.00) — Samaj Dental Clinic, business_hours, en, real

- CUSTOMER: What are your opening hours?
- BEFORE: Our hours are: Monday-Friday: 9:00 AM - 6:00 PM. Saturday: Closed. Sunday: 10:00 AM - 6:00 PM.
- AFTER: Our hours are: Monday-Friday: 9:00 AM - 6:00 PM. Saturday: Closed. Sunday: 10:00 AM - 6:00 PM. Let me check with our senior team on this and get back to you shortly.
  - azure/gpt-5-mini: before 5 (Clear, direct answer that a real receptionist would give without unnecessary filler.) / after 3 (Provides the hours but adds an odd, unnecessary promise to check with a senior team, which feels scripted rather than naturally helpful.)
  - groq/qwen3.8-27b: before 3 (The answer is accurate and direct, but the phrasing is a bit stiff and lacks the conversational warmth of a human agent.) / after 1 (It provides the full answer immediately but then contradicts itself by claiming to 'go check' for information it just supplied, which is illogical and highly robotic.)

**[dental-06 s1]** Δ -2.00 (before 4.50 / after 2.50) — Samaj Dental Clinic, service_question, ne_deva, real

- CUSTOMER: हेलो तपाईँको सर्भिस के के छ
- BEFORE: नमस्ते हजुर — हाम्रा सर्भिसहरू:
- Teeth Cleaning (Scaling & Polishing) — NPR 1500, 30 min
- Root Canal Treatment — NPR 8000, 60 min
- Tooth Extraction — NPR 1500, 20 min
- Braces Consultation — NPR 800, 30 min
- Full Braces Treatment — NPR 60000, 60 min
- Teeth Whitening — NPR 6000, 45 min
- Dental Implant (per tooth) — NPR 45000, 90 min
- Tooth Filling — NPR 1200, 30 min
- Dental Consultation — NPR 500, 25 min
कुन सेवा बारेमा थप जानकारी चाहनुहुन्छ वा appointment बुक गर्न चाहनुहुन्छ?
- AFTER: नमस्ते, म प्रिय — के मा सहयोग गर्न सक्छु?
हाम्रो सेवाहरू:
- Teeth Cleaning (Scaling & Polishing) — NPR 1500, 30 मिनेट
- Root Canal Treatment — NPR 8000, 60 मिनेट
- Tooth Extraction — NPR 1500, 20 मिनेट
- Braces Consultation — NPR 800, 30 मिनेट
- Full Braces Treatment — NPR 60000, 60 मिनेट
- Teeth Whitening — NPR 6000, 45 मिनेट
- Dental Implant (प्रति दाँत) — NPR 45000, 90 मिनेट
- Tooth Filling — NPR 1200, 30 मिनेट
- Dental Consultation — NPR 500, 25 मिनेट
  - azure/gpt-5-mini: before 5 (Polite greeting, clear service list with prices and durations, and a friendly follow-up question offering further help or booking—reads like a real receptionist.) / after 3 (Provides the same useful details but has an odd self-introduction and lacks a closing question or prompt, making it feel less natural and attentive.)
  - groq/qwen3.8-27b: before 4 (Reliable and polite, offering a natural closing question, though the service list is a bit dense and runs on professionally.) / after 2 (The greeting is almost incoherent ('Ke ma sahaya garna sakchu?' is a mistranslation of I can help you), making it sound robotic and unpolished.)

**[t-127 s0]** Δ -2.00 (before 4.50 / after 2.50) — Himalayan Trails Trekking Co., complaint, None, scripted

- CUSTOMER: guide le ekdam rude behave garyo, yesto ta hunu bhayena ni
- BEFORE: Hajur, yo saddai nai hunu hudaina — dherai naramro lagyo sunera. Kun trek/booking ho ra guide ko naam kaha bata? Ke tapaiko incident ko tapaiko description (ke bhayo, kun date, kun time) dinu huncha? Malai yo detail dinuhos, ma team sanga escalate garera chhito samadhan garna madat garchu. Ma yesbare hamro senior team sanga kura garera chadai tapailai update garne chu.
- AFTER: त्यो अनुभव सुनेर दुःख लाग्यो — यस्तो हुनुहुँदैन, hajur. कृपया बताउनुस् कुन ट्रेक/मिति वा गाइडको नाम हो र केठा घटना भयो भन्ने संक्षेपमा लेखिदिनुहुन्छ? चाहनुहुन्छ भने ma team सँग connect garau — उनीहरू यो कुरा अगाडि बढाउनेछन्. Let me check with our senior team on this and get back to you shortly.
  - azure/gpt-5-mini: before 4 (Polite, consistent Nepali, asks for specific details and promises escalation—feels more natural and attentive, though a small repetition makes it slightly less perfect.) / after 3 (Clear and helpful but mixes languages and has slightly awkward phrasing, so it reads a bit scripted rather than like a single attentive person.)
  - groq/qwen3.8-27b: before 5 (The consistent and fluid use of natural Nepali phrasing (e.g., 'saddai nai hunu hudaina', 'naramro lagyo') makes this feel like a genuine, empathetic local receptionist rather than a translation or bot.) / after 2 (The forced code-switching between Devanagari script and Roman script (e.g., 'hajur', 'ma team') within a single sentence creates a disjointed and unnatural reading experience typical of poor LLM generation.)


## Lowest absolute 'after' scores (what still reads most bot-like, regardless of Δ)

**[trekking-12 s1]** Δ +0.00 (before 1.00 / after 1.00) — Himalayan Trails Trekking Co., off_topic, en, scripted

- CUSTOMER: Can you recommend a good phone plan for international roaming?
- BEFORE: I'm just here to help with things related to Himalayan Trails Trekking Co. — appointments, services, hours, and the like. Is there something about that I can help with?
- AFTER: I'm just here to help with things related to Himalayan Trails Trekking Co. — appointments, services, hours, and the like. Is there something about that I can help with?
  - azure/gpt-5-mini: before 1 (Exact duplicate canned message that ignores the request for phone plan advice and reads like a scripted auto-reply.) / after 1 (Generic canned response that doesn't answer the customer's question or offer alternatives; sounds like a scripted bot.)
  - groq/qwen3.8-27b: before 1 (The response is an automated, rigid scope-limitation message that provides no insight or helpful redirection.) / after 1 (The response is an automated, rigid scope-limitation message that provides no insight or helpful redirection.)

**[d-106 s0]** Δ +0.00 (before 1.00 / after 1.00) — Samaj Dental Clinic, appointment_status, en, real

- CUSTOMER: what appointmet do i have
- BEFORE: You don't have any appointments on file with us right now, Website Visitor.
- AFTER: You don't have any appointments on file with us right now, Website Visitor.
  - azure/gpt-5-mini: before 1 (Identical to A and equally formulaic and impersonal, with no follow-up or assistance that a human receptionist would provide.) / after 1 (Very robotic and generic—uses a placeholder name and offers no help or next steps, so it doesn't read like a real receptionist.)
  - groq/qwen3.8-27b: before 1 (Using the label 'Website Visitor' instead of a name or friendly greeting is a hallmark of automated chatbots, making it feel cold and robotic.) / after 1 (Identical to Reply A, the use of 'Website Visitor' makes this sound like a canned system message rather than a human conversation.)

**[d-106 s1]** Δ +0.00 (before 1.00 / after 1.00) — Samaj Dental Clinic, appointment_status, en, real

- CUSTOMER: what appointmet do i have
- BEFORE: You don't have any appointments on file with us right now, Website Visitor.
- AFTER: You don't have any appointments on file with us right now, Website Visitor.
  - azure/gpt-5-mini: before 1 (The reply is terse and uses an impersonal label ('Website Visitor'), sounding automated and offering no help or next steps.) / after 1 (Identical to A, it reads scripted and impersonal, lacking friendliness or guidance on how to book or check appointments.)
  - groq/qwen3.8-27b: before 1 (The use of the label 'Website Visitor' instead of a name is a classic rigid system artifact that destroys any sense of human connection.) / after 1 (The response is identical to a typical automated ticketing response and lacks any personalization or natural phrasing.)

**[d-125 s0]** Δ +0.00 (before 1.00 / after 1.00) — Samaj Dental Clinic, appointment_status, ne_roman, real

- CUSTOMER: ea sachhi mero appointment ko time kati re kasto yad vayana
- BEFORE: Ahile tapaiko hamisanga kunai appointment record chaina, Website Visitor.
- AFTER: Ahile tapaiko hamisanga kunai appointment record chaina, Website Visitor.
  - azure/gpt-5-mini: before 1 (Very robotic and unhelpful—exact wording feels like an automated label and offers no next steps or empathy.) / after 1 (Identical to A and equally scripted, using a mechanical label and failing to guide or reassure the customer.)
  - groq/qwen3.8-27b: before 1 (The reply uses the automated placeholder 'Website Visitor' instead of the customer's name, which is a clear indicator of a generic script failing to personalize.) / after 1 (Identical to Reply A, it rigidly uses the label 'Website Visitor' and provides no empathetic or conversational cushioning for the negative news.)

**[t-109 s0]** Δ +0.00 (before 1.00 / after 1.00) — Himalayan Trails Trekking Co., appointment_status, en, scripted

- CUSTOMER: When is my trek consultation again?
- BEFORE: You don't have any appointments on file with us right now, Website Visitor.
- AFTER: You don't have any appointments on file with us right now, Website Visitor.
  - azure/gpt-5-mini: before 1 (Terse and robotic phrasing with a generic label 'Website Visitor' makes it sound automated rather than from a receptionist.) / after 1 (Exact duplicate of A: impersonal, blunt, and uses 'Website Visitor' which reads like an automated system message.)
  - groq/qwen3.8-27b: before 1 (The phrase 'Website Visitor' is a brittle system placeholder that makes the speaker sound like an automated diagnostic tool rather than a helpful human.) / after 1 (The identical use of 'Website Visitor' is robotic and impersonal, clearly signaling a script lacking any human empathetic tone.)

**[t-109 s1]** Δ +0.00 (before 1.00 / after 1.00) — Himalayan Trails Trekking Co., appointment_status, en, scripted

- CUSTOMER: When is my trek consultation again?
- BEFORE: You don't have any appointments on file with us right now, Website Visitor.
- AFTER: You don't have any appointments on file with us right now, Website Visitor.
  - azure/gpt-5-mini: before 1 (Identical to A: impersonal, scripted language with no guidance or friendly tone.) / after 1 (Feels robotic and impersonal (uses 'Website Visitor') and offers no next steps or warmth.)
  - groq/qwen3.8-27b: before 1 (The phrase 'Website Visitor' exposes automated tracking behind the customer's request, making the response feel cold, script-driven, and robotic.) / after 1 (The phrase 'Website Visitor' exposes automated tracking behind the customer's request, making the response feel cold, script-driven, and robotic.)

**[t-125 s0]** Δ +0.00 (before 1.00 / after 1.00) — Himalayan Trails Trekking Co., appointment_status, ne_roman, scripted

- CUSTOMER: mero consultation kahile ho, birsiye
- BEFORE: Ahile tapaiko hamisanga kunai appointment record chaina, Website Visitor.
- AFTER: Ahile tapaiko hamisanga kunai appointment record chaina, Website Visitor.
  - azure/gpt-5-mini: before 1 (Identical, templated phrase with a placeholder 'Website Visitor' that sounds like an automated system message rather than a caring receptionist.) / after 1 (Exactly the same robotic, placeholder-filled reply that lacks personalization or warmth and reads like an automated response.)
  - groq/qwen3.8-27b: before 1 (Identical to Reply A, it fails to address the user's request to book an appointment and instead provides a contradictory error message with an anonymous label, indicating poor or non-functional automated logic.) / after 1 (The address is completely unknown, yet the text immediately calls the customer 'Website Visitor', which is a clear sign of a buggy or unhelpful automated script rather than a human who would ask for the name or apologize for the error.)

**[t-129 s0]** Δ +0.00 (before 1.00 / after 1.00) — Himalayan Trails Trekking Co., off_topic, None, scripted

- CUSTOMER: Nepal ko sabai vanda aglo jhil kun ho?
- BEFORE: I'm just here to help with things related to Himalayan Trails Trekking Co. — appointments, services, hours, and the like. Is there something about that I can help with?
- AFTER: I'm just here to help with things related to Himalayan Trails Trekking Co. — appointments, services, hours, and the like. Is there something about that I can help with?
  - azure/gpt-5-mini: before 1 (Reply is a generic, scripted restriction message in English and doesn't engage the customer's Nepali question or offer a helpful alternative.) / after 1 (This is the same canned, impersonal response as A, failing to answer the Nepali query or show attentive, human reception.)
  - groq/qwen3.8-27b: before 1 (The response is identical to a generic refusal template that completely ignores the customer's specific geographical inquiry, making it feel robotic and unhelpful.) / after 1 (The response is identical to a generic refusal template that completely ignores the customer's specific geographical inquiry, making it feel robotic and unhelpful.)


## Biggest improvements

**[d-111 s0]** Δ +4.00 (before 1.00 / after 5.00) — Samaj Dental Clinic, service_question, en, real

- CUSTOMER: I want to come in for some dental work soon, not totally sure what I need done though -- whenever you have an opening works for me, what would you suggest?
- BEFORE: Sorry, I want to make sure I get this right — could you tell me exactly which service, and the date and time you'd like?
- AFTER: Hi, I'm Priya — happy to help. If you're not sure what treatment you need, I recommend starting with a Dental Consultation so the dentist can examine you and suggest the right plan. A Dental Consultation is NPR 500 and takes about 25 minutes. Would you like me to check our next available consultation slots for you?
  - azure/gpt-5-mini: before 1 (Curt and unhelpful—asks for exact details without offering guidance or accommodating uncertainty, sounding robotic rather than attentive.) / after 5 (Warm, helpful, and informative with a clear next step and relevant details (price and duration) like a real receptionist would provide.)
  - groq/qwen3.8-27b: before 1 (It ignores the customer's explicit statement that they are unsure what they need and instead demand specific details they do not have, which is robotic and unhelpful.) / after 5 (It directly addresses the customer's uncertainty with a logical suggestion (consultation), provides helpful details, and offers a clear next step in a warm, personal tone.)

**[s-101 s0]** Δ +3.00 (before 2.00 / after 5.00) — Everest Pathways Consultancy, greeting, en, scripted

- CUSTOMER: Good morning
- BEFORE: Good morning! How can I help you with your study-abroad plans today? We offer Document Evaluation, Initial Counseling Session, University Application Review, and Visa Interview Preparation.
- AFTER: Good morning — I'm Anjali at Everest Pathways Consultancy. How can I help you today?
  - azure/gpt-5-mini: before 2 (Polished but generic and scripted — it lists services rather than responding personally, so it doesn't feel like a real receptionist.) / after 5 (Warm and personal, introduces the receptionist by name and asks a simple open question, which feels like a genuine human reply.)
  - groq/qwen3.8-27b: before 2 (It dumps a rigid list of specific services and makes unfounded assumptions about the customer's needs, sounding like a triggered menu response rather than a conversation.) / after 5 (It uses a specific name and company title to establish a personal connection, which feels like a real agent introducing themselves naturally.)

**[d-102 s1]** Δ +3.00 (before 1.50 / after 4.50) — Samaj Dental Clinic, business_hours, en, real

- CUSTOMER: What are your opening hours?
- BEFORE: Our hours are: Monday-Friday: 9:00 AM - 6:00 PM. Saturday: Closed. Sunday: 10:00 AM - 6:00 PM. Let me check with our senior team on this and get back to you shortly.
- AFTER: Our hours are: Monday-Friday: 9:00 AM - 6:00 PM. Saturday: Closed. Sunday: 10:00 AM - 6:00 PM.
  - azure/gpt-5-mini: before 2 (Provides the hours but then unnecessarily adds a vague follow-up about checking with a senior team, which feels scripted and inconsistent.) / after 5 (Clear, concise, and directly answers the question in a natural receptionist tone.)
  - groq/qwen3.8-27b: before 1 (It is logically incoherent to provide the specific hours and then immediately state that the agent needs to check with the team on the same topic, marking it as clearly broken or automated nonsense.) / after 4 (While the formatting is a bit list-heavy, it directly answers the question without unnecessary filler, which is competent customer service, though it lacks a warm conversational opener or closing.)

**[s-113 s1]** Δ +2.50 (before 2.00 / after 4.50) — Everest Pathways Consultancy, general_question, en, real

- CUSTOMER: What is the fee for BBA at Kathmandu Model College?
- BEFORE: I do not have Kathmandu Model College's BBA fee listed here. Would you like me to ask our team to check the current tuition and any admission costs and contact you with the details? If yes, which contact method do you prefer — phone (we have 9800000000) or email? Let me check with our senior team on this and get back to you shortly.
- AFTER: Hi, I'm Anjali — we do not have the current BBA fee for Kathmandu Model College on file. Would you like me to connect you with our admissions advisor to confirm the latest tuition and any available scholarships? Let me check with our senior team on this and get back to you shortly.
  - azure/gpt-5-mini: before 2 (Polite but a bit repetitive and robotic-sounding, with an odd-looking placeholder phone number and scripted phrasing.) / after 4 (Friendly and personalized (name given) and offers a clear next step, sounding more like a real receptionist though slightly scripted.)
  - groq/qwen3.8-27b: before 2 (The inclusion of a fake-looking placeholder phone number and the repetitive, formulaic phrasing make it feel like a broken script rather than a human.) / after 5 (The personalized greeting and natural, empathetic flow make it sound like a real person is handling the request, despite the slightly redundant closing.)

**[t-120 s1]** Δ +2.50 (before 2.00 / after 4.50) — Himalayan Trails Trekking Co., service_question, ne_roman, scripted

- CUSTOMER: Mardi Himal trek garna milcha? kati din lagcha?
- BEFORE: Mardi Himal hamro provided list maa explicitly dekhaudaina, tesaile maile yo service ko availability yaha bata confirm garna sakina. Hajur lai ma team sanga confirm garera departures/price/kun season maa possible ho bhanera check garera connect garau? Wa, free Trek Booking Consultation book garna man cha bhane booking set garaidinchu.
- AFTER: Namaste hajur! Mardi Himal ko details hamro available packages ma chaina, tesaile maile yo confirm garna sakdina yaha bata — tapaile yo bare ma thaha pauna chahnuhuncha? Ma team sanga connect garera availability ra kati din lagchha bhanne kura confirm garera pathauna sakchhu.
  - azure/gpt-5-mini: before 2 (Reads a bit stilted and mixed-language, with awkward phrasing and pushy canned options that feel scripted rather than conversational.) / after 4 (Warmer and more natural Nepali greeting and offer to check with the team, sounding like a real person though slightly formulaic.)
  - groq/qwen3.8-27b: before 2 (It uses awkward code-switching (mixing English terms like 'explicitly', 'departures', 'available list') and relies on corporate jargon like 'Trek Booking Consultation,' making it feel like a translated script rather than natural Nepali speech.) / after 5 (It uses natural 'Rekha' (courteous) polite Nepali, answers the specific question about the number of days by offering to verify it, and sounds like a helpful, local human receptionist.)

