"""Phase 34 — the real entitlement-checking mechanism every V2 premium feature
will gate on. Deliberately plain Python with zero FastAPI/Depends imports: the
ticket requires this to be usable BOTH as a route dependency (see
`require_plan` in app/api/dependencies.py, which wraps `ensure_plan` below)
AND directly inside the conversation orchestrator's tool logic, which never
runs inside FastAPI's dependency-injection system at all. One function, two
callers — never two separate implementations of the same check.
"""

from app.core.exceptions import PlanRequiredError
from app.db.models.business import Business, BusinessPlan

# Ordinal rank, not just set membership — lets a future third tier slot in
# between FREE and PREMIUM (or above it) without every call site needing to
# change, since `plan_meets_minimum` only ever compares ranks.
_PLAN_RANK: dict[BusinessPlan, int] = {
    BusinessPlan.FREE: 0,
    BusinessPlan.PREMIUM: 1,
}

# What each plan includes, shown on the dashboard's Plan tab (GET /business/plan). List only what is built and gated:
# Premium = require_plan(PREMIUM) on Google Calendar, payments and yearly reports, plus SMS.
PLAN_FEATURES: dict[BusinessPlan, list[str]] = {
    BusinessPlan.FREE: [
        "AI assistant on WhatsApp, Messenger, Instagram and your website",
        "Bookings, rescheduling and cancellations in chat",
        "Email confirmations, reminders and follow-ups",
        "Inbox with human takeover",
        "Daily and monthly reports",
    ],
    BusinessPlan.PREMIUM: [
        "Everything in Free",
        "Online deposits through eSewa and Khalti",
        "Google Calendar sync",
        "SMS confirmations and reminders",
        "Yearly reports with year-over-year comparison",
    ],
}


def plan_meets_minimum(plan: BusinessPlan, minimum: BusinessPlan) -> bool:
    return _PLAN_RANK[plan] >= _PLAN_RANK[minimum]


def ensure_plan(business: Business | None, minimum: BusinessPlan) -> None:
    """Raises PlanRequiredError unless `business` is real AND its plan meets
    `minimum`. `business is None` fails closed (never grants access just
    because the business couldn't be resolved) — same "never guess, never
    silently allow" discipline as every other gate in this codebase (the
    contact-info gate, the booking-draft resolution, etc.).

    This is the ONE place a plan check actually happens — `require_plan`
    (the FastAPI route dependency) and the conversation orchestrator's test
    hook (Phase 34) both call this exact function, never re-implement the
    comparison themselves."""
    if business is None or not plan_meets_minimum(business.plan, minimum):
        current = business.plan.value if business is not None else "none"
        raise PlanRequiredError(
            f"This feature requires the {minimum.value} plan (current plan: {current})."
        )
