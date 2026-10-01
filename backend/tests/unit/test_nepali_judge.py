"""Nepali judge (tests/eval/nepali_judge): lint, prompt parsing, ensemble maths and the calibration gate, with fake
judges -- no network, no DB."""

import json
import sys
import types

import pytest

from tests.eval.nepali_judge import calibrate, engine, gold, judges, rubric
from tests.eval.nepali_judge.lint import CRITERIA, caps, language_of, lint


# --- lint ----------------------------------------------------------------------------------------------------------


@pytest.mark.parametrize("pair", gold.PAIRS, ids=lambda p: p["id"])
def test_lint_never_flags_a_good_gold_reply(pair):
    assert lint(pair["good"], pair["customer"], pair.get("history")) == []


@pytest.mark.parametrize("pair", [p for p in gold.PAIRS if p["lint"]], ids=lambda p: p["id"])
def test_lint_catches_every_defect_it_is_meant_to(pair):
    codes = [f.code for f in lint(pair["bad"], pair["customer"], pair.get("history"))]
    assert pair["defect"] in codes


@pytest.mark.parametrize(
    ("text", "lang"),
    [
        ("bholi 10 baje milxa?", "ne_roman"),
        ("eSewa ki Khalti bata tirna milcha, ki clinic mai aayera.", "ne_roman"),
        ("Cleaning ko price 1500 ho", "ne_roman"),
        ("Sure, what time would you like to come tomorrow?", "en"),
        ("do you open on saturday?", "en"),
        ("आज बेलुका ६ बजेसम्म खुल्ला छ।", "ne_deva"),
    ],
)
def test_language_detection(text, lang):
    assert language_of(text) == lang


def test_a_single_offer_is_human_but_a_repeated_one_is_not():
    history = [{"role": "customer", "text": "price?"}, {"role": "assistant", "text": "1500 ho. Booking garna man cha?"}]
    assert lint("Huncha, Nepali mai kura garaum. Bhannus, k help garum?", "Nepali") == []
    assert [f.code for f in lint("2 baje khali cha. Booking garna man cha?", "time?", history)] == ["stock_ending"]


def test_a_long_answer_to_an_explain_question_is_not_a_monologue():
    long_reply = " ".join(["word"] * 60)
    assert "monologue" not in [f.code for f in lint(long_reply, "what is tartar")]
    assert "monologue" in [f.code for f in lint(long_reply, "Payment")]


def test_locked_language_decides_over_the_current_message():
    findings = lint("Sure, 10 works.", "ok 10", locked_language="ne_roman")
    assert [f.code for f in findings] == ["wrong_language"]


def test_caps_take_the_lowest_cap_per_criterion():
    found = lint("Kya timro booking abhi Monday, October 5 at 10:00 AM ma cha?", "mero booking kaile ho")
    capped = caps(found)
    assert capped["language"] <= 3 and capped["register"] == 2 and capped["helpful"] == 5


# --- parsing -------------------------------------------------------------------------------------------------------

_GOOD = {c: 5 for c in CRITERIA}


def _abs(scores, extra=""):
    return extra + json.dumps({"devanagari": "", "gloss": "", "problems": [], "scores": scores})


def test_parse_absolute_accepts_think_blocks_and_rejects_bad_scores():
    assert rubric.parse_absolute(_abs(_GOOD, "<think>hmm {not json}</think>"))["scores"] == _GOOD
    with pytest.raises(rubric.BadJudgeOutput):
        rubric.parse_absolute(_abs(_GOOD | {"language": 7}))
    with pytest.raises(rubric.BadJudgeOutput):
        rubric.parse_absolute("I think it's fine")


def test_parse_pairwise_normalises_votes():
    raw = json.dumps({"winner": {"language": "a", "register": "B", "human": "?", "helpful": "tie"}, "overall": "b"})
    parsed = rubric.parse_pairwise(raw)
    assert parsed["overall"] == "B"
    assert parsed["winner"] == {"language": "A", "register": "B", "human": "tie", "helpful": "tie", "correct": "tie"}


def test_prompts_carry_the_rubric_anchors_and_context():
    messages = rubric.absolute_messages("Huss", "book garna paryo", [{"role": "assistant", "text": "Namaste!"}], "ne_roman")
    assert "Devanagari" in messages[0]["content"] and "kripaya" in messages[0]["content"]
    assert "Earlier in this chat" in messages[1]["content"] and "ne_roman" in messages[1]["content"]


# --- ensemble ------------------------------------------------------------------------------------------------------


def _const(raw):
    return lambda messages: raw


def test_score_takes_the_median_then_applies_lint_caps():
    judges_ = {
        "a": _const(_abs({c: 5 for c in CRITERIA})),
        "b": _const(_abs({c: 4 for c in CRITERIA})),
        "c": _const(_abs({c: 1 for c in CRITERIA})),  # one odd judge doesn't drag the median
    }
    result = engine.score("Kripaya naam pathaidinus.", "naam chahiyo?", judges_)
    assert result.criteria["human"] == 4.0
    assert result.criteria["language"] == 3.0  # median 4, capped by the bookish finding
    assert result.overall == engine.overall_of(result.criteria)


def test_a_broken_judge_is_reported_not_fatal():
    def boom(messages):
        raise RuntimeError("HTTP 500")

    result = engine.score("Huss!", "ok", {"good": _const(_abs(_GOOD)), "bad": boom})
    assert set(result.raw) == {"good"} and "bad" in result.errors


def test_malformed_output_is_retried():
    answers = iter(["oops", "still not json", _abs(_GOOD)])
    result = engine.score("Huss!", "ok", {"flaky": lambda m: next(answers)})
    assert result.raw["flaky"] == _GOOD


def _pairwise(winner):
    return json.dumps({"winner": {c: winner for c in CRITERIA}, "overall": winner})


def test_a_verdict_that_flips_with_the_order_counts_as_a_tie():
    always_a = _const(_pairwise("A"))  # pure position bias
    c = engine.compare("one", "two", "hi", {"biased": always_a})
    assert c.votes == {"biased": "tie"} and c.consistent == {"biased": False} and c.verdict == "tie"


def _knows_better(good_text):
    """A fake judge that genuinely prefers `good_text`, whichever slot it is in."""

    def call(messages):
        user = messages[1]["content"]
        a = user.split("Reply A:\n", 1)[1].split("\n\nReply B:\n", 1)[0]
        return _pairwise("A" if a == good_text else "B")

    return call


def test_consistent_judges_decide_by_majority():
    judges_ = {"x": _knows_better("good"), "y": _knows_better("good"), "z": _knows_better("bad")}
    c = engine.compare("good", "bad", "hi", judges_)
    assert c.verdict == "A" and all(c.consistent.values())


def test_lint_alone_prefers_the_reply_without_hard_defects():
    c = engine.compare("Kya abhi milcha?", "Milcha, aile aaunus.", "aile aauna milcha?", {})
    assert c.verdict == "B"


# --- calibration gate ----------------------------------------------------------------------------------------------


def test_cohen_kappa():
    assert calibrate.cohen_kappa([True, False, True, False], [True, False, True, False]) == 1.0
    assert calibrate.cohen_kappa([True, True, False, False], [True, False, True, False]) == 0.0
    assert calibrate.cohen_kappa([], []) is None


def _oracle(messages):
    """Perfect fake judge: knows the good side of every gold pair."""
    goods = {p["good"] for p in gold.PAIRS}
    user = messages[1]["content"]
    if "Reply A:" in user:
        a = user.split("Reply A:\n", 1)[1].split("\n\nReply B:\n", 1)[0]
        return _pairwise("A" if a in goods else "B")
    return _abs(_GOOD)


def test_the_gate_trusts_a_good_judge_and_rejects_a_position_biased_one():
    cache = calibrate.Cache(None)
    good = calibrate.evaluate_judge("oracle", _oracle, cache, gold.PAIRS, [])
    biased = calibrate.evaluate_judge("biased", _const(_pairwise("A")), cache, gold.PAIRS, [])
    assert good["accuracy"] == 1.0 and good["consistency"] == 1.0 and good["trusted"]
    assert biased["consistency"] == 0.0 and not biased["trusted"]
    lint_only = calibrate.evaluate_judge("lint", None, cache, gold.PAIRS, [])
    assert lint_only["pairs"] == sum(p["lint"] for p in gold.PAIRS) and lint_only["accuracy"] == 1.0


def test_good_reply_placement_is_balanced():
    placed_a = sum(calibrate._good_is_a(p["id"]) for p in gold.PAIRS)
    assert 0.3 < placed_a / len(gold.PAIRS) < 0.7


def test_native_review_sheet_parsing(tmp_path):
    sheet = tmp_path / "sheet.md"
    sheet.write_text(
        "# x\n\n## 1\n- Customer: price?\n- Before: Kripaya...\n- After: 1500 ho.\n- Your verdict: OK\n\n"
        "## 2\n- Customer: hours?\n- Before: a\n- After: Hamro samaya 9-5.\n- Your verdict: 9 dekhi 5 samma khulla cha.\n\n"
        "## 3\n- Customer: hi\n- Before: a\n- After: b\n- Your verdict: \n",
        encoding="utf-8",
    )
    labels = gold.native_labels(sheet)
    assert [(e["id"], e["ok"]) for e in labels] == [("native-1", True), ("native-2", False)]
    assert gold.native_pairs(sheet) == [
        {"id": "native-2", "defect": "native", "lint": False, "customer": "hours?",
         "good": "9 dekhi 5 samma khulla cha.", "bad": "Hamro samaya 9-5."}
    ]


# --- Claude judge request shape ------------------------------------------------------------------------------------


def test_claude_judge_sends_system_separately_with_fallbacks(monkeypatch):
    sent = {}

    class _Messages:
        def create(self, **kwargs):
            sent.update(kwargs)
            block = types.SimpleNamespace(type="text", text='{"ok": 1}')
            return types.SimpleNamespace(stop_reason="end_turn", content=[types.SimpleNamespace(type="thinking"), block])

    class _Client:
        def __init__(self, **kwargs):
            self.beta = types.SimpleNamespace(messages=_Messages())

    monkeypatch.setitem(sys.modules, "anthropic", types.SimpleNamespace(Anthropic=_Client))
    out = judges.claude([{"role": "system", "content": "RUBRIC"}, {"role": "user", "content": "reply"}])
    assert out == '{"ok": 1}'
    assert sent["model"] == "claude-opus-5-5" and sent["system"] == "RUBRIC"
    assert sent["messages"] == [{"role": "user", "content": "reply"}]
    assert sent["fallbacks"] == "default" and sent["betas"] == ["server-side-fallback-2026-07-01"]


def test_unknown_judge_name_is_rejected():
    with pytest.raises(ValueError):
        judges.get("gpt-17")


# --- v3: checklist, hybrid, Gemini, per-defect trust ----------------------------------------------------------------


def _check(**overrides):
    answers = {q: "yes" for q in rubric.CHECKLIST} | {k: ("yes" if v else "no") for k, v in overrides.items()}
    return json.dumps({"gloss_customer": "", "gloss_reply": "", "answers": answers})


def test_parse_checklist_needs_every_answer():
    assert all(rubric.parse_checklist(_check()).values())
    assert rubric.parse_checklist(_check(answers=False))["answers"] is False
    with pytest.raises(rubric.BadJudgeOutput):
        rubric.parse_checklist(json.dumps({"answers": {"answers": "maybe"}}))


def test_checklist_ensemble_averages_judges_and_uses_the_cache():
    calls = []

    def counting(raw):
        def call(messages):
            calls.append(1)
            return raw
        return call

    cache = calibrate.Cache(None)
    judges_ = {"x": counting(_check()), "y": counting(_check(would_send=False, right_length=False))}
    first = engine.checklist("Huss!", "ok", judges_, cache=cache)
    assert first.answers["would_send"] == 0.5 and first.answers["answers"] == 1.0
    assert first.score == pytest.approx((len(rubric.CHECKLIST) - 1) / len(rubric.CHECKLIST))  # two half-votes
    engine.checklist("Huss!", "ok", judges_, cache=cache)
    assert len(calls) == 2  # second time: both answers came from the cache


def test_hybrid_lets_the_lint_decide_language_defects_without_asking_anyone():
    asked = []
    judges_ = {"x": lambda m: asked.append(1) or _check()}
    h = engine.hybrid_compare("Kya abhi milcha?", "Milcha, aile aaunus.", "aile aauna milcha?", judges_)
    assert (h.verdict, h.decided_by) == ("B", "lint") and asked == []


def _prefers(good_text):
    """Checklist judge that says 'no' to would_send for anything but good_text."""

    def call(messages):
        reply = messages[1]["content"].rsplit("Business reply to check:\n", 1)[1]
        return _check(would_send=reply == good_text, reacts_to_feelings=reply == good_text)

    return call


def test_hybrid_uses_the_checklist_when_the_lint_sees_no_difference():
    h = engine.hybrid_compare("Aaja 3 baje khali cha.", "Ouch 😕 aaja 3 baje khali cha — milcha?", "daat dukhyo",
                              {"x": _prefers("Ouch 😕 aaja 3 baje khali cha — milcha?")})
    assert (h.verdict, h.decided_by) == ("B", "checklist")
    tie = engine.hybrid_compare("Huss.", "Hunchha.", "ok", {"x": _const(_check())})
    assert tie.verdict == "tie"


def test_parse_spec():
    assert calibrate.parse_spec("lint") == ("lint", [])
    assert calibrate.parse_spec("azure") == ("pairwise", ["azure"])
    assert calibrate.parse_spec("hybrid:gemini/gemini-3.5-flash+azure") == ("hybrid", ["gemini/gemini-3.5-flash", "azure"])
    assert calibrate.parse_spec("check:groq/qwen/qwen3.8-27b") == ("check", ["groq/qwen/qwen3.8-27b"])


def _gold_oracle_checklist(messages):
    """Perfect checklist judge for the gold set: every good reply passes, every bad one fails one question."""
    reply = messages[1]["content"].rsplit("Business reply to check:\n", 1)[1]
    goods = {p["good"] for p in gold.PAIRS}
    return _check() if reply in goods else _check(would_send=False)


def test_hybrid_with_a_good_checklist_judge_is_trusted_and_reports_what_it_is_trusted_for():
    r = calibrate.evaluate_judge("hybrid:fake", {"fake": _gold_oracle_checklist}, calibrate.Cache(None), gold.PAIRS, [], workers=4)
    assert r["accuracy"] == 1.0 and r["trusted"] and r["consistency"] is None
    assert r["decided_by"]["lint"] >= sum(p["lint"] for p in gold.PAIRS)  # robot-2 also has a bookish word
    assert {"hindi", "cold", "unhelpful"} <= set(r["trusted_for"])


def test_a_useless_checklist_judge_is_not_trusted_for_the_llm_only_defects():
    r = calibrate.evaluate_judge("check:fake", {"fake": _const(_check())}, calibrate.Cache(None), gold.PAIRS, [])
    assert not r["trusted"] and "cold" not in r["trusted_for"]


def test_pacer_spaces_out_calls(monkeypatch):
    slept = []
    clock = iter([0.0, 0.0, 0.0])
    monkeypatch.setattr(judges.time, "monotonic", lambda: next(clock))
    monkeypatch.setattr(judges.time, "sleep", slept.append)
    pacer = judges._Pacer(6.5)
    pacer.wait(), pacer.wait(), pacer.wait()
    assert slept == [0.0, 6.5, 13.0]


def test_gemini_judge_request_and_retry(monkeypatch):
    monkeypatch.setenv("GEMINI_API_KEY", "test-key")
    monkeypatch.setenv("GEMINI_MIN_INTERVAL", "0")
    monkeypatch.setattr(judges.time, "sleep", lambda s: None)
    judges._pacers.clear()
    sent, replies = [], iter([(503, {}), (200, {"choices": [{"message": {"content": "OK"}}]})])

    def post(url, headers, json, timeout):
        sent.append((url, headers, json))
        status, body = next(replies)
        return types.SimpleNamespace(status_code=status, json=lambda: body, text="busy", headers={})

    monkeypatch.setattr(judges.httpx, "post", post)
    assert judges.get("gemini/gemini-3.5-flash")([{"role": "user", "content": "hi"}]) == "OK"
    assert len(sent) == 2  # one retry after the 503
    url, headers, body = sent[-1]
    assert "generativelanguage.googleapis.com" in url and headers["Authorization"] == "Bearer test-key"
    assert body["model"] == "gemini-3.5-flash" and body["temperature"] == 0


def test_gemini_stops_at_once_when_the_daily_quota_is_gone(monkeypatch):
    monkeypatch.setenv("GEMINI_API_KEY", "k")
    monkeypatch.setenv("GEMINI_MIN_INTERVAL", "0")
    judges._pacers.clear()
    calls = []

    def post(url, headers, json, timeout):
        calls.append(1)
        return types.SimpleNamespace(status_code=429, text="quotaId GenerateRequestsPerDayPerProjectPerModel-FreeTier", headers={})

    monkeypatch.setattr(judges.httpx, "post", post)
    with pytest.raises(RuntimeError, match="daily quota"):
        judges.get("gemini/gemini-3.5-flash")([{"role": "user", "content": "hi"}])
    assert len(calls) == 1
