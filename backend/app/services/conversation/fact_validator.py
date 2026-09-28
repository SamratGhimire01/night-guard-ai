"""Deterministic post-generation grounding check for a drafted customer-facing reply.

Root cause (read-through of backend/data/regression/failure_log_batches/*.json, 23
unconfigured_fact + 4 invented_policy findings across 620 real/synthetic regression
cases): the model is handed correct config/knowledge every turn (services, prices,
deposit flags, business hours, retrieved knowledge) but sometimes states something else
anyway -- a deposit policy on a service that doesn't have one, a price in the wrong
currency, a day marked closed that's actually open, a phone number that matches nothing
it was ever given. This is "model override," not "gap-filling": the fix is a grounding
check against the SAME context already assembled for that turn, not a second retrieval
pass.

Deliberately narrow: catches claims of a specific, checkable SHAPE (a price, a percent,
a phone number, a weekday's open/closed status) that don't match anything in context.
It does NOT catch omissions (a real payment method that exists but wasn't mentioned) --
those aren't invented facts, and flagging them would require re-deriving "what should
this reply have said," a much harder problem than "is what it did say grounded."

Used by both the live orchestrator (pre-send guard, see orchestrator._handle_turn) and
the regression suite (backend/tests/eval/test_regression_suite.py) -- one set of rules,
checked the same way in both places, so a passing regression case is a true guarantee
about production behavior, not a parallel reimplementation that could drift.
"""

import re

_PRICE_RE = re.compile(r"(USD|NPR|Rs\.?|\$)\s?([0-9]+(?:[.,][0-9]+)?)")
_PERCENT_RE = re.compile(r"\b([0-9]{1,3})\s?%")
# No whitespace inside the digit run -- every real phone number in this dataset is
# dash-separated with no spaces ("+977-1-4781234"); allowing whitespace let a date+time
# ("2026-09-27 09:00") get matched as one long digit run and misread as a phone number.
_PHONE_RE = re.compile(r"\+?[0-9][0-9\-]{7,}[0-9]")
_ISO_DATE_RE = re.compile(r"^\d{4}-\d{1,2}-\d{1,2}")
_DEPOSIT_WORDS = ("deposit", "advance payment", "advance deposit")

_CURRENCY_SYMBOLS = {"USD": {"USD", "$"}, "NPR": {"NPR", "Rs", "Rs."}}

_URL_RE = re.compile(r"https?://\S+")
_UUID_RE = re.compile(r"\b[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}\b", re.I)
_SNAKE_CASE_RE = re.compile(r"\b[a-z]+(?:_[a-z]+){1,}\b")
# "e_sewa"/"e_mail" are real, correctly-spelled words in this dataset's Romanized Nepali/English replies, not an
# internal field name leaking through.
_SNAKE_CASE_ALLOW = {"e_sewa", "e_mail"}

# Confirmed regression (Test Chat Biz, batch5_testchat_misc.json): the model told a
# customer "no services are currently configured" while `services` (handed to it this
# same turn via _format_services) was non-empty -- a hallucinated absence of real,
# already-given config, the same "model override" failure mode as the price/hours/phone
# checks above, just with no existing check for this specific claim shape.
_NO_SERVICES_RE = re.compile(
    r"\bno\s+services?\b.{0,40}\bconfigured\b"
    r"|\bservices?\b.{0,60}\bconfigured\b.{0,20}\b(chaina|xaina)\b",
    re.I,
)

# Phase 2 (style exemplars): a style_exemplars row's `text` deliberately embeds
# placeholder tokens like {PRICE}/{TIME}/{NAME} in place of any real fact (see
# StyleExemplar's docstring) -- the LLM is instructed (intent.py's "Example
# replies" prompt section) to use these only as a tone illustration, never to
# copy a placeholder verbatim into `response`. A literal "{PRICE}"-shaped token
# surviving into a real reply means it leaked through unfilled -- zero
# tolerance, same regenerate-once-then-fallback pattern as every other check
# in this module. No legitimate reply ever contains a literal curly brace.
_UNFILLED_SLOT_RE = re.compile(r"\{[A-Z_]+\}")


def check_unfilled_slots(reply: str) -> list[str]:
    return [f"reply contains an unfilled placeholder token: {m}" for m in _UNFILLED_SLOT_RE.findall(reply)]


_WEEKDAY_NAMES = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"]
_CLOSED_WORDS = re.compile(r"\b(closed|band|bandha|bandh)\b", re.I)
_OPEN_WORDS = re.compile(r"\b(open|khula|khuli)\b", re.I)
# "nothing open on Saturday" / "I don't see anything open" describe availability (slots
# full), not the day's open/closed status -- only a negation-free "open" is a real claim
# that the day itself is open.
_OPEN_NEGATION_RE = re.compile(r"\b(nothing|no|not|n't|don't|doesn't|didn't)\b", re.I)
# Split only on strong sentence/contrast boundaries, never on a bare comma or "and"/"ra"
# ("and", Romanized Nepali) -- "Saturday ra Sunday closed" (the confirmed bug: one shared
# status word covering both days) must stay one clause so Sunday's contradiction is still
# caught, while "Saturday is closed, but open Sunday" (a correct, differentiated
# statement) must split apart so Sunday's "open" doesn't get misattributed to Saturday.
_CLAUSE_SPLIT_RE = re.compile(r"[.!?।—]|\bbut\b|\btara\b|\bhowever\b", re.I)


def _normalize_amount(raw: str) -> float | None:
    try:
        return round(float(raw.replace(",", "")), 2)
    except ValueError:
        return None


def check_price_and_deposit(
    reply: str, *, currency: str, services: list[dict], known_text: str = ""
) -> list[str]:
    """`services`: each a dict with name/price/deposit_enabled/deposit_percentage. A price
    that appears verbatim in `known_text` (an approved knowledge-base doc, e.g. one
    authored in a different currency than the business's default) is trusted rather than
    flagged -- it's not invented, it's a real value the business chose to write down."""
    violations: list[str] = []
    lower = reply.lower()
    configured_prices = {round(float(s["price"]), 2) for s in services}
    accepted_symbols = _CURRENCY_SYMBOLS.get(currency, {currency})

    for symbol, amount_str in _PRICE_RE.findall(reply):
        amount = _normalize_amount(amount_str)
        if amount is None or amount == 0:
            continue
        if f"{symbol}{amount_str}" in known_text or f"{symbol} {amount_str}" in known_text:
            continue
        if symbol not in accepted_symbols:
            violations.append(
                f"reply states a price using {symbol!r}, but this business's configured currency is {currency}"
            )
            continue
        if amount in configured_prices:
            continue
        is_valid_deposit = any(
            s.get("deposit_enabled") and s.get("deposit_percentage")
            and abs(amount - float(s["price"]) * float(s["deposit_percentage"]) / 100) < 1
            for s in services
        )
        if not is_valid_deposit:
            violations.append(f"reply states price {symbol}{amount_str} matching no configured service price or deposit")

    no_deposit_names = [s["name"].lower() for s in services if not s.get("deposit_enabled")]
    if any(k in lower for k in _DEPOSIT_WORDS):
        for name in no_deposit_names:
            if name and name in lower:
                violations.append(
                    f"reply claims a deposit/advance-payment requirement while discussing {name!r}, "
                    f"whose deposit_enabled is False for this tenant"
                )
        configured_pcts = {
            round(float(s["deposit_percentage"]))
            for s in services if s.get("deposit_enabled") and s.get("deposit_percentage")
        }
        for pct_str in _PERCENT_RE.findall(reply):
            if int(pct_str) not in configured_pcts:
                violations.append(
                    f"reply states a {pct_str}% deposit not matching any configured deposit percentage"
                )

    return violations


def check_weekday_hours(reply: str, *, hours_by_day: dict[int, bool] | None) -> list[str]:
    """`hours_by_day`: day_of_week (0=Monday..6=Sunday) -> closed bool. None/empty
    (no hours configured for this tenant) means there's nothing real to contradict."""
    if not hours_by_day:
        return []
    violations = []
    for clause in _CLAUSE_SPLIT_RE.split(reply):
        says_closed = _CLOSED_WORDS.search(clause)
        says_open = _OPEN_WORDS.search(clause) and not _OPEN_NEGATION_RE.search(clause)
        if not says_closed and not says_open:
            continue
        for day_index, name in enumerate(_WEEKDAY_NAMES):
            if not re.search(rf"\b{name}\b", clause, re.I):
                continue
            actual_closed = hours_by_day.get(day_index, True)
            if says_closed and not actual_closed:
                violations.append(f"reply claims {name} is closed, but this tenant's configured hours show it open")
            elif says_open and actual_closed:
                violations.append(f"reply claims {name} is open, but this tenant's configured hours show it closed")
    return violations


def check_no_internal_ids(reply: str) -> list[str]:
    """Root-cause fix for 21 of 30 id_leak findings (read-through of
    backend/data/regression/failure_log_batches/*.json): the customer-facing "Your booking
    ID is ..." confirmation was reading out the raw internal DB UUID -- never meant for a
    customer. Since Phase 55 the ONLY appointment identifier ever shown to a customer is
    Appointment.confirmation_code (app.db.models.appointment.generate_confirmation_code), a short,
    unambiguous, non-internal string -- so any raw UUID or snake_case-shaped internal field
    name surviving in a reply is a real regression, not a legitimate reference number.

    URLs are stripped before scanning: a functional link the customer is meant to click
    (check-in QR, payment redirect) necessarily embeds an opaque id/token in its path --
    that's normal web plumbing the customer never reads or copies, not the kind of leak
    this checks for (a raw identifier shown IN PROSE as if it were a friendly reference)."""
    prose = _URL_RE.sub("", reply)
    violations = []
    match = _UUID_RE.search(prose)
    if match:
        violations.append(f"reply leaks a raw internal UUID: {match.group(0)}")
    for token in _SNAKE_CASE_RE.findall(prose):
        if token not in _SNAKE_CASE_ALLOW:
            violations.append(f"reply leaks an internal-looking snake_case token: {token!r}")
    return violations


def check_grounded_phone_numbers(reply: str, *, known_text: str) -> list[str]:
    """A phone-number-shaped string in the reply must appear (digits-only match) in the
    real context given this turn (business fields + retrieved knowledge) -- otherwise
    it's not read off anything real."""
    known_digits = {re.sub(r"\D", "", m) for m in _PHONE_RE.findall(known_text)}
    violations = []
    for match in _PHONE_RE.findall(reply):
        if _ISO_DATE_RE.match(match):
            continue  # "2026-09-27" (a booked/proposed slot date) is shaped like a phone number, isn't one
        digits = re.sub(r"\D", "", match)
        if len(digits) < 7:
            continue
        if not any(digits in known or known in digits for known in known_digits if known):
            violations.append(f"reply states phone number {match!r}, which matches no phone number given this turn")
    return violations


def check_no_services_claim(reply: str, *, services: list[dict]) -> list[str]:
    """`services` non-empty means the model was handed a real, non-empty service list
    this same turn (_format_services) -- so a reply claiming none are configured is
    invented, not an honest gap."""
    if not services:
        return []
    if _NO_SERVICES_RE.search(reply):
        return [f"reply claims no services are configured, but this tenant has {len(services)} configured service(s)"]
    return []


def check_response_facts(
    reply: str,
    *,
    currency: str,
    services: list[dict],
    hours_by_day: dict[int, bool] | None,
    known_text: str,
) -> list[str]:
    return [
        *check_price_and_deposit(reply, currency=currency, services=services, known_text=known_text),
        *check_weekday_hours(reply, hours_by_day=hours_by_day),
        *check_grounded_phone_numbers(reply, known_text=known_text),
        *check_no_internal_ids(reply),
        *check_no_services_claim(reply, services=services),
        *check_unfilled_slots(reply),
    ]


def _demo() -> None:
    services = [
        {"name": "Tooth Filling", "price": 1200, "deposit_enabled": True, "deposit_percentage": 1},
        {"name": "Root Canal Treatment", "price": 8000, "deposit_enabled": False, "deposit_percentage": None},
    ]
    hours = {5: True, 6: False}  # Saturday closed, Sunday open

    # The confirmed Samaj Dental Clinic bug: invented 20% deposit on a service that has none.
    assert check_price_and_deposit(
        "Root Canal Treatment costs $8000, and a 20% advance deposit is required.",
        currency="NPR", services=services,
    )
    # Correctly-configured deposit must NOT trip the check.
    assert not check_price_and_deposit(
        "Tooth Filling is NPR 1200, with a 1% deposit due at booking.", currency="NPR", services=services,
    )
    # Wrong currency symbol for an NPR-configured tenant.
    assert check_price_and_deposit("That's $1200 for the filling.", currency="NPR", services=services)
    # A real config price in the right currency must pass clean.
    assert not check_price_and_deposit("That's NPR 1200 for the filling.", currency="NPR", services=services)
    # A price in a DIFFERENT currency than the tenant default, but verbatim in an approved
    # knowledge-base doc (a real, human-authored value), must not be flagged -- staff wrote
    # it that way on purpose (confirmed regression: test_training_direct_qa.py's authored
    # "NPR 12000" answer for a USD-currency tenant).
    assert not check_price_and_deposit(
        "Yes, that's NPR 12000.", currency="USD", services=services, known_text="...NPR 12000 for whitening..."
    )

    # The confirmed "Sat+Sun both closed" bug: Sunday is actually open.
    assert check_weekday_hours("Saturday ra Sunday clinic closed huncha.", hours_by_day=hours)
    # Correct statement of the same real hours must not trip it.
    assert not check_weekday_hours("Saturday is closed, but we're open Sunday.", hours_by_day=hours)
    # "nothing open on Saturday" describes availability, not day status -- must not misfire.
    assert not check_weekday_hours("There's nothing open for Cleaning on Saturday.", hours_by_day=hours)

    # A phone number grounded in this turn's real knowledge/context passes.
    assert not check_grounded_phone_numbers(
        "Our number is +977-1-4781234.", known_text="Phone: +977-1-4781234, New Baneshwor"
    )
    # A phone number with no match anywhere in context is flagged as invented.
    assert check_grounded_phone_numbers("Our number is +977-51-522345.", known_text="Phone: +977-1-4781234")
    # A slot date/date+time ("2026-09-27", "2026-09-27 09:00") is phone-shaped but isn't a
    # phone number -- confirmed regression: booking replies falsely flagged as invented contact info.
    assert not check_grounded_phone_numbers("Booked for 2026-09-27 09:00.", known_text="")
    assert not check_grounded_phone_numbers("Booked for 2026-09-27.", known_text="")

    # The confirmed bug: a raw internal UUID read out as if it were a friendly reference.
    assert check_no_internal_ids("Your booking ID is 69403613-e573-4d76-8ac1-071647061bf4.")
    # The Phase 55 fix: a short customer-facing confirmation code must never trip it.
    assert not check_no_internal_ids("Your booking ID is 7K3QXF9.")
    # An internal snake_case field name leaking through must be flagged.
    assert check_no_internal_ids("Sorry, tenant_id lookup failed for that request.")
    # A functional check-in/payment link legitimately embeds an opaque id/token in its URL --
    # that's normal web plumbing, not this category of leak.
    assert not check_no_internal_ids(
        "Here's your check-in link: http://example.com/qr/21955948be74468fa8da57f825d7a37c.1789962300.s-odXDUUAbJDOTsM3wnpFw"
    )

    # The confirmed Test Chat Biz bug: claiming no services exist while 4 are configured.
    assert check_no_services_claim(
        "ahile hamro system ma kunai services configured bhayeko chaina, tesaile ma services ko list din sakdina.",
        services=services,
    )
    assert check_no_services_claim("Sorry, no services are currently configured.", services=services)
    # A real, honest "no services configured" statement for a tenant with none must NOT trip it.
    assert not check_no_services_claim("Sorry, no services are currently configured.", services=[])
    # Any other real reply about the actual configured services must not misfire.
    assert not check_no_services_claim("We offer Tooth Filling and Root Canal Treatment.", services=services)

    # Phase 2: an unfilled exemplar placeholder leaking into a real reply is flagged.
    assert check_unfilled_slots("Sure -- that's {PRICE} and takes about {TIME}.")
    # A normal reply with real curly-brace-free text must not misfire.
    assert not check_unfilled_slots("Sure -- that's NPR 1200 and takes about 30 minutes.")

    print("fact_validator self-check: all assertions passed")


if __name__ == "__main__":
    _demo()
