"""LIVE probe (real running backend: real orchestrator + real Azure LLM + real DB) for
Phase 2's style exemplar retrieval/injection/isolation, run against real standing test
tenants across 3 different business_types (dental/trekking/study_abroad).

For each free-text-intent message this prints the customer message, the final reply the
customer actually received, and the retrieved exemplars for that turn (read back out of
the container logs by conversation_id, since the widget response itself doesn't expose
retrieval internals).

Not collected by pytest (no test_ prefix). usage: python live_style_exemplar_probe.py
"""
import json
import subprocess
import time
import urllib.request

BASE = "http://localhost:8010"

DENTAL = "f0ca2a54-d76b-4c48-b727-1b0a0faea4cd"       # Samaj Dental Clinic, business_type=dental
TREKKING = "ebc15cb7-2f66-4471-9f13-e0699dcdcd86"     # Himalayan Trails Trekking Co., business_type=trekking
STUDY_ABROAD = "5f61d5d1-87fb-4447-8698-39008f33a4e9"  # Everest Pathways Consultancy, business_type=study_abroad


def post(business_id: str, content: str) -> dict:
    body = json.dumps({"content": content}).encode()
    req = urllib.request.Request(
        f"{BASE}/api/v1/widget/{business_id}/messages", body, {"Content-Type": "application/json"}
    )
    with urllib.request.urlopen(req, timeout=120) as r:
        return json.load(r)


def docker_logs_since(seconds: int) -> str:
    result = subprocess.run(
        ["docker", "logs", "--since", f"{seconds}s", "night_guard_ai-backend-1"],
        capture_output=True, text=True, timeout=30,
    )
    return result.stdout + result.stderr


def run_case(label: str, business_id: str, content: str) -> None:
    print(f"\n=== {label} ===")
    print(f"CUSTOMER: {content}")
    t0 = time.time()
    out = post(business_id, content)
    elapsed = time.time() - t0
    print(f"intent: {out.get('intent')}")
    print(f"AGENT (final, post-guard): {out['response']}")
    time.sleep(0.5)  # let the log line flush before we grep for it
    logs = docker_logs_since(int(elapsed) + 5)
    for line in logs.splitlines():
        if "style exemplar retrieval" in line:
            print(f"RETRIEVAL LOG: {line.strip()}")


CASES = [
    ("dental / en / general_question", DENTAL, "Hi, do you guys take walk-ins or do I need an appointment?"),
    ("dental / ne_deva / pricing_question", DENTAL, "रूट क्यानल गर्न कति लाग्छ?"),
    ("dental / ne_roman / service_question", DENTAL, "scaling ra polishing ma k farak huncha, ali explain garnu na"),
    ("dental / mixed / pricing_question", DENTAL, "Hajur, teeth cleaning ko price kati ho, aru kunai discount xa?"),

    ("trekking / en / general_question", TREKKING, "Do I need a guide for a short trek or can I go on my own?"),
    ("trekking / ne_deva / pricing_question", TREKKING, "गाइड बुकिङको लागि कति खर्च लाग्छ?"),
    ("trekking / ne_roman / service_question", TREKKING, "gear rental ma k k items milxa, tent samet huncha ki hudaina?"),
    ("trekking / mixed / general_question", TREKKING, "Namaste, trek season kahile best huncha, monsoon ma jana milxa?"),

    ("study_abroad / en / general_question", STUDY_ABROAD, "What's the difference between a document evaluation and the application review service?"),
    ("study_abroad / ne_deva / pricing_question", STUDY_ABROAD, "भिसा इन्टरभ्यू तयारीको शुल्क कति हो?"),
    ("study_abroad / ne_roman / service_question", STUDY_ABROAD, "SOP लेख्न कति समय लाग्छ, aru kehi documents chai chaine ho?"),
    ("study_abroad / mixed / pricing_question", STUDY_ABROAD, "Hajur, initial counseling session ko lagi kati tirnu parxa?"),
]

for label, business_id, content in CASES:
    run_case(label, business_id, content)

print("\n\n########## SLOT-LEAK PROVOCATION ##########")
run_case(
    "dental / slot-leak bait: vague enough that a model paraphrasing toward an exemplar's "
    "{PRICE}/{TIME} wording is plausible",
    DENTAL,
    "roughly how much does stuff usually cost here and how long does a typical visit take?",
)

print("\n\n########## DISPATCH-BRANCH CONTROL (ne_roman booking) ##########")
run_case(
    "dental / ne_roman / booking dispatch (must be the deterministic template, unaffected by exemplars)",
    DENTAL,
    "Bholi 2 baje teeth cleaning ko lagi book garna sakinxa?",
)
