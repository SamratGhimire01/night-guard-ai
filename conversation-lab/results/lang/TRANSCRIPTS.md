# Language experiment — human-readable transcripts (rep 0 of each arm; real Azure gpt-5-mini output)

`C [kind exp=…]` = scripted customer turn and what the reply *should* be; `A [label]` = the arm's reply with an independent language label; `<-- MISMATCH` = label outside the accepted set. `pre25` = the original pre-Phase-25 prompt (git 2456440), `prod` = current production lock mechanism, `hybrid` = the new per-message design (frozen v3). Rows come from results/lang/*.jsonl; some arms may be missing a rep-0 row where Azure's content filter rejected the prompt.


## A. Within-message code-switching (mirroring)


### A1-nepali-frame-english-words — arm `pre25` (rep 0)
```
C [mix exp=mix]: hello, malai teeth whitening garna man cha, price kati hola?
A [ne_roman]: Namaste — Teeth Whitening ko price NPR 6000 ho ra session 45 minutes ko huncha. Booking garna cha bhane kun date ra time ramro huncha bhanera sodhnuhos, ma sahayog garnechu.
C [mix exp=mix]: ok thik cha, but weekend ma open hunxa ki hudaina?
A [ne_roman]: Weekend (Saturday ra Sunday) ma hami closed chau. Hamro hours Monday–Friday 9:00 AM–6:00 PM. Kun weekday ma Teeth Whitening ko appointment lina man cha? Ma booking ma sahayog garnechu.
C [mix exp=mix]: What app ma vaya hunxa payment?
A [ne_roman]: Hajur — payment cash, eSewa ra Khalti bata lina sakinchha.
C [mix exp=mix]: Friday 3pm ma slot cha? I have office until 2:30 so late chahiyo
A [ne_roman]: Thik cha — ma Friday 2026-09-25 15:00 ko Teeth Whitening ko availability herchhu. Kripaya tapaiko naam ra phone number dinu huncha?
C [mix exp=mix]: dhanyabad, very helpful!
A [ne_roman]: Khusi lagyo — dhanyabad! Booking garna chahanu huncha vane tapaiko naam ra phone number dinuhos, ma Friday 2026-09-25 15:00 ko availability herera tapai lai janakari dinchhu. Aru kehi sahayog chahiyo bhane bhanuhos.
```

### A1-nepali-frame-english-words — arm `prod` (rep 0)
```
C [mix exp=mix]: hello, malai teeth whitening garna man cha, price kati hola?
A [ne_roman]: Teeth Whitening ko price NPR 6000 ho, ra karib 45 minute lagcha. Book garna man cha?
C [mix exp=mix]: ok thik cha, but weekend ma open hunxa ki hudaina?
A [ne_roman]: Weekend ma hami bandha huncha — Saturday ra Sunday closed. Hamro kaamko samaya Monday–Friday 9:00 AM dekhi 6:00 PM samma ho. Kun din milcha tapaiko lagi?
C [mix exp=mix]: What app ma vaya hunxa payment?
A [ne_roman]: Payment hamro clinic ma cash chha, ani digital apps ma eSewa ra Khalti le accept garchau.
C [mix exp=mix]: Friday 3pm ma slot cha? I have office until 2:30 so late chahiyo
A [ne_roman]: Thik cha — ma Friday 3pm (15:00) ko slot herchu.
C [mix exp=mix]: dhanyabad, very helpful!
A [ne_roman]: Swagat cha — khusi lagyo madat garna paye. 😊
```

### A1-nepali-frame-english-words — arm `hybrid` (rep 0)
```
C [mix exp=mix]: hello, malai teeth whitening garna man cha, price kati hola?
A [ne_roman]: Teeth Whitening ko price NPR 6000 ho, ra karib 45 minute lagcha. Payment cash, eSewa, ra Khalti le hunchha.
C [mix exp=mix]: ok thik cha, but weekend ma open hunxa ki hudaina?
A [ne_roman]: Weekend (Saturday ra Sunday) hami bandha huncha. Hamro hours Monday–Friday 9:00 AM dekhi 6:00 PM samma huncha.
C [mix exp=mix]: What app ma vaya hunxa payment?
A [ne_roman]: Payment eSewa ra Khalti bata garna milcha; onsite cash pani accept garinchha.
C [mix exp=mix]: Friday 3pm ma slot cha? I have office until 2:30 so late chahiyo
A [ne_roman]: Huss — ma Friday (2026-09-25) 3:00 PM ko slot herchu.
C [mix exp=mix]: dhanyabad, very helpful!
A [mixed]: You're welcome! Khusi lagyo madat garna. 😊
```

### A3-real-long-roman-message — arm `pre25` (rep 0)
```
C [signal exp=roman]: sunnu na, mero baby ko tooth ali ali fatera dukheko xa, k garne bujhina, first available ma lyaidiye hunxa ki k garne, price kati parxa yesko, ani insurance chalxa ki chaina, ani weekend ma khula hunxa ki nai
A [ne_roman]: Sunnu — tapaiko baby ko daant faeta ra dukheko sunera naramro lagyo. Sabai bhanda pahila dentist le heraunu ramro huncha; Dental Consultation (NPR 500, 20 min) bata suru garna sakinchha — filling parne bhaye Tooth Filling (NPR 2500) huncha. Hamro payment: cash, eSewa, Khalti. Insurance chalxa ki chaina bhanne kura yaha available info ma chhaina; ma team sanga confirm garera thaha dinu sakchhu. Note: clinic weekend ma bandha huncha — aaja Saturday ho, agadi ko opening Monday 2026-09-21. Ke ma Monday ko first available slot herera rakhe? Baby ko naam, umar, ra contact number pathaunuhos (ra kun time may be better) so I can check availability.
C [mix exp=mix]: insurance chaina bhane ni hunxa? ok then bholi first slot ma book gardinuhos plz
A [ne_roman]: Insurance ko barema hamro available info ma chaina; ma team sanga confirm garera bhandaidinchu. Payment: cash, eSewa, Khalti. Clinic Saturday–Sunday bandha huncha, bholi (2026-09-20) bandha cha — agadi ko khulne din Monday 2026-09-21 ho. Ke ma Monday 2026-09-21 ko first available slot (clinic opens 9:00) ko lagi check garera rakhnu? Baby ko naam, umar, ra contact number pathaunuhos. Suruwat ma Dental Consultation (NPR 500, 20 min) recommend garinchha — thik cha?
```

### A3-real-long-roman-message — arm `prod` (rep 0)
```
C [signal exp=roman]: sunnu na, mero baby ko tooth ali ali fatera dukheko xa, k garne bujhina, first available ma lyaidiye hunxa ki k garne, price kati parxa yesko, ani insurance chalxa ki chaina, ani weekend ma khula hunxa ki nai
A [ne_roman]: Oh, baby ko daant dukhdaichha — bujhna garo huncha. Agadi ko step Dental Consultation ho; Consultation NPR 500 (20 min). Agar filling/RC paryo bhane Filling NPR 2500, Root Canal NPR 9000, Cleaning NPR 1500. Payment: cash, eSewa, Khalti; on-site parking available. Hamro clinic weekend (Sat–Sun) bandha cha. Thik cha — ma tapaiko lagi sabai bhanda chito slot herchu. Insurance ko barema hamro file ma thaha chhaina; yo confirm garna chahanu huncha bhane ma team sanga connect garna sakchhu.
C [mix exp=mix]: insurance chaina bhane ni hunxa? ok then bholi first slot ma book gardinuhos plz
A [ne_roman]: Thik cha — insurance nabhaeko bhaye pani huncha; payment cash, eSewa, ra Khalti chalxa. Tara bholi hamro clinic weekend ma bandha cha. Kun arko weekday ko first slot ma book garna milchha?
```

### A3-real-long-roman-message — arm `hybrid` (rep 0)
```
C [signal exp=roman]: sunnu na, mero baby ko tooth ali ali fatera dukheko xa, k garne bujhina, first available ma lyaidiye hunxa ki k garne, price kati parxa yesko, ani insurance chalxa ki chaina, ani weekend ma khula hunxa ki nai
A [ne_roman]: Oh no — baby ko tooth dukheko sunera dukh lagyo. Sabai bhanda pahila Dental Consultation garnu parcha; consultation NPR 500 (about 20 min). Aghadi treatment parne ho bhane Tooth Filling NPR 2500 ra Root Canal NPR 9000 pani huncha. Hamro clinic Saturday ra Sunday band cha, Monday–Friday 9:00–18:00 ho — tesaile first available sabai bhanda chito Monday ma hunu sakcha. Insurance ko barema hami sanga record chaina; tapaiko plan chalxa ki chaina confirm garna team sanga check garna parcha — chaheu bhane ma availability herchu.
C [mix exp=mix]: insurance chaina bhane ni hunxa? ok then bholi first slot ma book gardinuhos plz
A [ne_roman]: Insurance nabhay pani huncha — tapaile cash, eSewa, or Khalti bata pay garna sakincha. Hami sanga tapaiko insurance plan ko record chaina; plan chalxa ki chaina confirm garnu parcha bhane team sanga hernu parcha. Tara bholi (2026-09-20) hami Sunday bhayeko le clinic band cha, tesaile bholi ko slot hudaina — first available Monday 2026-09-21 ko first slot ma book garne ho?
```

### HA1-salon-code-mix — arm `pre25` (rep 0)
```
C [mix exp=mix]: hello didi, haircut ko lagi appointment book garna parne thiyo, but kati parcha?
A [ne_roman]: Hello — Haircut ko price NPR 600 ho ra service le karib 30 minute lagchha. Walk-ins pani welcome huncha if stylist free. Payment cash or eSewa le lina sakinchha. Booking garna man cha bhane kun date ra time chahanu huncha bhanera pathaunuhos.
C [mix exp=mix]: ok, beard trim ni chaiyo, with haircut same day ma huncha ki?
A [ne_roman]: Beard Trim NPR 300 ho ra karib 15 minutes lagchha. Haircut sanga same day ma garna milcha bhanne kura mero passko info ma explicit bhayeko chaina — ma availability herera dherai sajilo sanga booking garna madat garna sakchhu. Kun date ra time chahanu huncha?
C [mix exp=mix]: Saturday ma 4pm ma slot cha hola?
A [ne_roman]: Thik cha — ma availability herera herchu. Tapaile ‘Saturday’ bhaneko 2026-09-19 (today) 16:00 ho? Ra service Haircut ho, Beard Trim ho, or dui ota (both) ho? Confirm garnuhos.
C [mix exp=mix]: ekdum ramro, thanks!
A [ne_roman]: Thik cha — khusi lagyo! Aru kehi madat chahanu huncha? Booking garna chahanu hunuhunchha vane confirm garnuhos: Saturday (2026-09-19) 16:00 ma Haircut + Beard Trim, ma availability herera check garchu.
```

### HA1-salon-code-mix — arm `prod` (rep 0)
```
C [mix exp=mix]: hello didi, haircut ko lagi appointment book garna parne thiyo, but kati parcha?
A [ne_roman]: Hello! Haircut ko price NPR 600 ho, ra karib 30 minutes lagcha. Book garna mancha?
C [mix exp=mix]: ok, beard trim ni chaiyo, with haircut same day ma huncha ki?
A [ne_roman]: Milcha — Haircut (30 min) ra Beard Trim (15 min) milaera karib 45 minutes lagcha. Ma herchu kun samaya available cha.
C [mix exp=mix]: Saturday ma 4pm ma slot cha hola?
A [ne_roman]: Thik cha — ma 4pm ko slot herchu.
C [mix exp=mix]: ekdum ramro, thanks!
A [ne_roman]: Swaagat cha! 😊
```

### HA1-salon-code-mix — arm `hybrid` (rep 0)
```
C [mix exp=mix]: hello didi, haircut ko lagi appointment book garna parne thiyo, but kati parcha?
A [ne_roman]: Hello — Haircut ko price NPR 600 ho, ra karib 30 minutes lagcha. Payment cash wa eSewa accept garincha. Booking garna cha bhane kun din/time sochnu bhayo?
C [mix exp=mix]: ok, beard trim ni chaiyo, with haircut same day ma huncha ki?
A [ne_roman]: Milcha — beard trim sanga haircut same day ma garna sakincha. Haircut 30 min ra Beard Trim 15 min, total karib 45 minutes lagcha. Kun din ra kati baje milcha?
C [mix exp=mix]: Saturday ma 4pm ma slot cha hola?
A [ne_roman]: Huss, Saturday 4pm ko slot herchu.
C [mix exp=mix]: ekdum ramro, thanks!
A [en]: Welcome!   <-- MISMATCH
```

### HA2-trek-english-light-nepali — arm `pre25` (rep 0)
```
C [mix exp=mix_en]: Hi, I'm interested in Poon Hill, kati din ko hunchha?
A [ne_deva]: Namaste! Poon Hill Trek 5 दिनको हुन्छ। मूल्य USD 450 हो। बुकिङ्ग कन्फर्म गर्न ३०% डिपोजिट लाग्छ र ट्रेकिङ्ग अनुमति हामीले व्यवस्था गर्छौं र मूल्यमा समावेश छ। उपलब्ध मिति हेर्न वा बुक गर्न चाहनुहुन्छ भने बताउनुहोस्।   <-- MISMATCH
C [mix exp=mix]: nice. and permit ko kura? is it included or do I arrange separately
A [mixed]: Ho — Poon Hill trek ko permit hamro price ma samabesh cha ra hami nai arrange garchhau. Availability hernu cha, or book garna maan cha bhane kun date sochirहनु bhayo bhanera भन्नु hola?
C [mix exp=mix_en]: Perfect, dhanyabad!
A [ne_deva]: सुन्दर — धन्यवाद! बुकिङ्ग अगाडि बढाउन चाहनुहुन्छ भने कृपया तपाइँको इच्छित सुरुवात मिति बताउनुहोस्, म उपलब्धता हेरेर अगाडि बढाउँछु। स्मरण: ३०% डिपोजिटले बुकिङ्ग कन्फर्म हुन्छ र ट्रेकिङ्ग अनुमति हाम्रो मूल्यमा समावेश छ।   <-- MISMATCH
```

### HA2-trek-english-light-nepali — arm `prod` (rep 0)
```
C [mix exp=mix_en]: Hi, I'm interested in Poon Hill, kati din ko hunchha?
A [ne_roman]: Poon Hill Trek 5 dinko hunchha.   <-- MISMATCH
C [mix exp=mix]: nice. and permit ko kura? is it included or do I arrange separately
A [ne_roman]: Ho — permit haru hami le arrange garne ho ra yo trek ko price bhitra nai samabesh cha.
C [mix exp=mix_en]: Perfect, dhanyabad!
A [ne_roman]: Swagat cha 😊   <-- MISMATCH
```

### HA2-trek-english-light-nepali — arm `hybrid` (rep 0)
```
C [mix exp=mix_en]: Hi, I'm interested in Poon Hill, kati din ko hunchha?
A [ne_roman]: Poon Hill Trek 5 dinko hunchha (5 days). Price USD 450; 30% deposit le booking confirm hunchha, ra trekking permits price ma sammilit chan. Booking garna man cha?   <-- MISMATCH
C [mix exp=mix]: nice. and permit ko kura? is it included or do I arrange separately
A [ne_roman]: Pakka — trekking permits hamile arrange garinchha ra price (USD 450) ma sammilit cha.
C [mix exp=mix_en]: Perfect, dhanyabad!
A [mixed]: You're welcome! Booking garna man cha bhane bhannu hola.
```

## B. Deliberate language change mid-conversation


### B1-en-to-roman — arm `pre25` (rep 0)
```
C [signal exp=en]: Hi, how much is a teeth cleaning?
A [en]: A Teeth Cleaning is NPR 1500 and takes about 30 minutes. Would you like to book an appointment?
C [signal exp=en]: Ok and do you have a slot tomorrow?
A [en]: We're closed tomorrow (Sunday). Our next open day is Monday, 2026-09-21. Would you like me to look for a Teeth Cleaning then? If yes, what time works best for you?
C [switch exp=roman]: malai bholi bihana 10 baje ko slot chahiyo, milcha?
A [ne_roman]: Bholi (2026-09-20) hami Sunday ma bandha cha, tesaile 10:00 mildaina. Hami agadi khulne din Monday 2026-09-21 ho — Monday 10:00 ma Teeth Cleaning garne ho? Confirm garnuhos.
C [signal exp=roman]: ani parking cha ki chaina?
A [ne_roman]: Ma sanga yo information chaina. Chahanu huncha ma staff sanga sodhi confirm garera tapaailaai pathaun? Kun tarikale contact garnu — phone, SMS, or email?
C [neutral exp=roman]: ok
A [ne_roman]: Thik cha — ma Monday 2026-09-21 ma Teeth Cleaning ko 10:00 availability herchhu. Hami sanga on-site parking cha. Confirmation ra aru details kun tarikale pathaun? phone, SMS, or email?
C [neutral exp=roman]: Friday
A [ne_roman]: Friday bhanera bujhda — tapaile upcoming Friday (2026-09-25) ma Teeth Cleaning chaheko ho? Kun time (kati baje) ramro huncha? Ra confirmation kun tarikale pathaun — phone, SMS, or email?
```

### B1-en-to-roman — arm `prod` (rep 0)
```
C [signal exp=en]: Hi, how much is a teeth cleaning?
A [en]: Teeth Cleaning is NPR 1500 and takes about 30 minutes. We accept cash, eSewa, or Khalti, and on-site parking is available.
C [signal exp=en]: Ok and do you have a slot tomorrow?
A [en]: We're closed on Sundays, so we don't have slots tomorrow. Which service would you like so I can check the next available slot?
C [switch exp=roman]: malai bholi bihana 10 baje ko slot chahiyo, milcha?
A [en]: We're closed on Sundays, so we don't have any slots tomorrow. Which service would you like me to check for 10:00 AM on the next open day?   <-- MISMATCH
C [signal exp=roman]: ani parking cha ki chaina?
A [en]: Yes — we have on-site parking available.   <-- MISMATCH
C [neutral exp=roman]: ok
A [en]: Okay — which service should I check for 10:00 AM?   <-- MISMATCH
C [neutral exp=roman]: Friday
A [en]: Got it — Friday. Which service should I check for 10:00 AM?   <-- MISMATCH
```

### B1-en-to-roman — arm `hybrid` (rep 0)
```
C [signal exp=en]: Hi, how much is a teeth cleaning?
A [en]: Teeth Cleaning is NPR 1,500 and takes about 30 minutes. Would you like me to check available times?
C [signal exp=en]: Ok and do you have a slot tomorrow?
A [en]: Sure — let me see what's open for a Teeth Cleaning tomorrow.
C [switch exp=roman]: malai bholi bihana 10 baje ko slot chahiyo, milcha?
A [ne_roman]: Bholi Sunday ho ra clinic bandha huncha, tesaile 10 baje mildaina. Ke Monday (2026-09-21) 10:00 baje milcha?
C [signal exp=roman]: ani parking cha ki chaina?
A [ne_roman]: Cha — clinic ma on-site parking cha.
C [neutral exp=roman]: ok
A [ne_roman]: Thik cha.
C [neutral exp=roman]: Friday
A [ne_roman]: Thik cha — ma Friday (2026-09-25) ko available slots herchu.
```

### B2-roman-to-deva — arm `pre25` (rep 0)
```
C [signal exp=roman]: namaste, dental consultation ko price kati ho?
A [ne_roman]: Namaste — Dental Consultation ko price NPR 500 ho (20 min). Booking garna man cha bhane bhannu hola, madat garchu.
C [signal exp=roman]: ani kati baje samma khula huncha?
A [ne_roman]: Hami Somabar–Shukrabaar 9:00 AM dekhi 6:00 PM samma khulla huncha. Saturday ra Sunday banda huncha — aaja Saturday bhayera hami banda chhau.
C [switch exp=deva]: मलाई शनिबार अपोइन्टमेन्ट चाहियो, मिल्छ?
A [ne_deva]: हामी शनिबार बन्द छौं, त्यसैले शनिबार अपोइन्टमेन्ट दिन सक्दैनौं। हामी सोमबार–शुक्रबार 9:00–18:00 खुल्छौं। कुन सेवा चाहनुहुन्छ (Dental Consultation, Teeth Cleaning, Tooth Filling, Root Canal, Teeth Whitening) र कुन दिन/कस्तो समय मिल्छ बताउनुहोस् — म बुकिङको लागि मद्दत गर्छु।
C [signal exp=deva]: धन्यवाद
A [ne_deva]: स्वागत छ — अरू केही सहयोग चाहिन्छ भने भन्नुहोस्।
C [neutral exp=deva]: ok
A [ne_deva]: ठीक छ — धन्यवाद! अरू केही सहयोग चाहियो भने भन्नुहोस्।
```

### B2-roman-to-deva — arm `prod` (rep 0)
```
C [signal exp=roman]: namaste, dental consultation ko price kati ho?
A [ne_roman]: Namaste! Dental Consultation ko price NPR 500 ho, ra karib 20 minute lagcha.
C [signal exp=roman]: ani kati baje samma khula huncha?
A [ne_roman]: Hamro clinic Somabar dekhi Sukrabar samma 9:00 AM bata 6:00 PM samma khula huncha. Sanibaar ra Aaitabaar bandha huncha.
C [switch exp=deva]: मलाई शनिबार अपोइन्टमेन्ट चाहियो, मिल्छ?
A [ne_roman]: Maaf, hami Shanibar ra Aaitabaar banda chhau — Shanibar ma appointment dinu mildaina. Hamro clinic Somabar dekhi Sukrabar 9:00 AM bata 6:00 PM samma khula huncha. Kun din (Somabar–Sukrabar) ma appointment chahanu huncha?   <-- MISMATCH
C [signal exp=deva]: धन्यवाद
A [ne_roman]: Swagat cha!   <-- MISMATCH
C [neutral exp=deva]: ok
A [ne_roman]: Thik cha.   <-- MISMATCH
```

### B2-roman-to-deva — arm `hybrid` (rep 0)
```
C [signal exp=roman]: namaste, dental consultation ko price kati ho?
A [ne_roman]: Namaste! Dental Consultation ko price NPR 500 ho, ra karib 20 minute lagcha.
C [signal exp=roman]: ani kati baje samma khula huncha?
A [ne_roman]: Hami Monday–Friday 9 baje dekhi 6 baje samma khula huncha. Saturday ra Sunday banda huncha.
C [switch exp=deva]: मलाई शनिबार अपोइन्टमेन्ट चाहियो, मिल्छ?
A [ne_deva]: हाम्रो क्लिनिक शनिबार बन्द हुन्छ। हामी सोमवार–शुक्रबार 9:00 देखि 18:00 सम्म खुल्छौं — कुन अर्को दिन र कति बजे तपाईंलाई मिल्छ?
C [signal exp=deva]: धन्यवाद
A [ne_deva]: स्वागत छ! 😊
C [neutral exp=deva]: ok
A [ne_deva]: ठीक छ।
```

### B6-roman-then-sustained-english — arm `pre25` (rep 0)
```
C [signal exp=roman]: namaste, cleaning ko price kati ho?
A [ne_roman]: Namaste — Teeth Cleaning ko price NPR 1500 ho (30 min). Appointment book garnu cha bhane kun date ra time manparcha bhanera pathaunuhos, ma madat garnechu.
C [signal exp=roman]: ani root canal ko?
A [ne_roman]: Root Canal ko price NPR 9000 ho (90 min). Appointment book garnu cha bhane kun date ra time manparcha bhanera pathaunuhos, ma madat garnechu.
C [switch exp=en]: Okay. Do you accept eSewa or Khalti for payment?
A [en]: Yes — we accept both eSewa and Khalti, and cash payments as well. Would you like me to book an appointment for you?
C [signal exp=en]: And what are your hours on Friday?
A [en]: We're open Friday from 9:00 AM to 6:00 PM. Would you like me to book an appointment for you?
C [signal exp=en]: Can I book for next Tuesday afternoon?
A [en]: Sure — I can help with that. Which service would you like (Teeth Cleaning, Root Canal, etc.), and what time in the afternoon on Tuesday, Sept 22 would you prefer? Our Tuesday hours are 09:00–18:00.
C [neutral exp=en]: ok thanks
A [en]: You’re welcome — glad to help. If you want to book an appointment or have any other questions, tell me the service and a preferred date/time and I’ll assist.
```

### B6-roman-then-sustained-english — arm `prod` (rep 0)
```
C [signal exp=roman]: namaste, cleaning ko price kati ho?
A [ne_roman]: Namaste! Cleaning (Teeth Cleaning) ko price NPR 1500 ho, ra karib 30 minute lagcha.
C [signal exp=roman]: ani root canal ko?
A [ne_roman]: Root Canal ko price NPR 9000 ho, ra karib 90 minute lagcha.
C [switch exp=en]: Okay. Do you accept eSewa or Khalti for payment?
A [ne_roman]: Ho — haami eSewa ra Khalti dunai accept garchau. Cash pani chalcha.   <-- MISMATCH
C [signal exp=en]: And what are your hours on Friday?
A [ne_roman]: Friday ma hamro khulne samaya 9:00 AM dekhi 6:00 PM samma cha.   <-- MISMATCH
C [signal exp=en]: Can I book for next Tuesday afternoon?
A [ne_roman]: Thik cha — next Tuesday bhaneko 2026-09-22 ho. Afternoon ko lagi kun service book garna chahanu huncha?   <-- MISMATCH
C [neutral exp=en]: ok thanks
A [ne_roman]: Thik cha — swagat cha! 😊   <-- MISMATCH
```

### B6-roman-then-sustained-english — arm `hybrid` (rep 0)
```
C [signal exp=roman]: namaste, cleaning ko price kati ho?
A [ne_roman]: Teeth Cleaning ko price NPR 1500 ho, ra karib 30 minute lagcha.
C [signal exp=roman]: ani root canal ko?
A [ne_roman]: Root Canal ko price NPR 9000 ho, ra karib 90 minute lagcha.
C [switch exp=en]: Okay. Do you accept eSewa or Khalti for payment?
A [en]: Yes — we accept payment by cash, eSewa, and Khalti.
C [signal exp=en]: And what are your hours on Friday?
A [en]: We're open on Friday from 9:00 AM to 6:00 PM.
C [signal exp=en]: Can I book for next Tuesday afternoon?
A [en]: Sure — which service would you like for next Tuesday afternoon? I'll check available afternoon slots.
C [neutral exp=en]: ok thanks
A [en]: You're welcome! 😊
```

### B5-explicit-to-nepali — arm `pre25` (rep 0)
```
C [signal exp=en]: Hi, how much is a filling?
A [en]: A Tooth Filling is NPR 2500 and typically takes about 45 minutes. We accept cash, eSewa, or Khalti. Would you like to book an appointment?
C [signal exp=en]: and how long does it take?
A [en]: A Tooth Filling typically takes about 45 minutes. Would you like me to book an appointment for you?
C [explicit exp=roman]: Can we talk in Nepali from now on?
A [ne_deva]: अवश्य — अबदेखि म नेपालीमै कुरा गर्छु। के म अहिले केही सहयोग गर्न सक्छु? (उदाहरण: अपोइन्टमेन्ट बुक गर्न चाहनुहुन्छ?)   <-- MISMATCH
C [neutral exp=roman]: ok
A [ne_deva]: ठीक छ — के म तपाईंको लागि अपोइन्टमेन्ट बुक गर्न सहयोग गरूँ? कुन सेवा र कुन मिति/समय चाहनुहुन्छ?   <-- MISMATCH
C [neutral exp=roman]: Friday
A [ne_deva]: ठिक छ — के तपाईंले “शुक्रबार” भन्नाले 2026-09-25 (शुक्रबार) लाई जनाउनुभएको हो? कुन सेवा चाहनुहुन्छ (उदाहरण: Tooth Filling) र कति बजे उपयुक्त हुन्छ? हाम्रो कार्यालय सोम–शुक्र 9:00–18:00 खुला हुन्छ।   <-- MISMATCH
C [neutral exp=roman]: thanks
A [ne_deva]: ठीक छ — धन्यवाद! अरु केही चाहिन्छ भने भन्नुहोस्, म सहयोग गर्न तयार छु। अपोइन्टमेन्ट बुक गर्न चाहनुहुन्छ भने सेवा र समय बताउनुहोस्।   <-- MISMATCH
```

### B5-explicit-to-nepali — arm `prod` (rep 0)
```
C [signal exp=en]: Hi, how much is a filling?
A [en]: Hi — a Tooth Filling is NPR 2500 and takes about 45 minutes.
C [signal exp=en]: and how long does it take?
A [en]: A Tooth Filling takes about 45 minutes.
C [explicit exp=roman]: Can we talk in Nepali from now on?
A [ne_roman]: Pakka — aba Nepali (Romanized) ma kura garam. Ke sodhna cha?
C [neutral exp=roman]: ok
A [ne_roman]: Thik cha.
C [neutral exp=roman]: Friday
A [ne_roman]: Thik cha — Friday ko availability herchu. Yo Tooth Filling ko lagi ho?
C [neutral exp=roman]: thanks
A [ne_roman]: Swagat cha! 😊
```

### B5-explicit-to-nepali — arm `hybrid` (rep 0)
```
C [signal exp=en]: Hi, how much is a filling?
A [en]: Hi — a Tooth Filling costs NPR 2500 and takes about 45 minutes.
C [signal exp=en]: and how long does it take?
A [en]: A Tooth Filling typically takes about 45 minutes.
C [explicit exp=roman]: Can we talk in Nepali from now on?
A [ne_roman]: Pakka — ma Nepali ma kura garna sakchhu. Ke sodhna cha?
C [neutral exp=roman]: ok
A [ne_roman]: Thik cha. Aru kehi sodhna cha bhane bhanuhos.
C [neutral exp=roman]: Friday
A [ne_roman]: Thik cha — Friday ko lagi kun service book garna khojnu huncha?
C [neutral exp=roman]: thanks
A [ne_roman]: Koi kura hoina! 😊
```

### HB2-roman-to-en-trek — arm `pre25` (rep 0)
```
C [signal exp=roman]: namaste, Everest Base Camp ko price kati ho?
A [ne_roman]: Namaste — Everest Base Camp Trek ko price USD 1400 ho (14 din). Confirm garna 30% deposit chahinchha, ra trekking permits hami le arrange garera price ma samabesh gareko chha. Booking garna man cha bhane tapaiko ideal departure date dinu hola?
C [signal exp=roman]: ani deposit kati dinu parcha?
A [ne_deva]: 30% deposit चाहिन्छ — Everest Base Camp Trek को कुल USD 1400 को 30% = USD 420। यो deposit दिएपछि booking confirm गर्न सकिन्छ। अगाडि बढाउन चाहनुहुन्छ भने कृपया तपाइँको ideal departure date र preferred payment method बताउनुहोस्।   <-- MISMATCH
C [switch exp=en]: Sorry one more thing, what is your cancellation policy if I need to postpone by a month?
A [ne_roman]: Namaste — hami ko policy anusar, yadi tapaile departure date bata 14 din va bhandaa badi agadi cancel garnu bhayo bhane full refund dincha. Tapaile ek mahina (approx. 30 din) postpone garnu bhane: yadi yo notice original departure date bata 14+ din agadi ho bhane full refund ko sharte satta tapaiko option haru bare team sanga check garna sakchhu. 14 din bhitra ko cancel/postpone ko policy yaha specify bhayeko chhaina — ke ma team sanga sodhi tapailai thik option haru confirm garera contact garau? Kripaya original departure date dinuhos.   <-- MISMATCH
C [signal exp=en]: Got it. What are your office hours during the week?
A [en]: Our office hours during the week are Monday–Friday, 10:00 AM to 6:00 PM. (For reference: we’re closed Saturdays and open Sundays 10:00 AM–6:00 PM.)
C [neutral exp=en]: thanks
A [en]: You’re welcome! If you’d like to proceed, tell me your ideal departure date and preferred payment method (or I can connect you with the team). Our office hours are Mon–Fri 10:00–6:00 and Sun 10:00–6:00 (closed Saturdays).
```

### HB2-roman-to-en-trek — arm `prod` (rep 0)
```
C [signal exp=roman]: namaste, Everest Base Camp ko price kati ho?
A [ne_roman]: Namaste — Everest Base Camp Trek ko price USD 1400 ho; trek 14 din ko ho. Booking confirm garna 30% deposit chahinchha; 14 din bhanda agadi cancel garda full refund huncha. Trekking permits hamile arrange garne ra price ma samabesh cha. Book garnu cha bhane btaunuhos.
C [signal exp=roman]: ani deposit kati dinu parcha?
A [ne_roman]: Booking confirm garna 30% deposit chahinchha; Everest Base Camp ko price USD 1400 bhaye 30% = USD 420. Book garna chahanu bhaye btaunuhos.
C [switch exp=en]: Sorry one more thing, what is your cancellation policy if I need to postpone by a month?
A [ne_roman]: Hamro cancellation policy anusar, booking departure ko 14 din bhanda agadi cancel garema full refund dincha. Tara ek mahina postpone (reschedule) garda kunai fee lagcha ki deposit transfer garna milcha jasto kura yo info ma lekhiyeko chaina — chahanu huncha bhane ma team sanga confirm garera tapailai connect garau?   <-- MISMATCH
C [signal exp=en]: Got it. What are your office hours during the week?
A [ne_roman]: Hamro office Monday dekhi Friday samma 10:00 AM bata 6:00 PM samma khula huncha.   <-- MISMATCH
C [neutral exp=en]: thanks
A [ne_roman]: Swagat cha!   <-- MISMATCH
```

### HB2-roman-to-en-trek — arm `hybrid` (rep 0)
```
C [signal exp=roman]: namaste, Everest Base Camp ko price kati ho?
A [ne_roman]: Namaste — Everest Base Camp Trek ko price USD 1400 ho, ra duration 14 days ho. Trekking permits price ma samabesh chan, ra booking confirm garna 30% deposit chahinchha.
C [signal exp=roman]: ani deposit kati dinu parcha?
A [ne_roman]: 30% deposit USD 420 huncha — booking confirm garna yo chahinchha.
C [switch exp=en]: Sorry one more thing, what is your cancellation policy if I need to postpone by a month?
A [en]: For cancellations we offer a full refund if cancelled 14 or more days before departure. I don't have a specific postponement/rescheduling policy here — would you like me to connect you with our team so they can confirm if postponing by a month is allowed and any fees?
C [signal exp=en]: Got it. What are your office hours during the week?
A [en]: We're open Monday–Friday, 10:00 AM to 6:00 PM. Saturday closed; Sunday 10:00 AM to 6:00 PM.
C [neutral exp=en]: thanks
A [en]: You're welcome! 😊
```

### HB1-en-to-deva-salon — arm `pre25` (rep 0)
```
C [signal exp=en]: Hi, what is the price of a haircut?
A [en]: A haircut is NPR 600 and takes about 30 minutes. Would you like to book an appointment or check walk-in availability?
C [signal exp=en]: Do you take walk-ins?
A [en]: Yes — walk-ins are welcome when a stylist is free. Booking ahead usually means a shorter wait. Would you like me to check current availability or book a time for you?
C [switch exp=deva]: मलाई भोलि बिहान ११ बजे कपाल काट्न मिल्छ?
A [ne_deva]: ठीक छ — भोलि 2026-09-20 बिहान 11:00 का लागि उपलब्धता जाँच गर्छु।
C [signal exp=deva]: अनि दाह्री पनि मिल्छ?
A [ne_deva]: अवश्य — हामीसँग "Beard Trim" सेवा छ (NPR 300, करिब 15 मिनेट)। म भोलि 2026-09-20 बिहान 11:00 का लागि कपालको उपलब्धता जाँच्दै थिएँ; दाह्री पनि त्यही सँगै थप्न चाहनुहुन्छ?
C [neutral exp=deva]: ok
A [ne_deva]: ठीक छ — म भोलि 2026-09-20 बिहान 11:00 का लागि Haircut र Beard Trim दुवैको उपलब्धता जाँच्छु। अघि बढाउन कृपया तपाईंको पूरा नाम र फोन नम्बर दिन सक्नुहुन्छ?
```

### HB1-en-to-deva-salon — arm `prod` (rep 0)
```
C [signal exp=en]: Hi, what is the price of a haircut?
A [en]: A Haircut is NPR 600 and takes about 30 minutes.
C [signal exp=en]: Do you take walk-ins?
A [en]: Yes — walk-ins are welcome when a stylist is available. Booking ahead usually shortens wait times.
C [switch exp=deva]: मलाई भोलि बिहान ११ बजे कपाल काट्न मिल्छ?
A [en]: Let me check availability for a Haircut tomorrow at 11:00.   <-- MISMATCH
C [signal exp=deva]: अनि दाह्री पनि मिल्छ?
A [en]: Yes — we offer a Beard Trim (NPR 300, about 15 minutes). Would you like me to add it to the Haircut you're checking for tomorrow at 11:00?   <-- MISMATCH
C [neutral exp=deva]: ok
A [en]: Great — I'll check availability for a Haircut plus Beard Trim tomorrow at 11:00.   <-- MISMATCH
```

### HB1-en-to-deva-salon — arm `hybrid` (rep 0)
```
C [signal exp=en]: Hi, what is the price of a haircut?
A [en]: Hi! A Haircut is NPR 600 and takes about 30 minutes. We accept cash or eSewa, and walk-ins are welcome if a stylist is free.
C [signal exp=en]: Do you take walk-ins?
A [en]: Yes — walk-ins are welcome if a stylist is free. Booking ahead is recommended if you want to avoid waiting.
C [switch exp=deva]: मलाई भोलि बिहान ११ बजे कपाल काट्न मिल्छ?
A [ne_deva]: ठीक छ — भोलि बिहान 11:00 को लागि उपलब्धता हेर्छु।
C [signal exp=deva]: अनि दाह्री पनि मिल्छ?
A [ne_deva]: हो — दाह्री (Beard Trim) पनि गरिन्छ। शुल्क NPR 300 र करिब 15 मिनेट लाग्छ। भोलि 11:00 को haircut सँगै दाह्री पनि राख्न चाहनुहुन्छ?
C [neutral exp=deva]: ok
A [ne_deva]: ठीक छ — भोलि बिहान 11:00 मा Haircut सँगै Beard Trim राख्ने गरी उपलब्धता हेर्छु।
```

### HB3b-explicit-to-devanagari — arm `pre25` (rep 0)
```
C [signal exp=en]: hi, do you do haircuts?
A [en]: Yes — we offer Haircut (NPR 600, about 30 minutes). Walk-ins are welcome if a stylist is free. Would you like to book an appointment or check availability?
C [signal exp=en]: how much?
A [en]: A Haircut is NPR 600 and takes about 30 minutes. We accept cash or eSewa, and walk-ins are welcome if a stylist is free. Would you like to book an appointment?
C [explicit exp=deva]: Could you reply in Nepali (Devanagari script) from now on please?
A [ne_deva]: पक्कै — अबदेखि म देवनागरी लिपिमा (नेपाली) नै जवाफ दिनेछु। अरू के सहयोग चाहिन्छ?
C [neutral exp=deva]: ok
A [ne_deva]: ठीक छ — के म अपोइन्टमेन्ट बुक गरौँ? चाहनुभएको सेवा, मिति र समय बताउनुहोस्। वा वाक-इन गर्न चाहनुहुन्छ भने भन्नुहोस्।
C [neutral exp=deva]: Sunday
A [ne_deva]: आइतबार हाम्रा खुल्ने समय ९:०० बिहानदेखि ८:०० बेलुकासम्म हो। अपोइन्टमेन्ट बुक गर्न चाहनुहुन्छ भने सेवा, मिति र समय बताउनुहोस्, वा वाक-इन गर्न चाहनुहुन्छ भने भन्नुहोस् — वाक-इन स्टाइलिस्ट खाली हुँदा स्वागत छ।
```

### HB3b-explicit-to-devanagari — arm `prod` (rep 0)
```
C [signal exp=en]: hi, do you do haircuts?
A [en]: Hi — yes, we do haircuts. Price is NPR 600 and it takes about 30 minutes. Walk-ins are welcome if a stylist is free, or I can help you book an appointment; we accept cash or eSewa.
C [signal exp=en]: how much?
A [en]: A Haircut is NPR 600 and takes about 30 minutes. We accept cash or eSewa; walk-ins are welcome, or I can help you book an appointment.
C [explicit exp=deva]: Could you reply in Nepali (Devanagari script) from now on please?
A [ne_deva]: पक्कै — अबदेखि म देवनागरी नेपालीमै जवाफ दिनेछु। के म तपाईंलाई अहिले केही मद्दत गरूँ?
C [neutral exp=deva]: ok
A [ne_deva]: ठीक छ। अरु केही चाहनुहुन्छ भने भन्नुहोस्।
C [neutral exp=deva]: Sunday
A [ne_deva]: हामी आइतबार बिहान ९:०० बजेदेखि साँझ ८:०० बजे सम्म खुल्छौँ।
```

### HB3b-explicit-to-devanagari — arm `hybrid` (rep 0)
```
C [signal exp=en]: hi, do you do haircuts?
A [en]: Yes — we offer Haircut (NPR 600, about 30 minutes). Walk-ins welcome if a stylist is free; would you like to book an appointment?
C [signal exp=en]: how much?
A [en]: A Haircut is NPR 600 and takes about 30 minutes. Walk-ins are welcome — would you like me to book an appointment for you?
C [explicit exp=deva]: Could you reply in Nepali (Devanagari script) from now on please?
A [ne_deva]: पक्कै — म अबदेखि देवनागरी नेपालीमा उत्तर दिनेछु।
C [neutral exp=deva]: ok
A [ne_deva]: ठीक छ — के म तपाईंको लागि हेयरकट अपोइन्टमेन्ट बुक गरूँ?
C [neutral exp=deva]: Sunday
A [ne_deva]: ठीक छ — आइतबार (2026-09-20) का लागि हेयरकटको उपलब्धता जाँच्छु।
```

### B7-customer-alternates — arm `pre25` (rep 0)
```
C [signal exp=roman]: namaste, teeth whitening kati parcha?
A [ne_roman]: Namaste — Teeth Whitening ko price NPR 6000; lagbhag 45 minute lagcha. Booking garnu bhaye kun date ra time manparcha bhanera dinuhos, ma madat garchu.
C [switch exp=en]: Okay, and how long does it take?
A [ne_deva]: Teeth Whitening करिब 45 मिनेट लाग्छ। Appointment बनाउन मन भए कुन मिति र समय चाहनुहुन्छ भनी बताउनुहोस्, म मद्दत गर्छु।   <-- MISMATCH
C [switch exp=roman]: ani weekend ma khula huncha?
A [ne_deva]: Weekend मा हामी खुल्दैनौं — शनिवार र आइतबार बन्द हुन्छ। हाम्रा घण्टाहरू: सोमवार–शुक्रवार 9:00 AM–6:00 PM। कुनै weekday मा appointment चाहनुहुन्छ भने कुन मिति/समय मनपर्छ भन्नुहोस्, म मद्दत गर्छु।   <-- MISMATCH
C [switch exp=en]: Can I pay by card there?
A [en]: We accept cash, eSewa, or Khalti. Card payments aren't listed in our policies, so I can't confirm whether we take cards — would you like me to connect you with a team member to check?
C [switch exp=roman]: hunxa hunxa, bholi aauchu
A [ne_roman]: Thik cha — tara bholi aitabar ho ra hami bandha chhau. Sombar–Shukrabar 9:00–18:00 matra khulchha. Teeth Whitening ko lagi kun weekday ra kun samaya (kati baje) aunu manparcha?
```

### B7-customer-alternates — arm `prod` (rep 0)
```
C [signal exp=roman]: namaste, teeth whitening kati parcha?
A [ne_roman]: Namaste — Teeth Whitening ko price NPR 6000 ho ra karib 45 minutes lagcha. Booking garna man cha bhane bhanuhos.
C [switch exp=en]: Okay, and how long does it take?
A [ne_roman]: Teeth Whitening karib 45 minutes lagcha.   <-- MISMATCH
C [switch exp=roman]: ani weekend ma khula huncha?
A [ne_roman]: Weekend ma banda cha — Saturday ra Sunday hamro clinic closed huncha. Hamro regular hours Monday–Friday 9:00 AM bata 6:00 PM samma huncha.
C [switch exp=en]: Can I pay by card there?
A [ne_roman]: Ahileko thaha anusar, hamile cash, eSewa, ra Khalti matra linu huncha — card ko option list ma chaina. Confirm garna chahanu huncha bhane ma team sanga connect garera sodhi dinu?   <-- MISMATCH
C [switch exp=roman]: hunxa hunxa, bholi aauchu
A [ne_roman]: Thik cha — tara bholi hamro clinic closed cha (Sunday). Kun din milcha? Hamro hours Monday–Friday 9:00 AM bata 6:00 PM samma huncha.
```

### B7-customer-alternates — arm `hybrid` (rep 0)
```
C [signal exp=roman]: namaste, teeth whitening kati parcha?
A [ne_roman]: Namaste — Teeth Whitening ko price NPR 6000 ho, ra karib 45 minute lagcha.
C [switch exp=en]: Okay, and how long does it take?
A [en]: Teeth Whitening takes about 45 minutes.
C [switch exp=roman]: ani weekend ma khula huncha?
A [ne_roman]: Weekend ma khula hudaina. Saturday ra Sunday closed cha. Hami Monday–Friday 9:00 AM dekhi 6:00 PM samma khula chau.
C [switch exp=en]: Can I pay by card there?
A [en]: We accept cash, eSewa, and Khalti — card payments aren't listed. Want me to connect you with our team to confirm?
C [switch exp=roman]: hunxa hunxa, bholi aauchu
A [ne_roman]: Ah, bholi Sunday ho — clinic Sunday band cha. Monday aunu hunuhunchha?
```

## C. Ambiguous short input (the original flip-flop)


### C1-roman-neutral-tokens — arm `pre25` (rep 0)
```
C [signal exp=roman]: Namaste, tapaiko teeth cleaning ko lagi kati parcha?
A [ne_deva]: Namaste — Teeth Cleaning को शुल्क NPR 1500 हो (समय: 30 मिनेट)। भुक्तानी नगद, eSewa वा Khalti बाट गर्न सकिन्छ। बुकिंग गर्न चाहनुहुन्छ?   <-- MISMATCH
C [neutral exp=roman]: ok
A [ne_deva]: ठीक छ — बुकिंग गर्न चाहनुहुन्छ भने कुन मिति र कति बजे चाहिन्छ? हामी सोमबारदेखि शुक्रबार 9:00–18:00 खुला छौं। कृपया आफ्नो पूरा नाम र फोन नम्बर पनि दिनुहोस्।   <-- MISMATCH
C [neutral exp=roman]: Friday
A [ne_deva]: ठीक छ — “Friday” भन्नु भयो। कुन Friday चाहनुहुन्छ (आउँदो Friday वा मिति दिनुहोस्)? हामी सोमबार–शुक्रबार 09:00–18:00 खुल्छौं — कुन समय राम्रो हुन्छ? साथै तपाईँको पूरा नाम र फोन नम्बर दिनुहोस्। (सेवा: Teeth Cleaning, NPR 1500)   <-- MISMATCH
C [neutral exp=roman]: 3pm
A [ne_deva]: ठीक छ — तपाईँ Teeth Cleaning का लागि 3:00 PM चाहनुहुन्छ। कुन Friday चाहनुहुन्छ — आउँदो Friday वा मिति दिनुहोस्? साथै कृपया तपाईँको पूरा नाम र फोन नम्बर दिनुहोस्।   <-- MISMATCH
C [neutral exp=roman]: yes
A [ne_deva]: ठीक छ — तपाईं Teeth Cleaning का लागि 3:00 PM मा बुक गर्न चाहनुहुन्छ? कुन Friday चाहनुहुन्छ — आउँदो Friday (2026-09-25) वा अर्को मिति? साथै कृपया आफ्नो पूरा नाम र फोन नम्बर दिनुहोस्।   <-- MISMATCH
C [neutral exp=roman]: thanks
A [ne_deva]: स्वागत छ — सहयोगका लागि धन्यवाद। बुकिंग पूरा गर्न कृपया आफ्नो पूरा नाम र फोन नम्बर पठाउनुहोस् (सेवा: Teeth Cleaning; मिति: आउँदो शुक्रबार 2026-09-25; समय: 15:00)।   <-- MISMATCH
C [neutral exp=roman]: hi
A [en]: Hi — would you like to proceed with the Teeth Cleaning appointment for Friday, 2026-09-25 at 3:00 PM? If so, please send your full name and phone number and I’ll pass it on to complete the booking.   <-- MISMATCH   <-- FLIP
```

### C1-roman-neutral-tokens — arm `prod` (rep 0)
```
C [signal exp=roman]: Namaste, tapaiko teeth cleaning ko lagi kati parcha?
A [ne_deva]: Namaste! Teeth Cleaning को शुल्क NPR 1500 छ, र करिब 30 मिनेट लाग्छ।   <-- MISMATCH
C [neutral exp=roman]: ok
A [ne_roman]: Thik cha. Aru kehi chahiyo bhane bhanuhos.   <-- FLIP
C [neutral exp=roman]: Friday
A [ne_roman]: Thik cha — ma Friday ko available slots herchu.
C [neutral exp=roman]: 3pm
A [ne_roman]: Thik cha — ma Friday 3pm ko availability herchu.
C [neutral exp=roman]: yes
A [ne_roman]: Thik cha — ma availability herchu.
C [neutral exp=roman]: thanks
A [ne_roman]: Swagat cha!
C [neutral exp=roman]: hi
A [ne_roman]: Namaste! K ma madat garna sakchu?
```

### C1-roman-neutral-tokens — arm `hybrid` (rep 0)
```
C [signal exp=roman]: Namaste, tapaiko teeth cleaning ko lagi kati parcha?
A [ne_roman]: Teeth Cleaning ko price NPR 1500 ho, ra karib 30 minute lagcha.
C [neutral exp=roman]: ok
A [ne_roman]: Thik cha.
C [neutral exp=roman]: Friday
A [ne_roman]: Thik cha, Friday ko lagi herchu.
C [neutral exp=roman]: 3pm
A [ne_roman]: Thik cha, 15:00 (3pm) ko lagi herchu.
C [neutral exp=roman]: yes
A [ne_roman]: Thik cha, ma herchu.
C [neutral exp=roman]: thanks
A [ne_roman]: Swagat cha!
C [neutral exp=roman]: hi
A [ne_roman]: Namaste! K ma tapai lai sahayog garna sakchu?
```

### C2-deva-neutral-tokens — arm `pre25` (rep 0)
```
C [signal exp=deva]: नमस्ते, सफाइको मूल्य कति हो?
A [ne_deva]: नमस्ते — Teeth Cleaning (सफाइ) को मूल्य NPR 1500 हो। सेवा अवधि 30 मिनेट हुन्छ। अपोइन्टमेन्ट बुक गर्न चाहनुहुन्छ?
C [neutral exp=deva]: ok
A [ne_deva]: ठीक छ — Teeth Cleaning को लागि अपोइन्टमेन्ट बुक गरौं? कुन मिति र समय चाहनुहुन्छ? (हामी सोम–शुक्र 09:00–18:00 खुल्छौं; शनिबार र आइतबार बन्द छन्.)
C [neutral exp=deva]: Friday
A [ne_deva]: ठीक छ — शुक्रवार (2026-09-25) का लागि Teeth Cleaning चाहनुहुन्छ। कुन समय उपयुक्त हुन्छ? हामी सोम–शुक्र 09:00–18:00 खुल्छौं।
C [neutral exp=deva]: 3pm
A [ne_deva]: ठीक छ — शुक्रवार 2026-09-25, 15:00 का लागि Teeth Cleaning को उपलब्धता जाँच्छु।
C [neutral exp=deva]: yes
A [ne_deva]: ठीक छ — शुक्रवार 2026-09-25 मा 15:00 का लागि Teeth Cleaning को उपलब्धता जाँच गर्छु।
C [neutral exp=deva]: thanks
A [ne_deva]: स्वागत छ — म शुक्रवार 2026-09-25, 15:00 को उपलब्धता जाँचेर तपाईँलाई जानकारी दिनेछु। अपोइन्टमेन्ट पुष्टि गर्न म नाम र फोन नम्बर लिन सक्छु?
C [neutral exp=deva]: 2
A [ne_deva]: तपाईंले ‘2’ लेख्नुभएको छ — के त्यसले केही संकेत गर्छ? अपोइन्टमेन्ट अझै पुष्टि भएको छैन। पुष्टि गर्न कृपया आफ्नो नाम र फोन नम्बर दिनुहोस् (सेवा: Teeth Cleaning, प्रस्तावित मिति/समय: 2026-09-25, 15:00)। परिवर्तन चाहनुहुन्छ भने बताउनुहोस्।
```

### C2-deva-neutral-tokens — arm `prod` (rep 0)
```
C [signal exp=deva]: नमस्ते, सफाइको मूल्य कति हो?
A [ne_deva]: सफाइ (Teeth Cleaning) को मूल्य NPR 1500 हो, र करिब ३० मिनेट लाग्छ।
C [neutral exp=deva]: ok
A [ne_deva]: ठीक छ। अरू केही सहयोग चाहियो भने बताउनुहोस्।
C [neutral exp=deva]: Friday
A [ne_deva]: ठीक छ — शुक्रबारका लागि उपलब्धता हेर्छु।
C [neutral exp=deva]: 3pm
A [ne_deva]: ठीक छ — शुक्रबार 3 बजेको उपलब्धता हेर्छु।
C [neutral exp=deva]: yes
A [ne_deva]: ठीक छ।
C [neutral exp=deva]: thanks
A [ne_deva]: स्वागत छ! 😊
C [neutral exp=deva]: 2
A [ne_deva]: “2” भन्नाले के भन्न खोजिएको हो — 2 जना, 2 बजे, वा अरु केही? कृपया सजिलै बताउनुहोस्।
```

### C2-deva-neutral-tokens — arm `hybrid` (rep 0)
```
C [signal exp=deva]: नमस्ते, सफाइको मूल्य कति हो?
A [ne_deva]: Teeth Cleaning को मूल्य NPR 1500 हो र करिब 30 मिनेट लाग्छ। बुक गर्न चाहनुहुन्छ?
C [neutral exp=deva]: ok
A [ne_deva]: ठीक छ, म उपलब्धता हेर्छु।
C [neutral exp=deva]: Friday
A [ne_deva]: ठीक छ — शुक्रबारको लागि उपलब्धता हेर्छु।
C [neutral exp=deva]: 3pm
A [ne_deva]: ठीक छ — ३ बजेको लागि हेर्छु।
C [neutral exp=deva]: yes
A [ne_deva]: ठीक छ — हेर्छु।
C [neutral exp=deva]: thanks
A [ne_deva]: स्वागत छ!
C [neutral exp=deva]: 2
A [ne_deva]: तपाईंले '2' भन्नाले के जनाउनुभएको हो?
```

### C4-hlo-then-k-xa — arm `pre25` (rep 0)
```
C [neutral exp=None]: hlo
A [en]: Hi — welcome to Demo Dental Clinic. How can I help you today?
C [signal exp=roman]: K xa
A [ne_roman]: Namaste — k cha? Ma kasari madat garna sakchu?
C [signal exp=roman]: malai euta tooth dukheko xa
A [ne_roman]: Dukha bhayo — thik cha. Kati belā dekhi dukheko ho? Swelling, bukha (fever), ya gaḍbṛi bleed bhayo jasto cha? Hamro clinic aaja Saturday banda cha — hours Mon–Fri 9:00 AM–6:00 PM. Ke tapā'ī appointment book garna chāhanu huncha, ani kun din/kun samaya ramrō huncha? Phone number dinu bhaye hami tapaīlāī contact garna sakincha.
C [neutral exp=roman]: ok
A [ne_deva]: ठीक छ — के तपाईँ अपोइन्टमेन्ट बुक गर्न चाहनुहुन्छ? हाम्रो क्लिनिक आज शनिबार बन्द छ (Mon–Fri 9:00–18:00)। कुन सेवा चाहनुहुन्छ? (Teeth Cleaning, Tooth Filling, Root Canal, Teeth Whitening, Dental Consultation)। कुन दिन र समय अनुकूल हुन्छ र फोन नम्बर दिन सक्नुहुन्छ?   <-- MISMATCH   <-- FLIP
C [neutral exp=roman]: 2
A [ne_deva]: ठीक छ — तपाइँले "Tooth Filling" रोज्नुभयो। कुन दिन र कुन समयमा आउनु अनुकूल हुन्छ? हाम्रो क्लिनिक सोमबार–शुक्रबार 9:00–18:00 खुल्छ; आज शनिबार बन्द छ। सम्पर्कका लागि फोन नम्बर दिनुहुन्छ?   <-- MISMATCH
C [neutral exp=roman]: thanks
A [ne_deva]: ठीक छ — धन्यवाद! अरु केही चाहियो भने बताउनुहोस्। Tooth Filling का लागि अपोइन्टमेन्ट चाहनुहुन्छ भने अनुकूल दिन/समय (सोम–शुक्र 9:00–18:00) र फोन नम्बर दिनुहोस्।   <-- MISMATCH
```

### C4-hlo-then-k-xa — arm `prod` (rep 0)
```
C [neutral exp=None]: hlo
A [en]: Hi! How can I help you today?
C [signal exp=roman]: K xa
A [ne_roman]: Thik cha — ma Demo Dental Clinic ko receptionist hu. K ma help garu? Hamra services: Teeth Cleaning (NPR 1500, 30 min), Tooth Filling (NPR 2500, 45 min), Root Canal (NPR 9000, 90 min), Teeth Whitening (NPR 6000, 45 min), Dental Consultation (NPR 500, 20 min). Clinic Saturday ra Sunday bandh cha. Kun kura hernu cha?
C [signal exp=roman]: malai euta tooth dukheko xa
A [ne_roman]: Oh, dukhai sunera afno dukha lagyo. Ke tapaile appointment book garna chahanu huncha? (Note: aaja Saturday bhayeko le clinic bandh cha; aglo open Monday 9am–6pm.)
C [neutral exp=roman]: ok
A [ne_roman]: Thik cha. Clinic aaja bandh cha; aglo khula Monday 9am–6pm. Kun service ko appointment chahanu huncha?
C [neutral exp=roman]: 2
A [ne_roman]: Thik cha — Tooth Filling ko lagi herchu.
C [neutral exp=roman]: thanks
A [ne_roman]: Swagat cha! 😊
```

### C4-hlo-then-k-xa — arm `hybrid` (rep 0)
```
C [neutral exp=None]: hlo
A [ne_roman]: Hi! K garna khojnu huncha? Ma Demo Dental Clinic ko receptionist hu — appointment, services, hours, location adi ma madat garna sakchu.
C [signal exp=roman]: K xa
A [ne_roman]: Thik cha. K ma tapaiko appointment, services, hours wa location ma madat garna sakchu?
C [signal exp=roman]: malai euta tooth dukheko xa
A [ne_roman]: Oh, dukha bhayo — sorry. For toothache, we usually start with a Dental Consultation (NPR 500, ~20 min); if treatment lagyo bhane Tooth Filling (NPR 2500, 45 min) or Root Canal (NPR 9000, 90 min) huncha. Clinic aaja Saturday banda cha; pahilo khuleko din Monday 9:00 AM ho. Booking garna mancha bhane kun din/time thik huncha bhanera btaunus.
C [neutral exp=roman]: ok
A [ne_roman]: Thik cha — kun din ra kati baje ko lagi appointment chahanu huncha btaunus.
C [neutral exp=roman]: 2
A [ne_roman]: Thik cha — 2 baje bujhyo. Kun din ko lagi ho? Note: aaja clinic banda cha; pahilo khuleko din Monday 9:00 AM ho.
C [neutral exp=roman]: thanks
A [ne_roman]: Swagat cha! 😊
```

### HC1-salon-roman-neutral — arm `pre25` (rep 0)
```
C [signal exp=roman]: Namaste, hair colour garna kati lagcha?
A [ne_roman]: Namaste — Hair Colour ko cost NPR 3500 ho ra samaya lagbhag 120 minute (2 ghanta) ho. Booking garna chahanu huncha?
C [neutral exp=roman]: ok
A [ne_deva]: ठीक छ — Hair Colour को लागि booking गराउन चाहनुहुन्छ? कुन मिति र समय मन लाग्छ (हाम्रो समय: हरेक दिन 9:00–20:00)?   <-- MISMATCH   <-- FLIP
C [neutral exp=roman]: Sunday
A [ne_deva]: ठीक छ — Sunday (2026-09-20) को लागि कुन समय चाहनुहुन्छ? हाम्रो समय हरेक दिन 9:00–20:00 हो; Hair Colour मा करिब 2 घण्टा लाग्छ।   <-- MISMATCH
C [neutral exp=roman]: 5pm
A [ne_deva]: ठीक छ — म 2026-09-20 (Sunday) 17:00 का लागि Hair Colour को उपलब्धता जाँच्छु। Hair Colour करिब 2 घण्टा लाग्छ।   <-- MISMATCH
C [neutral exp=roman]: yes please
A [en]: Got it — I’ll check availability for a Hair Colour on 2026-09-20 at 17:00. Could I have your full name and phone number to proceed?   <-- MISMATCH   <-- FLIP
C [neutral exp=roman]: thank you
A [en]: You're welcome! Could I have your full name and phone number to proceed with the Hair Colour booking on 2026-09-20 at 17:00?   <-- MISMATCH
C [neutral exp=roman]: Yo
A [en]: Hi — ready to proceed with the Hair Colour on 2026-09-20 at 17:00. Could I have your full name and phone number to finish the booking?   <-- MISMATCH
```

### HC1-salon-roman-neutral — arm `prod` (rep 0)
```
C [signal exp=roman]: Namaste, hair colour garna kati lagcha?
A [ne_deva]: Namaste — Hair Colour को मूल्य NPR 3500 हो र करिब 120 मिनेट लाग्छ।   <-- MISMATCH
C [neutral exp=roman]: ok
A [ne_roman]: Thik cha, dhanyabad!   <-- FLIP
C [neutral exp=roman]: Sunday
A [ne_roman]: Ho — hami Sunday pani 9 baje dekhi 8 baje samma khula cha.
C [neutral exp=roman]: 5pm
A [ne_roman]: Thik cha — ma 5pm ko slot herchu.
C [neutral exp=roman]: yes please
A [ne_roman]: Thik cha — ma 5pm ko slot herchu.
C [neutral exp=roman]: thank you
A [ne_roman]: Swagat cha!
C [neutral exp=roman]: Yo
A [ne_roman]: Namaste! Ma kasari madat garna sakchu?
```

### HC1-salon-roman-neutral — arm `hybrid` (rep 0)
```
C [signal exp=roman]: Namaste, hair colour garna kati lagcha?
A [ne_roman]: Namaste — Hair Colour ko price NPR 3500 ho ra karib 120 minutes lagcha. Payment cash or eSewa chalcha. Walk-ins welcome if stylist free.
C [neutral exp=roman]: ok
A [ne_roman]: Thik cha — dhanyabad!
C [neutral exp=roman]: Sunday
A [ne_roman]: Ho — Sunday pani khula cha, 9:00 AM dekhi 8:00 PM samma.
C [neutral exp=roman]: 5pm
A [ne_roman]: Thik cha — 5pm ko lagi ek chin herchu.
C [neutral exp=roman]: yes please
A [ne_roman]: Thik cha — ek chin herchu.
C [neutral exp=roman]: thank you
A [ne_roman]: Swagat cha!
C [neutral exp=roman]: Yo
A [ne_roman]: Yo — namaste! K ma kehi madat garna sakchu?
```

### HC3-salon-deva-neutral — arm `pre25` (rep 0)
```
C [signal exp=deva]: नमस्ते, कपाल काट्ने कति पर्छ?
A [ne_deva]: नमस्ते — कपाल काट्ने शुल्क NPR 600 हो र समय करिब 30 मिनेट लाग्छ। हामीमा स्टाइलिस्ट खाली भए walk-ins स्वागत छ। भुक्तानी नकद वा eSewa मार्फत गर्न सकिन्छ। अपोइन्टमेन्ट चाहनुहुन्छ भने बताउनुहोस्।
C [neutral exp=deva]: ok
A [ne_deva]: ठीक छ — के म तपाईंका लागि अपोइन्टमेन्ट बुक गरिदिउँ? भएमा कुन मिति र समय चाहिन्छ भन्ने बताउनुहोस्, वा तपाईं walk-in आउनुहुन्छ भने स्टाइलिस्ट खाली भए स्वागत छ।
C [neutral exp=deva]: Saturday
A [ne_deva]: ठिक छ — शनीबार (2026-09-19) का लागि कपाल काट्न चाहनुहुन्छ। कुन समय राम्रो हुन्छ? हामी बिहान 09:00 देखि साँझ 20:00 सम्म खुल्छौं।
C [neutral exp=deva]: hi
A [en]: Hi — thanks for checking in! Do you want to book a Haircut (NPR 600, ~30 min) for Saturday (Sept 19)? What time between 09:00 and 20:00 would you like, or would you prefer to walk in if a stylist is free?   <-- MISMATCH   <-- FLIP
C [neutral exp=deva]: 3
A [en]: Got it — a Haircut for Saturday (2026-09-19) at 15:00. Let me check availability for that time.   <-- MISMATCH
C [neutral exp=deva]: thanks
A [en]: You're welcome — I'll check availability for your Haircut on Saturday (2026-09-19) at 15:00 and confirm shortly. Would you like to add a phone number or any notes for the stylist?   <-- MISMATCH
```

### HC3-salon-deva-neutral — arm `prod` (rep 0)
```
C [signal exp=deva]: नमस्ते, कपाल काट्ने कति पर्छ?
A [ne_deva]: नमस्ते! कपाल काट्ने (Haircut) NPR 600 हुन्छ र करिब 30 मिनेट लाग्छ। यदि stylist खाली भए भने walk-ins स्वागत छ। ढिला 15 मिनेटभन्दा बढी भए स्लट हराउन सक्छ। भुक्तानी cash वा eSewa accept गरिन्छ।
C [neutral exp=deva]: ok
A [ne_deva]: ठीक छ! अरू केही चाहियो भने बताउनुहोस्।
C [neutral exp=deva]: Saturday
A [ne_deva]: शनिबार हामी बिहान 9:00 देखि साँझ 8:00 सम्म खुल्छ। कपाल काटाउन आउन चाहनुहुन्छ भने कुन समय मिल्छ?
C [neutral exp=deva]: hi
A [ne_deva]: नमस्ते! कुन समयमा आउन चाहनुहुन्छ?
C [neutral exp=deva]: 3
A [ne_deva]: ठीक छ, 3 बजेका लागि हेर्छु।
C [neutral exp=deva]: thanks
A [ne_deva]: स्वागत छ!
```

### HC3-salon-deva-neutral — arm `hybrid` (rep 0)
```
C [signal exp=deva]: नमस्ते, कपाल काट्ने कति पर्छ?
A [ne_deva]: Haircut को price NPR 600 हो, र करिब 30 मिनेट लाग्छ।
C [neutral exp=deva]: ok
A [ne_deva]: ठीक छ, धन्यवाद!
C [neutral exp=deva]: Saturday
A [ne_deva]: ठीक छ — शनिबार Haircut नै हो?
C [neutral exp=deva]: hi
A [ne_deva]: नमस्ते! म कसरि मद्दत गर्न सक्छु?
C [neutral exp=deva]: 3
A [ne_deva]: ठीक छ — 3 बजेको लागि हेर्छु।
C [neutral exp=deva]: thanks
A [ne_deva]: स्वागत छ!
```

## D. Long conversation, no real signal change


### D1-long-roman — arm `pre25` (rep 0)
```
C [signal exp=roman]: namaste, dental clinic ma teeth cleaning garna paryo, kati parcha?
A [ne_deva]: नमस्ते — दाँत सफा गर्ने (Teeth Cleaning) शुल्क NPR 1500 हो र प्रक्रिया करिब 30 मिनेट लाग्छ। भुक्तानी: नगद, eSewa, वा Khalti। के म तपाईंको लागि अपोइन्टमेन्ट बुक गर्न मद्दत गरूँ?   <-- MISMATCH
C [signal exp=roman]: ani kati time lagcha?
A [ne_deva]: Teeth Cleaning करिब 30 मिनेट लाग्छ। अपोइन्टमेन्ट बुक गर्न चाहनुहुन्छ? चाहियो भने कुन दिन र समय मनपर्छ बताउनुहोस्।   <-- MISMATCH
C [signal exp=roman]: ok. weekend ma khula huncha?
A [ne_deva]: हामी सप्ताहन्तमा बन्द छौं — शनिबार र आइतबार बन्द हुन्छ। हामी सोमबार–शुक्रबार बिहान 9:00 देखि साँझ 6:00 सम्म खोल्छौं। कुन दिन र समय चाहनुहुन्छ? म अपोइन्टमेन्ट बुक गर्न सहयोग गर्छु।   <-- MISMATCH
C [signal exp=roman]: hunxa. ani sombar ko lagi slot cha?
A [ne_roman]: Thik cha. Sombar (2026-09-21) Teeth Cleaning ko lagi kun time manparcha? Hami 9:00–18:00 samma khula chau — kun time (e.g. 10:00) chahanu huncha?
C [neutral exp=roman]: 10am
A [ne_roman]: Thik cha — ma 2026-09-21 (Monday) 10:00 ko Teeth Cleaning ko availability herchhu. Naam ra phone number dinuhos?
C [signal exp=roman]: malai 10:30 ma milcha ki?
A [ne_roman]: Thik cha — ma 2026-09-21 10:30 ko availability herchhu. Naam ra phone number dinuhos?
C [neutral exp=roman]: ok
A [ne_roman]: Thik cha — ma 2026-09-21 10:30 ko Teeth Cleaning ko availability herchhu. Naam ra phone number dinuhos?
C [signal exp=roman]: mero naam Ramesh ho, phone 9812345678
A [ne_deva]: धन्यवाद — नाम Ramesh र फोन 9812345678 रेकर्ड भयो। म 2026-09-21 10:30 का लागि Teeth Cleaning को उपलब्धता जाँच्छु र छिट्टै पुष्टि गरिदिन्छु। रद्द गर्न कम्तीमा 4 घण्टा अघि जानकारी दिनुहोस्। भुक्तानी: नगद, eSewa, वा Khalti। के तपाईंलाई कुनै एलर्जी वा विशेष अनुरोध छ?   <-- MISMATCH
C [signal exp=roman]: cash le tirna milcha?
A [ne_deva]: हो — भुक्तानी नगद, eSewa, वा Khalti मार्फत गर्न मिल्छ। अरू केही मद्दत चाहिन्छ?   <-- MISMATCH
C [neutral exp=roman]: thanks
A [en]: You’re welcome — I’ll confirm availability for Teeth Cleaning on 2026-09-21 at 10:30 and get back to you shortly. Anything else I can help with?   <-- MISMATCH   <-- FLIP
C [signal exp=roman]: eSewa ma pani hunxa?
A [ne_deva]: हो — हामी eSewa मार्फत भुक्तानी लिन्छौं। अरू केही मद्दत चाहिन्छ?   <-- MISMATCH
C [neutral exp=roman]: ok done
A [en]: Great — I have your details and I'm checking availability for Teeth Cleaning on 2026-09-21 at 10:30. I'll confirm shortly. Reminder: please cancel at least 4 hours before; payment accepted by cash, eSewa, or Khalti. Anything else I can help with?   <-- MISMATCH   <-- FLIP
C [neutral exp=roman]: dhanyabad
A [ne_roman]: Swagat cha — ma tapaiko 2026-09-21 10:30 ko Teeth Cleaning ko availability chito herera confirm garnechhu. Aru kehi sahayog chahiyo?   <-- FLIP
```

### D1-long-roman — arm `prod` (rep 0)
```
C [signal exp=roman]: namaste, dental clinic ma teeth cleaning garna paryo, kati parcha?
A [ne_roman]: Namaste! Teeth Cleaning ko price NPR 1500 ho, ra karib 30 minute lagcha. Book garna man cha bhane bhanidinuhos.
C [signal exp=roman]: ani kati time lagcha?
A [ne_roman]: Teeth Cleaning ma karib 30 minute lagcha.
C [signal exp=roman]: ok. weekend ma khula huncha?
A [ne_roman]: Weekend ma hamro clinic khula hudaina — Saturday ra Sunday bandha huncha. Hamro regular hours Monday–Friday 9:00 AM dekhi 6:00 PM samma huncha.
C [signal exp=roman]: hunxa. ani sombar ko lagi slot cha?
A [ne_roman]: Thik cha — sombar (2026-09-21) ko available slots herchu.
C [neutral exp=roman]: 10am
A [ne_roman]: Thik cha — ma 10:00 AM ko slot herchu.
C [signal exp=roman]: malai 10:30 ma milcha ki?
A [ne_roman]: Thik cha — ma 10:30 AM ko slot herchu.
C [neutral exp=roman]: ok
A [ne_roman]: Thik cha.
C [signal exp=roman]: mero naam Ramesh ho, phone 9812345678
A [en]: Dhanyabad, Ramesh! Got it.   <-- MISMATCH
C [signal exp=roman]: cash le tirna milcha?
A [ne_roman]: Ho — cash, eSewa, ra Khalti le tirna milcha.
C [neutral exp=roman]: thanks
A [ne_roman]: Swagat cha, Ramesh!
C [signal exp=roman]: eSewa ma pani hunxa?
A [ne_roman]: Ho — eSewa pani tirna milcha. Hami cash, eSewa, ra Khalti sabai accept garchau.
C [neutral exp=roman]: ok done
A [ne_roman]: Thik cha.
C [neutral exp=roman]: dhanyabad
A [ne_roman]: Swagat cha!
```

### D1-long-roman — arm `hybrid` (rep 0)
```
C [signal exp=roman]: namaste, dental clinic ma teeth cleaning garna paryo, kati parcha?
A [ne_roman]: Namaste! Teeth Cleaning ko price NPR 1500 ho, ra karib 30 minute lagcha. Booking garna mancha?
C [signal exp=roman]: ani kati time lagcha?
A [ne_roman]: Teeth Cleaning karib 30 minute lagcha.
C [signal exp=roman]: ok. weekend ma khula huncha?
A [ne_roman]: Haina — weekend (Saturday ra Sunday) hami bandha huncha. Hafta ko dinharu Monday–Friday 9:00 AM dekhi 6:00 PM samma khula cha. Booking garna mancha?
C [signal exp=roman]: hunxa. ani sombar ko lagi slot cha?
A [ne_roman]: Thik cha — sombar (2026-09-21) ko Teeth Cleaning ko slot herchu.
C [neutral exp=roman]: 10am
A [ne_roman]: Thik cha — 10:00 AM ko slot herchu.
C [signal exp=roman]: malai 10:30 ma milcha ki?
A [ne_roman]: Thik cha — 10:30 ko slot herchu.
C [neutral exp=roman]: ok
A [ne_roman]: Thik cha.
C [signal exp=roman]: mero naam Ramesh ho, phone 9812345678
A [ne_roman]: Dhanyabad Ramesh — tapaiko naam ra phone paaye.
C [signal exp=roman]: cash le tirna milcha?
A [ne_roman]: Ho — cash le tirna milcha; eSewa ra Khalti pani available chan.
C [neutral exp=roman]: thanks
A [ne_roman]: Swagat cha 😊
C [signal exp=roman]: eSewa ma pani hunxa?
A [ne_roman]: Ho — eSewa pani chalcha. Khalti ra cash pani available chan.
C [neutral exp=roman]: ok done
A [ne_roman]: Thik cha.
C [neutral exp=roman]: dhanyabad
A [ne_roman]: Swagat cha 😊
```

### HD1-long-english-trek — arm `pre25` (rep 0)
```
C [signal exp=en]: Hello! Could you tell me what treks you offer?
A [en]: Hi — we offer three treks: Poon Hill Trek (USD 450, 5 days), Everest Base Camp Trek (USD 1400, 14 days), and Day Hike Nagarkot (USD 60, 1 day). Permits are arranged by us and included in the price; a 30% deposit confirms a booking and you’ll receive a full refund if cancelled 14 or more days before departure. Would you like details or availability for any of these?
C [signal exp=en]: How hard is the Poon Hill trek?
A [en]: I don’t have details about the Poon Hill trek’s difficulty in the information available to me. Would you like me to connect you with a team member who can explain difficulty, daily hiking hours, elevation gain, and fitness requirements — or tell me which specific details you want (e.g., walking hours, altitude, terrain)?
C [neutral exp=en]: ok
A [en]: Great — would you like me to connect you with a team member to explain the trek’s difficulty, daily hiking hours, elevation gain, and fitness requirements, or tell me which specific details you’d like (walking hours, altitude, terrain)?
C [signal exp=en]: And Everest Base Camp?
A [en]: If you mean its difficulty: I don’t have detailed difficulty info available here. We do offer the Everest Base Camp Trek (USD 1400, 14 days). Would you like me to connect you with a team member to explain difficulty, daily hiking hours, elevation gain, and fitness requirements — or tell me which specific details you want (walking hours, altitude, terrain)?
C [signal exp=en]: that's a lot of days. what does the price include?
A [en]: From the information I have: the listed price includes the trekking permits (we arrange those). Our booking requires a 30% deposit to confirm, and you get a full refund if cancelled 14 or more days before departure. I don’t have the full breakdown of other inclusions (meals, accommodation, guides, transport, etc.) here — would you like me to connect you with a team member to confirm exactly what’s included, and for which trek (Poon Hill or Everest Base Camp)?
C [neutral exp=en]: I see
A [en]: Got it — would you like me to connect you with a team member to go over difficulty and what’s included, or shall I check availability/pricing for a specific trek? If the latter, which trek (Poon Hill, Everest Base Camp, Day Hike Nagarkot) and any dates you have in mind?
C [signal exp=en]: Can I pay a deposit first?
A [en]: Yes — a 30% deposit is required to confirm a booking. If you cancel 14 or more days before departure you’ll receive a full refund. Would you like to pay now? If so, which trek and departure date should I note, or would you prefer I connect you with a team member to process the payment?
C [signal exp=en]: okay, and how much is the deposit for Poon Hill?
A [en]: The deposit is 30% of the trek price — for Poon Hill (USD 450) that’s USD 135. Would you like to pay the deposit now or shall I connect you with a team member to process it? If you want to pay, what departure date should I note?
C [neutral exp=en]: thanks
A [en]: You’re welcome! If you’d like to pay the USD 135 deposit for Poon Hill, tell me your preferred departure date and I can connect you with a team member to process the payment. Or I can help with any other questions you have.
C [signal exp=en]: What months are best?
A [en]: I don’t have information here about which months are best for the treks. Would you like me to connect you with a team member to recommend the best months and seasonal conditions? If so, which trek are you asking about — Poon Hill, Everest Base Camp, or Day Hike Nagarkot?
```

### HD1-long-english-trek — arm `prod` (rep 0)
```
C [signal exp=en]: Hello! Could you tell me what treks you offer?
A [en]: Hi! We offer these treks: Poon Hill Trek — USD 450 (5 days); Everest Base Camp Trek — USD 1,400 (14 days); and Day Hike Nagarkot — USD 60 (1 day). Trekking permits are arranged by us and included in the price; a 30% deposit confirms bookings and you get a full refund if you cancel 14 or more days before departure.
C [signal exp=en]: How hard is the Poon Hill trek?
A [en]: I don't have the trek's difficulty details in our info here. Our team can explain the trail grade, daily walking time, altitude gain, and fitness needed — would you like me to connect you with them?
C [neutral exp=en]: ok
A [en]: Great — I can connect you with our team. Which do you prefer: phone, email, or WhatsApp?
C [signal exp=en]: And Everest Base Camp?
A [en]: The Everest Base Camp Trek is USD 1,400 and lasts 14 days. I don't have the trek's difficulty details here — our team can explain trail grade, daily walking times, altitude gain, and fitness needed. I can connect you with them — which do you prefer: phone, email, or WhatsApp?
C [signal exp=en]: that's a lot of days. what does the price include?
A [en]: For the Everest Base Camp Trek the price includes trekking permits — we arrange those. I don't have the full list of inclusions here; would you like me to connect you with our team by phone, email, or WhatsApp so they can give a complete breakdown?
C [neutral exp=en]: I see
A [en]: Got it. Would you like me to connect you with our team by phone, email, or WhatsApp for full details on inclusions and difficulty?
C [signal exp=en]: Can I pay a deposit first?
A [en]: Yes — a 30% deposit confirms a booking. If you'd like to pay the deposit now, which do you prefer: phone, email, or WhatsApp?
C [signal exp=en]: okay, and how much is the deposit for Poon Hill?
A [en]: The deposit is 30% of the trek price — for Poon Hill Trek (USD 450) that’s USD 135.
C [neutral exp=en]: thanks
A [en]: You're welcome! 😊
C [signal exp=en]: What months are best?
A [en]: I don't have seasonal/best-month details in our info here — our team can tell you the best months for each trek. Would you like me to connect you with them by phone, email, or WhatsApp?
```

### HD1-long-english-trek — arm `hybrid` (rep 0)
```
C [signal exp=en]: Hello! Could you tell me what treks you offer?
A [en]: Hi — we offer these treks:
- Poon Hill Trek — USD 450, 5 days
- Everest Base Camp Trek — USD 1400, 14 days
- Day Hike Nagarkot — USD 60, 1 day
Note: a 30% deposit is needed to confirm a booking; full refund if cancelled 14+ days before departure; trekking permits are arranged by us and included. Would you like more details or availability for any of these?
C [signal exp=en]: How hard is the Poon Hill trek?
A [en]: Good question — I don't have the Poon Hill trek's difficulty details in our notes here. Would you like me to connect you with our trekking team so they can give trail difficulty, daily hiking hours, altitude gain, and fitness recommendations?
C [neutral exp=en]: ok
A [en]: Great — would you like our trekking team to contact you by phone or email? Please share the best number or email address for them to reach you.
C [signal exp=en]: And Everest Base Camp?
A [en]: We don't have Everest Base Camp's difficulty details here either. Want our trekking team to contact you with trail difficulty, daily hiking hours, altitude gain, and fitness recommendations? If yes, please say phone or email and share the best number or address.
C [signal exp=en]: that's a lot of days. what does the price include?
A [en]: Good question — our notes show that trekking permits are arranged by us and included in the price. A 30% deposit is needed to confirm a booking, and we offer a full refund if cancelled 14 or more days before departure. I don't have the full list of inclusions here — would you like me to connect you with our trekking team so they can send the complete inclusions?
C [neutral exp=en]: I see
A [en]: Got it. If you'd like full trip details (daily itinerary, difficulty, inclusions), should our trekking team contact you by phone or email? Please share the best number or email.
C [signal exp=en]: Can I pay a deposit first?
A [en]: Yes — a 30% deposit is required to confirm a booking. Would you like our trekking team to contact you to arrange the deposit by phone or email? Please share the best number or email.
C [signal exp=en]: okay, and how much is the deposit for Poon Hill?
A [en]: The deposit is 30% of USD 450 — that’s USD 135. Would you like our trekking team to contact you to arrange the deposit (phone or email)?
C [neutral exp=en]: thanks
A [en]: You're welcome!
C [signal exp=en]: What months are best?
A [en]: I don't have seasonal/month recommendations in our notes. Which trek do you mean — Poon Hill, Everest Base Camp, or Day Hike Nagarkot? I can have our trekking team send the best months and seasonal details once you tell me which one.
```

## Probes (limits of the design)


### P1-en-then-short-roman-question — arm `prod` (rep 0)
```
C [signal exp=en]: Hi, how much is a teeth cleaning?
A [en]: A Teeth Cleaning is NPR 1,500 and takes about 30 minutes.
C [probe exp=None]: kati parcha?
A [en]: A Teeth Cleaning costs NPR 1,500 and takes about 30 minutes.
C [probe exp=None]: ani parking cha?
A [en]: Yes — we have on-site parking available.
```

### P1-en-then-short-roman-question — arm `hybrid` (rep 0)
```
C [signal exp=en]: Hi, how much is a teeth cleaning?
A [en]: Teeth Cleaning costs NPR 1500 and takes about 30 minutes.
C [probe exp=None]: kati parcha?
A [en]: Teeth Cleaning costs NPR 1500 and takes about 30 minutes.
C [probe exp=None]: ani parking cha?
A [ne_roman]: Cha, hamro clinic ma on-site parking cha.
```

### P2-deva-then-english-please — arm `prod` (rep 0)
```
C [signal exp=deva]: नमस्ते, सफाइको मूल्य कति हो?
A [ne_deva]: Teeth Cleaning (सफाइ) को मूल्य NPR 1500 हो र करिब 30 मिनेट लाग्छ।
C [explicit exp=en]: English please
A [en]: Sure — switching to English now. How can I help?
C [neutral exp=en]: ok
A [en]: Okay — if you'd like to book a Teeth Cleaning or have any other questions, I can help.
```

### P2-deva-then-english-please — arm `hybrid` (rep 0)
```
C [signal exp=deva]: नमस्ते, सफाइको मूल्य कति हो?
A [ne_deva]: Teeth Cleaning (सफाइ) को मूल्य NPR 1500 हो र करिब 30 मिनेट लाग्छ।
C [explicit exp=en]: English please
A [en]: Sure — I’ll reply in English from now on. For reference: Teeth Cleaning costs NPR 1500 and takes about 30 minutes. Would you like to book an appointment?
C [neutral exp=en]: ok
A [en]: Great — let me check availability.
```

### P3-en-then-one-roman-word — arm `prod` (rep 0)
```
C [signal exp=en]: Hi, how much is a teeth cleaning?
A [en]: Teeth Cleaning is NPR 1500 and usually takes about 30 minutes.
C [probe exp=None]: dhanyabad
A [en]: You're welcome! 😊
C [probe exp=None]: ok
A [en]: Okay — if you'd like to book a Teeth Cleaning or have any other questions, I can help with that.
```

### P3-en-then-one-roman-word — arm `hybrid` (rep 0)
```
C [signal exp=en]: Hi, how much is a teeth cleaning?
A [en]: Teeth Cleaning costs NPR 1500 and takes about 30 minutes. Want me to check available times?
C [probe exp=None]: dhanyabad
A [en]: You're welcome!
C [probe exp=None]: ok
A [en]: Okay — let me check available times.
```