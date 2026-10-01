"""Conversation simulator: plays scripted customers (scenarios.py) against many kinds of business (businesses.py)
through the REAL conversation engine and scores every reply the way a native reader would.

A reply is OK when the native lint finds nothing, every scripted check passes, and -- if an LLM judge is given --
the yes/no checklist passes (same threshold the native calibration set). The headline number is the share of OK
replies; the stricter one is the share of conversations where EVERY reply was OK (what a customer actually feels).

Real DB, real LLM, costs money -- run it like the other live evals, inside the backend container:

    docker exec -e PYTHONPATH=/app night_guard_ai-backend-1 python -m tests.eval.simulator.run \
        --judges hybrid:gemini/gemini-3.1-flash-lite --out tests/eval/simulator/results/run_$(date +%F).json

    # quick, free judge (lint + checks only), 2 businesses per scenario
    ... python -m tests.eval.simulator.run --per-scenario 2

    # before/after: compare two saved runs
    ... python -m tests.eval.simulator.run compare results/before.json results/after.json

Every business is created as "SIM <name>" and deleted (with everything under it) at the end, even on errors."""

import argparse
import json
import sys
import time as time_mod
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, time
from decimal import Decimal
from pathlib import Path

from tests.eval.nepali_judge import engine, lint as lint_mod
from tests.eval.nepali_judge.calibrate import NATIVE_OK_CHECKLIST, Cache, parse_spec
from tests.eval.nepali_judge import judges as judge_mod
from tests.eval.simulator.businesses import BUSINESSES, BY_KEY
from tests.eval.simulator.checks import run_check
from tests.eval.simulator.scenarios import BY_ID, SCENARIOS, fill

SIM_PREFIX = "SIM "
# Intents whose reply is the model's own text; every other intent's reply is a fixed template (booking, cancel, status,
# hours, off-topic...). Mirrors orchestrator._VOICE_PASS_INTENTS (+ human_handoff: model text + a template addendum).
LLM_INTENTS = {"greeting", "general_question", "service_question", "pricing_question", "location", "complaint",
               "follow_up", "unknown", "human_handoff"}


def source_of(turn: dict) -> str:
    """"llm" or "template" -- where the reply text came from (a template reply can't be fixed by a better prompt)."""
    return "llm" if turn.get("intent") in LLM_INTENTS else "template"
RESULTS_DIR = Path(__file__).with_name("results")


# --- pairing ----------------------------------------------------------------------------------------------------------


def plan(scenario_ids: list[str] | None, business_keys: list[str] | None, per_scenario: int) -> list[tuple[str, str]]:
    """(scenario_id, business_key) pairs. By default every scenario runs on `per_scenario` businesses, rotating so all
    businesses get used about equally; per_scenario=0 = every scenario on every business."""
    scenarios = [BY_ID[s] for s in scenario_ids] if scenario_ids else SCENARIOS
    businesses = [BY_KEY[b] for b in business_keys] if business_keys else BUSINESSES
    pairs = []
    for i, s in enumerate(scenarios):
        if per_scenario <= 0 or per_scenario >= len(businesses):
            chosen = businesses
        else:
            chosen = [businesses[(i * per_scenario + j) % len(businesses)] for j in range(per_scenario)]
        pairs += [(s["id"], b["key"]) for b in chosen]
    return pairs


# --- scoring ------------------------------------------------------------------------------------------------------------


def score_turn(reply: str, customer: str, history: list[dict], locked: str | None, business: dict, checks: list[str],
               judges: dict, cache) -> dict:
    findings = lint_mod.lint(reply, customer, history, locked_language=locked)
    failed = [f"{c}: {why}" for c in checks if (why := run_check(c, reply, business))]
    result = {
        "lint": [f"{f.code} ({f.detail})" for f in findings],
        "checks": failed,
        "checklist": None,
        "checklist_no": [],
    }
    ok = not findings and not failed
    if judges:
        c = engine.checklist(reply, customer, judges, history=history, locked_language=locked, cache=cache)
        if c.errors and not c.raw:
            result["judge_error"] = next(iter(c.errors.values()))
        else:
            result["checklist"] = round(c.score, 3)
            result["checklist_no"] = [q for q, v in c.answers.items() if v < 0.5]
            ok = ok and c.score >= NATIVE_OK_CHECKLIST
    result["ok"] = ok
    return result


def summarize(records: list[dict]) -> dict:
    """Share of OK replies overall and per business type / situation / language / defect, plus clean conversations."""
    turns = [(r, t) for r in records for t in r["turns"] if "error" not in t]
    by = defaultdict(lambda: [0, 0])

    def add(bucket, ok):
        by[bucket][0] += ok
        by[bucket][1] += 1

    defects = defaultdict(int)
    for r, t in turns:
        add("all", t["ok"])
        add("business:" + r["business"], t["ok"])
        add("situation:" + r["situation"], t["ok"])
        add("lang:" + r["lang"], t["ok"])
        src = source_of(t)
        add("source:" + src, t["ok"])
        add(f"intent:{t.get('intent')}", t["ok"])
        for f in t["lint"]:
            defects["lint:" + f.split(" ")[0]] += 1
            defects[f"lint:{f.split(' ')[0]}@{src}"] += 1
        for c in t["checks"]:
            defects["check:" + c.split(":")[0]] += 1
            defects[f"check:{c.split(':')[0]}@{src}"] += 1
        for q in t["checklist_no"]:
            defects["judge:" + q] += 1
            defects[f"judge:{q}@{src}"] += 1
    convs = [r for r in records if r["turns"] and all("error" not in t for t in r["turns"])]
    clean = sum(all(t["ok"] for t in r["turns"]) for r in convs)
    errors = sum("error" in t for r in records for t in r["turns"])
    return {
        "buckets": {k: {"ok": v[0], "n": v[1], "pct": round(100 * v[0] / v[1], 1)} for k, v in by.items()},
        "clean_conversations": {"ok": clean, "n": len(convs), "pct": round(100 * clean / len(convs), 1) if convs else None},
        "defects": dict(sorted(defects.items(), key=lambda kv: -kv[1])),
        "errors": errors,
    }


def report(run: dict) -> str:
    s = run["summary"]
    b = s["buckets"]
    allb = b.get("all", {"ok": 0, "n": 0, "pct": 0})
    out = [
        f"# Conversation simulator — {run['started']}",
        "",
        f"Judges: `{run['judges'] or 'lint + checks only'}` · {len(run['records'])} conversations · {allb['n']} replies"
        f" · {s['errors']} engine errors",
        "",
        f"**Replies OK: {allb['pct']}%** ({allb['ok']}/{allb['n']})  ",
        f"**Conversations with every reply OK: {s['clean_conversations']['pct']}%** "
        f"({s['clean_conversations']['ok']}/{s['clean_conversations']['n']})",
        "",
    ]
    for prefix, title in (("source:", "By where the reply came from"), ("situation:", "By situation"),
                          ("intent:", "By intent"), ("business:", "By business"), ("lang:", "By language")):
        rows = sorted(((k[len(prefix):], v) for k, v in b.items() if k.startswith(prefix)), key=lambda kv: kv[1]["pct"])
        out += [f"## {title} (worst first)", "", "| | OK | replies |", "|---|---|---|"]
        out += [f"| {k} | {v['pct']}% | {v['n']} |" for k, v in rows]
        out.append("")
    out += ["## What goes wrong most", "", "| defect | replies |", "|---|---|"]
    out += [f"| {k} | {v} |" for k, v in s["defects"].items() if "@" not in k][:20]
    out += ["", "## Worst replies", ""]
    bad = [(r, t) for r in run["records"] for t in r["turns"] if "error" not in t and not t["ok"]]
    bad.sort(key=lambda rt: (len(rt[1]["lint"]) + len(rt[1]["checks"]) + len(rt[1]["checklist_no"])), reverse=True)
    for r, t in bad[:25]:
        why = "; ".join(t["lint"] + t["checks"] + [f"judge: {q}" for q in t["checklist_no"]])
        out += [f"- **{r['business']} / {r['scenario']}** — customer: `{t['customer']}`",
                f"  - reply: {t['reply']}", f"  - why: {why}"]
    return "\n".join(out) + "\n"


def compare(before: dict, after: dict) -> str:
    out = ["# Simulator: before vs after", "", "| bucket | before | after | change |", "|---|---|---|---|"]
    bb, ab = before["summary"]["buckets"], after["summary"]["buckets"]
    keys = ["all"] + sorted(k for k in set(bb) | set(ab) if k != "all")
    for k in keys:
        x, y = bb.get(k, {}).get("pct"), ab.get(k, {}).get("pct")
        delta = f"{y - x:+.1f}" if x is not None and y is not None else "—"
        out.append(f"| {k} | {x if x is not None else '—'}% | {y if y is not None else '—'}% | {delta} |")
    cb, ca = before["summary"]["clean_conversations"]["pct"], after["summary"]["clean_conversations"]["pct"]
    out += ["", f"Conversations with every reply OK: {cb}% → {ca}%"]
    fixed, broken, same = paired(before, after)
    out += ["", "## Paired (same scenario, business and turn in both runs)", "",
            f"- bad → OK: **{len(fixed)}**  ·  OK → bad: **{len(broken)}**  ·  unchanged: {same}",
            f"- {_sign_test(len(fixed), len(broken))}", ""]
    for title, rows in (("Fixed", fixed), ("Broken", broken)):
        if rows:
            out += [f"### {title} (first 10)", ""]
            for key, b, a in rows[:10]:
                out += [f"- `{key}` customer: `{a['customer']}`", f"  - before: {b['reply']}", f"  - after: {a['reply']}"]
            out.append("")
    if before.get("judges") != after.get("judges"):
        out += ["", f"⚠ different judges: `{before.get('judges')}` vs `{after.get('judges')}` — not like for like."]
    return "\n".join(out) + "\n"


def _turn_index(run: dict) -> dict:
    return {f"{r['scenario']}/{r['business']}/{i}": t for r in run["records"] for i, t in enumerate(r["turns"])
            if "error" not in t}


def paired(before: dict, after: dict) -> tuple[list, list, int]:
    """Replies present in both runs: which flipped bad -> OK, OK -> bad, and how many didn't change. Pairing removes the
    business-to-business noise a per-bucket percentage has with 5-12 replies per bucket."""
    b, a = _turn_index(before), _turn_index(after)
    fixed, broken, same = [], [], 0
    for key in sorted(set(b) & set(a)):
        if b[key]["ok"] == a[key]["ok"]:
            same += 1
        elif a[key]["ok"]:
            fixed.append((key, b[key], a[key]))
        else:
            broken.append((key, b[key], a[key]))
    return fixed, broken, same


def _sign_test(wins: int, losses: int) -> str:
    """Two-sided exact sign test on the flips: is the change more than a coin toss?"""
    from math import comb

    n = wins + losses
    if n == 0:
        return "no reply changed verdict"
    k = min(wins, losses)
    p = min(1.0, 2 * sum(comb(n, i) for i in range(k + 1)) / 2 ** n)
    verdict = "a real difference" if p < 0.05 else "could be noise"
    return f"sign test p = {p:.2f} ({verdict}; needs p < 0.05)"


def analyze(run: dict, defect: str = "not_template", limit: int = 30) -> str:
    """Where one defect comes from: per source and intent, plus examples."""
    rows = [(r, t) for r in run["records"] for t in r["turns"] if "error" not in t]
    hit = [(r, t) for r, t in rows if defect in " ".join(t["lint"] + t["checks"] + t["checklist_no"])]
    out = [f"# `{defect}`: {len(hit)} of {len(rows)} replies", "", "| source | intent | flagged | of |", "|---|---|---|---|"]
    by = defaultdict(lambda: [0, 0])
    for r, t in rows:
        key = (source_of(t), t.get("intent"))
        by[key][1] += 1
        by[key][0] += any(defect in x for x in t["lint"] + t["checks"] + t["checklist_no"])
    for (src, intent), (k, n) in sorted(by.items(), key=lambda kv: -kv[1][0]):
        if k:
            out.append(f"| {src} | {intent} | {k} | {n} |")
    out += ["", "## Examples", ""]
    for r, t in hit[:limit]:
        out += [f"- **{source_of(t)} / {t.get('intent')}** ({r['business']}/{r['scenario']}) customer: `{t['customer']}`",
                f"  - {t['reply']}"]
    return "\n".join(out) + "\n"


# --- live engine ------------------------------------------------------------------------------------------------------


def create_business(db, spec: dict, *, with_knowledge: bool):
    from app.db.models.business import Business, BusinessHours
    from app.db.models.knowledge import KnowledgeDocumentStatus
    from app.db.models.service import Service
    from app.services import knowledge_service

    description = spec["description"] if with_knowledge else f"{spec['description']}. {spec['faq']}"
    business = Business(
        name=SIM_PREFIX + spec["name"], timezone="Asia/Kathmandu", currency="NPR", description=description,
        address=spec["address"], phone=spec["phone"], business_type=spec["business_type"],
        persona_name=spec["persona"], booking_enabled=spec["booking"],
    )
    db.add(business)
    db.flush()
    _CREATED.add(business.id)
    for name, price, minutes, desc in spec["services"]:
        db.add(Service(business_id=business.id, name=name, description=desc or None, price=Decimal(price),
                       duration_minutes=max(minutes, 15)))
    open_t, close_t, closed_days = spec["hours"]
    for day in range(7):
        closed = day in closed_days
        db.add(BusinessHours(business_id=business.id, day_of_week=day, closed=closed,
                             open_time=None if closed else time.fromisoformat(open_t),
                             close_time=None if closed else time.fromisoformat(close_t)))
    db.commit()
    if with_knowledge:
        knowledge_service.create_document(db, business_id=business.id, title="FAQ", content=spec["faq"],
                                          source="simulator", status=KnowledgeDocumentStatus.APPROVED)
    return business


# Businesses THIS process created. Cleanup deletes only these: a test's teardown once deleted every SIM business in
# the shared DB, including the ones a simulator run in another process was still chatting with (2026-10-01).
_CREATED: set = set()


def delete_sim_businesses(db) -> int:
    """Removes the SIM businesses this process created; all tenant tables cascade on business delete."""
    from app.db.models.business import Business

    if not _CREATED:
        return 0
    n = db.query(Business).filter(Business.id.in_(list(_CREATED))).delete(synchronize_session=False)
    db.commit()
    _CREATED.clear()
    return n


def delete_all_sim_businesses(db) -> int:
    """Every SIM business, from any process: the explicit `cleanup` command only (never while a run is going)."""
    from app.db.models.business import Business

    n = db.query(Business).filter(Business.name.like(SIM_PREFIX + "%")).delete(synchronize_session=False)
    db.commit()
    return n


def play(business_id, spec: dict, scenario: dict, judges: dict, cache, n: int) -> dict:
    from app.db.database import SessionLocal
    from app.db.models.conversation import Conversation
    from app.services.channels.base import get_or_create_conversation
    from app.services.conversation.orchestrator import handle_incoming_message

    db = SessionLocal()
    record = {"scenario": scenario["id"], "situation": scenario["situation"], "lang": scenario["lang"],
              "business": spec["key"], "business_type": spec["business_type"], "turns": []}
    history: list[dict] = []
    try:
        conversation = get_or_create_conversation(db, business_id=business_id, channel="website",
                                                  external_ref=f"sim-{scenario['id']}-{n}",
                                                  default_customer_name="Website Visitor")
        for turn in scenario["turns"]:
            customer = fill(turn["say"], spec)
            started = time_mod.monotonic()
            try:
                result = handle_incoming_message(db, conversation_id=conversation.id, business_id=business_id,
                                                 content=customer)
            except Exception as exc:  # noqa: BLE001 -- one broken turn must not stop the run; it's reported
                db.rollback()
                record["turns"].append({"customer": customer, "error": f"{type(exc).__name__}: {exc}"[:300]})
                break
            reply = (result or {}).get("response") or ""
            db.refresh(conversation)
            locked = db.get(Conversation, conversation.id).detected_language
            scored = score_turn(reply, customer, history, locked, spec, turn.get("checks", []), judges, cache)
            intent = (result or {}).get("intent")
            record["turns"].append({"customer": customer, "reply": reply, "locked": locked,
                                    "intent": getattr(intent, "value", intent),
                                    "seconds": round(time_mod.monotonic() - started, 2), **scored})
            history += [{"role": "customer", "text": customer}, {"role": "assistant", "text": reply}]
    finally:
        db.close()
    return record


def _judges(spec: str | None) -> dict:
    if not spec:
        return {}
    mode, names = parse_spec(spec)
    if mode not in ("check", "hybrid"):
        sys.exit("--judges takes one checklist spec, e.g. hybrid:gemini/gemini-3.1-flash-lite")
    return {n: judge_mod.get(n) for n in names}


def main(argv=None) -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("command", nargs="?", default="run", choices=["run", "compare", "analyze", "cleanup"])
    ap.add_argument("paths", nargs="*", help="compare: before.json after.json; analyze: run.json")
    ap.add_argument("--defect", default="not_template", help="analyze: which defect to break down")
    ap.add_argument("--judges", default="", help="checklist judge spec; empty = lint + checks only (free)")
    ap.add_argument("--scenarios", default="", help="comma-separated scenario ids (default all)")
    ap.add_argument("--businesses", default="", help="comma-separated business keys (default all)")
    ap.add_argument("--per-scenario", type=int, default=3, help="businesses per scenario; 0 = all of them")
    ap.add_argument("--workers", type=int, default=4, help="conversations in parallel")
    ap.add_argument("--no-knowledge", action="store_true", help="put the FAQ in the description (no embedding calls)")
    ap.add_argument("--cache", default=str(Path(__file__).parents[1] / "nepali_judge" / "cache.json"))
    ap.add_argument("--out", help="save the run (JSON) here; a .md report is written next to it")
    args = ap.parse_args(argv)

    if args.command == "compare":
        if len(args.paths) != 2:
            sys.exit("compare needs two run JSON files")
        before, after = (json.loads(Path(p).read_text(encoding="utf-8")) for p in args.paths)
        print(compare(before, after))
        return
    if args.command == "analyze":
        if len(args.paths) != 1:
            sys.exit("analyze needs one run JSON file")
        print(analyze(json.loads(Path(args.paths[0]).read_text(encoding="utf-8")), args.defect))
        return

    from app.db.database import SessionLocal

    db = SessionLocal()
    if args.command == "cleanup":
        print(f"deleted {delete_all_sim_businesses(db)} SIM businesses")
        return

    pairs = plan([s for s in args.scenarios.split(",") if s] or None,
                 [b for b in args.businesses.split(",") if b] or None, args.per_scenario)
    judges, cache = _judges(args.judges), Cache(Path(args.cache) if args.cache else None)
    run = {"started": datetime.now(UTC).isoformat(timespec="seconds"), "judges": args.judges, "records": []}
    try:
        created = {}
        for key in sorted({b for _, b in pairs}):
            created[key] = create_business(db, BY_KEY[key], with_knowledge=not args.no_knowledge).id
        print(f"{len(pairs)} conversations on {len(created)} businesses", flush=True)
        with ThreadPoolExecutor(max_workers=max(1, args.workers)) as pool:
            futures = [pool.submit(play, created[b], BY_KEY[b], BY_ID[s], judges, cache, i)
                       for i, (s, b) in enumerate(pairs)]
            for i, f in enumerate(futures, 1):
                rec = f.result()
                run["records"].append(rec)
                marks = "".join("E" if "error" in t else ("." if t["ok"] else "x") for t in rec["turns"])
                print(f"[{i}/{len(pairs)}] {rec['business']:<11} {rec['scenario']:<15} {marks}", flush=True)
    finally:
        delete_sim_businesses(db)
        db.close()
    run["summary"] = summarize(run["records"])
    text = report(run)
    print(text)
    if args.out:
        out = Path(args.out)
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(json.dumps(run, ensure_ascii=False, indent=1), encoding="utf-8")
        out.with_suffix(".md").write_text(text, encoding="utf-8")


if __name__ == "__main__":
    main()
