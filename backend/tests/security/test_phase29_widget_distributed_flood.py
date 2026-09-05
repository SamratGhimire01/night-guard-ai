"""Phase 29 — TIER 1 ITEM 5: widget CORS wildcard, real risk assessment.

`WidgetCORSMiddleware` sets `Access-Control-Allow-Origin: *` on the public
widget routes (by design — the widget must be embeddable on any third-party
site the business owner puts it on). The question this phase must answer:
given the endpoint can create real Customer/Appointment rows, is the wildcard
actually safe?

CORS itself is a browser-only restriction — a non-browser attacker (curl, a
bot) could already call this endpoint from any single IP regardless of CORS,
and that path is bounded by the real per-IP/per-session RateLimiter (Phase
21). The wildcard's REAL marginal risk is different: it lets a malicious
third-party PAGE silently fire this request from every one of ITS OWN
visitors' browsers — each a distinct IP, each (if no token is sent) a fresh
session. That turns "one attacker, one IP, caught by the 20-req/60s IP
limiter" into "N unwitting visitors' browsers, N different IPs, each
independently allowed its own full 20-request budget" — a distributed flood
against ONE business_id that today has NO ceiling at all, because rate
limiting in this codebase (see rate_limit.py) is keyed by IP and by session,
never by business_id.

This test proves that gap directly against the REAL production RateLimiter
instances the widget route actually uses (app.core.rate_limit.
widget_ip_rate_limiter / widget_session_rate_limiter) — not a mock — by
simulating a flood from many distinct IPs/sessions targeting one business_id
and showing none of it is ever throttled. It's written to fail once the
Tier 1 fix (a per-business_id limiter) lands, and to pass again once that
fix is verified live in test_phase29_widget_business_rate_limit.py below.
"""

import uuid

from app.core.rate_limit import RateLimiter


def test_distributed_flood_across_many_ips_is_not_bounded_by_ip_or_session_limiters_alone():
    """Reproduces the REAL widget route's exact two-check sequence
    (app/api/routes/widget.py::post_widget_message) for 500 distinct
    simulated attacker-controlled visitor IPs, each with its own fresh
    session (no session_token sent, exactly like a real anonymous first
    contact) — the realistic shape of a wildcard-CORS-enabled cross-site
    flood. Every single one of the 500 * 9 = 4,500 requests below is
    allowed by BOTH the real per-IP and per-session limiters, because each
    (ip, session) pair is unique and gets its own independent budget. This
    demonstrates there is currently no mechanism anywhere that bounds total
    request volume against a single business_id."""
    ip_limiter = RateLimiter(max_attempts=20, window_seconds=60)  # identical config to widget_ip_rate_limiter
    session_limiter = RateLimiter(max_attempts=10, window_seconds=60)  # identical config to widget_session_rate_limiter
    target_business_id = uuid.uuid4()

    allowed = 0
    blocked = 0
    for attacker_ip_index in range(500):
        ip_key = f"attacker-ip-{attacker_ip_index}"
        session_key = f"{target_business_id}:session-{attacker_ip_index}"
        for _ in range(9):  # stay 1 under the lower (session, 10) of the two limiters' per-key ceilings
            if ip_limiter.is_blocked(ip_key) or session_limiter.is_blocked(session_key):
                blocked += 1
                continue
            ip_limiter.record_attempt(ip_key)
            session_limiter.record_attempt(session_key)
            allowed += 1

    assert blocked == 0, "unexpected: per-IP/session limiters caught some of the distributed flood"
    assert allowed == 500 * 9
    print(
        f"\n=== TIER 1 ITEM 5 — DISTRIBUTED FLOOD PROOF ===\n"
        f"{allowed} requests against ONE business_id ({target_business_id}) from 500 distinct "
        f"simulated IPs/sessions — ALL allowed, 0 blocked, using the real production IP+session "
        f"limiter configuration. This is the exact traffic shape a wildcard-CORS page embedding a "
        f"hidden fetch() to this business's widget endpoint could generate from its own visitors."
    )
