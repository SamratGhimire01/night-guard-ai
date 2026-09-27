# Night Guard AI — Frontend API Contract

**Status:** Phase 28. Documents every business-facing endpoint that exists in the
codebase today, as of commit `3381280` (Phase 27) plus two small Phase 28 fixes
(see "Phase 28 fixes" below). Every request/response example on this page is a
**real** call against a running instance (`docker compose up`, base URL
`http://localhost:8010`), not invented. Timestamps in examples reflect the date
this doc was written (2026-09-04/05); nothing about their *shape* is cherry-picked.

Machine-readable spec: **`GET /openapi.json`** (not `/api/v1/openapi.json` — see
Finding F1 below). Interactive docs: `GET /docs`.

## 0. Conventions

- **Base path:** all business-facing routes are under `/api/v1`. Channel webhooks
  (`/api/v1/webhooks/*`) and the widget (`/widget.js`, `/api/v1/widget/{business_id}/messages`)
  are the only paths not meant to be called by the dashboard frontend.
- **Auth:** `Authorization: Bearer <JWT>`, obtained from `POST /api/v1/auth/login`.
  The token encodes `sub` (user id), `business_id`, `role`; every route derives
  tenant scope from the token, never from a client-supplied `business_id`.
- **Roles:** exactly three — `owner`, `admin`, `staff` (`BusinessUserRole`). There
  is no `viewer` or other tier.
- **RBAC pattern (see Finding F4 for the full breakdown):** most business-config
  resources (services, staff, business profile, hours, knowledge) are read = any
  authenticated role, write = `owner`/`admin`. Appointments and customer-contact
  writes are open to all three roles (operational, not config). Reports and the
  AI Training Room are `owner`/`admin` for *both* read and write (sensitive
  data). Handoffs are `owner`/`admin`/`staff` for both (staff field escalations).
- **Error envelope:** `{"error": {"type": "<snake_case>", "message": "<human string>"}}`
  on every app-raised error, every validation error, and every auth failure, at
  the matching HTTP status code — **as of the Phase 28 fix**; two real
  inconsistencies existed before it (Finding F2). No endpoint returns FastAPI's
  raw `{"detail": ...}` shape today.
- **IDs:** UUIDv4 strings everywhere (`gen_random_uuid()` server-side).
- **Money:** `Decimal`, serialized as a JSON string (e.g. `"90.00"`), not a float.
- **Pagination:** none. Every list endpoint returns the full unbounded result set.
  See Finding F3 for which of these are a real production risk.

---

## 1. Auth

### `POST /api/v1/auth/register`
Public. Creates a **new Business** plus its first `BusinessUser` (always role
`owner` — see Finding F5, there is no way to add a second user to an *existing*
business).

Request:
```json
{"business_name": "Willow Creek Family Dentistry", "timezone": "America/New_York",
 "email": "owner@willowcreekdental.example", "password": "Phase28pass1"}
```
Password policy (enforced): ≥8 chars, ≥1 letter, ≥1 digit.

Real response (`201`):
```json
{"business_id":"7e0295dc-635f-42cc-85ae-04a4a1323780",
 "user_id":"7712c32a-8ecb-437f-b423-ce2147aff3e6",
 "email":"owner@willowcreekdental.example","role":"owner"}
```

Real error (`422`, invalid email + weak password together):
```json
{"error":{"type":"validation_error",
 "message":"email: value is not a valid email address: ...; password: Value error, Password must be at least 8 characters long."}}
```
Real error (`409`, duplicate email) — not re-triggered live this phase, but
`auth_service.register_business` raises `ConflictError("An account with this email already exists.")`.

### `POST /api/v1/auth/login`
Public, rate-limited (`login_rate_limiter`, per-email).

Request: `{"email": "...", "password": "..."}`

Real response (`200`):
```json
{"access_token":"eyJhbGciOiJIUzI1NiIs...","token_type":"bearer","expires_in":1800}
```
Real error (`429`, after repeated bad attempts): `{"error":{"type":"too_many_requests","message":"Too many login attempts. Try again later."}}`

### `GET /api/v1/auth/me`
Auth: any role.

Real response (`200`):
```json
{"user_id":"7712c32a-8ecb-437f-b423-ce2147aff3e6","business_id":"7e0295dc-635f-42cc-85ae-04a4a1323780",
 "email":"owner@willowcreekdental.example","role":"owner"}
```

---

## 2. Business Profile & Hours

### `GET /api/v1/business/me` — any role
Real response:
```json
{"id":"7e0295dc-...","name":"Willow Creek Family Dentistry","description":null,
 "address":"142 Willow Creek Rd, Asheville, NC","phone":"555-201-4488","email":null,
 "website":null,"timezone":"America/New_York","languages":null,"tone":null,
 "sms_enabled":false,"follow_ups_enabled":false}
```
Note: `sms_enabled`/`follow_ups_enabled` **are** the notification-config surface
— there is no separate "notifications config" resource. `email` here also doubles
as the daily/monthly report recipient address (`report_service`/`monthly_report_service`
send to `Business.email`).

### `PATCH /api/v1/business/me` — owner/admin
PATCH semantics used identically across every resource in this API: an **omitted**
field is left unchanged; an **explicit `null`** clears a nullable field, and is
**rejected with 422** on a NOT-NULL field (e.g. `name`, `timezone`, `sms_enabled`).

Request: `{"phone": "555-201-4488", "address": "142 Willow Creek Rd, Asheville, NC"}`
→ returns the full updated `BusinessRead` (shown above).

### `GET /api/v1/business/hours` — any role
Real response:
```json
{"weekly":[{"day_of_week":0,"closed":false,"open_time":"09:00:00","close_time":"17:00:00"},
 {"day_of_week":5,"closed":true,"open_time":null,"close_time":null},
 {"day_of_week":6,"closed":true,"open_time":null,"close_time":null}],
 "exceptions":[{"id":"4b03b5d9-...","date":"2026-12-25","closed":true,"open_time":null,"close_time":null}]}
```
`day_of_week`: 0=Monday..6=Sunday.

### `PUT /api/v1/business/hours` — owner/admin
Replaces the **entire week** in one call. Request body is `{"days": [...]}`
(**not** a bare array — see Finding F6).
```json
{"days":[{"day_of_week":0,"open_time":"09:00","close_time":"17:00"}, ...]}
```
Real response is a **bare array** of `BusinessHourRead` (not wrapped in `{"weekly": ...}`
the way GET is — Finding F6):
```json
[{"day_of_week":0,"closed":false,"open_time":"09:00:00","close_time":"17:00:00"}, ...]
```

### `POST /api/v1/business/hours/exceptions` — owner/admin
Request: `{"date":"2026-12-25","reason":"Christmas Day - Closed"}` — note: `reason`
is accepted but **not stored/returned** (not a field on `HolidayExceptionCreate`/`Read`;
silently ignored by Pydantic). Real response:
```json
{"id":"4b03b5d9-3443-4419-b203-6f1ac0d27ee9","date":"2026-12-25","closed":true,"open_time":null,"close_time":null}
```

### `DELETE /api/v1/business/hours/exceptions/{exception_id}` — owner/admin
`204` on success, `404` `{"error":{"type":"not_found",...}}` if the exception
doesn't exist or belongs to another tenant.

---

## 3. Services

### `GET /api/v1/services` — any role · `POST` / `PATCH /{id}` / `DELETE /{id}` — owner/admin

Real create request/response:
```
POST {"name":"Teeth Cleaning","price":90,"duration_minutes":30,"description":"Routine cleaning and checkup"}
201 {"id":"b79edeae-...","business_id":"7e0295dc-...","name":"Teeth Cleaning",
     "description":"Routine cleaning and checkup","price":"90.00","duration_minutes":30,"staff_id":null}
```
`price` is echoed back as a **string** (`"90.00"`), even though the request sent
a bare number — normal Pydantic `Decimal` serialization, worth flagging to a
frontend dev expecting a JS number.

`PATCH` clears `description`/`staff_id` with explicit `null`; `name`/`price`/`duration_minutes`
reject explicit `null` with 422 (same NOT-NULL pattern as everywhere else).

---

## 4. Staff

### `GET /api/v1/staff` — any role · `POST` / `PATCH /{id}` / `DELETE /{id}` — owner/admin

```
POST {"name":"Dr. Elena Kapoor","role":"Dentist"}
201 {"id":"f7f1267a-...","business_id":"7e0295dc-...","name":"Dr. Elena Kapoor","role":"Dentist"}
```
`role` here is a **free-text job title** ("Dentist", "Hygienist") — unrelated to
`BusinessUserRole` (owner/admin/staff), a naming collision worth flagging to a
frontend dev (Finding F7).

---

## 5. Knowledge Base

### `GET /api/v1/knowledge` — any role (optional `?status=` filter)
### `POST /api/v1/knowledge` — owner/admin (manual doc)
### `POST /api/v1/knowledge/upload` — owner/admin (`.pdf`/`.txt`, 10MB cap)
### `GET /{id}` — any role · `PATCH /{id}` / `DELETE /{id}` — owner/admin
### `POST /api/v1/knowledge/search` — any role (RAG chunk search, `{"query","top_k"}`)

Status enum is **`draft` / `approved` / `archived`** — not `"published"`
(confirmed by triggering the real 422 below; a frontend dev guessing this enum
would guess wrong):
```
PATCH {"status":"published"}
422 {"error":{"type":"validation_error","message":"status: Input should be 'draft', 'approved' or 'archived'"}}
```
Real create → approve flow:
```
POST {"title":"Cancellation Policy","content":"Cancellations require 24 hours notice or a $25 fee applies."}
201 {"id":"18c8deb0-...","status":"draft","version":1,"approved_by":null,"approved_at":null,
     "created_at":"2026-09-04T19:09:20.169442","updated_at":"2026-09-04T19:09:20.169442", ...}

PATCH {"status":"approved"}
200 {"id":"18c8deb0-...","status":"approved","version":1,
     "approved_by":"7712c32a-8ecb-437f-b423-ce2147aff3e6",
     "approved_at":"2026-09-04T19:09:42.393853Z",
     "created_at":"2026-09-04T19:09:20.169442","updated_at":"2026-09-04T19:09:42.391412"}
```
Note the timestamp shapes on this one response alone — `approved_at` ends in `Z`,
`created_at`/`updated_at` don't. See Finding F8 (structural, not fixed this phase).

Upload wrong file type — real error:
```
POST /knowledge/upload  (file="bad.exe")
415 {"error":{"type":"unsupported_media_type","message":"Unsupported file type '.exe'. Only .pdf and .txt are accepted."}}
```

`POST /knowledge/search` real response shape (no results before a doc is approved
— unapproved/draft docs are excluded from search, confirmed: search against the
draft doc above returned `{"results":[]}`, and only started returning results
after `approved`):
```json
{"results":[{"chunk_id":"9c150abf-...","document_id":"18c8deb0-...",
 "document_title":"Cancellation Policy","content":"Cancellations require 24 hours notice or a $25 fee applies.",
 "similarity":0.6242664402480262}]}
```

---

## 6. Appointments

### `POST /api/v1/appointments` — **any role** (see F4 — deliberately not owner/admin-gated)
Request requires a **timezone-aware** `scheduled_at` — a naive datetime is
rejected with 422 (real, triggered live):
```
POST {"customer_id":"...","service_id":"...","scheduled_at":"2026-09-10T14:00:00"}
422 {"error":{"type":"validation_error","message":"scheduled_at: Value error, scheduled_at must include a timezone offset."}}

POST {"customer_id":"5cdd0a1d-...","service_id":"b79edeae-...","scheduled_at":"2026-09-10T14:00:00-04:00"}
201 {"id":"72d73f0f-...","business_id":"7e0295dc-...","customer_id":"5cdd0a1d-...","service_id":"b79edeae-...",
     "staff_id":null,"scheduled_at":"2026-09-10T18:00:00Z","duration_minutes":30,
     "status":"confirmed","created_at":"2026-09-04T19:09:43.069619","group_booking_id":null}
```
`duration_minutes` is **derived server-side from the service** — not accepted as
client input, by design (prevents a client or the LLM tool from inventing a
duration).

### `GET /api/v1/appointments` — any role
Filters (all optional query params, no pagination): `customer_id`, `status`,
`date_from`, `date_to`, `group_booking_id`.

### `GET /api/v1/appointments/{id}` — any role → `404` if missing/other-tenant.

### `PATCH /api/v1/appointments/{id}/cancel` — any role
```
200 {"id":"72d73f0f-...", ..., "status":"cancelled", ...}
```

### `PATCH /api/v1/appointments/{id}/reschedule` — any role
Real business-rule rejection (422, app-shaped, not a raw validation error —
this one is an app-raised `UnprocessableEntityError` from `booking_service`,
distinct from the Pydantic 422s above but same status code and envelope):
```
PATCH {"scheduled_at":"2026-09-11T15:00:00-04:00"}
422 {"error":{"type":"unprocessable_entity","message":"Requested time is not available (outside business hours, on a closed date, or in the past)."}}
```

### Group bookings — **no dedicated endpoint** (Finding F9)
Booking 2+ people (e.g. "book me and my daughter for cleanings") is reachable
**only** through the conversation/widget message endpoints (§8) — the LLM tool
calls `booking_service.create_group_appointments` internally. Every `Appointment`
row written from one group request shares a `group_booking_id`, filterable via
`GET /appointments?group_booking_id=...`; there is no way to *create* a group
booking directly via a business-facing REST call today. A frontend "book for the
whole family" screen would need either (a) a new dedicated endpoint (not built),
or (b) to make N individual `POST /appointments` calls itself and accept that it
won't get the exclusion-constraint clustering behavior the LLM path gets for a
shared slot (see PHASE_STATUS.md Phase 12 for why that clustering exists).

---

## 7. Customers

### `POST /api/v1/customers` — any role
### `GET /{id}` — any role
### `PATCH /{id}` — **any role** (deliberate — see code comment in `customers.py`: same tier as create/read, not the owner/admin config-write tier)
### `DELETE /{id}` — owner/admin only

```
POST {"name":"Maria Gonzalez","phone":"+15551234567","email":"maria.g@example.com"}
201 {"id":"5cdd0a1d-...","business_id":"7e0295dc-...","name":"Maria Gonzalez",
     "phone":"+15551234567","email":"maria.g@example.com","preferred_language":null,"sms_opt_in":false}
```

---

## 8. Conversations (internal orchestrator test endpoint)

### `POST /api/v1/conversations/{conversation_id}/messages` — owner/admin only (403 for staff; was any role before Phase 52)
**Not a channel integration point.** Real customer traffic arrives through the
widget (§9) or a channel webhook (§10), each of which creates its own
`Conversation` row internally. This route is the internal way to drive the
Phase 8 orchestrator against an **already-existing** `conversation_id` (e.g. one
produced by a prior widget message) for testing — there is no `POST /conversations`
to create one directly from the dashboard.

```
POST {"content": "..."}
201 {"intent": "booking", "response": "...", "customer_message_id": "...", "agent_message_id": "..."}
```
**While a staff member owns the conversation (Phase 52 human takeover)** the customer message is stored but the AI
drafts nothing: `response` and `agent_message_id` are `null` (and `intent` is `null`, or the classification if the LLM had
already produced one when takeover was noticed). The widget (`POST .../widget/{id}/messages`, `.../voice-message`) returns
the same `null` `response`.

### `POST /api/v1/inbox/conversations/{conversation_id}/takeover` — owner/admin/staff
### `POST /api/v1/inbox/conversations/{conversation_id}/release` — owner/admin/staff
Claim a conversation (the AI goes silent for `HUMAN_TAKEOVER_SECONDS`, default 7200 = 2h, sliding — every staff reply restarts
it) / hand it back to the AI immediately (idempotent). Resolving a handoff (`PATCH /handoffs/{id}`) also releases.
```
200 {"active": true, "until": "2026-09-21T16:40:00Z", "taken_over_by": "<business_user_id>"}
200 {"active": false, "until": null, "taken_over_by": null}      (release)
```
404 for a conversation that is not this business's (never reveals another tenant's).

### `GET /api/v1/inbox/conversations?tab=all|needs_reply|handoffs&channel=whatsapp|messenger|instagram|website&q=<name>&limit&offset` — owner/admin/staff
The inbox home, newest activity first. Item: `{id, channel, customer_name, last_message_preview (<=160 chars), last_message_sender,
last_message_at (UTC), last_message_delivery_status, needs_reply, unread, open_handoff, takeover_active, takeover_by_email}`.
`needs_reply` = a human is responsible (open handoff, or a staff member owns it) AND the customer spoke last. `unread` = the
customer's latest message is newer than the last `POST .../read` (shared across staff). Conversations with no messages are not listed.
### `GET /api/v1/inbox/summary` -> `{needs_reply, handoffs}` (sidebar badge)
### `POST /api/v1/inbox/conversations/{id}/read` -> 204 (staff opened it; clears `unread`)

### `GET /api/v1/inbox/conversations/{id}` — owner/admin/staff
Header for one conversation: `{id, channel, customer_id, customer_name, takeover:{active,until,taken_over_by}, takeover_by_email, reply:{can_reply, reason, window_closes_at}, open_handoff:{id,reason}|null, last_customer_message_at}`.
`reply.can_reply=false` + `reply.reason` (show verbatim) when a reply can't reach the customer: WhatsApp/Messenger/Instagram
24-hour window closed ("Can't reply: the 24-hour WhatsApp reply window closed (the customer's last message was 30 hours ago)."),
channel not connected, or a channel with no outbound path (sms/test channels). The website channel has no window.

### `GET /api/v1/inbox/conversations/{id}/messages?after=<message_id>&limit=200&latest=false` — owner/admin/staff
`latest=true` returns the NEWEST `limit` messages (still oldest-first) — what a chat view wants for a long conversation. All timestamps are UTC-tagged.
The whole thread oldest-first, every channel through one query. Each item: `{id, sender_type: customer|agent|staff, content, created_at,
delivery_status: sent|simulated|failed|suppressed|pending|null, delivery_detail, sent_by_user_id, sent_by_email}`.
`agent` = the AI. `delivery_status` is recorded for staff replies, AI replies (webhook channels) and system messages (payment
confirmation); `null` for customer messages, pre-Phase-52 messages and website-widget AI replies (their delivery is the HTTP response).
`simulated` = no real token configured. `failed` carries `delivery_detail` like `failed: HTTP 400` (never a raw provider body).
Non-text customer messages appear as text placeholders: `[Customer sent an image]`, `[Customer sent a voice note]`, … Poll with `after=<last id you have>`.

### `POST /api/v1/inbox/conversations/{id}/reply` — owner/admin/staff
```
POST {"content": "Yes, we open at 9.", "client_msg_id": "<uuid per composer submit, optional>"}
201 <InboxMessage>   (sender_type "staff"; a send Meta rejects is still 201 with delivery_status "failed" + the reason)
409 {"error":{"message":"Can't reply: the 24-hour WhatsApp reply window closed (...)"}}   nothing stored, nothing sent, AI NOT silenced
409 "This conversation is busy (an automated reply is being delivered). Please retry."   (rare; retry)
422 blank, or over the channel limit (WhatsApp 4096 chars, Messenger 2000 chars, Instagram 1000 bytes, website 4000 chars)
```
A reply claims the conversation (AI silent for `HUMAN_TAKEOVER_SECONDS`, sliding). Repeating the same `client_msg_id` returns the first
message and sends nothing again (to retry a `failed` send, use a NEW `client_msg_id`).

### Widget changes (public)
`POST .../widget/{id}/messages` and `.../voice-message` now also return `customer_message_id` (and `agent_message_id` for voice) — the
polling cursor when there is no AI reply. `GET .../widget/{id}/updates?session_token&after=<message id>` now returns STAFF messages as
well as system (AGENT) ones. widget.js polls while its panel is open and the tab is visible (10s; 5s for 30 min after a payment link).

---

## 9. Widget (public, no auth — CORS-gated by `WidgetCORSMiddleware` instead)

### `POST /api/v1/widget/{business_id}/messages`
```
POST {"session_id":"sess-doc-demo-1","content":"What are your hours?"}
200 {"session_token":"AcMiODBgoOABT9wKbgLEcK_2YfAcL-Gax4GdKKqiok4",
     "response":"...", "intent":"business_hours"}
```
`session_token` (opaque, server-minted) — not a JWT — must be echoed back as
`session_token` on the visitor's next message to continue the same conversation.
This is a **different auth model** from every other endpoint in this doc (no
`Authorization` header at all); a frontend dev building the *business dashboard*
never calls this directly, but a dev building the embeddable *widget* would.

---

## 10. Channel Webhooks (Meta platforms — WhatsApp / Messenger / Instagram)

Not dashboard-facing; documented for completeness since they're real endpoints.
`GET /api/v1/webhooks/{whatsapp,messenger,instagram}` — Meta's verification
handshake (`hub.mode`, `hub.verify_token`, `hub.challenge` query params, each
platform has its own token in `.env`). Real live check:
```
GET ?hub.mode=subscribe&hub.verify_token=<real token>&hub.challenge=CHALLENGE123
200 "CHALLENGE123"   (plain text, not JSON)

GET ?hub.mode=subscribe&hub.verify_token=wrong&hub.challenge=CHALLENGE123
403 {"error":{"type":"forbidden","message":"Webhook verification failed."}}
```
`POST /api/v1/webhooks/{platform}` — the real inbound-message delivery path,
signature-verified (`meta_webhook_signature.py`), not bearer-auth'd.

---

## 11. Reports — owner/admin only, read **and** write (F4)

### `GET /api/v1/reports/daily?date=YYYY-MM-DD`
Real response (trimmed):
```json
{"business_id":"7e0295dc-...","business_name":"Willow Creek Family Dentistry",
 "timezone":"America/New_York","report_date":"2026-09-04","appointments":[],
 "cancellations":[{"id":"72d73f0f-...","originally_scheduled_at":"2026-09-10T18:00:00+00:00",
   "cancelled_at":"2026-09-04T19:10:32.492152","customer_name":"Maria Gonzalez","service_name":"Teeth Cleaning"}],
 "reschedules":[],
 "new_leads":[{"id":"5cdd0a1d-...","name":"Maria Gonzalez","created_at":"2026-09-04T19:09:32.194938", ...}],
 "human_review":{"count":0,"implemented":true,"note":"Real count of currently-open human handoffs for this business."},
 "summary":{"appointments_scheduled":0,"cancellations":1,"reschedules":0,"new_leads":1,"human_review_open_count":0}}
```
Note `originally_scheduled_at` uses a **third** timestamp style (`+00:00` suffix)
distinct from both `Z`-suffixed and naive fields elsewhere on the very same
response — see Finding F8.

### `GET /api/v1/reports/daily/excel?date=YYYY-MM-DD`
Real headers:
```
content-type: application/vnd.openxmlformats-officedocument.spreadsheetml.sheet
content-disposition: attachment; filename="daily_report_2026-09-04.xlsx"
```
Binary body, not JSON.

### `POST /api/v1/reports/daily/send?date=YYYY-MM-DD`
Emails the report to `Business.email` right now — **not a scheduled job**; there
is no cron/scheduler infrastructure in this codebase (documented explicitly in
PHASE_STATUS.md Phase 16/17). A frontend "schedule my daily report" toggle would
have nothing real to bind to today.

### `GET /api/v1/reports/monthly?year=YYYY&month=M` / `GET .../excel` / `POST .../send`
Same shape family. Real response (trimmed) shows several fields that are
**honestly stubbed**, not fabricated — worth surfacing to a frontend dev so a
chart isn't built against a metric that's always zero by construction:
```json
{"appointments":{"completed":{"count":0,"implemented":false,
  "note":"AppointmentStatus.COMPLETED has no real producer anywhere in this codebase (verified by grep) — nothing ever marks an appointment completed, so this is honestly always 0 today, not fabricated."}},
 "booking_conversion":{"value":null,"numerator":1,"denominator":0,
  "definition":"... this codebase does not persist per-conversation intent classification ..."}}
```

---

## 12. Follow-ups — owner/admin only

### `POST /api/v1/followups/run?inactivity_hours=N` (default in `followup_service.DEFAULT_INACTIVITY_HOURS`, 1–720 allowed)
Real, callable-now action — **not scheduled**, same "no cron infra" caveat as
reports. Real response: `{"processed":0,"results":[]}` (no stale conversations
existed in this test business).

---

## 13. Human Handoffs — owner/admin/staff, read **and** write (F4)

### `GET /api/v1/handoffs?status=open|resolved|all` (default `open`)
### `PATCH /api/v1/handoffs/{id}` — body is always `{"status":"resolved"}` (the only real transition; no "reopen")

```
GET → 200 []
PATCH /handoffs/00000000-0000-0000-0000-000000000000 {"status":"resolved"}
404 {"error":{"type":"not_found","message":"Handoff not found."}}
```

---

## 14. AI Training Room — owner/admin only

### `POST /api/v1/training/ask` — ask a question exactly as a customer would; returns the real answer + which knowledge chunks it drew on, **without** creating a real Conversation/Customer.
```
POST {"question":"What is your cancellation policy?"}
200 {"training_question_id":"757cdb98-...","question":"...","answer":"We require at least 24 hours' notice for cancellations—if you cancel with less than 24 hours' notice, a $25 fee applies. Can I help you with anything else?",
     "intent":"general_question",
     "knowledge_chunks_used":[{"chunk_id":"9c150abf-...","document_id":"18c8deb0-...",
       "document_title":"Cancellation Policy","content":"Cancellations require 24 hours notice or a $25 fee applies.","similarity":0.624266...}]}
```
### `POST /api/v1/training/feedback` — `{"training_question_id","is_correct","corrected_answer"}` (`corrected_answer` required iff `is_correct=false`, enforced by a cross-field validator).
### `GET /api/v1/training/history` — full unbounded list, no pagination/date filter.

---

## Findings — Consistency Audit

### F1 — `/api/v1/openapi.json` does not exist (structural doc bug, not code)
`app = FastAPI(title=...)` has no `openapi_url` override, so FastAPI serves the
spec at the **app root**, `GET /openapi.json` — unaffected by the `/api/v1`
router prefixes. Verified live:
```
GET /api/v1/openapi.json → 404 {"detail":"Not Found"}
GET /openapi.json        → 200, full spec, 39 paths
GET /docs                → 200
```
Not fixed (this phase's instructions named the wrong path; the real one already
works and needed no code change) — documented here so the frontend dev doesn't
hit the same 404.

### F2 — Error envelope was NOT uniform before this phase; is now (fixed)
Two real gaps existed, both confirmed live before the fix and re-confirmed after:
1. **Missing `Authorization` header** → FastAPI's `HTTPBearer(auto_error=True)`
   default raised its own `403 {"detail":"Not authenticated"}`, bypassing the
   app's handler entirely — wrong status code too (401 is correct for "no/invalid
   credentials"; 403 means "authenticated but not permitted").
2. **Any Pydantic validation failure** (bad body/query shape, a `field_validator`
   raising `ValueError`) → FastAPI's own `RequestValidationError` handler, never
   routed through `night_guard_exception_handler`, produced raw
   `{"detail": [{"type":...,"loc":...,"msg":...}, ...]}`.

Every other error path in the codebase (all `NightGuardError` subclasses:
`NotFoundError`, `ConflictError`, `UnauthorizedError`, `ForbiddenError`,
`TooManyRequestsError`, `UnsupportedMediaTypeError`, `PayloadTooLargeError`,
`UnprocessableEntityError`) already used the uniform envelope, by construction —
`night_guard_exception_handler` is the single place that shape is built.

**Fix applied** (`backend/app/api/dependencies.py`, `backend/app/core/exceptions.py`):
`HTTPBearer(auto_error=False)` + an explicit `UnauthorizedError` when credentials
are absent; a `RequestValidationError` handler that flattens Pydantic's error
list into the same `{"error": {"type": "validation_error", "message": "..."}}`
shape. Before/after, both live:
```
# before
GET /appointments (no Authorization header)       → 403 {"detail":"Not authenticated"}
PATCH /knowledge/{id} {"status":"published"}       → 422 {"detail":[{"type":"enum",...}]}

# after (docker compose restart backend)
GET /appointments (no Authorization header)        → 401 {"error":{"type":"unauthorized","message":"Not authenticated."}}
PATCH /knowledge/{id} {"status":"published"}        → 422 {"error":{"type":"validation_error","message":"status: Input should be 'draft', 'approved' or 'archived'"}}
```
Bad-but-present token still correctly 401 with the app shape (unchanged,
re-verified): `{"error":{"type":"unauthorized","message":"Invalid token."}}`.
Full integration test suite run after the fix — see "Verification" section below.

### F3 — Pagination: none, anywhere. Real risk on two endpoints.
Every list endpoint (`GET /services`, `/staff`, `/knowledge`, `/handoffs`,
`/training/history`, `/appointments`) returns its **entire** unbounded result
set — confirmed by reading every route in `backend/app/api/routes/*.py`; none
accept `limit`/`offset`/`cursor`.
- **`GET /appointments`** — real risk. A business books indefinitely; this table
  grows without bound, the endpoint has date-range filters but they're optional
  and default to none, and a client that forgets them gets every appointment the
  business has ever had in one response.
- **`GET /training/history`** — same shape of risk, lower likely volume (one
  entry per training-room question asked by staff, not per customer).
- Everything else (`services`, `staff`, `knowledge`, `handoffs`) is bounded in
  practice by real-world business size (a dental office has dozens of services/
  staff/docs, not thousands) — lower priority.
Not fixed this phase (adding pagination is a response-shape change across 6
endpoints, i.e. a retrofit, not a small fix) — flagged for a later phase.

### F4 — RBAC is NOT one uniform "read:any, write:owner/admin" rule — by design, consistently documented in code, but a frontend dev needs the real breakdown:

| Resource | Read | Write |
|---|---|---|
| services, staff, business profile/hours, knowledge | any role | owner/admin |
| customers | any role | **any role** (PATCH), owner/admin (DELETE only) |
| appointments | any role | **any role** (create/cancel/reschedule) |
| handoffs | owner/admin/**staff** | owner/admin/**staff** |
| reports, training room, followups | owner/admin | owner/admin |

Every one of these is a deliberate choice with a code comment explaining it
(quoted inline in §3–14 above), not drift — but the earlier assumption of one
uniform rule doesn't hold. Two roles express "any authenticated role" two
different ways in the source: most routes just omit any role check
(`Depends(get_current_user)`), while `handoffs.py` spells out
`require_role(["owner","admin","staff"])` explicitly. Behaviorally identical
today (those are the only three roles that exist), but if a fourth role is ever
added, the explicit-allowlist form silently excludes it while the no-check form
includes it automatically — worth normalizing in a later phase, not fixed here
(purely stylistic, zero behavior difference today).

### F5 — No endpoint exists to add a second user to an existing business
`POST /auth/register` always creates a **new** `Business` + a fresh `owner`.
There is no invite/add-staff-user endpoint. Confirmed directly from the test
suite's own fixture comment (`tests/integration/test_business_configuration.py`):
```python
@pytest.fixture
def staff_token(two_businesses):
    """Mints a staff-role token for Business A (no staff-user invite endpoint exists yet)."""
    ...  # constructs a BusinessUser row directly via SQLAlchemy, bypassing the API entirely
```
A frontend "invite your team" screen has nothing to call today. Flagged as
structural — not attempted this phase (real feature work, not a consistency fix).

### F6 — `PUT /business/hours` request/response shape asymmetry with `GET`
`GET /business/hours` → `{"weekly": [...], "exceptions": [...]}` (wrapped).
`PUT /business/hours` → request body `{"days": [...]}` (wrapped, different key
name than the GET response's `weekly`), **response** is a bare `[...]` array
(unwrapped) — confirmed live in §2. Small enough to normalize later; not fixed
this phase since `response_model=list[BusinessHourRead]` is explicit in the
route decorator (a real, if debatable, deliberate choice, not an obvious bug)
and changing a response shape is exactly the kind of "small fix" that isn't
actually small once a frontend might already depend on it.

### F7 — `Staff.role` (free-text job title) vs `BusinessUserRole` (owner/admin/staff) name collision
Both are called "role" in the API surface — `StaffCreate.role` is an arbitrary
string ("Dentist", "Hygienist"), completely unrelated to the RBAC enum. No code
bug (they're different models, never compared), but a real naming trap for a
frontend dev skimming field names. Documented, not renamed (renaming a public
field is not a "small, safe" fix).

### F8 — Timestamp format is genuinely inconsistent (structural, not fixed)
Three distinct wire formats coexist for "this is a UTC instant," confirmed with
real values from live responses in this doc:
- `Z` suffix: `knowledge.approved_at = "2026-09-04T19:09:42.393853Z"`,
  `appointment.scheduled_at = "2026-09-10T18:00:00Z"`
- `+00:00` suffix: `daily report.cancellations[].originally_scheduled_at = "2026-09-10T18:00:00+00:00"`
- **No offset at all** (naive): `knowledge.created_at = "2026-09-04T19:09:20.169442"`,
  `appointment.created_at = "2026-09-04T19:09:43.069619"`, `customer.created_at`
  in the daily report's `new_leads[]`, `knowledge.updated_at`

**Root cause, confirmed by reading the code:** `CreatedAtMixin`/`UpdatedAtMixin`
(`backend/app/db/models/mixins.py`) declare their columns with
`mapped_column(server_default=func.now(), ...)` — no `DateTime(timezone=True)` —
so **every** `created_at`/`updated_at` on **every** model in the codebase
(businesses, services, staff, knowledge docs, customers, appointments, handoffs,
training questions...) is a naive timestamp. Fields set explicitly in Python with
`datetime.now(timezone.utc)` (`approved_at`) or declared with
`DateTime(timezone=True)` (`Appointment.scheduled_at`) come out tz-aware; the
`+00:00` vs `Z` difference between the report and other tz-aware fields is just
Python's default `isoformat()` rendering vs FastAPI/Pydantic's `Z`-substitution,
depending on which code path serializes them.

All values are actually UTC underneath (confirmed: Postgres columns without
`timezone=True` still get UTC `now()` from `func.now()` in this DB setup) — so
there's no *correctness* bug, only a serialization inconsistency a frontend
Date-parser needs to tolerate (most JS/TS date parsers treat a bare ISO string
with no offset as **local time**, not UTC — a real footgun). **Not fixed this
phase**: fixing it properly means `DateTime(timezone=True)` on both mixins, an
Alembic migration touching every table with `created_at`/`updated_at` (every
table in the schema), and reverifying every existing test — a genuine retrofit,
explicitly out of scope per this phase's instructions. Flagged for Phase 29+.

### F9 — Group bookings have no direct API (see §6) — documented, not a bug, but a real gap a frontend dev needs to know before designing a "book for my family" screen.

---

## Small fixes made this phase (recap)
1. `backend/app/api/dependencies.py` — `HTTPBearer(auto_error=False)` + explicit
   `UnauthorizedError` on missing credentials (was: raw FastAPI 403).
2. `backend/app/core/exceptions.py` + `main.py`'s `register_exception_handlers` —
   added a `RequestValidationError` handler producing the app's error envelope
   (was: raw FastAPI `{"detail": [...]}`).

Both re-verified live post-fix (see F2). Full test suite run after both changes
— see "Verification" section below for the real pass/fail output.

---

## Verification (real, this phase)

1. **First full suite run after the two fixes** (`docker compose exec backend python -m pytest -q`):
   `1 failed, 287 passed, 1 skipped` — the one failure was
   `test_tenant_isolation.py::test_unauthenticated_request_is_rejected`, which
   asserted the **old, buggy** behavior (`403`, comment: `# HTTPBearer: no
   credentials supplied`) — i.e. it was pinned to the exact bug F2 fixes, not a
   real regression.
2. **Test updated** to assert the corrected behavior (401, app error envelope) —
   `backend/tests/integration/test_tenant_isolation.py`.
3. **Second full suite run:**
```
........................................................................ [ 24%]
........................................................................ [ 49%]
.............................................................s.......... [ 74%]
........................................................................ [ 99%]
.                                                                        [100%]
288 passed, 1 skipped, 1 warning in 325.12s (0:05:25)
```
   `0` failed. The 1 skip predates this phase (unrelated to these changes).
4. **`openapi.json` confirmed real and complete:**
```
GET /openapi.json → 200
  title: Night Guard AI | version: 0.1.0 | openapi: 3.1.0
  paths: 39
```
   Sample path entry (`GET /api/v1/knowledge/{document_id}`) has a real
   `security: [{"HTTPBearer": []}]` requirement, a real path parameter with
   `format: uuid`, and a real `$ref` to `KnowledgeDocumentRead` in its 200
   response schema — matches the hand-written contract above exactly.
