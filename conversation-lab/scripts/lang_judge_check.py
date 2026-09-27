"""Is the (already validated) judge's language_match criterion trustworthy on the NEW multi-turn cases -- a real mid-
conversation switch, neutral turns, within-message mixing? Its rubric says "same language ... and stays there", which
could punish a legitimate follow-the-customer switch. 8 hand-written good/bad pairs (synthetic, labeled), judge x5 at
default effort, NO rubric change. Reports language_match and total score per reply; pass = good beats bad on language_match."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from lab.businesses import facts_text
from lab.judge import ReplyJudge
from lab.llm import configure

configure()
J = ReplyJudge(samples=5)
R = lambda *h: "\n".join(f"{w}: {t}" for w, t in h)
PAIRS = [
    ("switch en->roman", R(("Customer", "Hi, how much is a teeth cleaning?"), ("Assistant", "A Teeth Cleaning is NPR 1500 and takes about 30 minutes.")),
     "malai bholi bihana 10 baje ko slot chahiyo, milcha?",
     "Milcha, bholi 10 baje ko slot khali cha. Tapaiko naam ra phone number dinuhos?",
     "Yes, 10 AM tomorrow is available. Could I have your name and phone number?"),
    ("switch roman->en", R(("Customer", "namaste, cleaning ko price kati ho?"), ("Assistant", "Teeth Cleaning ko price NPR 1500 ho.")),
     "Actually can you tell me if you're open on Sunday?",
     "We're closed on Sunday -- open Monday to Friday, 9 AM to 6 PM.",
     "Sunday ma hami band chau, Monday dekhi Friday samma 9 dekhi 6 samma khula huncha."),
    ("switch roman->deva", R(("Customer", "namaste, cleaning ko price kati ho?"), ("Assistant", "Teeth Cleaning ko price NPR 1500 ho.")),
     "मलाई शनिबार अपोइन्टमेन्ट चाहियो, मिल्छ?",
     "शनिबार हामी बन्द हुन्छौं; सोमबारदेखि शुक्रबारसम्म बिहान ९ देखि साँझ ६ बजेसम्म खुला हुन्छ।",
     "Saturday ma hami band chau, Monday dekhi Friday samma khula huncha."),
    ("neutral 'ok' after Devanagari", R(("Customer", "नमस्ते, सफाइको मूल्य कति हो?"), ("Assistant", "Teeth Cleaning को मूल्य NPR 1500 हो।")),
     "ok", "ठीक छ।", "Alright!"),
    ("neutral 'thanks' after Roman", R(("Customer", "cleaning ko price kati ho?"), ("Assistant", "NPR 1500 ho.")),
     "thanks", "Hunxa!", "You're welcome!"),
    ("within-message mix", "", "malai teeth whitening garna man cha, price kati hola?",
     "Teeth Whitening ko price NPR 6000 ho, ani 45 min jati lagcha.",
     "Teeth whitening costs NPR 6000 and takes about 45 minutes."),
    ("within-message mix vs over-formal", "", "malai teeth whitening garna man cha, price kati hola?",
     "Teeth Whitening ko price NPR 6000 ho, ani 45 min jati lagcha.",
     "दाँत सेतो बनाउने सेवाको शुल्क ६००० रुपैयाँ हो र यसमा ४५ मिनेट लाग्छ।"),
    ("explicit request", R(("Customer", "Hi, how much is a filling?"), ("Assistant", "A Tooth Filling is NPR 2500.")),
     "Can we talk in Nepali from now on?",
     "Pakka, ma Nepali ma kura garna sakchu! Kehi sodhna man lagcha?",
     "Sure! What would you like to know?"),
]
wins = 0
for name, conv, cust, good, bad in PAIRS:
    g = J(cust, good, conversation=conv, facts=facts_text("dental", sandbox_note=False))
    b = J(cust, bad, conversation=conv, facts=facts_text("dental", sandbox_note=False))
    ok = g.criteria["language_match"] > b.criteria["language_match"]
    wins += ok
    print(f"{'PASS' if ok else 'FAIL'}  {name:32} language_match good {g.criteria['language_match']:.1f} vs bad {b.criteria['language_match']:.1f}"
          f"   | total good {g.score:.1f} vs bad {b.score:.1f}")
print(f"language_match pairwise: {wins}/{len(PAIRS)}")
