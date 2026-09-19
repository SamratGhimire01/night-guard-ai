"""The CURRENT production conversation prompt, read from backend/app/services/conversation/intent.py.

READ-ONLY: the template string is pulled out with `ast` (nothing from backend/ is imported or executed, nothing is
written), so it always reflects whatever intent.py currently says. Two things are built from it:
  * ProductionReceptionist -- the full production system prompt + a user prompt laid out like intent._build_user_prompt,
    one LLM call, parse the JSON `response` (same fence-stripping / raw-text fallback as intent._parse_response).
  * RULES_INSTRUCTION -- only the reply-STYLE rules (0-6, 13, 16, 17 verbatim; rule 7 condensed by me) as a plain
    instruction, the optimizer's starting point (the full prompt is ~10k tokens of booking/JSON-extraction rules that
    have nothing to do with how a reply reads).
Not replicated (documented limitation): the orchestrator's deterministic templates/overrides (booking confirmations,
contact gate, off_topic static decline, handoff addenda), the language lock, and real knowledge retrieval."""
import ast
import json
import re
from pathlib import Path

from lab.businesses import BUSINESSES

_BACKEND = Path(__file__).resolve().parents[2] / "backend" / "app"
_DAYS = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"]


def _template() -> str:
    tree = ast.parse((_BACKEND / "services/conversation/intent.py").read_text())
    return next(n.value.value for n in tree.body
                if isinstance(n, ast.Assign) and getattr(n.targets[0], "id", "") == "_SYSTEM_PROMPT_TEMPLATE")


def _intents() -> list[str]:
    text = (_BACKEND / "schemas/conversation.py").read_text()
    body = text[text.index("class ConversationIntent"):]
    body = body[: body.index("\nclass ", 1)]
    return re.findall(r'^\s+[A-Z_]+ = "([a-z_]+)"', body, re.M)


TEMPLATE = _template()


def _rules() -> dict[int, str]:
    body = TEMPLATE[TEMPLATE.index("Rules you must always follow:"):]
    parts = re.split(r"(?m)^(\d+)\. ", body)
    return {int(parts[i]): parts[i + 1].rstrip() for i in range(1, len(parts) - 1, 2)}


_RULE7 = ("Write `response` in the same language and script as the customer's current message -- English, Devanagari "
          "Nepali, Romanized Nepali, or a natural Nepali/English code-mix -- and stay in it; never drift between them. "
          "When writing Romanized Nepali, write the way the customer actually writes it: natural spoken contractions "
          "like \"cha,\" \"xa,\" \"huncha,\" \"hunxa,\" \"garna paryo,\" \"gardim,\" \"milcha,\" \"bholi,\" \"aile\" -- never "
          "silently upgrade it into full formal Devanagari-style vocabulary. English service names or numbers mixed "
          "into a Romanized-Nepali sentence should get the same natural mix back. Example: customer \"doctor ko "
          "appointment kati baje samma huncha?\" -> \"Appointment ko lagi 6 baje samma slot available huncha,\" not a "
          "formally-phrased rewrite of the same fact. If the customer explicitly asks to switch language, switch "
          "immediately, yourself.")


def _build_rules_instruction() -> str:
    r = _rules()
    parts = [
        "You are the customer-facing AI assistant for the business named in `business_name` (described in "
        "`business_facts`). You are standing in for a good human receptionist -- not a generic chatbot. Tone: warm, "
        "concise, and professional. Write ONLY the reply text to send to the customer. Wherever the rules below say "
        "<business_name>, write the exact value of `business_name` (e.g. in the off-topic decline sentence) -- never "
        "'this business', 'the clinic' or another paraphrase.",
        "Rules you must always follow:",
    ]
    for n in (0, 1, 2, 3, 4, 5, 6):
        parts.append(f"{n}. {r[n]}")
    parts.append(f"7. {_RULE7}")
    for n in (13, 16, 17):
        parts.append(f"{n}. {r[n]}")
    return "\n".join(parts).replace("{business_name}", "<business_name>")


RULES_INSTRUCTION = _build_rules_instruction()


def system_prompt(biz: str, template: str | None = None) -> str:
    b = BUSINESSES[biz]
    return (template or TEMPLATE).format(business_name=b["name"], business_description=f", a {b['type']}",
                           tone="warm, concise, and professional", intent_list=", ".join(_intents()))


def user_prompt(item) -> str:
    b = BUSINESSES[item.biz]
    hours = "\n".join(
        f"- {d}: {b['hours'][d][0]} - {b['hours'][d][1]}" if d in b["hours"] else f"- {d}: Closed" for d in _DAYS)
    services = "\n".join(f"- {n} ({b['currency']} {p}, {d})" for n, p, d in b["services"])
    if b["policies"]:
        services += "\n" + "\n".join(f"(policy) {p}" for p in b["policies"])  # sandbox stand-in for the knowledge base
    parts = []
    if item.history:
        parts.append("Recent conversation:\n" + "\n".join(f"{'CUSTOMER' if w == 'Customer' else 'AGENT'}: {t}" for w, t in item.history))
    parts.append("Retrieved knowledge:\n" + (f"- (Business notes, similarity=0.90): {item.note}" if item.note
                                             else "No relevant knowledge found for this query."))
    parts.append("Today's date: 2026-09-19 (Saturday)")
    parts.append(f"Business hours:\n{hours}")
    parts.append(f"Available services:\n{services}")
    parts.append(f"New customer message to respond to:\n{item.customer}")
    return "\n\n".join(parts)


def parse_response(raw: str) -> str:
    text = raw.strip()
    if text.startswith("```"):
        text = text.strip("`").strip()
        if text.lower().startswith("json"):
            text = text[4:].strip()
    try:
        return (json.loads(text).get("response") or "").strip() or text
    except (json.JSONDecodeError, AttributeError):
        return text  # production falls back to the raw text too


def production_reply(item, lm, template: str | None = None) -> str:
    """template: an in-memory patched copy of TEMPLATE for what-if tests (intent.py itself is never modified)."""
    out = lm(messages=[{"role": "system", "content": system_prompt(item.biz, template)},
                       {"role": "user", "content": user_prompt(item)}])
    return parse_response(out[0] if isinstance(out, list) else out)
