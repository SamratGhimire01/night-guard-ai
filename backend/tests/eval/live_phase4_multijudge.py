"""Phase 4 — large-scale before/after human-likeness eval, judged by several
independent models, plus a blind human-read packet. Measurement only: no app
code touched, nothing reverted, nothing committed.

Same generation discipline as live_human_likeness_before_after.py (reuses its
_run_one: fresh throwaway conversation per reply, deleted afterwards). Two
differences:
  * N samples per case per arm (default 2): Phase 3 showed a single sample moves
    the "before" mean by ~0.3 run-to-run.
  * Every before/after pair is scored by every judge in JUDGES, each with its
    own random A/B order, so position bias doesn't correlate across judges.
    Agreement between judges is reported next to the delta.

"Before" = the same three monkeypatches Phase 3 used (persona note, style exemplar
retrieval, style check all off), applied ONCE from the main thread around a
batch of before-runs. Not per call: unittest.mock.patch entered/exited
concurrently from worker threads restores the wrong "original" and can leave
the pipeline permanently patched.

Stages are resumable. Every result is checkpointed to --out, so a crash or a
429 storm loses nothing, and re-running skips what's already done:

    docker exec night_guard_ai-backend-1 python -m tests.eval.live_phase4_multijudge \
        --out tests/eval/phase4_results_2026-09-29.json [--samples 2] [--stages gen,judge,report,packet]
    # after the human fills in the scoresheet:
    ... --stages human --scores tests/eval/phase4_blind_read/scoresheet.csv
"""

import csv
import hashlib
import json
import os
import random
import re
import sys
import threading
import time
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor
from contextlib import ExitStack
from statistics import mean
from unittest.mock import patch

import httpx

from app.db.database import SessionLocal
from app.db.models.business import Business
from app.llm.azure_openai import AzureChatProvider
from app.services.conversation.response_templates import TEMPLATES
from tests.eval.live_human_likeness_before_after import _JUDGE_SYSTEM_PROMPT, _run_one
from tests.eval.phase4_cases import CASES

GEN_WORKERS = 2  # shared Azure quota with the live server; 3 still gave a 13% 429-fallback burst overnight
GEN_CHUNK = 30  # alternate before/after per chunk so time-of-day drift can't pile up in one arm
RECHECK_STRIDE = 6  # every 6th case, sample 0, is re-judged by each judge (self-consistency)
_PROVIDER_FAILURE = set(TEMPLATES["provider_failure"].values())

_BEFORE_PATCHES = (
    ("app.services.conversation.intent._persona_name_note", lambda business=None: ""),
    ("app.services.style_exemplar_service.retrieve", lambda *a, **k: []),
    ("app.services.conversation.orchestrator.check_response_style", lambda *a, **k: []),
)

_lock = threading.Lock()


def _failed(reply: str) -> bool:
    # provider_failure is always followed by a handoff addendum, hence startswith, not ==
    return reply.startswith(tuple(_PROVIDER_FAILURE)) or reply.startswith("(error") or reply == "(no result)"


# ----------------------------------------------------------------- judges

def _groq(model: str, max_tokens: int | None = None):
    def call(messages):
        for attempt in range(10):
            try:
                r = httpx.post(
                    "https://api.groq.com/openai/v1/chat/completions",
                    headers={"Authorization": f"Bearer {os.environ['GROQ_API_KEY']}"},
                    json={"model": model, "messages": messages} | ({"max_tokens": max_tokens} if max_tokens else {}),
                    timeout=90,
                )
            except httpx.TransportError:  # read timeouts seen on qwen overnight
                time.sleep(10)
                continue
            if r.status_code == 200:
                return r.json()["choices"][0]["message"]["content"] or ""
            if r.status_code in (429, 500, 502, 503, 504):
                time.sleep(min(float(r.headers.get("retry-after", 0) or 0) + 2 + attempt * 3, 120))
                continue
            raise RuntimeError(f"groq {model} HTTP {r.status_code}: {r.text[:200]}")
        raise RuntimeError(f"groq {model}: retries exhausted")
    return call


def _azure(messages):
    for attempt in range(6):
        try:
            return AzureChatProvider().chat(messages)
        except RuntimeError:  # 429 / transient; provider already retried 404/transport internally
            time.sleep(15 * (attempt + 1))
    raise RuntimeError("azure judge: retries exhausted")


JUDGES = {
    "azure/gpt-5-mini": _azure,  # NB: same model family as the bot itself -- possible self-preference
    "groq/gpt-oss-120b": _groq("openai/gpt-oss-120b"),
    "groq/qwen3.8-27b": _groq("qwen/qwen3.8-27b", max_tokens=250),  # most independent judge; cap: uncapped trips Groq's 1000 output-tok/min
}

_THINK_RE = re.compile(r"<think>.*?</think>", re.DOTALL)
_JSON_RE = re.compile(r"\{.*\}", re.DOTALL)


def _judge_once(call, message: str, reply_a: str, reply_b: str) -> dict:
    prompt = [
        {"role": "system", "content": _JUDGE_SYSTEM_PROMPT},
        {"role": "user", "content": f"Customer message:\n{message}\n\nReply A:\n{reply_a}\n\nReply B:\n{reply_b}"},
    ]
    last = None
    for _ in range(3):  # malformed JSON / out-of-range score -> ask again
        raw = _THINK_RE.sub("", call(prompt))
        m = _JSON_RE.search(raw)
        try:
            d = json.loads(m.group(0))
            sa, sb = int(d["reply_a"]["score"]), int(d["reply_b"]["score"])
            if 1 <= sa <= 5 and 1 <= sb <= 5:
                return {"a": sa, "b": sb, "reason_a": d["reply_a"].get("reason", ""), "reason_b": d["reply_b"].get("reason", "")}
        except Exception as exc:  # noqa: BLE001
            last = f"{type(exc).__name__}: {raw[:200]!r}"
    raise ValueError(f"judge gave no usable JSON: {last}")


def _a_is_before(judge: str, key: str) -> bool:
    return int(hashlib.sha256(f"{judge}|{key}".encode()).hexdigest(), 16) % 2 == 0


# ----------------------------------------------------------------- state

def _load(path):
    if os.path.exists(path):
        with open(path) as f:
            return json.load(f)
    return {"gen": {}, "judge": {}}


def _put(state, path, section, key, value):
    with _lock:
        state[section][key] = value
        tmp = path + ".tmp"
        with open(tmp, "w") as f:
            json.dump(state, f, ensure_ascii=False, indent=1)
        os.replace(tmp, path)


# ----------------------------------------------------------------- stage: gen

def _gen_one(state, path, case, sample, arm):
    key = f"{case['id']}|{sample}|{arm}"
    db = SessionLocal()
    try:
        business = db.query(Business).filter(Business.name == case["business"]).one()
        for attempt in range(4):
            try:
                reply, intent, language = _run_one(db, business, case["message"])
            except Exception as exc:  # noqa: BLE001
                reply, intent, language = f"(error: {type(exc).__name__}: {exc})", None, None
            if not _failed(reply):
                break
            print(f"  retry {key} after: {reply[:80]}", flush=True)
            time.sleep(30 * (attempt + 1))
        _put(state, path, "gen", key, {"reply": reply, "intent": intent, "language": language})
        print(f"  gen {key}: {intent}/{language} {len(reply.split())}w", flush=True)
    finally:
        db.close()


def stage_gen(state, path, samples):
    todo = [(c, s) for c in CASES for s in range(samples)]
    for i in range(0, len(todo), GEN_CHUNK):
        chunk = todo[i : i + GEN_CHUNK]
        for arm in ("before", "after"):
            pending = [(c, s) for c, s in chunk if f"{c['id']}|{s}|{arm}" not in state["gen"]]
            if not pending:
                continue
            print(f"[gen] {arm} chunk {i // GEN_CHUNK + 1}: {len(pending)} runs", flush=True)
            with ExitStack() as stack:
                if arm == "before":
                    for target, fake in _BEFORE_PATCHES:
                        stack.enter_context(patch(target, new=fake))
                with ThreadPoolExecutor(GEN_WORKERS) as pool:
                    list(pool.map(lambda cs: _gen_one(state, path, cs[0], cs[1], arm), pending))


# ----------------------------------------------------------------- stage: judge

def _judge_all(state, path, judge, samples):
    call = JUDGES[judge]
    for idx, case in enumerate(CASES):
        for s in range(samples):
            for rep in (0, 1) if (idx % RECHECK_STRIDE == 0 and s == 0) else (0,):
                jkey = f"{judge}|{case['id']}|{s}|{rep}"
                if jkey in state["judge"]:
                    continue
                b = state["gen"].get(f"{case['id']}|{s}|before")
                a = state["gen"].get(f"{case['id']}|{s}|after")
                if not (a and b):
                    continue
                ab = _a_is_before(judge, f"{case['id']}|{s}")
                ra, rb = (b["reply"], a["reply"]) if ab else (a["reply"], b["reply"])
                try:
                    j = _judge_once(call, case["message"], ra, rb)
                except Exception as exc:  # noqa: BLE001 -- record and move on; rerun resumes it
                    print(f"  [{judge}] {jkey} FAILED: {exc}", flush=True)
                    continue
                _put(state, path, "judge", jkey, {
                    "before": j["a"] if ab else j["b"], "after": j["b"] if ab else j["a"],
                    "before_reason": j["reason_a"] if ab else j["reason_b"],
                    "after_reason": j["reason_b"] if ab else j["reason_a"],
                    "a_was_before": ab,
                })
                print(f"  [{judge}] {jkey}: before={state['judge'][jkey]['before']} after={state['judge'][jkey]['after']}", flush=True)


def stage_judge(state, path, samples):
    with ThreadPoolExecutor(len(JUDGES)) as pool:  # one thread per judge; each paces itself
        list(pool.map(lambda j: _judge_all(state, path, j, samples), JUDGES))


# ----------------------------------------------------------------- stage: report

def _records(state, samples):
    """One record per (case, sample) that has both replies and >=1 judge score."""
    out = []
    for case in CASES:
        for s in range(samples):
            b = state["gen"].get(f"{case['id']}|{s}|before")
            a = state["gen"].get(f"{case['id']}|{s}|after")
            scores = {j: state["judge"][f"{j}|{case['id']}|{s}|0"] for j in JUDGES if f"{j}|{case['id']}|{s}|0" in state["judge"]}
            if not (a and b and scores) or _failed(a["reply"]) or _failed(b["reply"]):
                continue
            out.append({
                "case_id": case["id"], "sample": s, "business": case["business"], "source": case["source"],
                "intended_lang": case["lang"], "intended_intent": case["intent"], "message": case["message"],
                "intent": a["intent"], "language": a["language"], "before_intent": b["intent"],
                "before_reply": b["reply"], "after_reply": a["reply"], "scores": scores,
                "before": mean(v["before"] for v in scores.values()),
                "after": mean(v["after"] for v in scores.values()),
            })
    return out


def _boot_ci(deltas, n=4000, seed=7):
    if len(deltas) < 2:
        return (float("nan"), float("nan"))
    rng = random.Random(seed)
    ms = sorted(mean(rng.choices(deltas, k=len(deltas))) for _ in range(n))
    return ms[int(0.025 * n)], ms[int(0.975 * n)]


def _pearson(x, y):
    mx, my = mean(x), mean(y)
    sx = sum((a - mx) ** 2 for a in x) ** 0.5
    sy = sum((b - my) ** 2 for b in y) ** 0.5
    return sum((a - mx) * (b - my) for a, b in zip(x, y)) / (sx * sy) if sx and sy else float("nan")


def _sign(x):
    return (x > 0) - (x < 0)


def stage_report(state, samples, out_md):
    recs = [r for r in _records(state, samples) if len(r["scores"]) == len(JUDGES)]
    L = []
    p = L.append
    judges = list(JUDGES)
    p(f"# Phase 4 multi-judge eval — {len(recs)} (case, sample) pairs, {len({r['case_id'] for r in recs})} cases, {len(judges)} judges\n")

    # headline
    case_d = defaultdict(list)
    for r in recs:
        case_d[r["case_id"]].append(r["after"] - r["before"])
    case_deltas = [mean(v) for v in case_d.values()]
    lo, hi = _boot_ci(case_deltas)
    p("## Headline (consensus = mean of judges)\n")
    p(f"- before {mean(r['before'] for r in recs):.2f} → after {mean(r['after'] for r in recs):.2f}, "
      f"**Δ {mean(case_deltas):+.2f}** (95% bootstrap CI over cases {lo:+.2f} … {hi:+.2f})")
    p(f"- cases improved/tied/regressed (consensus, averaged over samples): "
      f"{sum(d > 0 for d in case_deltas)}/{sum(d == 0 for d in case_deltas)}/{sum(d < 0 for d in case_deltas)}")
    changed = [r for r in recs if r["before_reply"] != r["after_reply"]]
    p(f"- {len(recs) - len(changed)}/{len(recs)} pairs got byte-identical before/after replies (deterministic templates the "
      f"Phase 1-3 pipeline never touches); Δ over only the {len(changed)} pairs that differ: "
      f"{mean(r['after'] - r['before'] for r in changed):+.2f}\n")
    p("| judge | before | after | Δ | 95% CI (cases) |\n|---|---|---|---|---|")
    for j in judges:
        cd = defaultdict(list)
        for r in recs:
            cd[r["case_id"]].append(r["scores"][j]["after"] - r["scores"][j]["before"])
        d = [mean(v) for v in cd.values()]
        jlo, jhi = _boot_ci(d)
        p(f"| {j} | {mean(r['scores'][j]['before'] for r in recs):.2f} | {mean(r['scores'][j]['after'] for r in recs):.2f} | "
          f"{mean(d):+.2f} | {jlo:+.2f} … {jhi:+.2f} |")

    # agreement
    p("\n## Inter-judge agreement\n")
    p("Per reply score (both arms pooled) and per pair Δ (after − before):\n")
    p("| judge pair | score within ±1 | exact | Pearson r | Δ same sign | Δ within ±1 |\n|---|---|---|---|---|---|")
    for i, j1 in enumerate(judges):
        for j2 in judges[i + 1 :]:
            x = [r["scores"][j1][arm] for r in recs for arm in ("before", "after")]
            y = [r["scores"][j2][arm] for r in recs for arm in ("before", "after")]
            dx = [r["scores"][j1]["after"] - r["scores"][j1]["before"] for r in recs]
            dy = [r["scores"][j2]["after"] - r["scores"][j2]["before"] for r in recs]
            p(f"| {j1} vs {j2} | {mean(abs(a - b) <= 1 for a, b in zip(x, y)):.0%} | {mean(a == b for a, b in zip(x, y)):.0%} | "
              f"{_pearson(x, y):.2f} | {mean(_sign(a) == _sign(b) for a, b in zip(dx, dy)):.0%} | "
              f"{mean(abs(a - b) <= 1 for a, b in zip(dx, dy)):.0%} |")
    allw = mean(max(r["scores"][j][arm] for j in judges) - min(r["scores"][j][arm] for j in judges) <= 1
                for r in recs for arm in ("before", "after"))
    unanimous_dir = mean(len({_sign(r["scores"][j]["after"] - r["scores"][j]["before"]) for j in judges}) == 1 for r in recs)
    p(f"\n- all {len(judges)} judges within ±1 of each other on a reply: **{allw:.0%}**")
    p(f"- all judges agree on the direction of Δ (better/same/worse) for a pair: **{unanimous_dir:.0%}**")

    p("\nSelf-consistency (same judge, identical input, re-judged):\n")
    p("| judge | rechecks | exact | max abs diff |\n|---|---|---|---|")
    for j in judges:
        diffs = []
        for k, v in state["judge"].items():
            if k.startswith(j + "|") and k.endswith("|1"):
                v0 = state["judge"].get(k[:-1] + "0")
                if v0:
                    diffs += [abs(v["before"] - v0["before"]), abs(v["after"] - v0["after"])]
        if diffs:
            p(f"| {j} | {len(diffs) // 2} | {mean(d == 0 for d in diffs):.0%} | {max(diffs)} |")

    by_case = defaultdict(dict)
    for r in recs:
        by_case[r["case_id"]][r["sample"]] = r["after"] - r["before"]
    pairs = [(v[0], v[1]) for v in by_case.values() if 0 in v and 1 in v]
    if pairs:
        p(f"\nGeneration noise (same case, sample 0 vs 1, consensus Δ): same sign {mean(_sign(a) == _sign(b) for a, b in pairs):.0%}, "
          f"mean |Δ0 − Δ1| {mean(abs(a - b) for a, b in pairs):.2f} over {len(pairs)} cases.")

    # breakdowns
    for title, keyf in (
        ("tenant", lambda r: r["business"]),
        ("language (detected, after arm)", lambda r: r["language"]),
        ("intent (detected, after arm)", lambda r: r["intent"]),
    ):
        p(f"\n## By {title}\n")
        p("| slice | n pairs | before | after | Δ | 95% CI | " + " | ".join(f"Δ {j.split('/')[1]}" for j in judges) + " | all-judges ±1 |")
        p("|---|---|---|---|---|---|" + "---|" * len(judges) + "---|")
        groups = defaultdict(list)
        for r in recs:
            groups[keyf(r)].append(r)
        for g, rs in sorted(groups.items(), key=lambda kv: -len(kv[1])):
            d = [r["after"] - r["before"] for r in rs]
            glo, ghi = _boot_ci(d)
            per_j = " | ".join(f"{mean(r['scores'][j]['after'] - r['scores'][j]['before'] for r in rs):+.2f}" for j in judges)
            agree = mean(max(r["scores"][j][arm] for j in judges) - min(r["scores"][j][arm] for j in judges) <= 1
                         for r in rs for arm in ("before", "after"))
            p(f"| {g} | {len(rs)} | {mean(r['before'] for r in rs):.2f} | {mean(r['after'] for r in rs):.2f} | "
              f"{mean(d):+.2f} | {glo:+.2f} … {ghi:+.2f} | {per_j} | {agree:.0%} |")

    # gaps
    worst = sorted(recs, key=lambda r: (r["after"] - r["before"], r["after"]))
    p("\n## Biggest remaining gaps (consensus Δ most negative), with transcripts\n")
    for r in worst[:10]:
        _gap(p, r)
    p("\n## Lowest absolute 'after' scores (what still reads most bot-like, regardless of Δ)\n")
    seen = {r["case_id"] for r in worst[:10]}
    for r in [r for r in sorted(recs, key=lambda r: r["after"]) if r["case_id"] not in seen][:8]:
        _gap(p, r)
    p("\n## Biggest improvements\n")
    for r in worst[::-1][:5]:
        _gap(p, r)

    text = "\n".join(L)
    with open(out_md, "w") as f:
        f.write(text + "\n")
    print(text)
    return recs


def _gap(p, r):
    p(f"**[{r['case_id']} s{r['sample']}]** Δ {r['after'] - r['before']:+.2f} (before {r['before']:.2f} / after {r['after']:.2f}) — "
      f"{r['business']}, {r['intent']}, {r['language']}, {r['source']}\n")
    p(f"- CUSTOMER: {r['message']}")
    p(f"- BEFORE: {r['before_reply']}")
    p(f"- AFTER: {r['after_reply']}")
    for j, v in r["scores"].items():
        p(f"  - {j}: before {v['before']} ({v['before_reason']}) / after {v['after']} ({v['after_reason']})")
    p("")


# ----------------------------------------------------------------- stage: packet

def stage_packet(state, samples, out_dir, n=20, seed=20260929):
    """20 before/after pairs for a blind human read. Real customer messages first. Stratified
    by detected language, then round-robin across tenants. Within a stratum, the pairs picked
    first are the ones where the judges disagreed most or the Δ was largest, i.e. the pairs
    where a human verdict is most informative. One pair per case."""
    # identical before/after text (deterministic templates) tells a blind reader nothing
    recs = [r for r in _records(state, samples) if len(r["scores"]) == len(JUDGES) and r["before_reply"] != r["after_reply"]]
    quota = {"en": 6, "ne_roman": 6, "ne_deva": 5, "mixed": 3}

    def info(r):
        spread = max(max(v[a] for v in r["scores"].values()) - min(v[a] for v in r["scores"].values()) for a in ("before", "after"))
        return (r["source"] == "real", spread + abs(r["after"] - r["before"]))

    picked, used = [], set()
    for lang, q in quota.items():
        pool = sorted([r for r in recs if r["language"] == lang], key=info, reverse=True)
        by_t = defaultdict(list)
        for r in pool:
            by_t[r["business"]].append(r)
        got = 0
        while got < q and any(by_t.values()):
            for t in list(by_t):
                while by_t[t] and by_t[t][0]["case_id"] in used:
                    by_t[t].pop(0)
                if by_t[t] and got < q:
                    r = by_t[t].pop(0)
                    picked.append(r)
                    used.add(r["case_id"])
                    got += 1
    for r in sorted(recs, key=info, reverse=True):  # top up if a language ran short
        if len(picked) >= n:
            break
        if r["case_id"] not in used:
            picked.append(r)
            used.add(r["case_id"])
    rng = random.Random(seed)
    rng.shuffle(picked)

    os.makedirs(out_dir, exist_ok=True)
    md = ["# Blind read — 20 reply pairs\n",
          "Each item: one real (or realistic) first customer message to one of the 3 businesses, and two candidate",
          "replies, A and B. The order is random per item, and there's no label for which pipeline wrote which. For each",
          "item, score A and B 1–5 on **\"sounds like a real, attentive human receptionist, not a bot\"** (5 = clearly",
          "human, 1 = obviously scripted). Note which one you'd rather receive, or `=` if you can't choose. Fill in",
          "`scoresheet.csv`, then run the `human` stage to compare your scores with the judges'.",
          "",
          "Don't open `answer_key.json` until you're done.\n"]
    key, sheet = [], [["item", "score_a", "score_b", "prefer (A/B/=)", "notes"]]
    for i, r in enumerate(picked, 1):
        a_before = rng.random() < 0.5
        ra, rb = (r["before_reply"], r["after_reply"]) if a_before else (r["after_reply"], r["before_reply"])
        md += [f"---\n\n## Item {i} — {r['business']}\n", f"**Customer:** {r['message']}\n",
               f"**Reply A:**\n\n> " + ra.replace("\n", "\n> ") + "\n", f"**Reply B:**\n\n> " + rb.replace("\n", "\n> ") + "\n",
               "Score A: __  Score B: __  Prefer: __\n"]
        key.append({"item": i, "case_id": r["case_id"], "sample": r["sample"], "a_is": "before" if a_before else "after",
                    "language": r["language"], "intent": r["intent"], "source": r["source"],
                    "judges": {j: {"A": v["before"] if a_before else v["after"], "B": v["after"] if a_before else v["before"]}
                               for j, v in r["scores"].items()}})
        sheet.append([i, "", "", "", ""])
    with open(os.path.join(out_dir, "packet.md"), "w") as f:
        f.write("\n".join(md))
    with open(os.path.join(out_dir, "answer_key.json"), "w") as f:
        json.dump(key, f, ensure_ascii=False, indent=1)
    with open(os.path.join(out_dir, "scoresheet.csv"), "w", newline="") as f:
        csv.writer(f).writerows(sheet)
    print(f"[packet] {len(picked)} items -> {out_dir}  langs={[k['language'] for k in key]}")


# ----------------------------------------------------------------- stage: human

def stage_human(scores_csv, key_path):
    key = {k["item"]: k for k in json.load(open(key_path))}
    rows = [r for r in csv.DictReader(open(scores_csv)) if r["score_a"].strip() and r["score_b"].strip()]
    hb, ha, prefs = [], [], []
    agree = defaultdict(list)
    for r in rows:
        k = key[int(r["item"])]
        sa, sb = int(r["score_a"]), int(r["score_b"])
        before, after = (sa, sb) if k["a_is"] == "before" else (sb, sa)
        hb.append(before)
        ha.append(after)
        pref = r["prefer (A/B/=)"].strip().upper()
        prefs.append("=" if pref not in ("A", "B") else ("before" if (pref == "A") == (k["a_is"] == "before") else "after"))
        for j, v in k["judges"].items():
            jb, ja = (v["A"], v["B"]) if k["a_is"] == "before" else (v["B"], v["A"])
            agree[j].append((abs(jb - before) <= 1 and abs(ja - after) <= 1, _sign(ja - jb) == _sign(after - before)))
    print(f"human, n={len(rows)}: before {mean(hb):.2f}  after {mean(ha):.2f}  Δ {mean(ha) - mean(hb):+.2f}")
    print(f"preferred: after {prefs.count('after')}, before {prefs.count('before')}, can't tell {prefs.count('=')}")
    for j, v in agree.items():
        print(f"  vs {j}: both scores within ±1 {mean(a for a, _ in v):.0%}, same Δ direction {mean(b for _, b in v):.0%}")


def main():
    args = sys.argv[1:]
    opt = lambda name, default=None: args[args.index(name) + 1] if name in args else default  # noqa: E731
    out = opt("--out", "tests/eval/phase4_results_2026-09-29.json")
    samples = int(opt("--samples", "2"))
    stages = opt("--stages", "gen,judge,report,packet").split(",")
    global CASES, JUDGES
    if opt("--judges"):  # report/packet on a subset, e.g. when one judge ran out of daily quota
        JUDGES = {k: v for k, v in JUDGES.items() if k in opt("--judges").split(",")}
    if opt("--cases"):  # comma-separated ids: smoke test / targeted re-run
        CASES = [c for c in CASES if c["id"] in set(opt("--cases").split(","))]
    blind_dir = os.path.join(os.path.dirname(out), "phase4_blind_read")
    state = _load(out)
    if "gen" in stages:
        stage_gen(state, out, samples)
    if "judge" in stages:
        stage_judge(state, out, samples)
    if "report" in stages:
        stage_report(state, samples, out.replace(".json", f"_report_{len(JUDGES)}judges.md"))
    if "packet" in stages:
        stage_packet(state, samples, blind_dir)
    if "human" in stages:
        stage_human(opt("--scores", os.path.join(blind_dir, "scoresheet.csv")), os.path.join(blind_dir, "answer_key.json"))


if __name__ == "__main__":
    main()
