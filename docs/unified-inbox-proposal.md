# Unified Inbox + Human Takeover — investigation and proposal

Status: **PROPOSAL, no code written** (2026-09-21). Everything under "Findings" was read from the
current code/DB this session, not recalled from earlier phases. Claims about Meta's platform rules are
marked **(verify)** — they are from my knowledge of Meta's docs, not checked live, and must be
confirmed before build.

## 0. Summary

* The data model is already channel-agnostic: one `conversations` + one `messages` table for all four
  channels, `MessageSenderType` **already has `STAFF`** (never written by anything). "All messages of a
  conversation" is a single query. No per-channel storage quirks.
* Sending **into** an existing conversation already has one working, shared path —
  `services/channels/proactive.send_to_conversation` (built for the "payment received" message). It
  covers WhatsApp, Messenger, Instagram; the website widget "sends" by the widget polling. A staff reply
  is that function plus: sender = STAFF, delivery status kept, and the 24h-window problem handled.
* **The AI does not stop today when a handoff is open** — nothing in the orchestrator reads handoff
  state. If staff replied from an inbox tomorrow with no other change, the AI would answer the
  customer's next message on top of them. Takeover is the load-bearing part of this feature.
* Real-time: **no push infrastructure exists** (no SSE/WebSocket anywhere; the dashboard doesn't poll
  at all). Recommend **polling** for v1 — and a real prerequisite: the three Meta webhook handlers are
  `async def` running blocking LLM turns, which stalls the whole event loop (see §4).
* RBAC: view = any authenticated role; reply = same set, **but note only OWNER logins can exist today**
  (no code path creates admin/staff users). The RBAC decision is mostly about the future.

## 1. Findings — conversation/message model

| Item | Reality |
|---|---|
| `conversations` | tenant-scoped; `customer_id`, `channel` (free string), `status` (only `"open"` is ever written — no close action exists), language lock, booking-draft slot fields, `payment_choice_appointment_id`, `created_at`/`updated_at`. **No** last-message time, unread state, assignee, or takeover state. |
| `messages` | `conversation_id`, `sender_type` (customer/agent/**staff**), `content`, `detected_intent`, `external_message_id` (globally UNIQUE, only inbound WhatsApp/Messenger/Instagram ids), `created_at`. **No** delivery status, no author user id, no message type/attachments. Only index: `conversation_id` (no `(conversation_id, created_at)`). |
| Identity | `channel_identities(business, channel, external_ref) → customer`. External ref is a phone or **BSUID** (WhatsApp), PSID (Messenger), IGSID (Instagram), or a **SHA-256 hash of the widget session token** (website — not reversible, by design). |
| Real data (all tenants) | 539 website, 12 whatsapp, 1 messenger, 1 instagram conversations (+ a handful of `sms`/`widget`/`debug_test*` test rows). Messages: 1613 customer / 1615 agent / **0 staff**. Users: 26, **all `owner`**. |

Answers to Q1: yes, a clean channel-independent query exists today —
`SELECT … FROM messages WHERE conversation_id = :id ORDER BY created_at`. `memory/context.py` already
does exactly this for the LLM. Every adapter goes through the same `get_or_create_conversation` +
`handle_incoming_message`, so nothing is stored differently per channel. Two caveats:

1. **Inbound non-text is dropped before storage** (WhatsApp `type != "text"`, Messenger/IG no
   `message.text`, delivery/read receipts, postbacks). A customer's photo/voice note never reaches the DB
   at all — an inbox will show a gap, and it is exactly what a human takeover cares about.
2. **AI replies carry no delivery info.** `send_detail` from each webhook is only logged. An AI reply
   that failed to send (`failed: HTTP 400`) is stored as a normal AGENT message.

## 2. Findings — how to send INTO an existing conversation, per channel

Confirmed one at a time by reading each adapter:

| Channel | Mechanism | Needs | Notes |
|---|---|---|---|
| WhatsApp | `WhatsAppChannelAdapter.send_message(to, text, phone_number_id, access_token)` → Graph `POST /{phone_number_id}/messages` (urllib). BSUID handled (`recipient` + ≥v26.0). | identity `external_ref` (prefers phone over BSUID — `proactive` already does this), `Integration(type="whatsapp").config{phone_number_id, access_token}` | Returns a status *string*. Falls back to a logged **simulation** if no token — so a "sent" in dev may not be real. |
| Messenger | `MessengerChannelAdapter.send_message(psid, text, page_access_token)` → `POST /me/messages` | PSID identity, `Integration(type="messenger").config.page_access_token` | Token per Page. |
| Instagram | `InstagramChannelAdapter.send_message(igsid, text, ig_account_id, access_token)` → `POST /{ig_account_id}/messages`, host by token prefix (`IGAA` → graph.instagram.com) | IGSID identity, `Integration(type="instagram")` config | Same body shape as Messenger, different path/host. |
| Website widget | **No push channel.** `proactive.send_to_conversation` records the message and returns `"recorded for widget poll"`; widget.js polls `GET /api/v1/widget/{biz}/updates?session_token&after`. | just the stored `Message` | Poll is today (a) only started when an AI reply contained a payment link, (b) 5s for ≤30 min, (c) **filters `sender_type == AGENT`** so a STAFF row would never be delivered, (d) needs an `after` message id the widget only has after a turn in this page-load; the widget renders no history after reload. |

`proactive.send_to_conversation(db, conversation=, text=)` already: records an AGENT message, resolves
identity + integration + credentials, dispatches per channel, never raises. It is the right seam. Gaps
for staff use:

* **The 24-hour window is not handled anywhere** (grep: no `131047`, no window logic). WhatsApp only
  allows free-form messages within 24h of the customer's last message; after that only approved template
  messages **(verify)**. Messenger/Instagram: 24h standard window, extendable to 7 days with the
  `HUMAN_AGENT` message tag which needs Meta approval **(verify)**. A staff reply to a 3-day-old
  conversation will fail on all three. AI replies never hit this (always answering a fresh inbound); the
  payment message rarely does. **The inbox must know the window and show "can't reply here — outside
  24h" instead of letting staff type into a box that will fail.** Computable from the last CUSTOMER
  message time; no schema needed.
* It returns only a string (`sent wamid=…` / `simulated…` / `failed: HTTP n` / `recorded; …`). A staff
  UI needs a persisted status.
* Record-first-then-send: fine (a failed push leaves a message that never reached the customer, which is
  why the status must be stored and shown).
* Outbound is synchronous urllib (≤15s timeout) — acceptable inside a normal `def` route (threadpool).

Channel-native echoes: Messenger/Instagram webhooks deliver `is_echo` for messages the Page owner sends
**from Meta's own inbox/app**; `meta_messaging_webhook` currently **discards** them. A business whose
staff already reply from the Page inbox today has the same AI-double-reply problem, and the echo is a
free takeover signal (§3, phase 2). WhatsApp Cloud API has no equivalent without coexistence — out of
scope.

## 3. The critical question — AI behaviour after a human replies

**What happens today (verified):** `handle_incoming_message` never consults handoff state.
`maybe_create_handoff` only creates/reuses an open row, and on a turn that itself qualifies for a
handoff the orchestrator appends the "I've also let our team know" sentence — including when the handoff
was already open (§9; my first draft overstated this as "every reply"). Resolving a handoff changes
nothing about AI behaviour. `Conversation.status` is never anything but `open`.

**Technically feasible:** yes, and cheap in one place. Every channel path funnels through
`handle_incoming_message` (WhatsApp/Messenger/Instagram/website/voice/`POST /conversations/.../messages`).
A guard right after the `get_conversation` lookup runs before all six early-return branches
(premium test, language question, payment choice, provider failure, bare-digit, main flow).

### Proposed design

Two columns on `conversations`:

* `human_takeover_until timestamptz NULL` — the AI is **silent** while `now() < human_takeover_until`.
* `human_takeover_by uuid NULL` (BusinessUser id, display only: "Sita is handling this").

Rules:

1. **Staff sends a reply → takeover starts/extends automatically:** `until = now + T`. Sending *is* the
   claim; no separate "take over" click required (and one exists anyway for claiming before typing).
2. **While active, an inbound customer message is stored (CUSTOMER row, `detected_intent` NULL) and the
   orchestrator returns `response=None`** — no LLM call, no agent message, nothing sent. This also saves
   the LLM cost on human-handled turns. Callers must accept `response is None`: the 3 Meta webhook
   handlers (skip the send), widget route (return empty reply), voice route, and the testing endpoint's
   `OrchestratedMessageResponse` (`response` is required `str` today).
3. **Second check just before the AI commits/sends.** An AI turn takes seconds (LLM). A staff reply landing
   mid-turn would otherwise produce both messages. After the LLM call, re-read `human_takeover_until`; if
   active, discard the draft (persist only the customer message, `response=None`). Not a lock — a
   narrow window remains between that check and the channel send (sub-second) and is accepted; a
   per-conversation advisory lock would close it if ever needed.
4. **Ending takeover:** (a) explicit **"Hand back to AI"** (sets NULL); (b) **resolving the handoff**
   also hands back; (c) automatic expiry — recommended default **T = 2 hours, sliding** (each staff reply
   pushes it out). `T` a constant in v1, per-business setting later if anyone asks.
5. **Hand-back must not re-greet or contradict.** The LLM prompt renders history as `staff: …` lines
   already (`intent.py` transcript) but has no instruction about who "staff" is. Add one prompt line: the
   `staff:` lines are a human colleague speaking for the business — treat as authoritative, don't repeat
   or contradict them. (Prompt change ⇒ needs the conversation-quality eval, per your usual process.)
6. **System messages still go through** during takeover (payment-received etc. via
   `send_to_conversation`): deterministic, tied to a real event, not a "second voice".

Why not the alternatives:

* *Pause while an open handoff exists (no timer):* handoffs open for reasons where nobody replied
  (provider outage, low-knowledge). AI silent + nobody looking = customer ignored. Takeover must require
  a human action.
* *Permanent until handed back:* a staff member who replies once and forgets leaves the customer talking
  to a wall indefinitely. Sliding expiry is the safe failure mode: worst case the AI answers after 2h
  quiet, seeing the staff messages in its context.
* *Stateless rule "AI silent while the last message is a staff message":* breaks on the customer's very
  next reply ("ok 3pm works") — the exact case to protect.

**Residual risks (call these out, don't hide them):**

* *Customer message unanswered during takeover* is the new failure mode: AI is silent and the human may
  not be looking. Mitigations in the plan: unread badge + "waiting for reply" sort, and the sliding
  expiry. Not solved: a staff member who claims and walks away for <2h. Optional v2: if a customer
  message sits unanswered >15 min during takeover, AI resumes (or sends one "a team member will be with
  you shortly").
* Staff replying from Meta's native inbox is invisible until the echo signal is added (phase 2).
* Follow-ups/reminders are email/SMS — not chat — so they don't conflict; only chat sends need the guard.

## 4. Real-time approach

Verified facts:

* No SSE/WebSocket/`StreamingResponse` anywhere. Only polling exists (widget.js 5s). The dashboard has
  **zero** polling (plain `fetch` + `useState`, no react-query).
* One `uvicorn` process, no `--workers`, no pub/sub (Redis/LISTEN-NOTIFY) — a push design would need a
  broker before a second worker, and needs auth for the stream: browser `EventSource` can't send the
  `Authorization` header the API uses (would force a token in the URL, which ends up in logs/ngrok).
* **Real problem found (from reading the code; not benchmarked):** `receive_whatsapp/messenger/instagram_webhook`
  are `async def` and call the blocking `process_webhook_payload` (embedding + LLM + send, several
  seconds) directly. That blocks the event loop, so *every other request in the process* (staff replies,
  polls, widget) waits for the turn to finish. A stream connection would stall the same way.

**Recommendation: polling for v1.**

* Thread view: `GET /inbox/conversations/{id}/messages?after=<created_at|id>` every **3s** while open and
  the tab is visible.
* List view: `GET /inbox/conversations` every **10s** while the page is visible (plus refetch on tab focus)
  and a light `GET /inbox/summary` (unread + needs-attention counts) every 30s for the nav badge.
* Everything is indexed reads; at today's volume this is trivial. Latency ≤3s for the active thread —
  "near-real-time" as requested. If a second worker/pub-sub ever arrives, SSE can be layered on later
  with the same endpoints as the fallback.
* **Prerequisite fix (small, separate):** run the webhook body in the threadpool
  (`await run_in_threadpool(process_webhook_payload, …)` or make the handlers plain `def` after reading
  the body) so an LLM turn no longer freezes the dashboard. Worth doing before this ships regardless.
* Widget side: staff replies to website customers arrive only by the widget's poll. Change the poll to
  run **whenever the panel is open** (8–10s, only while tab visible, existing `widget_poll_rate_limiter`
  applies), include `STAFF` in the server filter, and when there's no `after` yet, return messages since
  session start. That is the only widget change.

## 5. RBAC

* Today: `owner`/`admin`/`staff` roles exist; `/handoffs` = all three; check-in = any authenticated
  user; reports/analytics/channels/knowledge/settings = owner/admin. **But no code creates admin/staff
  users** (`auth_service` only creates the owner; there is no invite flow) — all 26 rows are owners. So
  in practice the inbox has one role right now; the design has to be right for when staff logins exist.
* Proposal: **view and reply both = owner/admin/staff** (`_INBOX_ROLES`, same as handoffs). Rationale:
  the people fielding a handoff are exactly the people who must answer it; splitting view from reply
  makes "staff can see a customer waiting but can't help" — the failure the feature exists to remove.
  The replying risk (a message going out under the business's name) is bounded by: every staff message
  stores its author (`sent_by_user_id`), the inbox shows who replied, and an `AuditLog` row is written
  (`action="inbox_reply"`) — the same audit mechanism bookings use.
* Kept owner/admin-only: nothing in v1 (no delete-message, no export, no editing a customer's contact
  info from the inbox). Open question §8-Q4: do you want a per-user "can reply" switch later?
* Tenant isolation: every query tenant-scoped through `business_id` like all existing routes; a
  conversation from another business is a 404 (`get_conversation` already does this).
* Privacy note: the inbox exposes raw customer conversations (phone numbers/PII in text) to whichever
  roles get it — same data staff already see in Handoffs/Appointments, but worth a conscious yes.

## 6. Concrete plan

### 6.1 Data model (one migration)

`conversations`: `human_takeover_until timestamptz NULL`, `human_takeover_by uuid NULL`,
`staff_last_read_at timestamptz NULL` (shared read marker, not per-user — per-user read state is v2).

`messages`: `sent_by_user_id uuid NULL` (staff author; composite tenant FK not possible since `messages`
has no `business_id` — same "inherits tenant via conversation" convention, validated in the service),
`delivery_status varchar(20) NULL` (`sent` | `simulated` | `failed` | `not_applicable`; NULL = legacy),
`delivery_detail varchar(255) NULL` (the existing `send_detail` string, e.g. `failed: HTTP 400`),
`client_msg_id varchar(64) NULL` + `UNIQUE(conversation_id, client_msg_id)` (idempotent double-click/retry).
New index `(conversation_id, created_at)`.

Deliberately **not** added: `last_message_at` (would need writes at ~10 Message-creation sites; computing
it from `messages` with the new index is fast at this scale — denormalize only if the list query gets
slow), an `assignee` table, per-user read state, a `closed` conversation status, attachments.

### 6.2 API (`/api/v1/inbox/…`, roles owner/admin/staff)

| Route | Purpose |
|---|---|
| `GET /inbox/conversations?tab=needs_reply\|handoffs\|all&channel=&limit&offset` | list: customer name, channel, last message preview/time/sender, unread flag, open-handoff flag, takeover state (`human_takeover_by` name), `can_reply` + reason (window) |
| `GET /inbox/conversations/{id}` | header info: customer (name/phone/email masked as elsewhere), channel, handoff (id/reason), takeover, reply-window state |
| `GET /inbox/conversations/{id}/messages?after=` | thread, oldest→newest, incl. sender type, staff author name, delivery status |
| `POST /inbox/conversations/{id}/reply {content, client_msg_id}` | staff send (see 6.3) |
| `POST /inbox/conversations/{id}/takeover` / `…/release` | claim / hand back to AI (release also resolves nothing — resolving a handoff stays its own action, and resolving it releases) |
| `POST /inbox/conversations/{id}/read` | sets `staff_last_read_at` |
| `GET /inbox/summary` | unread + needs-attention counts (nav badge) |

Existing `/handoffs` stays as is; its `PATCH resolve` additionally clears takeover. The existing
`POST /conversations/{id}/messages` (customer-message test endpoint) is untouched — new routes live under
`/inbox` to avoid confusion with it.

### 6.3 Send architecture

`inbox_service.send_staff_reply(db, conversation, user, content, client_msg_id)`:
1. Validate: non-blank, length cap (WhatsApp 4096), conversation is this tenant's, and **reply window open**
   for the channel (else 409 with a clear message).
2. Idempotency: existing row with the same `(conversation_id, client_msg_id)` → return it.
3. Insert `Message(STAFF, sent_by_user_id, content, delivery_status=pending)` + set
   `human_takeover_until/by`, commit (customer's next message is now already protected).
4. Push via a refactored `proactive._push_to_channel(db, conversation, text) -> str` (the existing
   try-block extracted; `send_to_conversation` keeps working unchanged for payments).
5. Map the returned string → `delivery_status` (`sent…`→sent, `simulated…`→simulated, `failed…`/`push failed`→failed),
   store `delivery_detail`, commit, write `AuditLog`. Website: status `sent` (= "delivered on next poll").
6. On `failed`, the UI shows the message with a red "Not delivered — <reason>" and a retry (same
   `client_msg_id` semantics: retry creates a new attempt only after the failed one).

Not building: message queue/outbox worker (a failed send is visible and retryable by a human — YAGNI until
volume), attachments, templates (WhatsApp template messages to re-open the window are a real follow-on,
see Q3).

### 6.4 Orchestrator change (the risky part — small diff, big blast radius)

* Guard at the top of `handle_incoming_message` (§3.2) + re-check after the LLM call (§3.3).
* Return shape: `response: None` plus `takeover: True`; update the 3 webhook handlers, widget route,
  voice route, testing endpoint to tolerate it.
* Prompt line for `staff:` history (§3.5) → run the conversation-quality eval.
* Tests: takeover suppresses the AI for all four channels + widget; expiry resumes; release resumes;
  race (staff reply committed during a stubbed slow LLM call → AI draft discarded); system payment
  message still sent during takeover; cross-tenant 404s; role checks; window rules per channel;
  idempotent double-send; failed-send status.

### 6.5 UI (reuses the redesign components)

New nav item **"Inbox"** (icon `IconInbox`), above "Human Handoffs", with a badge from `/inbox/summary`.
`/dashboard/inbox` and `/dashboard/inbox/:conversationId`. Use existing `PageHeader`, `StatusBadge`
(add colours to `statusColors.ts`: `human` = blue, `ai` = gray, `unread`/`waiting` = orange,
`not_delivered` = red), `EmptyState`/`EmptyRow`, `TableSkeleton`, Mantine `Paper`/`SegmentedControl`.

```
Inbox  (PageHeader: "Every customer conversation, one place")
[ Needs reply (3) | Handoffs (1) | All ]   [ Channel ▾ ]          <- SegmentedControl + Select
┌──────────────────────────┬──────────────────────────────────────────────┐
│ ● Sita K.   WhatsApp 2m  │ Sita K. · WhatsApp · +977…   [Handled by: AI]│  <- StatusBadge
│   "can I come earlier?"  │ [Handoff: customer asked for a human]        │
│   [handoff] [waiting]    │ [Take over]  [Hand back to AI]  [Resolve]    │
│ ─────────────────────────│ ──────────────────────────────────────────── │
│   Website visitor  8m    │  customer bubble                              │
│   "what are your hours?" │        AI bubble (labelled "AI")              │
│   [AI handling]          │        staff bubble ("Ram" — delivered ✓)     │
│ …                        │  system: "You took over — AI is paused"       │
│                          │ ──────────────────────────────────────────── │
│                          │ [ type a reply…                       ] [Send]│
│                          │ ⚠ 24h window closed — can't send on WhatsApp  │
└──────────────────────────┴──────────────────────────────────────────────┘
mobile (≤ sm): list page → tap → thread page (same routes), back button.
```

Details: message bubbles distinguish CUSTOMER / AI / STAFF (name); a banner shows "AI is paused — hands
back automatically at HH:MM"; composer disabled with an explanation when `can_reply=false`; sending
shows an optimistic bubble → confirmed/failed; unread rows bold; polling per §4. The existing Handoffs
page gains a "Open in inbox" action rather than being replaced.

## 7. Phasing (each independently reviewable; commit only on your go-ahead per rule #6)

1. **Foundations:** webhook event-loop fix; migration; `(conversation_id, created_at)` index.
2. **Read-only inbox:** list/thread endpoints + UI, polling, unread badge. No sending yet — lowest risk,
   useful immediately for monitoring.
3. **Takeover + orchestrator guard + staff reply + widget poll change** — *the* risky phase; ships with the
   full test list in 6.4 and a live end-to-end proof per channel (real widget; real WhatsApp/Messenger/IG
   only where credentials exist — the rest is signature-simulated, and will be labelled as such).
4. **Later:** Meta echo → auto-takeover; non-text inbound placeholders; per-user read state;
   WhatsApp template messages for the closed window; unanswered-during-takeover fallback; SSE.

## 8. Decisions needed from you

* **Q1 — Takeover timer:** 2h sliding + explicit hand-back + resolve-releases (recommended), or
  hand-back-only (no auto-expiry), or a shorter/longer default?
* **Q2 — Scope of v1 channels for *sending*:** all four in phase 3 (recommended; the send path exists),
  or website + WhatsApp first?
* **Q3 — Closed 24h window:** v1 shows "can't reply, window closed" only (recommended), or should v1 include
  WhatsApp template messages / Meta `HUMAN_AGENT` tag handling (needs Meta approval + templates)? **(verify** rules
  first — I can do the Meta-docs check as a mini-phase if you want.)
* **Q4 — RBAC:** view+reply for owner/admin/staff (recommended). Want a "can reply" restriction later?
  Related: there is currently **no way to create staff/admin logins** — do you want that (invite flow) scheduled
  before/alongside, or is the owner the only user for now?
* **Q5 — Non-text inbound (images/voice notes):** leave dropped in v1 (recommended, called out in the UI),
  or store a "[image received — open in WhatsApp]" placeholder now?
* **Q6 — Prompt change** for `staff:` lines requires the conversation-quality eval (real Azure credits) —
  OK to spend that in phase 3?

## 9. Other things found while investigating (not part of this feature)

* **CORRECTED (first draft overstated this):** the "I've also let our team know" addendum is NOT appended to every
  reply in an open-handoff conversation. `_handoff_reason` returns `None` for a non-qualifying turn *before* the
  "already open?" check, so only turns that themselves qualify (complaint / asked-for-human / low-knowledge) get it —
  but on those it repeats every time, because `handoff is not None` cannot tell "created now" from "already open".
  Different from the earlier addendum fixes (which stopped it firing on turns that did NOT need a human).
* `POST /conversations/{id}/messages` lets any authenticated role inject a *customer* message into any of
  their tenant's conversations and trigger the AI — a test endpoint still live in production routing.
* AI-reply send failures are not recorded anywhere except logs (§1).
* All Meta webhook handlers block the event loop during an LLM turn (§4).
