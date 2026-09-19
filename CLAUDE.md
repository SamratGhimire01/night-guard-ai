# Working rules for this project

## Deployment / live-verification discipline (added 2026-09-16, Phase 7)

- **Never use `uvicorn --reload`** for this backend. It's unsafe for a process handling real
  bookings and running Phase 45's in-process background scheduler — a reload mid-request could
  interrupt an in-progress transaction or fire on a half-completed multi-file edit.
- The backend container (`night_guard_ai-backend-1`) does **not** auto-reload code on file
  change. Editing files on the bind-mounted volume does not re-execute the already-running
  `uvicorn app.main:app` process — it keeps whatever module state it imported at container start
  until it is explicitly restarted.
- **Mandatory step, every phase:** run `docker compose up -d --force-recreate backend` BEFORE any
  live verification that hits the actual running server (curl/HTTP against `localhost:8010` or
  the public tunnel, a real WhatsApp/widget conversation, a browser session) — and BEFORE
  reporting a phase complete. Do this even if it feels redundant.
- This does **not** apply to `pytest` runs or any one-off `docker exec night_guard_ai-backend-1
  python <script>.py` invocation (including the eval runners in `backend/tests/eval/`) — each of
  those is a fresh Python process that imports current code from disk on every invocation, so it's
  never stale regardless of the long-running server's state. The staleness risk is specific to the
  one persistent server process that answers real HTTP traffic.
- Root cause of the 2026-09-16 incident: the host/Docker environment rebooted once around 12:50
  local and the backend container was never restarted again that day; every fix committed to the
  working tree from 14:01 onward sat inert in that stale process (never reaching real customers)
  until this rule was added and the container was force-recreated.

## Standing rule #6 — commits

Never commit without the user's explicit, in-the-moment confirmation, even if a ticket or prior
instruction implies it should happen automatically. Confirm at the end of every phase.
