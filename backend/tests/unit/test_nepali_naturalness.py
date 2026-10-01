"""Natural-voice pass (2026-10-01): the Romanized Nepali word bank, the template wordings, the no-repeat rule, the reply
finalizer's guards, and Nepali-style dates. No DB, no LLM."""

import csv
import string
from datetime import datetime, time
from pathlib import Path

import pytest

from app.services.conversation import response_templates as rt
from app.services.conversation.intent import _build_system_prompt
from app.services.conversation.nepali_wordbank import (
    NATURAL,
    customer_spelling_style,
    find_issues,
    mirror_spelling,
    polish_reply,
)
from app.services.conversation.reply_polish import finalize_reply

EXEMPLARS = Path(__file__).resolve().parents[2] / "data" / "style_exemplars" / "seed_v1.csv"


# --- word bank ---------------------------------------------------------------------------------------------------------


def test_word_bank_is_a_real_arsenal():
    assert sum(len(v) for v in NATURAL.values()) >= 250
    for group in ("greet", "acknowledge", "time", "question", "booking", "softeners", "money", "empathy"):
        assert NATURAL[group], group
    for word in ("huss", "la", "pakka", "bholi", "parsi", "kaile", "sadhe 10 baje", "dedh baje", "milaidinchu", "ni"):
        assert any(word in words for words in NATURAL.values()), word
    natural_text = " ".join(w for words in NATURAL.values() for w in words)
    assert not find_issues(natural_text), "the natural list must not contain a never-use word"


@pytest.mark.parametrize(
    "bad, good",
    [
        ("Maaf garnuhos, ali problem bhayo.", "Sorry, ali problem bhayo."),
        ("Kripaya tapaiko naam dinuhos.", "Tapaiko naam dinus."),
        ("Kun samaya milcha?", "Kun time milcha?"),
        ("Aagami hapta ma aaunuhos.", "Aune hapta ma aaunus."),
        ("Payment prapta bhayo.", "Payment aayo."),
        ("Kahan cha?", "Kaha cha?"),
        ("Bilkul milcha.", "Pakka milcha."),
        ("Kehi bhena.", "Kehi bhayena."),
        ("Hamiले book garyau.", "Hamile book garyau."),
        ("Ma madat garna chu.", "Ma help garna yaha chu."),
        ("Kun din aauna chahanu huncha?", "Kun din aauna man cha?"),
        ("Phone number dina sakinu huncha?", "Phone number dina milcha?"),
        ("Harek vyakti ko lagi janakari chahincha.", "Harek jana ko lagi info chahincha."),
    ],
)
def test_never_use_words_are_swapped_for_what_people_actually_type(bad, good):
    text, changes = polish_reply(bad)
    assert text == good
    assert changes


def test_polish_never_touches_names_links_ids_or_numbers():
    reply = "Samaya Dental ma {when} 10:30 baje book bhayo. Link: https://x.example/abhi/samaya ID: AB12CD3 Rs 1500."
    text, _ = polish_reply(reply, protected=["Samaya Dental"])
    assert text == reply


def test_spelling_mirrors_the_customer():
    assert customer_spelling_style(["k xa hajur", "voli milxa?"]) == "x"
    assert customer_spelling_style(["k cha", "bholi milcha?"]) == "ch"
    assert customer_spelling_style(["hello", "price?"]) == "ch", "no signal keeps the default"
    assert mirror_spelling("Milcha! Tyo bhayo, ahile check garchu.", "x") == "Milxa! Tyo vayo, aile check garxu."
    assert mirror_spelling("Check the chat, change it.", "x") == "Check the chat, change it.", "English is never touched"


# --- templates -----------------------------------------------------------------------------------------------------------


def _placeholders(text: str) -> set[str]:
    return {f for _, f, _, _ in string.Formatter().parse(text) if f}


def test_every_romanized_template_wording_is_natural():
    for name in rt.TEMPLATES:
        for wording in rt.variants(name, "ne_roman"):
            assert not find_issues(wording), (name, wording, find_issues(wording))


def test_every_wording_of_a_template_carries_the_same_facts():
    for name, langs in rt.TEMPLATES.items():
        for lang in langs:
            sets = [_placeholders(v) for v in rt.variants(name, lang)]
            assert all(s == sets[0] for s in sets), (name, lang, sets)


def test_the_most_repeated_asks_have_several_wordings():
    for name in ("booking_no_contact", "booking_gate_with_progress", "booking_clarify", "off_topic",
                 "availability_options", "handoff_addendum", "requested_time_unavailable", "booking_ask_missing"):
        for lang in ("en", "ne_deva", "ne_roman"):
            assert len(rt.variants(name, lang)) >= 3, (name, lang)


def test_render_never_sends_the_same_fixed_text_twice_in_one_chat():
    assert rt.render("booking_no_contact", "ne_roman") == rt.variants("booking_no_contact", "ne_roman")[0]
    history: list[str] = []
    seen = []
    for _ in range(len(rt.variants("booking_no_contact", "ne_roman"))):
        with rt.reply_history(history):
            text = rt.render("booking_no_contact", "ne_roman")
        seen.append(text)
        history.append(text)
    assert len(set(seen)) == len(seen), "every wording used once before any repeats"
    with rt.reply_history(history):
        assert rt.render("booking_no_contact", "ne_roman") == seen[0], "then the one used longest ago"


def test_render_recognises_a_wording_after_the_spelling_mirror():
    first = rt.variants("booking_no_contact", "ne_roman")[0]
    with rt.reply_history([mirror_spelling(first, "x")]):
        assert rt.render("booking_no_contact", "ne_roman") != first


def test_second_contact_ask_is_shorter():
    wordings = rt.variants("booking_no_contact", "ne_roman")
    assert len(wordings[1]) < len(wordings[0]) and len(wordings[2]) < len(wordings[0])


def test_fixed_off_topic_and_clarify_no_longer_sound_like_a_government_office():
    assert "Maaf garnuhos" not in " ".join(rt.variants("booking_clarify", "ne_roman"))
    assert rt.variants("booking_clarify", "ne_roman")[0] == "Sorry, ali bujhina — kun service ho, ra kaile aauna milcha?"
    assert "madat garna chu" not in " ".join(rt.variants("off_topic", "ne_roman"))


# --- dates -----------------------------------------------------------------------------------------------------------------


@pytest.mark.parametrize(
    "hour, minute, expected",
    [
        (10, 0, "bihana 10 baje"),
        (10, 30, "bihana sadhe 10 baje"),
        (13, 30, "diuso dedh baje"),
        (14, 30, "diuso adhai baje"),
        (9, 15, "bihana sawa 9 baje"),
        (17, 45, "beluka 5:45 baje"),
        (20, 0, "raati 8 baje"),
    ],
)
def test_times_read_the_nepali_way(hour, minute, expected):
    assert rt.format_clock(time(hour, minute), "ne_roman") == expected


def test_dates_read_the_nepali_way_and_english_is_unchanged():
    dt = datetime(2026, 10, 5, 10, 0)
    assert rt.format_when(dt, "ne_roman") == "Sombar (Oct 5), bihana 10 baje"
    assert rt.format_when(dt, "mixed") == "Sombar (Oct 5), bihana 10 baje"
    assert rt.format_when(dt, "ne_deva") == "सोमबार (Oct 5), बिहान 10 बजे"
    assert rt.format_when(dt, "en") == "Monday, October 5 at 10:00 AM"
    slots = [datetime(2026, 10, 5, 9, 0), datetime(2026, 10, 5, 9, 30), datetime(2026, 10, 5, 14, 0)]
    assert rt.format_slot_list(slots, "ne_roman") == "Sombar (Oct 5) — bihana 9 baje, sadhe 9 baje, diuso 2 baje"
    assert rt.format_slot_list(slots, "en") == "Monday, October 5 at 9:00 AM, 9:30 AM, 2:00 PM"
    two_days = [datetime(2026, 10, 5, 9, 0), datetime(2026, 10, 5, 9, 30), datetime(2026, 10, 6, 10, 0)]
    assert rt.format_slot_list(two_days, "ne_roman") == (
        "Sombar (Oct 5) — bihana 9 baje, sadhe 9 baje; Mangalbar (Oct 6) — bihana 10 baje"
    )


# --- finalizer guards ------------------------------------------------------------------------------------------------------


def _finalize(text, previous=(), customer=(), language="en"):
    return finalize_reply(text, language=language, previous_replies=list(previous), customer_texts=list(customer),
                          protected=[])[0]


def test_filler_ending_is_dropped():
    assert _finalize("Cleaning is $90. Let me know if you have any questions.") == "Cleaning is $90."
    assert _finalize("Cleaning Rs 1500 parcha. Aru kehi chahiyo bhane bhannus.", language="ne_roman") == (
        "Cleaning Rs 1500 parcha."
    )


def test_offer_ending_survives_once_but_not_on_the_next_turns():
    first = "Cleaning is $90. Would you like me to check availability?"
    assert _finalize(first) == first
    assert _finalize("Whitening is $200. Would you like me to book one?", previous=[first]) == "Whitening is $200."


def test_same_opener_is_never_used_twice_in_a_row():
    assert _finalize("Got it — which day works?", previous=["Got it — cleaning it is."]) == "Which day works?"
    assert _finalize("Got it — which day works?", previous=["Sure, cleaning it is."]) == "Got it — which day works?"


def test_repeated_real_request_is_kept():
    ask = "Cleaning it is. I just need your name and a phone number or email to lock that in."
    assert _finalize(ask, previous=[ask]) == ask


def test_guards_never_empty_a_reply_or_break_a_list():
    assert _finalize("Let me know if you need anything.") == "Let me know if you need anything."
    listing = "Our services:\n- Cleaning\n- Whitening. Let me know if you have questions."
    assert _finalize(listing) == "Our services:\n- Cleaning\n- Whitening."


def test_romanized_reply_is_polished_and_mirrored():
    out = _finalize("Kripaya tapaiko naam dinuhos, ani turuntai book garchu.", customer=["voli milxa?"], language="ne_roman")
    assert out == "Tapaiko naam dinus, ani turuntai book garxu."
    english = "Please share your name."
    assert _finalize(english, language="en") == english, "English replies never go through the word bank"


# --- prompt and exemplars --------------------------------------------------------------------------------------------------


def test_prompt_carries_the_word_bank_and_no_broken_nepali():
    prompt = _build_system_prompt(None)
    assert "ROMANIZED NEPALI WORD BANK" in prompt
    for broken in ("Hamiले", "saknchu", "Aru kehi sahayog chahiyo bhane", 'address the customer as \\\n"hajur"'):
        assert broken not in prompt
    assert '"tapai"' in prompt and "never \"timi\"" in prompt


def test_style_exemplars_are_five_times_richer_and_natural():
    rows = list(csv.DictReader(EXEMPLARS.open(encoding="utf-8")))
    nepali = [r for r in rows if r["language"] in ("ne_roman", "mixed")]
    assert len([r for r in rows if r["language"] == "ne_roman"]) >= 80
    assert len(nepali) >= 120
    for r in nepali:
        assert not find_issues(r["text"]), (r["id"], r["text"])
    assert len({r["id"] for r in rows}) == len(rows)
    assert all("है" not in r["text"] for r in rows if r["language"] == "ne_deva"), "Hindi है is not Nepali"


def test_a_swap_never_matches_inside_another_word():
    # regression: an ungrouped "aaunuhos|aunuhos" turned "btaunuhos" into "btaaunus"
    assert polish_reply("btaunuhos")[0] == "Btaunus"
    assert polish_reply("Sahayogi staff")[0] == "Sahayogi staff"


def test_a_greeting_keeps_its_help_question():
    greeting = "Hi! Welcome to Samaj Dental. How can I help you today — book, or a question?"
    previous = ["Sure. Would you like me to check availability?"]
    assert finalize_reply(greeting, language="en", previous_replies=previous, customer_texts=[], protected=[],
                          intent="greeting")[0] == greeting
    assert _finalize(greeting, previous=previous) == greeting


# --- from the native review (2026-10-01) ---------------------------------------------------------------------------


def test_hindi_health_words_become_nepali():
    from app.services.conversation.nepali_wordbank import polish_reply

    fixed, _ = polish_reply("Anesthesia le dard hudaina, rakt ra khoon kabhi-kabhi aaucha.")
    assert fixed == "Anesthesia le dukhai hudaina, ragat ra ragat kahile kahi aaucha."


def test_phrases_that_need_a_human_rewrite_are_flagged_not_swapped():
    from app.services.conversation.nepali_wordbank import find_issues

    for phrase in ("Sunera man chhuttiyo", "bukha cha?", "record ma configured bhayeko chaina", "sacchai ko manche"):
        assert find_issues(phrase), phrase


def test_one_reply_is_never_written_in_two_spelling_styles():
    from app.services.conversation.nepali_wordbank import mirror_spelling

    mixed = "Thik xa — garo vayo vane bujhxu. Booking garna man cha bhane milxa."
    assert mirror_spelling(mixed, "ch") == "Thik cha — garo bhayo bhane bujhchu. Booking garna man cha bhane milcha."
    assert mirror_spelling(mixed, "x") == "Thik xa — garo vayo vane bujhxu. Booking garna man xa vane milxa."
    assert mirror_spelling("K help garum?", "ch") == "K help garum?"  # a bare "k" is never expanded


def test_slot_unavailable_replies_never_carry_the_internal_reason():
    from app.services.conversation.response_templates import TEMPLATES

    for name in ("booking_unavailable_with_alts", "booking_unavailable_no_alts"):
        for wordings in TEMPLATES[name].values():
            for text in wordings if isinstance(wordings, list) else [wordings]:
                assert "{message}" not in text


@pytest.mark.parametrize("template", ["cancellation_fail", "reschedule_fail"])
@pytest.mark.parametrize("message", [
    "Appointment not found.",
    "This appointment is already cancelled and cannot be cancelled.",
    "This appointment is already completed and cannot be rescheduled.",
    "Requested time is not available (outside business hours, on a closed date, or in the past).",
    "This slot was just booked by someone else — please choose another time.",
    "Some brand new internal error nobody mapped yet.",
])
@pytest.mark.parametrize("language", ["en", "ne_roman", "ne_deva"])
def test_tool_failures_never_leak_system_text(template, message, language):
    """Native review #5 (2026-10-01): "requested time is not available (outside business hours, ...)" pasted mid-Nepali.
    The cancel/reschedule tools' own messages must never reach the customer, in any language."""
    from app.services.conversation.response_templates import render

    reply = render(template, language, who="", message=message.rstrip(".").lower())
    assert message.rstrip(".").lower() not in reply.lower()
    for leak in ("internal", "requested time", "cannot be", "business hours", "appointment not found"):
        assert leak not in reply.lower(), reply
