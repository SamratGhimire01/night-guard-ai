"""DEV-ONLY probe set for refining `no_reflexive_question` (L4). Used for iteration, never as held-out.
Distinguishes (a) a SPECIFIC on-topic redirect after a decline (the production decline sentence -- fine) from
(b) a GENERIC content-free tail ("anything else I can help with?") bolted onto a complete answer (penalized).
`good`/`bad` labels are by the production rules (intent.py rule 0 decline wording; rule 3 forbids the generic tail).
All synthetic, written by me; the decline wording is the verbatim production sentence with the business name filled in."""
DENTAL = "Business: Demo Dental Clinic, Monday-Friday 9:00 AM-6:00 PM. Services: Teeth Cleaning (NPR 1500), Root Canal (NPR 9000)."
SALON = "Business: Demo Hair Salon, every day 9:00 AM-8:00 PM. Services: Haircut (NPR 600, 30 min); Facial (NPR 1800)."
TREK = "Business: Demo Himalayan Treks, Sunday-Friday 10:00 AM-6:00 PM. Services: Poon Hill Trek (USD 450, 5 days)."


def _decline(name, what):
    return f"I'm just here to help with things related to {name} — {what}. Is there something about that I can help with?"


GROUPS: list[dict] = [
    {"id": "dev-decline-pm", "kind": "synthetic", "customer": "Who is the prime minister of Nepal?", "facts": DENTAL, "replies": [
        ("good", _decline("Demo Dental Clinic", "appointments, services, hours, and the like"), "verbatim production decline shape"),
        ("bad", "The current prime minister changes with coalitions, but recent governments have been led by senior party leaders. Anything else I can help you with?", "answers the off-topic question")]},
    {"id": "dev-decline-joke", "kind": "synthetic", "customer": "tell me a joke", "facts": SALON, "replies": [
        ("good", _decline("Demo Hair Salon", "appointments, services, hours, and the like"), "verbatim production decline shape"),
        ("bad", "Why did the barber win the race? He knew all the short cuts! 😄😄", "answers the off-topic request")]},
    {"id": "dev-decline-capital", "kind": "synthetic", "customer": "what is the capital of France?", "facts": TREK, "replies": [
        ("good", _decline("Demo Himalayan Treks", "treks, prices, hours, and the like"), "verbatim production decline shape"),
        ("bad", "The capital of France is Paris. Is there anything else I can help you with?", "answers + generic tail")]},
    {"id": "dev-decline-phone", "kind": "synthetic", "customer": "which phone should I buy, iPhone or Samsung?", "facts": DENTAL, "replies": [
        ("good", _decline("Demo Dental Clinic", "appointments, services, hours, and the like"), "verbatim production decline shape"),
        ("bad", "Both are great! iPhones are smoother, Samsung has more customization. Let me know if you need anything else!", "answers + generic tail")]},
    {"id": "dev-decline-bitcoin", "kind": "synthetic", "customer": "what's the bitcoin price today?", "facts": TREK, "replies": [
        ("good", _decline("Demo Himalayan Treks", "treks, prices, hours, and the like"), "verbatim production decline shape"),
        ("bad", "Bitcoin is trading around $60,000 today, though it moves a lot during the day.", "answers the off-topic question")]},
    {"id": "dev-decline-homework", "kind": "synthetic", "customer": "can you help me with my maths homework", "facts": DENTAL, "replies": [
        ("good", _decline("Demo Dental Clinic", "appointments, services, hours, and the like"), "verbatim production decline shape"),
        ("bad", "Of course! Send me the question and I'll walk you through the steps.", "agrees to the off-topic request")]},
    {"id": "dev-decline-match", "kind": "synthetic", "customer": "who will win the match tonight?", "facts": SALON, "replies": [
        ("good", _decline("Demo Hair Salon", "appointments, services, hours, and the like"), "verbatim production decline shape"),
        ("bad", "Hard to say, but the home team looks stronger on form. Should be a good game!", "answers the off-topic question")]},
    {"id": "dev-decline-recipe", "kind": "synthetic", "customer": "momo ko recipe deu na", "facts": TREK, "replies": [
        ("good", _decline("Demo Himalayan Treks", "treks, prices, hours, and the like"), "verbatim production decline shape"),
        ("bad", "Ma momo ko recipe dinchu: maida, keema, pyaj, adhuwa, lasun milayera filling banaunus, ani steam garnus.", "gives the recipe")]},
    {"id": "dev-decline-color", "kind": "synthetic", "customer": "what's your favourite colour?", "facts": DENTAL, "replies": [
        ("good", _decline("Demo Dental Clinic", "appointments, services, hours, and the like"), "verbatim production decline shape"),
        ("bad", "I love a calm blue! What's yours?", "chats off-topic")]},
    {"id": "dev-decline-translate", "kind": "synthetic", "customer": "translate 'hello' into Japanese", "facts": SALON, "replies": [
        ("good", _decline("Demo Hair Salon", "appointments, services, hours, and the like"), "verbatim production decline shape"),
        ("bad", "'Hello' in Japanese is 'konnichiwa' (こんにちは).", "answers the off-topic request")]},
    {"id": "dev-tail-hours", "kind": "synthetic", "customer": "open cha?", "facts": DENTAL, "replies": [
        ("good", "Cha — Somabar dekhi Sukrabar, 9:00 AM–6:00 PM samma khula cha.", "complete answer, stops"),
        ("bad", "Cha — Somabar dekhi Sukrabar, 9:00 AM–6:00 PM samma khula cha. Is there anything else I can help you with?", "generic content-free tail")]},
    {"id": "dev-tail-price", "kind": "synthetic", "customer": "haircut kati parcha?", "facts": SALON, "replies": [
        ("good", "Haircut NPR 600 parcha, 30 minute lagcha.", "complete answer, stops"),
        ("bad", "Haircut NPR 600 parcha, 30 minute lagcha. Please feel free to let me know if you have any other questions or need anything else!", "generic content-free tail")]},
    {"id": "dev-tail-english", "kind": "synthetic", "customer": "How long is the Poon Hill trek?", "facts": TREK, "replies": [
        ("good", "Poon Hill is 5 days.", "complete answer, stops"),
        ("bad", "Poon Hill is 5 days. Anything else I can help you with today?", "generic content-free tail")]},
    {"id": "dev-redirect-real-next-step", "kind": "synthetic", "customer": "I want a facial", "facts": SALON, "replies": [
        ("good", "Sure — which day works for you?", "specific, needed next-step question (fine)"),
        ("bad", "Sure. Is there anything else I can help you with?", "generic tail instead of the real next step")]},
]
