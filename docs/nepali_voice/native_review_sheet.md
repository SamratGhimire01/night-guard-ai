# Native review: 30 real Romanized-Nepali replies, before -> after

From the real conversations in backend/data/regression/real_conversations. 'Before' is what was sent;
'after' is what today's code sends for the same turn (new template wording + word bank + guards). LLM-drafted
replies only show the word-bank/guard changes -- the new prompt's effect needs a live run.

For each: mark OK, or write how a Nepali receptionist would actually text it.

## 1
- Customer: sunnu na mero teeth ali ali dukhay ko 2 din vayo check garau nai parxara?
- Before: Bujhe — Dental Consultation. Lock garna malai tapaiko naam ra phone number wa email chahincha.
- After: Huss — Dental Consultation. Pakka garna tapaiko naam ra phone number (wa email) chahiyo.
- Your verdict: 

## 2
- Customer: I keep asking you to speak Nepali and you're not listening to me, just switch already.
- Before: Maaf garnuhos — tapaiko kura suni raheina jasto bhayo. Ma ahile dekhi Nepali (romanized) ma nai kura garchu. Ke ma availability heraun ki appointment book garna madat garu?
- After: Sorry — tapaiko kura suni raheina jasto bhayo. Ma ahile dekhi Nepali (romanized) ma nai kura garchu. Ke ma availability heraun ki appointment book garna madat garu?
- Your verdict: 

## 3
- Customer: thanks!
- Before: Thik cha — dhanyabad! Booking garna chahanu huncha bhane kun date ra time milcha bhanera batau, ma madat garna sakchhu.
- After: Thik cha — dhanyabad! Booking garna man cha bhane kun date ra time milcha bhanera batau, ma madat garna sakchhu.
- Your verdict: 

## 4
- Customer: ma confuse ma xu k k garne vanera
- Before: Thik cha — bujhna garo bhayo bhane bujhchu. Dantko dukha ko lagi pahilo step Dental Consultation ho (20 min, $50) — doctor le herera ke garnu parne bhanne kura recommend garchan. Yadi dukhā jasto tez dukha, swelling, jharko, ya rakta aaune jasto cha bhane eso emergency huncha — front desk ma call garnuhos. Booking garna man cha bhane tapaiko naam ra phone number wa email pathaunuhos, ma madat garna sakchu.
- After: Thik xa — bujhna garo vayo vane bujhxu. Dantko dukha ko lagi pahilo step Dental Consultation ho (20 min, $50) — doctor le herera k garnu parne bhanne kura recommend garxan. Yadi dukhā jasto tez dukha, swelling, jharko, ya rakta aaune jasto xa vane eso emergency hunxa — front desk ma call garnus. Booking garna man xa vane tapaiko naam ra phone number wa email pathaunus, ma madat garna sakxu.
- Your verdict: 

## 5
- Customer: Cleaning nai ho. Mero naam Sunita Thapa ho, phone number 555-2231 ho.
- Before: Tyo samaya ahile available chaina, Sunita Thapa — requested time is not available (outside business hours, on a closed date, in the past, or already booked). Cleaning ko lagi aru kehi available samaya haru: Monday, September 7 at 9:00 AM, Monday, September 7 at 9:15 AM, Monday, September 7 at 9:30 AM, Monday, September 7 at 9:45 AM, Monday, September 7 at 10:00 AM. Yi madhye kunai milcha? Maile tapaiko contact information update gare.
- After: Tyo time bharkhar book bhaisakyo, Sunita Thapa — requested time is not available (outside business hours, on a closed date, in the past, or already booked). Cleaning ko lagi yo time haru khali cha: Sombar (Sep 7) — bihana 9 baje, sawa 9 baje, sadhe 9 baje, 9:45 baje, 10 baje. Kunai milcha? Maile tapaiko contact information update gare.
- Your verdict: 

## 6
- Customer: my name is Gaurav Bista my number is 9803665942 ani email chai bistagaurav47@gmail.com ho malai voli ko 9 baje ko appointment chai yako theyo follow for prior RTC
- Before: Dhanyabad, Gaurav — naam, phone, ra email paeen. Bholi (2026-09-06) 9:00 baje ko appointment ko kura ho? "follow for prior RTC" le prior Root Canal ko follow-up ho bhaney — ke tapaile appointment confirm garna chahanu huncha, change garnu, or cancel garnu huncha? Kripaya ke garna chahanu huncha bhanera pathaun. Maile tapaiko contact information update gare.
- After: Dhanyabad, Gaurav — naam, phone, ra email paeen. Bholi (2026-09-06) 9:00 baje ko appointment ko kura ho? "follow for prior RTC" le prior Root Canal ko follow-up ho bhaney — k tapaile appointment confirm garna man xa, change garnu, or cancel garnu hunxa? K garna man xa vanera pathaun. Maile tapaiko contact information update gare.
- Your verdict: 

## 7
- Customer: what is tartar means
- Before: Tartar is the hard buildup of plaque that forms on your teeth and along the gumline. During a professional cleaning, scaling removes this hard buildup — you may feel mild pressure or vibration and brief sensitivity if your gums are inflamed. We usually recommend a cleaning every six months (or every 3–4 months if you have heavier tartar or gum issues). Would you like to book a cleaning?
- After: Tartar is the hard buildup of plaque that forms on your teeth and along the gumline. During a professional cleaning, scaling removes this hard buildup — you may feel mild pressure or vibration and brief sensitivity if your gums are inflamed. We usually recommend a cleaning every six months (or every 3–4 months if you have heavier tartar or gum issues).
- Your verdict: 

## 8
- Customer: Tooth extraction ma kati bleeding huncha, dherai dukhchha ki?
- Before: Sādhāraṇtā tooth extraction pachhi thulo bleeding hudaina — pahile local anesthesia le dard hudaina, tara procedure pachi kehi ghanta samma halka oozing ra pahilo 24 ghanta ma thori bleeding normal ho. Gauze chabaera kadā 30 minute samma kadā dabāunu le rakt rokīncha. Anesthesia bitisakepachi 24–48 ghanta samma halko soreness ra swelling hun sakcha; paracetamol/ibuprofen jasta OTC pain reliever le manage huncha. Tara yadi rakt gauze le 30 minute kadā pani rokdaina, dukhāi 2–3 din pachi bigriyo, joro ayo, wa socket bata kharab smell/taste ayo bhane turunta front desk ma phone garnuhos: +977-1-4781234. Appointment cha bhane bhanuhos, madat garna tayār chu.
- After: Sādhāraṇtā tooth extraction pachhi thulo bleeding hudaina — pahile local anesthesia le dard hudaina, tara procedure pachi kehi ghanta samma halka oozing ra pahilo 24 ghanta ma thori bleeding normal ho. Gauze chabaera kadā 30 minute samma kadā dabāunu le rakt rokīncha. Anesthesia bitisakepachi 24–48 ghanta samma halko soreness ra swelling hun sakcha; paracetamol/ibuprofen jasta OTC pain reliever le manage huncha. Tara yadi rakt gauze le 30 minute kadā pani rokdaina, dukhāi 2–3 din pachi bigriyo, joro ayo, wa socket bata kharab smell/taste ayo bhane turunta front desk ma phone garnus: +977-1-4781234. Appointment cha bhane bhannus, madat garna tayār chu.
- Your verdict: 

## 9
- Customer: Mero asti bata dukheko over nai dukhirako cha ka januk garnu pani thaxaina
- Before: Sunera man chhuttiyo — dukha bhayeko ma afno dukh lai samjhera dukha lagyo. Yadi dukha gahro cha, sujan failirahyo, bukha cha, daant nikalyo, wa rokina nasakne bleeding cha bhane turuntai front desk +977-1-4781234 ma phone garnuhos. Mild bhaye ma regular appointment book garna madat garna sakchhu — dukha kahile bata suru bhayo ra tapaiko mukh ma sujan wa bukha cha? Appointment chahanu huncha?
- After: Sunera man chhuttiyo — dukha bhayeko ma afno dukh lai samjhera dukha lagyo. Yadi dukha gahro cha, sujan failirahyo, bukha cha, daant nikalyo, wa rokina nasakne bleeding cha bhane turuntai front desk +977-1-4781234 ma phone garnus. Mild bhaye ma regular appointment book garna madat garna sakchhu — dukha kahile bata suru bhayo ra tapaiko mukh ma sujan wa bukha cha? Appointment chahiyo?
- Your verdict: 

## 10
- Customer: मेरो नाम त अशोक चौधरी हो
- Before: Dhanyabad Ashok! Phone number wa email pathaunuhos — bholi (2026-09-08) ko appointment ko lagi. Phone dinuhunchha? Maile tapaiko contact information update gare.
- After: Dhanyabad Ashok! Phone number wa email pathaunus — bholi (2026-09-08) ko appointment ko lagi. Phone dinuhunchha? Maile tapaiko contact information update gare.
- Your verdict: 

## 11
- Customer: Yo
- Before: Hi — welcome to Samaj Dental Clinic in New Baneshwor. How can I help you today? I can book an appointment, give directions (we have on-site parking), or tell you about our services and prices.
- After: Hi — welcome to Samaj Dental Clinic in New Baneshwor. I can book an appointment, give directions (we have on-site parking), or tell you about our services and prices.
- Your verdict: 

## 12
- Customer: Sam Tapa samratghimire01@gmail.com
- Before: Dhanyabad, Sam Tapa! Email (samratghimire01@gmail.com) paaye. Kripaya tapaiko phone number dinuhos. Braces ko lagi tapaile pahilo consultation chahanu huncha ki seedha Full Braces treatment ko barema thaha pauna mancha? Ma availability herera madat garna sakchu — ke tapaile appointment book garnu huncha? Maile tapaiko contact information update gare.
- After: Dhanyabad, Sam Tapa! Email (samratghimire01@gmail.com) paaye. Tapaiko phone number dinus. Braces ko lagi tapaile pahilo consultation chahiyo ki seedha Full Braces treatment ko barema thaha pauna mancha? Ma availability herera madat garna sakxu — k tapaile appointment book garnu hunxa? Maile tapaiko contact information update gare.
- Your verdict: 

## 13
- Customer: Payment
- Before: Payment ko bare ma ho bhane: hamile cash ra card donai swikarchhau, ra saadharan roopma payment clinic ma appointment pachi huncha — tara agadi milayera QR pathauna pani thik cha. Thulo treatments (Root Canal, Full Braces, Dental Implant jasta) ko lagi 20% advance deposit magincha. Kun service ko payment ho? Ra tapaiko naam ra phone number wa email dinuhos; QR pathauna WhatsApp ho ki email thik huncha bhanera pani btaunuhos.
- After: Payment ko bare ma ho vane: hamile cash ra card donai swikarchhau, ra saadharan roopma payment clinic ma appointment pachi hunxa — tara agadi milayera QR pathauna pani thik xa. Thulo treatments (Root Canal, Full Braces, Dental Implant jasta) ko lagi 20% advance deposit magincha. Kun service ko payment ho? Ra tapaiko naam ra phone number wa email dinus; QR pathauna WhatsApp ho ki email thik hunxa vanera pani btaunus.
- Your verdict: 

## 14
- Customer: teeth cleaning available cha?
- Before: Teeth Cleaning (Scaling & Polishing) ko lagi yi samaya haru khali chan: Thursday, September 17 at 9:30 AM, Thursday, September 17 at 9:45 AM, Thursday, September 17 at 10:00 AM, Thursday, September 17 at 10:15 AM, Thursday, September 17 at 10:30 AM. Kun milcha?
- After: Teeth Cleaning (Scaling & Polishing) ko lagi yo time haru khali cha: Bihibar (Sep 17) — bihana sadhe 9 baje, 9:45 baje, 10 baje, sawa 10 baje, sadhe 10 baje. Kun milcha?
- Your verdict: 

## 15
- Customer: open cha?
- Before: Ho — hamro clinic Somabar dekhi Shukrabar 9:00 AM–6:00 PM samma khula cha. Saturday ra Sunday bandha huncha.
- After: Ho — hamro clinic Somabar dekhi Shukrabar 9:00 AM–6:00 PM samma khula cha. Saturday ra Sunday banda huncha.
- Your verdict: 

## 16
- Customer: bholi book garna milcha
- Before: Bujhe — kripaya malai kun service ra kun samaya batauna sakinu huncha?
- After: Huncha — kun service ra kun time?
- Your verdict: 

## 17
- Customer: Teeth Cleaning ko lagi kun samaya khali cha?
- Before: Teeth Cleaning ko lagi yi samaya haru khali chan: Sunday, September 20 at 9:00 AM, Sunday, September 20 at 9:15 AM, Sunday, September 20 at 9:30 AM, Sunday, September 20 at 9:45 AM, Sunday, September 20 at 10:00 AM. Kun milcha?
- After: Teeth Cleaning ko lagi yo time haru khali cha: Aaitabar (Sep 20) — bihana 9 baje, sawa 9 baje, sadhe 9 baje, 9:45 baje, 10 baje. Kun milcha?
- Your verdict: 

## 18
- Customer: Teeth Cleaning ko lagi kun samaya khali cha?
- Before: Teeth Cleaning ko lagi yi samaya haru khali chan: Sunday, September 20 at 9:00 AM, 9:15 AM, 9:30 AM, 9:45 AM, 10:00 AM. Kun milcha?
- After: Teeth Cleaning ko lagi yo time haru khali cha: Aaitabar (Sep 20) — bihana 9 baje, sawa 9 baje, sadhe 9 baje, 9:45 baje, 10 baje. Kun milcha?
- Your verdict: 

## 19
- Customer: 1
- Before: Bujhe — Teeth Cleaning, Sunday, September 20 at 9:30 AM. Lock garna malai tapaiko naam ra phone number wa email chahincha.
- After: Huss — Teeth Cleaning, Aaitabar (Sep 20), bihana sadhe 9 baje. Pakka garna tapaiko naam ra phone number (wa email) chahiyo.
- Your verdict: 

## 20
- Customer: Nepali
- Before: Huncha, Nepali ma kura garaun. Ma tapailai kasari madat garna sakchu?
- After: Huncha, Nepali mai kura garaum. Bhannus, k help garum?
- Your verdict: 

## 21
- Customer: ok thik cha, ma bholi aauna sakchu
- Before: Teeth Cleaning (Scaling & Polishing) ko lagi yi samaya haru khali chan: Monday, September 21 at 10:00 AM, 10:15 AM, 10:30 AM, 10:45 AM, 11:00 AM. Kun milcha?
- After: Teeth Cleaning (Scaling & Polishing) ko lagi yo time haru khali cha: Sombar (Sep 21) — bihana 10 baje, sawa 10 baje, sadhe 10 baje, 10:45 baje, 11 baje. Kun milcha?
- Your verdict: 

## 22
- Customer: Actually, can you tell me what time you open on weekends?
- Before: Weekend ma closed huncha — Saturday ra Sunday bandha cha. Hafta bhitra hamro hours: Monday–Thursday 9:00 AM–5:00 PM ra Friday 9:00 AM–2:00 PM.
- After: Weekend ma closed huncha — Saturday ra Sunday banda cha. Hafta bhitra hamro hours: Monday–Thursday 9:00 AM–5:00 PM ra Friday 9:00 AM–2:00 PM.
- Your verdict: 

## 23
- Customer: Actually, can you tell me what time you open on weekends?
- Before: Weekend ma hamro clinic bandha huncha — Saturday ra Sunday closed huncha. Hamro regular hours Monday dekhi Friday 9:00 AM bata 6:00 PM samma huncha.
- After: Weekend ma hamro clinic banda huncha — Saturday ra Sunday closed huncha. Hamro regular hours Monday dekhi Friday 9:00 AM bata 6:00 PM samma huncha.
- Your verdict: 

## 24
- Customer: hlo, malai teeth cleaning ko barema janna man cha
- Before: Namaste — Teeth Cleaning (Scaling & Polishing) bhaneko plaque ra tartar hataayera tooth surface lai polish garne procedure ho. Dherai mancheharu lai bishesh dukha hudaina; scaling maa halko pressure/vibration mahsoos huncha ra sensitive gums bhaye chito sensitivity auna sakcha, tara samanya ma ek din bhitra thik huncha. Samaya: praya 30 minutes. Price: NPR 1500. Recommendation: adhikansh lai 6 mahina ma ek patak; gum disease bhaye 3–4 mahina ma check-up garna sakinchha. Payment clinic ma cash/card le huncha ra routine cleaning ko advance deposit chahindaina. Hamro clinic ma on-site parking pani cha. Booking garna man cha bhane bhanuhos, madat garchu.
- After: Namaste — Teeth Cleaning (Scaling & Polishing) bhaneko plaque ra tartar hataayera tooth surface lai polish garne procedure ho. Dherai mancheharu lai bishesh dukha hudaina; scaling maa halko pressure/vibration mahsoos huncha ra sensitive gums bhaye chito sensitivity auna sakcha, tara samanya ma ek din bhitra thik huncha. Time: praya 30 minutes. Price: NPR 1500. Recommendation: adhikansh lai 6 mahina ma ek patak; gum disease bhaye 3–4 mahina ma check-up garna sakinchha. Payment clinic ma cash/card le huncha ra routine cleaning ko advance deposit chahindaina. Hamro clinic ma on-site parking pani cha. Booking garna man cha bhane bhannus, madat garchu.
- Your verdict: 

## 25
- Customer: k xa
- Before: Thik cha — Samaj Dental Clinic ma ke madat chahiyo? Appointment book garna ho, consultation, ki aru?
- After: Thik xa — Samaj Dental Clinic ma k madat chahiyo? Appointment book garna ho, consultation, ki aru?
- Your verdict: 

## 26
- Customer: which service is available according to my pain
- Before: Thik cha — pahila malai tapaiko symptoms thap bhani dinu hola: dard continuous ra tej cha ki kabhi-kabhi? swelling cha? khoon aaudai cha? daant bhatki/chuwaeko cha? Knocked-out bhaeko ho? Mild sensitivity bhaye Dental Consultation, Tooth Filling, wa Teeth Cleaning le help garna sakcha. Severe/unrelenting pain, thulo swelling, khoon rukdaina, wa saans/khanu garna garo bhaye yo emergency ho — kripaya front desk ma turuntai phone garnuhos: +977-1-4781234. K kura cha tapaiko symptoms ho?
- After: Thik cha — pahila malai tapaiko symptoms thap bhani dinu hola: dard continuous ra tej cha ki kabhi-kabhi? Swelling cha? Khoon aaudai cha? Daant bhatki/chuwaeko cha? Knocked-out bhaeko ho? Mild sensitivity bhaye Dental Consultation, Tooth Filling, wa Teeth Cleaning le help garna sakcha. Severe/unrelenting pain, thulo swelling, khoon rukdaina, wa saans/khanu garna garo bhaye yo emergency ho — front desk ma turuntai phone garnus: +977-1-4781234. K kura cha tapaiko symptoms ho?
- Your verdict: 

## 27
- Customer: What time do you open tomorrow?
- Before: Bholi kati baje dekhi khulne ho bhanne kura hamro record ma configured bhayeko chaina — ma team sanga jodera thikai samaya sodhi dinchu. Team sanga jodnu hola? Maile hamro team lai pani janakari diye, tyesaile euta sacchai ko manche le tapailai follow-up garnecha.
- After: Bholi kati baje dekhi khulne ho bhanne kura hamro record ma configured bhayeko chaina — ma team sanga jodera thikai time sodhi dinchu. Team sanga jodnu hola? Maile hamro team lai pani info diye, tyesaile euta sacchai ko manche le tapailai follow-up garnecha.
- Your verdict: 

## 28
- Customer: k k hunxa tapai ko ma
- Before: Hajur, Everest Pathways le study-abroad ko lagi sabai kura help garcha. Hamra mukhya services:
- Initial Counseling Session (USD 0.00, 45 min)
- Document Evaluation (USD 2500.00, 30 min)
- University Application Review (USD 4000.00, 60 min)
- Visa Interview Preparation (USD 3000.00, 45 min)

Suru ko lagi Initial Counseling free huncha — booking garna man cha hajur?
- After: Hajur, Everest Pathways le study-abroad ko lagi sabai kura help garxa. Hamra mukhya services:
- Initial Counseling Session (USD 0.00, 45 min)
- Document Evaluation (USD 2500.00, 30 min)
- University Application Review (USD 4000.00, 60 min)
- Visa Interview Preparation (USD 3000.00, 45 min)

Suru ko lagi Initial Counseling free hunxa — booking garna man xa hajur?
- Your verdict: 

## 29
- Customer: Tapai ko ma japan ko k xa
- Before: Tyo ma guess garna chahanna — ma team bata sahi jankari lera tapailai follow-up garauchu. Ma yesbare hamro senior team sanga kura garera chadai tapailai update garne chu.
- After: Tyo ma guess garna chahanna — team bata sahi kura bujhera tapailai khabar garna lagauxu. Ma yesbare hamro senior team sanga kura garera xadai tapailai update garne xu.
- Your verdict: 

## 30
- Customer: k k xata timro clicic ma
- Before: Hajur, hami le yehā yei services dinchhau:
- Teeth Cleaning (Scaling & Polishing) — NPR 1500 (30 min)
- Root Canal Treatment — NPR 8000 (60 min)
- Tooth Extraction — NPR 1500 (20 min)
- Braces Consultation — NPR 800 (30 min)
- Full Braces Treatment — NPR 60000 (60 min)
- Teeth Whitening — NPR 6000 (45 min)
- Dental Implant (per tooth) — NPR 45000 (90 min)
- Tooth Filling — NPR 1200 (30 min)
- Dental Consultation — NPR 500 (25 min)

On-site parking pani available cha. Kun service ko lagi appointment book garauna cha?
- After: Hajur, hami le yehā yei services dinxau:
- Teeth Cleaning (Scaling & Polishing) — NPR 1500 (30 min)
- Root Canal Treatment — NPR 8000 (60 min)
- Tooth Extraction — NPR 1500 (20 min)
- Braces Consultation — NPR 800 (30 min)
- Full Braces Treatment — NPR 60000 (60 min)
- Teeth Whitening — NPR 6000 (45 min)
- Dental Implant (per tooth) — NPR 45000 (90 min)
- Tooth Filling — NPR 1200 (30 min)
- Dental Consultation — NPR 500 (25 min)

On-site parking pani available xa. Kun service ko lagi appointment book garauna xa?
- Your verdict: 
