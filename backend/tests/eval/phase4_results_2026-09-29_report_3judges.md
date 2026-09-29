# Phase 4 multi-judge eval — 235 (case, sample) pairs, 119 cases, 3 judges

## Headline (consensus = mean of judges)

- before 3.35 → after 3.40, **Δ +0.04** (95% bootstrap CI over cases -0.10 … +0.17)
- cases improved/tied/regressed (consensus, averaged over samples): 41/37/41
- 64/235 pairs got byte-identical before/after replies (deterministic templates the Phase 1-3 pipeline never touches); Δ over only the 171 pairs that differ: +0.07

| judge | before | after | Δ | 95% CI (cases) |
|---|---|---|---|---|
| azure/gpt-5-mini | 3.71 | 3.67 | -0.06 | -0.22 … +0.11 |
| groq/gpt-oss-120b | 3.16 | 3.16 | -0.01 | -0.16 … +0.14 |
| groq/qwen3.8-27b | 3.17 | 3.36 | +0.18 | -0.01 … +0.36 |

## Inter-judge agreement

Per reply score (both arms pooled) and per pair Δ (after − before):

| judge pair | score within ±1 | exact | Pearson r | Δ same sign | Δ within ±1 |
|---|---|---|---|---|---|
| azure/gpt-5-mini vs groq/gpt-oss-120b | 88% | 37% | 0.68 | 79% | 84% |
| azure/gpt-5-mini vs groq/qwen3.8-27b | 81% | 36% | 0.54 | 73% | 77% |
| groq/gpt-oss-120b vs groq/qwen3.8-27b | 84% | 40% | 0.52 | 74% | 76% |

- all 3 judges within ±1 of each other on a reply: **71%**
- all judges agree on the direction of Δ (better/same/worse) for a pair: **64%**

Self-consistency (same judge, identical input, re-judged):

| judge | rechecks | exact | max abs diff |
|---|---|---|---|
| azure/gpt-5-mini | 32 | 64% | 2 |
| groq/gpt-oss-120b | 20 | 75% | 2 |
| groq/qwen3.8-27b | 31 | 40% | 3 |

Generation noise (same case, sample 0 vs 1, consensus Δ): same sign 59%, mean |Δ0 − Δ1| 0.76 over 116 cases.

## By tenant

| slice | n pairs | before | after | Δ | 95% CI | Δ gpt-5-mini | Δ gpt-oss-120b | Δ qwen3.8-27b | all-judges ±1 |
|---|---|---|---|---|---|---|---|---|---|
| Samaj Dental Clinic | 134 | 3.40 | 3.42 | +0.02 | -0.13 … +0.18 | -0.01 | -0.06 | +0.13 | 70% |
| Himalayan Trails Trekking Co. | 75 | 3.16 | 3.20 | +0.05 | -0.16 … +0.26 | -0.11 | +0.04 | +0.21 | 71% |
| Everest Pathways Consultancy | 26 | 3.62 | 3.83 | +0.22 | -0.10 … +0.53 | +0.00 | +0.19 | +0.46 | 75% |

## By language (detected, after arm)

| slice | n pairs | before | after | Δ | 95% CI | Δ gpt-5-mini | Δ gpt-oss-120b | Δ qwen3.8-27b | all-judges ±1 |
|---|---|---|---|---|---|---|---|---|---|
| en | 98 | 3.11 | 3.36 | +0.25 | +0.07 … +0.44 | +0.10 | +0.21 | +0.44 | 75% |
| ne_roman | 81 | 3.47 | 3.37 | -0.10 | -0.27 … +0.07 | -0.16 | -0.22 | +0.09 | 66% |
| ne_deva | 50 | 3.60 | 3.43 | -0.17 | -0.43 … +0.08 | -0.22 | -0.22 | -0.08 | 74% |
| None | 6 | 3.44 | 4.06 | +0.61 | -0.11 … +1.28 | +0.67 | +1.33 | -0.17 | 42% |

## By intent (detected, after arm)

| slice | n pairs | before | after | Δ | 95% CI | Δ gpt-5-mini | Δ gpt-oss-120b | Δ qwen3.8-27b | all-judges ±1 |
|---|---|---|---|---|---|---|---|---|---|
| service_question | 42 | 3.56 | 3.76 | +0.21 | -0.12 … +0.56 | -0.10 | +0.17 | +0.55 | 71% |
| booking | 30 | 3.01 | 2.91 | -0.10 | -0.24 … +0.00 | -0.10 | -0.13 | -0.07 | 68% |
| pricing_question | 29 | 4.00 | 3.64 | -0.36 | -0.70 … +0.00 | -0.34 | -0.38 | -0.34 | 76% |
| greeting | 20 | 3.42 | 4.18 | +0.77 | +0.28 … +1.17 | +0.80 | +0.80 | +0.70 | 68% |
| complaint | 16 | 3.85 | 3.75 | -0.10 | -0.54 … +0.35 | -0.44 | -0.06 | +0.19 | 66% |
| location | 14 | 3.43 | 3.71 | +0.29 | -0.07 … +0.64 | +0.50 | +0.00 | +0.36 | 54% |
| general_question | 13 | 3.69 | 3.41 | -0.28 | -0.92 … +0.36 | -0.08 | -0.31 | -0.46 | 73% |
| off_topic | 12 | 1.72 | 1.72 | +0.00 | +0.00 … +0.00 | +0.00 | +0.00 | +0.00 | 67% |
| cancellation | 12 | 3.92 | 3.72 | -0.19 | -0.56 … +0.19 | -0.67 | -0.08 | +0.17 | 71% |
| business_hours | 10 | 2.27 | 2.23 | -0.03 | -0.50 … +0.40 | +0.10 | -0.30 | +0.10 | 80% |
| human_handoff | 9 | 3.33 | 3.89 | +0.56 | +0.04 … +1.04 | +0.33 | +0.44 | +0.89 | 78% |
| appointment_status | 9 | 1.37 | 1.37 | +0.00 | +0.00 … +0.00 | +0.00 | +0.00 | +0.00 | 100% |
| resend_confirmation | 9 | 3.81 | 4.07 | +0.26 | -0.22 … +0.70 | +0.00 | -0.11 | +0.89 | 72% |
| rescheduling | 9 | 3.67 | 3.56 | -0.11 | -0.96 … +0.67 | -0.22 | -0.11 | +0.00 | 56% |
| follow_up | 1 | 4.67 | 3.33 | -1.33 | +nan … +nan | -2.00 | -1.00 | -1.00 | 100% |

## Biggest remaining gaps (consensus Δ most negative), with transcripts

**[d-132 s0]** Δ -2.33 (before 4.67 / after 2.33) — Samaj Dental Clinic, greeting, ne_deva, real

- CUSTOMER: नमस्ते
- BEFORE: नमस्ते, हाजुर — म कसरि सहयोग गर्न सक्छु?
- AFTER: नमस्ते! म प्रिय — तपाईंलाई के सहयोग चाहियो, हजुर?
  - azure/gpt-5-mini: before 5 (Concise, polite and natural Nepali phrasing that reads like a real receptionist offering help.) / after 3 (Polite and attempts friendliness by introducing a name, but the name/word choice ('प्रिय' instead of 'प्रिया' or a clearer introduction) and slight awkward phrasing make it feel a bit off/scripted.)
  - groq/gpt-oss-120b: before 4 (Polite and concise, uses natural phrasing without obvious placeholders, feels like a real receptionist.) / after 2 (Contains a broken intro ('म प्रिय —') that looks like an unfilled template, making it feel scripted.)
  - groq/qwen3.8-27b: before 5 (It is a grammatically correct, polite, and concise standard opening that sounds completely natural for a Nepali-speaking receptionist.) / after 2 (The phrase 'म प्रिय' (I [am] love) is grammatically incorrect and nonsensical in this context, resembling a poor machine translation or hallucination rather than a human error.)

**[d-133 s1]** Δ -2.33 (before 4.67 / after 2.33) — Samaj Dental Clinic, general_question, ne_deva, real

- CUSTOMER: हेलो हामी नेपालीमा बोल्न सक्छौँ
- BEFORE: नमस्ते! पक्का — हामी नेपालीमै बोल्न सक्छौँ, हाजुर। म कसरी सहयोग गर्न सक्छु?
- AFTER: नमस्ते, म प्रिय हुँ — पक्कै, हामी नेपालीमै कुरा गर्न सक्छौं, हजुर। म कसरी सहयोग गर्न सक्छु?
  - azure/gpt-5-mini: before 5 (स्पष्ट, मिलनसार र स्वाभाविक स्वागत — मानव रिसेप्सनिस्टले बोले जस्तो लाग्छ।) / after 3 (सामान्यतया ठिक छ तर 'म प्रिय हुँ' भनाइ अलि असम्बद्ध/अनावश्यक छ र थोरै औपचारिकता बोटो देखिन्छ।)
  - groq/gpt-oss-120b: before 4 (Uses natural, polite Nepali phrasing and a friendly tone, sounding like a real receptionist.) / after 2 (Contains odd phrasing like “म प्रिय हुँ” and feels scripted rather than a genuine human response.)
  - groq/qwen3.8-27b: before 5 (The use of the respectful form 'हाजुर' combined with natural phrasing and a welcoming tone ('पक्का') reads exactly like a polite and attentive human receptionist in a Nepali-speaking context.) / after 2 (The phrase 'म प्रिय हुँ' ('I am dear') is semantically nonsensical and grammatically awkward in this context, reading more like a machine translation error or a typo for 'प्रियंका' (a name), which breaks the illusion of a human writer.)

**[t-123 s0]** Δ -2.33 (before 4.33 / after 2.00) — Himalayan Trails Trekking Co., rescheduling, ne_roman, scripted

- CUSTOMER: mero gear pickup parsi lai sarna milcha?
- BEFORE: Thik cha, hajur — tara kun Gear Rental Pickup appointment sarnu bhannu bhayeko ho malaai thaha chhaina. Kripaya original pickup ko date ra time (or booking reference) dinuhos, ani confirm garnuhos ki "parsi" bhaneko 2026-10-01 ma sarnu ho?
- AFTER: Huss — ke yo tapaiko Gear Rental Pickup appointment ho?
  - azure/gpt-5-mini: before 4 (Polite and clarifying — asks for the original booking details and confirms what 'parsi' refers to, sounding like an attentive receptionist.) / after 2 (Very brief and abrupt, lacking confirmation steps or polite detail so it feels more like a curt scripted reply than a thoughtful human response.)
  - groq/gpt-oss-120b: before 4 (Polite, detailed, and asks for specific info, resembling a genuine human handling the request.) / after 2 (Very brief and generic, sounding like a canned clarification rather than a thoughtful response.)
  - groq/qwen3.8-27b: before 5 (It naturally acknowledges the uncertainty of the specific date, asks for the necessary details (booking ref/date), and confirms the translation of 'parsi' to a specific date, showing genuine attentiveness.) / after 2 (The bizarre use of 'Huss' as a greeting instead of the standard Nepali 'Ho' makes it sound like a glitchy translation or AI error rather than a human.)

**[d-127 s1]** Δ -2.00 (before 4.67 / after 2.67) — Samaj Dental Clinic, service_question, ne_roman, real

- CUSTOMER: Mero daath dukheko cha k garnu sakvhu
- BEFORE: Dukhai bhayeko sunera afno laagi naramro lagyo. Pahila doctor le herera thik diagnosis garne parcha — Dental Consultation (NPR 500, 25 min) recommend garchu; tes pachi jaruri bhaye filling, extraction, or root canal jasto treatment salla garincha. Appointment book garna man cha hajur? Kun din/kun samaya milcha bhanera pathaunuhos, tara dherai dukha bhaye aaja chadhnu hola (Saturday banda cha, tara Sunday 10:00‑18:00 khula cha).
- AFTER: Dukhai ko lagi duchh, hajur. Daath ko pain ko lagi pahila Dental Consultation le herera exact karan thahaa garincha — hami ko Dental Consultation NPR 500 ho ra karib 25 minutes lagcha. Agar severe pain, gaalo sujeko, jor/fever cha bhane yo emergency jasto ho — chito aunuhos. Booking garna man cha hajur?
  - azure/gpt-5-mini: before 5 (Warmer and more empathetic, offers clear next steps and scheduling details, and invites a specific appointment time like a real receptionist would.) / after 2 (Short, a bit stilted with typos and blunt phrasing; reads like a scripted response rather than a warm receptionist.)
  - groq/gpt-oss-120b: before 4 (Shows empathy, gives specific details and options, and asks for a convenient time, feeling more personalized than a canned response.) / after 3 (Provides basic info and empathy but is shorter and more formulaic, sounding more like a generic template.)
  - groq/qwen3.8-27b: before 5 (It reads like a knowledgeable and empathetic human receptionist because it proactively provides specific next-step treatments (filling, root canal) and detailed, date-aware availability context (mentioning Saturday is closed) rather than just stating a price.) / after 3 (It is polite and functional but feels more like a standard script because it relies on generic safety warnings and lacks the specific, context-rich details (like today's operational status) that would make it sound genuinely attentive.)

**[trekking-09 s0]** Δ -2.00 (before 4.00 / after 2.00) — Himalayan Trails Trekking Co., pricing_question, ne_deva, real

- CUSTOMER: गाइड बुकिङको लागि कति खर्च लाग्छ?
- BEFORE: त्यसमा म अड्कल गर्न चाहन्न — म टिमबाट सही जानकारी लिएर तपाईंलाई फलो-अप गराउँछु। म यसबारे हाम्रो सिनियर टिमसँग कुरा गरेर चाँडै तपाईंलाई अपडेट गर्नेछु।
- AFTER: Private Guide Booking Consultation को खर्च USD 0.00 हुन्छ र करिब 30 मिनेट लग्छ। बुक गर्न चाहनुहुन्छ भने कुन मिति वा समय उपयुक्त होला?
  - azure/gpt-5-mini: before 4 (सिधा जवाफ नदिई पनि इमान्दारपूर्वक अनुमान नगर्ने र टिमसँग परामर्श गरेर फोलोअप गर्ने कुरा गर्नु भएको छ—ध्यानपूर्वक मान्छेले लेखेको जस्तो लाग्छ।) / after 3 (स्पष्ट र तुरुन्त जवाफ दिएको भएता पनि USD 0.00 जस्तो अचम्मको विवरण र थोरै औपचारिक टोनले थोरै साँचो-स्क्रिप्ट झल्किन्छ।)
  - groq/gpt-oss-120b: before 4 (Sounds personal and acknowledges needing to get accurate info, like a human would.) / after 2 (Looks like a generic template with odd zero‑price detail and mixed language.)
  - groq/qwen3.8-27b: before 4 (The tone is respectful and natural, expressing a desire to be accurate rather than guessing, though the specific phrasing is slightly formal for a quick chat.) / after 1 (It awkwardly mixes English terms like 'Private Guide Booking Consultation' with Nepali and provides a suspiciously precise and likely incorrect detail of 'USD 0.00' cost, reading like a broken template.)

**[trekking-02 s1]** Δ -1.67 (before 4.67 / after 3.00) — Himalayan Trails Trekking Co., general_question, ne_roman, scripted

- CUSTOMER: Namaste! Trek ko bare ma sodhna man lagyo.
- BEFORE: Namaste hajur! Trek ko bare ma sodhna man lagyo bhane ma madat garna sakchu — kun trek ko bare ma sodhna cha? (Everest Base Camp, Annapurna Circuit, Langtang, Poon Hill, or general details like season/pricing). Vanna saknu bhaye ma free Trek Booking Consultation set garna pani help garnechu.
- AFTER: Namaste! Ma Pemba — kasari madat garna sakincha hajur?
  - azure/gpt-5-mini: before 5 (Warm, responsive and specific—asks a clarifying question, offers example options and a helpful next step, sounding like a real receptionist.) / after 4 (Concise and personable with a name and an offer to help, but a bit short and lacking the specific follow-up details of a fuller human reply.)
  - groq/gpt-oss-120b: before 5 (Offers specific follow‑up questions, lists common trek options, and even mentions a free consultation, sounding like a genuinely helpful human.) / after 2 (Very brief and generic, offering only a vague offer of help without any tailored detail.)
  - groq/qwen3.8-27b: before 4 (It mirrors the user's phrase naturally and offers specific, organized assistance like a competent assistant, though the rapid shift to formal booking terminology feels slightly procedural.) / after 3 (It sounds like a standard, polite greeting script ('This is Pemba, how can I help?') that lacks any specific acknowledgment of the user's immediate intent, making it feel more like an automated standby message.)

**[d-102 s0]** Δ -1.67 (before 4.00 / after 2.33) — Samaj Dental Clinic, business_hours, en, real

- CUSTOMER: What are your opening hours?
- BEFORE: Our hours are: Monday-Friday: 9:00 AM - 6:00 PM. Saturday: Closed. Sunday: 10:00 AM - 6:00 PM.
- AFTER: Our hours are: Monday-Friday: 9:00 AM - 6:00 PM. Saturday: Closed. Sunday: 10:00 AM - 6:00 PM. Let me check with our senior team on this and get back to you shortly.
  - azure/gpt-5-mini: before 5 (Clear, direct answer that a real receptionist would give without unnecessary filler.) / after 3 (Provides the hours but adds an odd, unnecessary promise to check with a senior team, which feels scripted rather than naturally helpful.)
  - groq/gpt-oss-120b: before 4 (Provides the requested hours directly and concisely, resembling a straightforward human reply.) / after 3 (Adds an unnecessary promise to verify information already given, making it sound scripted rather than a natural, attentive response.)
  - groq/qwen3.8-27b: before 3 (The answer is accurate and direct, but the phrasing is a bit stiff and lacks the conversational warmth of a human agent.) / after 1 (It provides the full answer immediately but then contradicts itself by claiming to 'go check' for information it just supplied, which is illogical and highly robotic.)

**[dental-06 s1]** Δ -1.67 (before 4.33 / after 2.67) — Samaj Dental Clinic, service_question, ne_deva, real

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
  - groq/gpt-oss-120b: before 4 (Uses a friendly greeting, lists services clearly, and asks a follow‑up question, feeling like a helpful human receptionist.) / after 3 (Greeting and list are fine, but the phrasing (“म प्रिय”) feels odd and it lacks a personal follow‑up, making it seem more scripted.)
  - groq/qwen3.8-27b: before 4 (Reliable and polite, offering a natural closing question, though the service list is a bit dense and runs on professionally.) / after 2 (The greeting is almost incoherent ('Ke ma sahaya garna sakchu?' is a mistranslation of I can help you), making it sound robotic and unpolished.)

**[d-131 s1]** Δ -1.67 (before 4.33 / after 2.67) — Samaj Dental Clinic, booking, ne_roman, real

- CUSTOMER: sunnu na mero teeth ali ali dukhay ko 2 din vayo check garau nai parxara?
- BEFORE: Dental Consultation ko lagi yi samaya haru khali chan: Thursday, October 1 at 9:00 AM, 9:15 AM, 9:30 AM, 11:30 AM, 11:45 AM. Kun milcha?
- AFTER: Maaf garnuhos, maile thik sanga bujhna chahanchu — kun service, ra kun miti ra samaya chahanu huncha bhanera batauna sakinu huncha?
  - azure/gpt-5-mini: before 4 (Provides concrete appointment options like a receptionist, but is a bit terse and doesn't acknowledge the customer's pain.) / after 4 (Polite and seeks clarification in a conversational way, sounding attentive, though it could show more empathy for the pain.)
  - groq/gpt-oss-120b: before 4 (Offers concrete appointment slots and asks which works, sounding helpful and personal rather than generic.) / after 2 (Only asks for clarification without addressing the pain complaint, and reads like a scripted request for more info.)
  - groq/qwen3.8-27b: before 5 (It directly addresses the customer's specific request for a dental checkup and provides concrete options, demonstrating active listening and immediate helpfulness in natural Nepali.) / after 2 (It acts defensively and ignores the clear context of the customer's message, asking for basic details that were already implied, which sounds robotic and uninformed.)

**[d-143 s1]** Δ -1.67 (before 5.00 / after 3.33) — Samaj Dental Clinic, rescheduling, ne_deva, scripted

- CUSTOMER: मेरो भोलिको अपोइन्टमेन्ट पर्सि सार्न मिल्छ?
- BEFORE: ठिक छ — भोलिको अपोइन्टमेन्ट पर्सि सार्न चाहनुहुन्छ भन्ने बुझें। कुन समय मिल्छ हजुर? एउटै समयमै राख्ने हो कि फरक समय चाहिन्छ?
- AFTER: नमस्ते, म प्रिया — पक्कै, भोलिको अपोइन्टमेन्ट पर्सि सार्न मद्दत गर्छु। कुन अपोइन्टमेन्ट हो — कृपया सेवा नाम र हालको मिति/समय बताउनुहोस् (वा जुन अपोइन्टमेन्ट सार्न चाहनु हुन्छ त्यो विस्तृत रुपमा लेख्नुहोस्).
  - azure/gpt-5-mini: before 5 (सिधा, स्वागतात्मक र स्वाभाविक भाषा प्रयोग भएको छ—सोधिने प्रश्नहरू स्पष्ट र हाम्राे जिवन्तRecepशनी शैली अनुसार छन्।) / after 4 (मैत्रीपूर्ण र सहायक छ र नामसमेत प्रस्तुत गरेकोले मानवीय लाग्छ, तर अलिकति औपचारिक र थोरै स्क्रिप्टजस्तो संरचना छ।)
  - groq/gpt-oss-120b: before 5 (Conversational, directly asks for the preferred time, and sounds naturally attentive.) / after 4 (Polite and personal with a name, but the phrasing feels slightly templated.)
  - groq/qwen3.8-27b: before 5 (Uses natural, conversational Nepali phrasing and intuitively asks the most practical follow-up question (time preference) without unnecessary formalities or robotic instructions.) / after 2 (While it uses a friendly Nepali personal name, the language is stiff, uses gendered honorifics that feel awkwardly formal, and the parenthetical instruction to 'write in detail' reads like a rigid system prompt rather than natural speech.)


## Lowest absolute 'after' scores (what still reads most bot-like, regardless of Δ)

**[trekking-12 s1]** Δ +0.00 (before 1.00 / after 1.00) — Himalayan Trails Trekking Co., off_topic, en, scripted

- CUSTOMER: Can you recommend a good phone plan for international roaming?
- BEFORE: I'm just here to help with things related to Himalayan Trails Trekking Co. — appointments, services, hours, and the like. Is there something about that I can help with?
- AFTER: I'm just here to help with things related to Himalayan Trails Trekking Co. — appointments, services, hours, and the like. Is there something about that I can help with?
  - azure/gpt-5-mini: before 1 (Exact duplicate canned message that ignores the request for phone plan advice and reads like a scripted auto-reply.) / after 1 (Generic canned response that doesn't answer the customer's question or offer alternatives; sounds like a scripted bot.)
  - groq/gpt-oss-120b: before 1 (Identical to A, it’s a canned response unrelated to the request, indicating no human attentiveness.) / after 1 (The reply is a generic, out‑of‑context script that doesn’t answer the question at all, sounding robotic.)
  - groq/qwen3.8-27b: before 1 (The response is an automated, rigid scope-limitation message that provides no insight or helpful redirection.) / after 1 (The response is an automated, rigid scope-limitation message that provides no insight or helpful redirection.)

**[d-125 s0]** Δ +0.00 (before 1.00 / after 1.00) — Samaj Dental Clinic, appointment_status, ne_roman, real

- CUSTOMER: ea sachhi mero appointment ko time kati re kasto yad vayana
- BEFORE: Ahile tapaiko hamisanga kunai appointment record chaina, Website Visitor.
- AFTER: Ahile tapaiko hamisanga kunai appointment record chaina, Website Visitor.
  - azure/gpt-5-mini: before 1 (Very robotic and unhelpful—exact wording feels like an automated label and offers no next steps or empathy.) / after 1 (Identical to A and equally scripted, using a mechanical label and failing to guide or reassure the customer.)
  - groq/gpt-oss-120b: before 1 (The reply is a generic, placeholder‑style sentence with no personalization or effort to address the customer's query.) / after 1 (Identical to reply A, it sounds scripted and robotic rather than a thoughtful human response.)
  - groq/qwen3.8-27b: before 1 (The reply uses the automated placeholder 'Website Visitor' instead of the customer's name, which is a clear indicator of a generic script failing to personalize.) / after 1 (Identical to Reply A, it rigidly uses the label 'Website Visitor' and provides no empathetic or conversational cushioning for the negative news.)

**[t-109 s0]** Δ +0.00 (before 1.00 / after 1.00) — Himalayan Trails Trekking Co., appointment_status, en, scripted

- CUSTOMER: When is my trek consultation again?
- BEFORE: You don't have any appointments on file with us right now, Website Visitor.
- AFTER: You don't have any appointments on file with us right now, Website Visitor.
  - azure/gpt-5-mini: before 1 (Terse and robotic phrasing with a generic label 'Website Visitor' makes it sound automated rather than from a receptionist.) / after 1 (Exact duplicate of A: impersonal, blunt, and uses 'Website Visitor' which reads like an automated system message.)
  - groq/gpt-oss-120b: before 1 (The reply is generic, uses a placeholder name, and doesn't address the customer's request, sounding robotic.) / after 1 (Identical to reply A, it is generic, impersonal, and unhelpful, like a scripted response.)
  - groq/qwen3.8-27b: before 1 (The phrase 'Website Visitor' is a brittle system placeholder that makes the speaker sound like an automated diagnostic tool rather than a helpful human.) / after 1 (The identical use of 'Website Visitor' is robotic and impersonal, clearly signaling a script lacking any human empathetic tone.)

**[t-109 s1]** Δ +0.00 (before 1.00 / after 1.00) — Himalayan Trails Trekking Co., appointment_status, en, scripted

- CUSTOMER: When is my trek consultation again?
- BEFORE: You don't have any appointments on file with us right now, Website Visitor.
- AFTER: You don't have any appointments on file with us right now, Website Visitor.
  - azure/gpt-5-mini: before 1 (Identical to A: impersonal, scripted language with no guidance or friendly tone.) / after 1 (Feels robotic and impersonal (uses 'Website Visitor') and offers no next steps or warmth.)
  - groq/gpt-oss-120b: before 1 (Identical to reply A, it is generic, impersonal and fails to provide a helpful, human‑like response.) / after 1 (The reply is generic, impersonal and doesn't address the customer's request, sounding like a scripted bot.)
  - groq/qwen3.8-27b: before 1 (The phrase 'Website Visitor' exposes automated tracking behind the customer's request, making the response feel cold, script-driven, and robotic.) / after 1 (The phrase 'Website Visitor' exposes automated tracking behind the customer's request, making the response feel cold, script-driven, and robotic.)

**[dental-14 s1]** Δ +0.00 (before 1.33 / after 1.33) — Samaj Dental Clinic, off_topic, en, real

- CUSTOMER: Random question — how was America discovered?
- BEFORE: I'm just here to help with things related to Samaj Dental Clinic — appointments, services, hours, and the like. Is there something about that I can help with?
- AFTER: I'm just here to help with things related to Samaj Dental Clinic — appointments, services, hours, and the like. Is there something about that I can help with?
  - azure/gpt-5-mini: before 2 (Identical to A: courteous yet canned and non-personal, giving a standard scope answer without any human warmth or follow-up to the unusual question.) / after 2 (Polite but clearly scripted and generic — doesn't engage the customer's curiosity and reads like a stock refusal tied to clinic scope.)
  - groq/gpt-oss-120b: before 1 (Identical generic reply, no attempt to answer, feels robotic.) / after 1 (Clearly scripted and unrelated to the question, not a thoughtful human response.)
  - groq/qwen3.8-27b: before 1 (Identical to the other reply, it is a stark, robotic script that fails to acknowledge the human element of the conversation.) / after 1 (The response is a rigid, canned phrase that ignores the customer's query entirely, reading like an automated boilerplate filter.)

**[d-106 s0]** Δ +0.00 (before 1.33 / after 1.33) — Samaj Dental Clinic, appointment_status, en, real

- CUSTOMER: what appointmet do i have
- BEFORE: You don't have any appointments on file with us right now, Website Visitor.
- AFTER: You don't have any appointments on file with us right now, Website Visitor.
  - azure/gpt-5-mini: before 1 (Identical to A and equally formulaic and impersonal, with no follow-up or assistance that a human receptionist would provide.) / after 1 (Very robotic and generic—uses a placeholder name and offers no help or next steps, so it doesn't read like a real receptionist.)
  - groq/gpt-oss-120b: before 2 (The response is generic and uses a placeholder name, lacking a personal or attentive tone.) / after 2 (Identical to reply A—generic, impersonal, and feels scripted rather than a thoughtful human reply.)
  - groq/qwen3.8-27b: before 1 (Using the label 'Website Visitor' instead of a name or friendly greeting is a hallmark of automated chatbots, making it feel cold and robotic.) / after 1 (Identical to Reply A, the use of 'Website Visitor' makes this sound like a canned system message rather than a human conversation.)

**[d-106 s1]** Δ +0.00 (before 1.33 / after 1.33) — Samaj Dental Clinic, appointment_status, en, real

- CUSTOMER: what appointmet do i have
- BEFORE: You don't have any appointments on file with us right now, Website Visitor.
- AFTER: You don't have any appointments on file with us right now, Website Visitor.
  - azure/gpt-5-mini: before 1 (The reply is terse and uses an impersonal label ('Website Visitor'), sounding automated and offering no help or next steps.) / after 1 (Identical to A, it reads scripted and impersonal, lacking friendliness or guidance on how to book or check appointments.)
  - groq/gpt-oss-120b: before 2 (Very generic, uses a placeholder name and sounds like a scripted response rather than a thoughtful human.) / after 2 (Identical to reply A; overly generic and robotic with no personal touch.)
  - groq/qwen3.8-27b: before 1 (The use of the label 'Website Visitor' instead of a name is a classic rigid system artifact that destroys any sense of human connection.) / after 1 (The response is identical to a typical automated ticketing response and lacks any personalization or natural phrasing.)

**[d-109 s0]** Δ +0.00 (before 1.33 / after 1.33) — Samaj Dental Clinic, off_topic, en, real

- CUSTOMER: write a c program of finding odd and even number
- BEFORE: I'm just here to help with things related to Samaj Dental Clinic — appointments, services, hours, and the like. Is there something about that I can help with?
- AFTER: I'm just here to help with things related to Samaj Dental Clinic — appointments, services, hours, and the like. Is there something about that I can help with?
  - azure/gpt-5-mini: before 2 (Identical canned message that ignores the customer's coding request; sounds scripted and not thoughtfully tailored to the user.) / after 2 (Polite but clearly canned and off-topic — reads like a scripted auto-response rather than a real receptionist engaging with the request.)
  - groq/gpt-oss-120b: before 1 (Identical to reply A, it is a canned clinic message irrelevant to the C program request, lacking human attentiveness.) / after 1 (The response is a generic, unrelated clinic script that shows no attempt to address the programming request, feeling robotic.)
  - groq/qwen3.8-27b: before 1 (It is a generic, scripted refusal that ignores the user's specific coding request without any natural variation or effort to assist.) / after 1 (It is a generic, scripted refusal that ignores the user's specific coding request without any natural variation or effort to assist.)


## Biggest improvements

**[d-111 s0]** Δ +3.67 (before 1.00 / after 4.67) — Samaj Dental Clinic, service_question, en, real

- CUSTOMER: I want to come in for some dental work soon, not totally sure what I need done though -- whenever you have an opening works for me, what would you suggest?
- BEFORE: Sorry, I want to make sure I get this right — could you tell me exactly which service, and the date and time you'd like?
- AFTER: Hi, I'm Priya — happy to help. If you're not sure what treatment you need, I recommend starting with a Dental Consultation so the dentist can examine you and suggest the right plan. A Dental Consultation is NPR 500 and takes about 25 minutes. Would you like me to check our next available consultation slots for you?
  - azure/gpt-5-mini: before 1 (Curt and unhelpful—asks for exact details without offering guidance or accommodating uncertainty, sounding robotic rather than attentive.) / after 5 (Warm, helpful, and informative with a clear next step and relevant details (price and duration) like a real receptionist would provide.)
  - groq/gpt-oss-120b: before 1 (Very brief, asks for details without addressing the customer's uncertainty, reads like a scripted bot.) / after 4 (Warm, personalized tone with a clear suggestion and follow‑up question, feels like a real receptionist.)
  - groq/qwen3.8-27b: before 1 (It ignores the customer's explicit statement that they are unsure what they need and instead demand specific details they do not have, which is robotic and unhelpful.) / after 5 (It directly addresses the customer's uncertainty with a logical suggestion (consultation), provides helpful details, and offers a clear next step in a warm, personal tone.)

**[d-111 s1]** Δ +2.00 (before 3.00 / after 5.00) — Samaj Dental Clinic, service_question, en, real

- CUSTOMER: I want to come in for some dental work soon, not totally sure what I need done though -- whenever you have an opening works for me, what would you suggest?
- BEFORE: A good first step is a Dental Consultation — NPR 500 for about 25 minutes. The dentist will assess your teeth, recommend any treatment (cleaning, filling, root canal, braces consult, etc.), and we can book the right follow-up from there. Would you like me to check our next available consultation slot for you?
- AFTER: Hi, I'm Priya — happy to help. If you're not sure what you need, I recommend starting with a Dental Consultation (NPR 500, about 25 minutes) so the dentist can examine you and suggest the right treatment. After the consultation we can book any follow-up work (cleaning, filling, root canal, etc.) based on what they find. Would you like me to check our next available consultation slots — mornings or afternoons better for you?
  - azure/gpt-5-mini: before 3 (Clear and helpful but a bit terse and impersonal, reads like a standard scripted response rather than a conversational receptionist.) / after 5 (Warm, introduces the speaker, mirrors the customer's uncertainty, and asks a polite scheduling preference—sounds like a thoughtful human receptionist.)
  - groq/gpt-oss-120b: before 3 (Provides the needed info but feels generic and lacks personal touches that a human would add.) / after 5 (Introduces a name, uses friendly language, and asks about preferred times, sounding like a thoughtful human receptionist.)
  - groq/qwen3.8-27b: before 3 (It is clear and helpful but lacks the personal touch and conversational warmth of a human receptionist, acting more like a standard knowledge-base article.) / after 5 (Opening with a name and warmly acknowledging the customer's uncertainty creates an immediate sense of being personally attended to by a real person.)

**[t-101 s0]** Δ +1.67 (before 3.00 / after 4.67) — Himalayan Trails Trekking Co., greeting, en, scripted

- CUSTOMER: Hi there!
- BEFORE: Hi! Welcome to Himalayan Trails Trekking Co. — how can I help you today?
- AFTER: Hi, I'm Pemba — welcome to Himalayan Trails! How can I help you today?
  - azure/gpt-5-mini: before 3 (Polite and clear but a bit generic and formal—sounds like a standard scripted greeting rather than a named individual.) / after 5 (Feels personal and attentive by introducing the receptionist by name, making it sound like a real person ready to help.)
  - groq/gpt-oss-120b: before 3 (Uses a generic company tagline without personal touch, sounding more scripted.) / after 4 (Adds a personal name and a warm greeting, feeling more like a human receptionist.)
  - groq/qwen3.8-27b: before 3 (It reads like a standard, polite automated greeting that lacks any personal touch or specific identity.) / after 5 (It feels much warmer and more human because it introduces a specific person ('Pemba'), which immediately personalizes the interaction.)

**[d-132 s1]** Δ +1.67 (before 3.00 / after 4.67) — Samaj Dental Clinic, greeting, ne_deva, real

- CUSTOMER: नमस्ते
- BEFORE: नमस्ते! कसरी सहयोग गर्न सक्छु, हजुर?
- AFTER: नमस्ते, म Priya हुँ — हजुरलाई के सहयोग चाहियो?
  - azure/gpt-5-mini: before 4 (Polite and natural Nepali phrasing, but a bit generic and brief without a personal touch.) / after 5 (Introduces a name and asks a clear question, sounding warm and genuinely attentive like a receptionist.)
  - groq/gpt-oss-120b: before 3 (Polite and correct language but feels generic and a bit formulaic.) / after 4 (Adds a personal name and a warm phrasing, sounding more like a human receptionist.)
  - groq/qwen3.8-27b: before 2 (The phrasing is a direct, stiff translation of the standard AI query 'How can I help you?', lacking any personal warmth or identity markers.) / after 5 (The use of the agent's personal name (Priya) and the specific conversational phrasing in Nepali makes it feel like a distinct, friendly individual rather than a generic interface.)

**[study-06 s0]** Δ +1.67 (before 3.00 / after 4.67) — Everest Pathways Consultancy, service_question, ne_deva, scripted

- CUSTOMER: भिसा इन्टरभ्यूको लागि कस्तो तयारी गर्नुपर्छ?
- BEFORE: भिसा इन्टरभ्यूको तयारीमा सामान्यतया: आवश्यक कागजातहरूको तयारी र चेकलिस्ट, साधारण र आवधिक प्रश्नहरूको मॉक इन्टरभ्यू अभ्यास, अंग्रेजी/कम्युनिकेसन स्किल सुधार, शरीरभाषा र दृष्टि·दृष्टान्त अभ्यास, र समय व्यवस्थापन समावेश हुन्छ। हामीसँग 'Visa Interview Preparation' सेवा छ (NPR 3000, 45 मिनेट) — चाहनुहुन्छ भने त्यसको लागि समय हेर्ने वा बुकिङमा मद्दत गरौं।
- AFTER: नमस्ते — म अञ्जली। भिसा इन्टरभ्यूको तयारीमा सामान्यतया निम्न कुरामा ध्यान दिनुपर्छ: प्रश्न–उत्तर अभ्यास (आफ्नो शिक्षा, योजना र फाइनान्सियल अवस्था स्पष्ट रूपमा बताउन सक्नुपर्ने), सम्भावित दस्तावेजहरु तयार राख्ने (आवेदन कपी, पढ़ाइ/आर्थिक प्रमाणहरु), आत्मविश्वासपूर्ण प्रस्तुति र अलि अन्तरवार्ता शैलीमा रुचि देखाउने अभ्यास। हामीसँग विशेष रुपमा Visa Interview Preparation सेवा छ जसले mock interview, सामान्य प्रश्नहरू र feedback समावेश गर्छ (NPR 3000, 45 min)। चाहनु भयो भने यो सेवा बारे थप जानकारी दिन सक्छु वा समय हेरेर उपलब्धता मिलाइदिन सक्छु।
  - azure/gpt-5-mini: before 3 (Clear and useful but reads a bit list-like and impersonal without a greeting or warm tone.) / after 5 (Warm and conversational with a personal introduction and an explicit offer to help, sounding like a real receptionist.)
  - groq/gpt-oss-120b: before 3 (Provides useful info but feels formulaic and lacks a personal touch.) / after 4 (Uses a friendly greeting and a name, sounding more like a considerate human receptionist.)
  - groq/qwen3.8-27b: before 3 (It reads as a competent but formulaic list of services without a greeting or personal touch, making it feel slightly mechanical.) / after 5 (It opens with a warm, personal introduction and name, uses natural conversational phrasing, and feels like a genuine human receptionist engaging with the client.)

