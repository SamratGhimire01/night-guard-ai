"""The "speak" step: when it runs, and that a rewrite which changes any fact is never sent."""

import pytest

from app.core.config import settings
from app.services.conversation import voice_pass as vp


@pytest.fixture(autouse=True)
def _auto(monkeypatch):
    monkeypatch.setattr(settings, "voice_pass_mode", "auto")


class _Chat:
    def __init__(self, reply):
        self.reply, self.calls = reply, []

    def __call__(self, messages):
        self.calls.append(messages)
        if isinstance(self.reply, Exception):
            raise self.reply
        return self.reply


# --- when it runs -----------------------------------------------------------------------------------------------------


def test_clean_draft_is_left_alone():
    assert vp.needs_voice("Cleaning ko 1500 parcha hajur.", "cleaning kati?", "ne_roman") == []
    assert vp.needs_voice("Cleaning is Rs 1500.", "how much is cleaning?", "en") == []


def test_words_polish_fixes_alone_do_not_trigger_a_call():
    # "aap" is swapped to "tapai" by reply_polish deterministically -- no LLM needed for that
    assert vp.needs_voice("Aap lai 1500 parcha.", "kati?", "ne_roman") == []


@pytest.mark.parametrize("draft,customer,lang,reason", [
    ("Kya tapai bholi aauna sakchha?", "bholi milcha?", "ne_roman", "hindi"),
    ("Malai yo kura bujhna chahanchu.", "k ho?", "ne_roman", "textbook"),
    ("Hajur, the requested time is not available for you at this point.", "4 baje?", "ne_roman", "English sentence"),
    (" ".join(["word"] * 60), "hello there", "en", "too long"),
    ("I'm an AI assistant for Smile Care.", "hi", "en", "AI"),
])
def test_defects_trigger_it(draft, customer, lang, reason):
    reasons = vp.needs_voice(draft, customer, lang)
    assert reasons and reason.lower() in " ".join(reasons).lower()


def test_long_answer_to_an_explain_question_is_fine():
    assert vp.needs_voice(" ".join(["word"] * 60), "root canal vaneko k ho?", "ne_roman") == []


def test_ai_word_is_fine_when_the_customer_asked():
    assert vp.needs_voice("Ma AI assistant hu, tara team sanga jodna sakchu.", "tapai bot ho?", "ne_roman") == []


# --- what it accepts ---------------------------------------------------------------------------------------------------


@pytest.mark.parametrize("rewritten,why", [
    ("", "empty"),
    ("Cleaning ko 1600 parcha.", "numbers"),
    ("Cleaning ko 1500 parcha, 20% discount pani cha.", "numbers"),
    ("Cleaning ko 1500 parcha, info@x.com ma email garnus.", "links"),
    ("Tyo ko 1500 parcha.", "dropped"),
    ("Kya Teeth Cleaning ko 1500 parcha?", "not better"),
])
def test_unsafe_rewrites_are_rejected(rewritten, why):
    draft = "Teeth Cleaning ko lagi 1,500 rupaiya parcha. Kya aap aauna chahanchu?"
    assert why in (vp.accept_rewrite(draft, rewritten, "cleaning kati?", "ne_roman", ["Teeth Cleaning"]) or "")


def test_good_rewrite_is_accepted():
    draft = "Teeth Cleaning ko lagi 1,500 rupaiya parcha. Kya aap aauna chahanchu?"
    assert vp.accept_rewrite(draft, "Teeth Cleaning ko 1500 parcha hajur. Kaile aauna milcha?", "cleaning kati?",
                             "ne_roman", ["Teeth Cleaning"]) is None


def test_devanagari_digits_count_as_the_same_number():
    assert vp.accept_rewrite("सफाइको १५०० पर्छ। कृपया सम्पर्क गर्नुहोस्।", "सफाइको 1500 पर्छ।", "कति?", "ne_deva", []) is None


# --- revoice end to end --------------------------------------------------------------------------------------------------


def test_revoice_sends_the_rewrite_when_safe():
    chat = _Chat('"Teeth Cleaning ko 1500 parcha hajur. Kaile aauna milcha?"')
    out, info = vp.revoice("Teeth Cleaning ko 1500 parcha. Kya aap aana chahenge?", customer="cleaning kati?",
                           language="ne_roman", previous_reply=None, protected=["Teeth Cleaning"], chat=chat)
    assert out == "Teeth Cleaning ko 1500 parcha hajur. Kaile aauna milcha?" and info["used"]
    prompt = chat.calls[0][1]["content"]
    assert "cleaning kati?" in prompt and "Draft to rewrite" in prompt


def test_revoice_keeps_the_draft_when_unsafe_or_failing():
    draft = "Teeth Cleaning ko 1500 parcha. Kya aap aana chahenge?"
    out, info = vp.revoice(draft, customer="kati?", language="ne_roman", previous_reply=None, chat=_Chat("1400 parcha"))
    assert out == draft and "numbers" in info["rejected"]
    out, info = vp.revoice(draft, customer="kati?", language="ne_roman", previous_reply=None,
                           chat=_Chat(RuntimeError("timeout")))
    assert out == draft and "timeout" in info["error"]


def test_revoice_makes_no_call_for_a_clean_draft_or_when_off(monkeypatch):
    chat = _Chat("x")
    vp.revoice("Cleaning ko 1500 parcha.", customer="kati?", language="ne_roman", previous_reply=None, chat=chat)
    monkeypatch.setattr(settings, "voice_pass_mode", "off")
    vp.revoice("Kya aap aana chahenge?", customer="kati?", language="ne_roman", previous_reply=None, chat=chat)
    assert chat.calls == []


def test_always_mode_rewrites_clean_drafts_too(monkeypatch):
    monkeypatch.setattr(settings, "voice_pass_mode", "always")
    chat = _Chat("Cleaning ko 1500 ho hajur.")
    out, info = vp.revoice("Cleaning ko 1500 parcha.", customer="kati?", language="ne_roman", previous_reply=None,
                           chat=chat)
    assert len(chat.calls) == 1 and out == "Cleaning ko 1500 ho hajur."


def test_prompt_forbids_claiming_to_be_human_and_uses_examples():
    class Ex:
        text = "Huss, bholi 10 baje milcha!"

    msgs = vp._messages("draft", "cust", "prev", "ne_roman", ["hindi words: kya"], [Ex()])
    assert "Never say you are a human" in msgs[0]["content"]
    assert "Huss, bholi 10 baje milcha!" in msgs[1]["content"] and "prev" in msgs[1]["content"]
