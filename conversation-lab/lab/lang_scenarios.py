"""Scripted customer conversations for the language experiment. The CUSTOMER turns are fixed; every arm generates its own
assistant turns (so each arm's history is its own). Each customer turn carries an expectation `exp` written BEFORE any run:

  en        reply should be English
  roman     reply should be Romanized Nepali (labeler says ne_roman or mixed)
  deva      reply should be Devanagari Nepali
  mix       Nepali-frame + English words in the customer message  -> reply mixed or ne_roman
  mix_en    English-frame + a few Nepali words                    -> reply en or mixed
  deva_mix  Devanagari + Latin words                              -> reply ne_deva or mixed
  None      unconstrained (a bare first-message greeting: rule 7 allows either language)
kind: what the turn tests -- signal (real language evidence) | neutral (no language evidence: the tiebreak case) |
      switch (real change from earlier turns) | explicit (asks to change language) | mix (within-message code-switch).
Types: A within-message code-switching | B deliberate mid-conversation change | C ambiguous short input (the original
flip-flop) | D long conversation with no real language change.
DEV = used while building/iterating the hybrid (so its numbers are optimistic). HELD = written up-front, NOT looked at until
the hybrid was frozen. Phone numbers/names are obviously fake."""
from dataclasses import dataclass


@dataclass(frozen=True)
class T:
    text: str
    exp: str | None
    kind: str


@dataclass(frozen=True)
class Scenario:
    id: str
    type: str          # A/B/C/D
    biz: str
    turns: tuple
    note: str = ""


def S(id, type_, biz, turns, note=""):
    return Scenario(id, type_, biz, tuple(T(*t) for t in turns), note)


DEV = [
    # ---- A: within-message code-switching (some lines echo real production transcripts: "What app ma vaya hunxa", "K xa")
    S("A1-nepali-frame-english-words", "A", "dental", [
        ("hello, malai teeth whitening garna man cha, price kati hola?", "mix", "mix"),
        ("ok thik cha, but weekend ma open hunxa ki hudaina?", "mix", "mix"),
        ("What app ma vaya hunxa payment?", "mix", "mix"),
        ("Friday 3pm ma slot cha? I have office until 2:30 so late chahiyo", "mix", "mix"),
        ("dhanyabad, very helpful!", "mix", "mix"),
    ], "real-style code-mix throughout"),
    S("A2-english-frame-light-nepali", "A", "dental", [
        ("Hi, I want to book a cleaning, aaja huncha?", "mix_en", "mix"),
        ("ok great, and how long does a root canal take? dherai dukhcha ki?", "mix", "mix"),
        ("Thank you so much, ramro!", "mix_en", "mix"),
    ], "an English writer sprinkling Nepali"),
    S("A3-real-long-roman-message", "A", "dental", [
        ("sunnu na, mero baby ko tooth ali ali fatera dukheko xa, k garne bujhina, first available ma lyaidiye hunxa ki k garne, price kati parxa yesko, ani insurance chalxa ki chaina, ani weekend ma khula hunxa ki nai", "roman", "signal"),
        ("insurance chaina bhane ni hunxa? ok then bholi first slot ma book gardinuhos plz", "mix", "mix"),
    ], "adapted from the real long transcript in PHASE_STATUS.md"),
    S("A4-devanagari-plus-english-words", "A", "dental", [
        ("मलाई tomorrow को appointment चाहियो, cleaning को लागि", "deva_mix", "mix"),
        ("morning मा slot छ? maybe 10am वा 11am", "deva_mix", "mix"),
        ("ठीक छ, thank you", "deva_mix", "mix"),
    ], "two scripts inside one message"),

    # ---- B: deliberate, real language change mid-conversation
    S("B1-en-to-roman", "B", "dental", [
        ("Hi, how much is a teeth cleaning?", "en", "signal"),
        ("Ok and do you have a slot tomorrow?", "en", "signal"),
        ("malai bholi bihana 10 baje ko slot chahiyo, milcha?", "roman", "switch"),
        ("ani parking cha ki chaina?", "roman", "signal"),
        ("ok", "roman", "neutral"),
        ("Friday", "roman", "neutral"),
    ], "switches without ever asking to"),
    S("B2-roman-to-deva", "B", "dental", [
        ("namaste, dental consultation ko price kati ho?", "roman", "signal"),
        ("ani kati baje samma khula huncha?", "roman", "signal"),
        ("मलाई शनिबार अपोइन्टमेन्ट चाहियो, मिल्छ?", "deva", "switch"),
        ("धन्यवाद", "deva", "signal"),
        ("ok", "deva", "neutral"),
    ]),
    S("B3-deva-to-en", "B", "dental", [
        ("नमस्ते, दाँत सफा गर्न कति पर्छ?", "deva", "signal"),
        ("अनि कति बजेसम्म खुला हुन्छ?", "deva", "signal"),
        ("Sorry, my Nepali typing is slow. Can you tell me if you're open on Sunday and how long a whitening takes?", "en", "switch"),
        ("great, and is there parking?", "en", "signal"),
        ("thanks", "en", "neutral"),
    ]),
    S("B4-explicit-to-english", "B", "dental", [
        ("namaste, teeth cleaning ko price kati ho?", "roman", "signal"),
        ("ani root canal ko?", "roman", "signal"),
        ("Can we just switch to English please?", "en", "explicit"),
        ("2", "en", "neutral"),
        ("ok", "en", "neutral"),
    ], "production's Phase 25b path"),
    S("B5-explicit-to-nepali", "B", "dental", [
        ("Hi, how much is a filling?", "en", "signal"),
        ("and how long does it take?", "en", "signal"),
        ("Can we talk in Nepali from now on?", "roman", "explicit"),
        ("ok", "roman", "neutral"),
        ("Friday", "roman", "neutral"),
        ("thanks", "roman", "neutral"),
    ], "explicit request, then neutral turns: does it stick?"),
    S("B6-roman-then-sustained-english", "B", "dental", [
        ("namaste, cleaning ko price kati ho?", "roman", "signal"),
        ("ani root canal ko?", "roman", "signal"),
        ("Okay. Do you accept eSewa or Khalti for payment?", "en", "switch"),
        ("And what are your hours on Friday?", "en", "signal"),
        ("Can I book for next Tuesday afternoon?", "en", "signal"),
        ("ok thanks", "en", "neutral"),
    ], "no request; production needs a streak of 3 before it moves"),
    S("B7-customer-alternates", "B", "dental", [
        ("namaste, teeth whitening kati parcha?", "roman", "signal"),
        ("Okay, and how long does it take?", "en", "switch"),
        ("ani weekend ma khula huncha?", "roman", "switch"),
        ("Can I pay by card there?", "en", "switch"),
        ("hunxa hunxa, bholi aauchu", "roman", "switch"),
    ], "STRESS: the customer alternates. Mirroring replies alternate too -- that is the cost, reported honestly"),

    # ---- C: ambiguous short input after an established language (the original flip-flop)
    S("C1-roman-neutral-tokens", "C", "dental", [
        ("Namaste, tapaiko teeth cleaning ko lagi kati parcha?", "roman", "signal"),
        ("ok", "roman", "neutral"),
        ("Friday", "roman", "neutral"),
        ("3pm", "roman", "neutral"),
        ("yes", "roman", "neutral"),
        ("thanks", "roman", "neutral"),
        ("hi", "roman", "neutral"),
    ]),
    S("C2-deva-neutral-tokens", "C", "dental", [
        ("नमस्ते, सफाइको मूल्य कति हो?", "deva", "signal"),
        ("ok", "deva", "neutral"),
        ("Friday", "deva", "neutral"),
        ("3pm", "deva", "neutral"),
        ("yes", "deva", "neutral"),
        ("thanks", "deva", "neutral"),
        ("2", "deva", "neutral"),
    ]),
    S("C3-english-neutral-tokens", "C", "dental", [
        ("Hi, how much is a teeth cleaning?", "en", "signal"),
        ("ok", "en", "neutral"),
        ("Friday", "en", "neutral"),
        ("3pm", "en", "neutral"),
        ("yes", "en", "neutral"),
        ("thanks", "en", "neutral"),
        ("hi", "en", "neutral"),
    ]),
    S("C4-hlo-then-k-xa", "C", "dental", [
        ("hlo", None, "neutral"),
        ("K xa", "roman", "signal"),
        ("malai euta tooth dukheko xa", "roman", "signal"),
        ("ok", "roman", "neutral"),
        ("2", "roman", "neutral"),
        ("thanks", "roman", "neutral"),
    ], "real transcript 28017051 openers"),
    S("C5-roman-with-english-nouns", "C", "dental", [
        ("malai cleaning garna cha", "roman", "signal"),
        ("cleaning", "roman", "neutral"),
        ("tomorrow", "roman", "neutral"),
        ("Monday", "roman", "neutral"),
        ("10am", "roman", "neutral"),
        ("ok thanks", "roman", "neutral"),
    ], "English words that are just nouns/times in a Nepali chat"),

    # ---- D: long conversation, no real language change
    S("D1-long-roman", "D", "dental", [
        ("namaste, dental clinic ma teeth cleaning garna paryo, kati parcha?", "roman", "signal"),
        ("ani kati time lagcha?", "roman", "signal"),
        ("ok. weekend ma khula huncha?", "roman", "signal"),
        ("hunxa. ani sombar ko lagi slot cha?", "roman", "signal"),
        ("10am", "roman", "neutral"),
        ("malai 10:30 ma milcha ki?", "roman", "signal"),
        ("ok", "roman", "neutral"),
        ("mero naam Ramesh ho, phone 9812345678", "roman", "signal"),
        ("cash le tirna milcha?", "roman", "signal"),
        ("thanks", "roman", "neutral"),
        ("eSewa ma pani hunxa?", "roman", "signal"),
        ("ok done", "roman", "neutral"),
        ("dhanyabad", "roman", "neutral"),
    ]),
    S("D2-long-english", "D", "dental", [
        ("Hello, I'd like to know the price of a teeth cleaning.", "en", "signal"),
        ("And how long does it take?", "en", "signal"),
        ("ok", "en", "neutral"),
        ("Are you open on weekends?", "en", "signal"),
        ("Monday then. Do you have anything in the morning?", "en", "signal"),
        ("10am", "en", "neutral"),
        ("yes", "en", "neutral"),
        ("My name is Ramesh, phone 9812345678", "en", "signal"),
        ("Can I pay with eSewa?", "en", "signal"),
        ("thanks", "en", "neutral"),
        ("Is there parking nearby?", "en", "signal"),
        ("great, see you", "en", "neutral"),
    ]),
    S("D3-long-deva", "D", "dental", [
        ("नमस्ते, दाँतको उपचारको मूल्य कति हो?", "deva", "signal"),
        ("अनि कति समय लाग्छ?", "deva", "signal"),
        ("ok", "deva", "neutral"),
        ("आइतबार खुला हुन्छ?", "deva", "signal"),
        ("2", "deva", "neutral"),
        ("धन्यवाद", "deva", "signal"),
        ("thanks", "deva", "neutral"),
        ("बिहान १० बजे मिल्छ?", "deva", "signal"),
    ]),
]

HELD = [
    S("HA1-salon-code-mix", "A", "salon", [
        ("hello didi, haircut ko lagi appointment book garna parne thiyo, but kati parcha?", "mix", "mix"),
        ("ok, beard trim ni chaiyo, with haircut same day ma huncha ki?", "mix", "mix"),
        ("Saturday ma 4pm ma slot cha hola?", "mix", "mix"),
        ("ekdum ramro, thanks!", "mix", "mix"),
    ]),
    S("HA2-trek-english-light-nepali", "A", "trek", [
        ("Hi, I'm interested in Poon Hill, kati din ko hunchha?", "mix_en", "mix"),
        ("nice. and permit ko kura? is it included or do I arrange separately", "mix", "mix"),
        ("Perfect, dhanyabad!", "mix_en", "mix"),
    ]),
    S("HB1-en-to-deva-salon", "B", "salon", [
        ("Hi, what is the price of a haircut?", "en", "signal"),
        ("Do you take walk-ins?", "en", "signal"),
        ("मलाई भोलि बिहान ११ बजे कपाल काट्न मिल्छ?", "deva", "switch"),
        ("अनि दाह्री पनि मिल्छ?", "deva", "signal"),
        ("ok", "deva", "neutral"),
    ]),
    S("HB2-roman-to-en-trek", "B", "trek", [
        ("namaste, Everest Base Camp ko price kati ho?", "roman", "signal"),
        ("ani deposit kati dinu parcha?", "roman", "signal"),
        ("Sorry one more thing, what is your cancellation policy if I need to postpone by a month?", "en", "switch"),
        ("Got it. What are your office hours during the week?", "en", "signal"),
        ("thanks", "en", "neutral"),
    ]),
    # HB3 originally opened "hi, do you do facials? / how much?" -- Azure's content filter rejected that prompt for EVERY arm
    # (false positive, unrelated to language), so no arm produced usable data; topic changed to haircuts, id renamed HB3b.
    S("HB3b-explicit-to-devanagari", "B", "salon", [
        ("hi, do you do haircuts?", "en", "signal"),
        ("how much?", "en", "signal"),
        ("Could you reply in Nepali (Devanagari script) from now on please?", "deva", "explicit"),
        ("ok", "deva", "neutral"),
        ("Sunday", "deva", "neutral"),
    ], "explicit request for a specific script"),
    S("HC1-salon-roman-neutral", "C", "salon", [
        ("Namaste, hair colour garna kati lagcha?", "roman", "signal"),
        ("ok", "roman", "neutral"),
        ("Sunday", "roman", "neutral"),
        ("5pm", "roman", "neutral"),
        ("yes please", "roman", "neutral"),
        ("thank you", "roman", "neutral"),
        ("Yo", "roman", "neutral"),
    ]),
    S("HC2-trek-english-neutral", "C", "trek", [
        ("Hello, how many days is the Poon Hill trek?", "en", "signal"),
        ("ok", "en", "neutral"),
        ("April", "en", "neutral"),
        ("2 people", "en", "neutral"),
        ("haha ok", "en", "neutral"),
        ("thanks", "en", "neutral"),
        ("👍", "en", "neutral"),
    ]),
    S("HC3-salon-deva-neutral", "C", "salon", [
        ("नमस्ते, कपाल काट्ने कति पर्छ?", "deva", "signal"),
        ("ok", "deva", "neutral"),
        ("Saturday", "deva", "neutral"),
        ("hi", "deva", "neutral"),
        ("3", "deva", "neutral"),
        ("thanks", "deva", "neutral"),
    ]),
    S("HD1-long-english-trek", "D", "trek", [
        ("Hello! Could you tell me what treks you offer?", "en", "signal"),
        ("How hard is the Poon Hill trek?", "en", "signal"),
        ("ok", "en", "neutral"),
        ("And Everest Base Camp?", "en", "signal"),
        ("that's a lot of days. what does the price include?", "en", "signal"),
        ("I see", "en", "neutral"),
        ("Can I pay a deposit first?", "en", "signal"),
        ("okay, and how much is the deposit for Poon Hill?", "en", "signal"),
        ("thanks", "en", "neutral"),
        ("What months are best?", "en", "signal"),
    ]),
    S("HD2-long-roman-salon", "D", "salon", [
        ("namaste, haircut ko price kati ho?", "roman", "signal"),
        ("ani beard trim?", "roman", "signal"),
        ("ok", "roman", "neutral"),
        ("walk-in huncha ki appointment nai chahincha?", "roman", "signal"),
        ("Saturday ma khula huncha?", "roman", "signal"),
        ("4pm", "roman", "neutral"),
        ("facial ko chai kati parcha ani kati time lagcha?", "roman", "signal"),
        ("thik cha, thanks", "roman", "neutral"),
        ("eSewa le pay garna milcha?", "roman", "signal"),
        ("ok", "roman", "neutral"),
    ]),
]

# PROBE: descriptive edge cases for the design's known limit (a real switch expressed in <=2 words). exp=None = not scored.
PROBE = [
    S("P1-en-then-short-roman-question", "P", "dental", [
        ("Hi, how much is a teeth cleaning?", "en", "signal"),
        ("kati parcha?", None, "probe"),
        ("ani parking cha?", None, "probe"),
    ], "two Roman-Nepali words in an English chat: short => cannot switch alone; a 3-word one can"),
    S("P2-deva-then-english-please", "P", "dental", [
        ("नमस्ते, सफाइको मूल्य कति हो?", "deva", "signal"),
        ("English please", "en", "explicit"),
        ("ok", "en", "neutral"),
    ], "explicit request in only 2 words"),
    S("P3-en-then-one-roman-word", "P", "dental", [
        ("Hi, how much is a teeth cleaning?", "en", "signal"),
        ("dhanyabad", None, "probe"),
        ("ok", None, "probe"),
    ], "a single Nepali word in an English chat"),
]

ALL = {s.id: s for s in DEV + HELD + PROBE}

if __name__ == "__main__":
    for name, group in (("DEV", DEV), ("HELD", HELD), ("PROBE", PROBE)):
        print(name, len(group), "scenarios,", sum(len(s.turns) for s in group), "turns;",
              {t: sum(1 for s in group if s.type == t) for t in "ABCDP"})
    assert len(ALL) == len(DEV) + len(HELD) + len(PROBE)
