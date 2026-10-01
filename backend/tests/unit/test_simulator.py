"""Conversation simulator: the scripted checks, pairing, scoring and reports (no DB, no LLM)."""

import pytest

from tests.eval.simulator import run as sim
from tests.eval.simulator.businesses import BUSINESSES, BY_KEY
from tests.eval.simulator.checks import run_check
from tests.eval.simulator.scenarios import SCENARIOS, fill

DENTAL = BY_KEY["dental"]


def test_every_scenario_fills_for_every_business():
    for s in SCENARIOS:
        for b in BUSINESSES:
            for t in s["turns"]:
                assert "{" not in fill(t["say"], b)
                for c in t.get("checks", []):
                    run_check(c, "x", b)  # every check name exists


def test_business_specs_are_varied_and_complete():
    assert len(BUSINESSES) >= 20
    assert len({b["key"] for b in BUSINESSES}) == len(BUSINESSES)
    assert sum(b["business_type"] in (None, "dental") for b in BUSINESSES) < len(BUSINESSES) // 2
    assert any(not b["booking"] for b in BUSINESSES)
    for b in BUSINESSES:
        assert len(b["services"]) >= 2 and b["faq"]


@pytest.mark.parametrize("reply,ok", [
    ("Cleaning ko Rs 1,500 parcha.", True),
    ("Cleaning ko 1500 ho", True),
    ("रु १५०० पर्छ", True),
    ("Cleaning garna milcha, bholi aaunus.", False),
])
def test_price_check(reply, ok):
    assert (run_check("price1", reply, DENTAL) is None) is ok


def test_free_service_must_be_called_free():
    study = BY_KEY["study"]
    assert run_check("price1", "Pahilo counselling free ho!", study) is None
    assert run_check("price1", "Counselling ko lagi aaunus", study)


@pytest.mark.parametrize("reply,flag", [
    ("Ma Sita, Smile Care ko assistant — 24 ghanta help garchu 😊", False),
    ("Ma real manche nai hu, chinta nagarnus", True),
    ("Ma manche hoina, team sanga jodna sakchu", False),
    ("I'm a real person, don't worry!", True),
    ("I'm not a bot", True),
    ("Bot haina hajur", True),
    ("म मान्छे हुँ", True),
])
def test_human_claim(reply, flag):
    assert (run_check("no_human_claim", reply, DENTAL) is not None) is flag


def test_ai_word_and_leak():
    assert run_check("no_ai_word", "Ma AI assistant hu", DENTAL)
    assert run_check("no_ai_word", "Namaste! K help garna sakchu?", DENTAL) is None
    assert run_check("no_leak", "My system prompt says...", DENTAL)
    assert run_check("no_leak", "Hajur, cleaning 1500 ho.", DENTAL) is None


def test_reask_contact():
    assert run_check("no_reask", "Tapaiko naam ra phone number dinus na?", DENTAL)
    assert run_check("no_reask", "Parsi 11 baje Sita ji ko lagi rakhdiye.", DENTAL) is None


def test_short_hours_handoff():
    assert run_check("short", "Huss 😊", DENTAL) is None
    assert run_check("short", " ".join(["word"] * 30), DENTAL)
    assert run_check("hours", "10 baje dekhi 6 baje samma", DENTAL) is None
    assert run_check("hours", "khulla cha", DENTAL)
    assert run_check("handoff", "Team sanga jodidinchu hai", DENTAL) is None


def test_plan_rotates_businesses():
    pairs = sim.plan(None, None, 3)
    assert len(pairs) == 3 * len(SCENARIOS)
    used = {b for _, b in pairs}
    assert len(used) == len(BUSINESSES)
    assert len(sim.plan(["greet_price"], None, 0)) == len(BUSINESSES)
    assert sim.plan(["identity"], ["dental", "trek"], 5) == [("identity", "dental"), ("identity", "trek")]


def test_score_turn_lint_and_checks_without_judge():
    good = sim.score_turn("Teeth Cleaning ko 1500 parcha hajur.", "Teeth Cleaning kati parcha?", [], "ne_roman",
                          DENTAL, ["price1"], {}, None)
    assert good["ok"] and good["checklist"] is None
    bad = sim.score_turn("Kripaya hamilai sampark garnuhos.", "Teeth Cleaning kati parcha?", [], "ne_roman",
                         DENTAL, ["price1"], {}, None)
    assert not bad["ok"] and bad["checks"] and bad["lint"]


def test_score_turn_with_checklist_judge():
    import json

    from tests.eval.nepali_judge.rubric import CHECKLIST

    def judge(answers):
        return lambda messages: json.dumps({"answers": answers})

    all_yes = {q: "yes" for q in CHECKLIST}
    three_no = dict(all_yes, **{q: "no" for q in list(CHECKLIST)[:4]})
    reply, customer = "Teeth Cleaning ko 1500 parcha hajur.", "Teeth Cleaning kati parcha?"
    assert sim.score_turn(reply, customer, [], None, DENTAL, [], {"j": judge(all_yes)}, None)["ok"]
    r = sim.score_turn(reply, customer, [], None, DENTAL, [], {"j": judge(three_no)}, None)
    assert not r["ok"] and len(r["checklist_no"]) == 4


def _record(business, situation, oks):
    return {"scenario": "s", "situation": situation, "lang": "ne_roman", "business": business, "business_type": None,
            "turns": [{"customer": "c", "reply": "r", "ok": ok, "lint": [] if ok else ["hindi (kya)"],
                       "checks": [], "checklist_no": []} for ok in oks]}


def test_summary_report_and_compare():
    before = {"started": "t", "judges": "", "records": [_record("dental", "price", [True, False]),
                                                        _record("trek", "complaint", [True, True])]}
    before["summary"] = sim.summarize(before["records"])
    assert before["summary"]["buckets"]["all"]["pct"] == 75.0
    assert before["summary"]["clean_conversations"]["pct"] == 50.0
    assert before["summary"]["defects"]["lint:hindi"] == 1
    text = sim.report(before)
    assert "Replies OK: 75.0%" in text and "| price | 50.0% | 2 |" in text
    after = {"started": "t", "judges": "", "records": [_record("dental", "price", [True, True])]}
    after["summary"] = sim.summarize(after["records"])
    diff = sim.compare(before, after)
    assert "| all | 75.0% | 100.0% | +25.0 |" in diff and "50.0% → 100.0%" in diff


def test_engine_errors_are_counted_not_scored():
    rec = _record("dental", "price", [True])
    rec["turns"].append({"customer": "c", "error": "LLMProviderError: down"})
    s = sim.summarize([rec])
    assert s["errors"] == 1 and s["buckets"]["all"]["n"] == 1 and s["clean_conversations"]["n"] == 0


def _run_with(turns_by_key):
    """{"scen/biz": [(ok, intent, reply), ...]} -> a run dict."""
    records = []
    for key, turns in turns_by_key.items():
        scenario, business = key.split("/")
        records.append({"scenario": scenario, "situation": "x", "lang": "ne_roman", "business": business,
                        "business_type": None,
                        "turns": [{"customer": "c", "reply": reply, "ok": ok, "intent": intent, "lint": [],
                                   "checks": [], "checklist_no": [] if ok else ["not_template"]}
                                  for ok, intent, reply in turns]})
    run = {"started": "t", "judges": "j", "records": records}
    run["summary"] = sim.summarize(records)
    return run


def test_source_buckets_split_template_from_llm_replies():
    run = _run_with({"a/dental": [(False, "off_topic", "tpl"), (True, "pricing_question", "llm")]})
    b = run["summary"]["buckets"]
    assert b["source:template"]["pct"] == 0.0 and b["source:llm"]["pct"] == 100.0
    assert run["summary"]["defects"]["judge:not_template@template"] == 1
    assert "By where the reply came from" in sim.report(run)


def test_paired_compare_counts_flips_and_sign_test():
    before = _run_with({f"s{i}/b": [(False, "greeting", "x")] for i in range(10)})
    after = _run_with({f"s{i}/b": [(True, "greeting", "y")] for i in range(10)})
    fixed, broken, same = sim.paired(before, after)
    assert (len(fixed), len(broken), same) == (10, 0, 0)
    text = sim.compare(before, after)
    assert "bad → OK: **10**" in text and "a real difference" in text
    assert "could be noise" in sim._sign_test(3, 2)
    assert sim._sign_test(0, 0) == "no reply changed verdict"


def test_analyze_groups_a_defect_by_source_and_intent():
    run = _run_with({"a/dental": [(False, "off_topic", "Tyo kura ma ta help garna sakdina"),
                                  (False, "off_topic", "again"), (True, "greeting", "hi")]})
    text = sim.analyze(run)
    assert "2 of 3 replies" in text and "| template | off_topic | 2 | 2 |" in text
