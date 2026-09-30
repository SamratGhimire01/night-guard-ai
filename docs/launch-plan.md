# Launch-readiness plan (2026-09-30)

Goal: a business owner can sign up, set up, go live and run their day without help, and nothing in the product
promises something it doesn't do. Conversation quality work starts after this.

Source: the live audit in the UX review (every dashboard section driven in a real browser against the real backend
and database). Each item lists how it is verified; nothing counts as done until that check passes.

## Phase 1 — Fix what is broken or misleading

| # | Item | Done when |
|---|------|-----------|
| 1.1 | Knowledge Base and Training Room return a clear "AI service unavailable, try again" instead of crashing when the AI provider is unreachable | Integration test with a failing provider gets 503 + message; browser shows the message |
| 1.2 | Follow-ups run automatically (background scheduler) for businesses that turned them on; page copy says so | Scheduler test proves `run_followups` is called for enabled businesses only |
| 1.3 | New businesses get the currency that matches their time zone (Asia/Kathmandu → NPR) | Registration test |
| 1.4 | Plan: an owner can request an upgrade from the dashboard; Payments no longer says "ask an owner" to the owner; plan descriptions match what shipped | Endpoint test + browser check |
| 1.5 | Copy pass: no "real", no "patient", no developer terms on customer-facing screens | Grep check on the frontend |
| 1.6 | Friendly dates ("Today, 8:25 AM") instead of "9/30/2026, 8:25:15 AM" | Browser check |
| 1.7 | Prove the AI personality settings reach the AI's instructions | Integration test inspects the built system prompt |

## Phase 2 — What every owner needs

| # | Item | Done when |
|---|------|-----------|
| 2.1 | Setup checklist on the Overview (services, hours, knowledge, channel, website chat), ticking itself off | `GET /business/setup-status` test + browser check on a new business |
| 2.2 | Owner email alert when a conversation needs a person and when a customer books (on by default, can be turned off) | Tests with a fake mailer: one email per new handoff/booking, none when off, never blocks the chat reply |
| 2.3 | Forgot password (emailed link), reset page, change password in Settings | Tests: token works once, expires, old password stops working; browser flow |
| 2.4 | Team logins: owner adds admins/staff by email (they get a "set your password" link), changes roles, removes them | Tests incl. roles and tenant isolation; browser flow |
| 2.5 | Add an appointment from the dashboard (phone and walk-in bookings) | Browser flow creates a booking visible in the list |

## Phase 3 — Clarity

| # | Item | Done when |
|---|------|-----------|
| 3.1 | Fewer, clearer menu items: "Needs a person" lives in the Inbox; Reports and Analytics become one "Insights" page | Browser check; old URLs still work |
| 3.2 | Customers page: everyone who contacted the business, search, CSV export | Endpoint + tenant isolation tests; browser check |

## Phase 4 — Production hardening

| # | Item | Done when |
|---|------|-----------|
| 4.1 | Security headers on every response; refuse to start in production with a weak `SECRET_KEY` or wildcard CORS | Tests |
| 4.2 | Backend container runs as a non-root user and applies migrations on start | Dockerfile review + entrypoint script |
| 4.3 | Production frontend is a static build (not the Vite dev server) | Documented in `docs/deployment.md` |
| 4.4 | Real customer conversations are no longer tracked in git going forward | `.gitignore` + files untracked; history purge is a separate decision |
| 4.5 | Deployment checklist: env vars, backups, monitoring, HTTPS, Meta webhook setup | `docs/deployment.md` |

## Not in this batch, and why

- **One-click WhatsApp / Instagram / Messenger connection** needs a Meta app that has passed Meta's review, plus
  Tech Provider access. The code for WhatsApp Embedded Signup exists and switches on once those IDs are configured.
- **Self-serve paid plans** need a merchant agreement with eSewa or Khalti for recurring billing. The upgrade-request
  flow (1.4) covers launch.
- **Nepali dashboard** needs translations checked by a native speaker; the text is now plain enough to translate.
- **"Questions your AI couldn't answer" list, calendar view, phone app** are the first items after launch.
