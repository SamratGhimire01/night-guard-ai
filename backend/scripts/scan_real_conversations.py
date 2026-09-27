"""Deterministic pre-scan over every dumped real conversation
(backend/data/regression/real_conversations/*.json). Flags objective, regex-checkable
failure signals so a human/LLM pass can prioritize what to read closely instead of
reading all 578 conversations cold. Pure local file processing -- no DB, no LLM calls.

Usage: python backend/scripts/scan_real_conversations.py
"""

import json
import re
from pathlib import Path

IN_DIR = Path(__file__).resolve().parent.parent / "data" / "regression" / "real_conversations"
OUT_PATH = Path(__file__).resolve().parent.parent / "data" / "regression" / "real_conversations_scan.json"

UUID_RE = re.compile(r"\b[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}\b", re.I)
SNAKE_LEAK_RE = re.compile(r"\b[a-z]+(?:_[a-z]+){1,}\b")
# snake_case words that are legitimate customer/domain vocabulary, not internal-field leaks
SNAKE_ALLOW = {"e_sewa", "e_mail"}
PRICE_RE = re.compile(r"(?:USD|NPR|Rs\.?|\$)\s?([0-9]+(?:[.,][0-9]+)?)")


def scan_conversation(rec: dict) -> dict:
    flags = []
    configured_prices = {round(s["price"], 2) for s in rec["business"]["services"]}

    agent_msgs = [m for m in rec["messages"] if m["sender_type"] == "agent"]
    customer_msgs = [m for m in rec["messages"] if m["sender_type"] == "customer"]

    if not rec["messages"]:
        flags.append({"category": "empty_conversation", "detail": "no messages at all"})
    elif customer_msgs and not agent_msgs:
        flags.append({"category": "no_agent_reply", "detail": "customer messaged but agent never replied"})

    if len(rec["messages"]) > 60:
        flags.append({"category": "unusually_long", "detail": f"{len(rec['messages'])} messages"})

    for m in agent_msgs:
        text = m["content"]

        for uid in UUID_RE.findall(text):
            flags.append({"category": "id_leak", "detail": f"raw UUID in reply: {uid}"})

        for tok in SNAKE_LEAK_RE.findall(text):
            if tok in SNAKE_ALLOW:
                continue
            flags.append({"category": "snake_case_leak", "detail": f"internal-looking token in reply: {tok!r}"})

        words = text.split()
        if len(words) > 90:
            flags.append({"category": "wall_of_text", "detail": f"{len(words)} words in one reply"})

        qmarks = text.count("?")
        if qmarks >= 2:
            flags.append({"category": "multi_question", "detail": f"{qmarks} question marks in one reply"})

        for price_str in PRICE_RE.findall(text):
            try:
                price = round(float(price_str.replace(",", "")), 2)
            except ValueError:
                continue
            if price not in configured_prices and price != 0:
                flags.append(
                    {
                        "category": "price_mismatch",
                        "detail": f"reply states {price_str} which matches no configured service price "
                        f"({sorted(configured_prices)})",
                    }
                )

        if not text.strip():
            flags.append({"category": "empty_agent_reply", "detail": "agent sent an empty message"})

    # repeated identical agent reply back-to-back = possible loop
    for i in range(1, len(agent_msgs)):
        if agent_msgs[i]["content"].strip() and agent_msgs[i]["content"] == agent_msgs[i - 1]["content"]:
            flags.append({"category": "possible_loop", "detail": "identical agent reply sent twice in a row"})

    appt_count = len(rec["appointments_for_this_customer"])
    booking_words = ("book", "appointment", "schedule", "reserve")
    mentions_booking = any(any(w in m["content"].lower() for w in booking_words) for m in customer_msgs)
    if mentions_booking and appt_count == 0 and rec["booking_draft"]["date"]:
        flags.append(
            {
                "category": "booking_incomplete",
                "detail": "customer discussed booking, draft had a date, but no appointment row exists "
                "(may be legitimately abandoned by the customer -- needs a read)",
            }
        )

    return {
        "conversation_id": rec["conversation_id"],
        "business_name": rec["business"]["name"],
        "channel": rec["channel"],
        "created_at": rec["created_at"],
        "message_count": len(rec["messages"]),
        "flags": flags,
    }


def main() -> None:
    files = sorted(IN_DIR.glob("*.json"))
    results = []
    category_counts: dict[str, int] = {}
    for f in files:
        rec = json.loads(f.read_text())
        scanned = scan_conversation(rec)
        if scanned["flags"]:
            results.append(scanned)
            for fl in scanned["flags"]:
                category_counts[fl["category"]] = category_counts.get(fl["category"], 0) + 1

    OUT_PATH.write_text(json.dumps({"flagged_conversations": results, "category_counts": category_counts}, indent=2))
    print(f"scanned={len(files)} flagged={len(results)}")
    for cat, n in sorted(category_counts.items(), key=lambda kv: -kv[1]):
        print(f"  {cat:22s} {n}")
    print(f"written -> {OUT_PATH}")


if __name__ == "__main__":
    main()
