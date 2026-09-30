# Deploying Night Guard AI to production

This is the checklist for running Night Guard AI for real customers. Development (`scripts/run-vesper.sh`, ngrok,
the Vite dev server) is described in `docs/development.md`; none of it belongs in production.

## 1. What runs

| Piece | How | Notes |
|---|---|---|
| Database | Postgres 16 with the `pgvector` extension | Managed Postgres is best (automatic backups). `CREATE EXTENSION vector;` once. |
| API | `backend/Dockerfile` | Runs as a non-root user. Applies database migrations on every start (`docker-entrypoint.sh`); a failed migration stops the container instead of serving the wrong schema. One process per container (the background scheduler runs inside it: reminders, no-shows, lead scoring, follow-ups). |
| Dashboard | `frontend/Dockerfile` | A static build served by nginx. Build with `--build-arg VITE_API_BASE_URL=https://api.yourdomain/api/v1`. |
| HTTPS | A reverse proxy or load balancer in front of both (Caddy, nginx, Cloudflare, your host's LB) | The API trusts `X-Forwarded-*` headers from the proxy (`--proxy-headers`). |

Run **one** API container: the in-process scheduler would otherwise send reminders and follow-ups twice.

## 2. Required settings (`backend/.env`)

Start from `backend/.env.example`. With `ENVIRONMENT=production` the API **refuses to start** if:

- `SECRET_KEY` is shorter than 32 characters or looks like a placeholder. Generate one: `openssl rand -hex 32`.
- `DASHBOARD_CORS_ORIGINS` is `*` or empty. Set it to your dashboard's exact origin, e.g. `https://app.yourdomain.com`.

It starts but logs a warning (read the first lines of `docker compose logs backend`) if:

- `BACKEND_BASE_URL` / `DASHBOARD_BASE_URL` are not public `https://` domains. Customer links (QR codes, payment
  pages, password-reset links) are built from them.
- eSewa or Khalti still point at their sandboxes (`ESEWA_BASE_URL`, `ESEWA_PRODUCT_CODE`, `ESEWA_SECRET_KEY`,
  `KHALTI_BASE_URL`, `KHALTI_SECRET_KEY`).
- There is no platform email (`GMAIL_ADDRESS`, `GMAIL_APP_PASSWORD`): password resets, invites and owner alerts need it.

Also set: `DATABASE_URL`, the Azure OpenAI variables, `PLATFORM_SUPPORT_EMAIL` (where "Request Premium" goes),
Meta app secrets and verify tokens for the channels you offer, `GOOGLE_*` for Calendar, `DEEPGRAM_API_KEY` for voice.

In production the API also turns off `/docs`, `/redoc` and `/openapi.json`, hides the `/test-chat` and `/widget-demo`
developer pages, stops accepting ngrok origins, and sends HSTS.

## 3. Meta (WhatsApp, Messenger, Instagram)

- Webhook URLs: `https://api.yourdomain.com/api/v1/webhooks/{whatsapp|messenger|instagram}`, with the verify tokens
  from your `.env`.
- For self-serve WhatsApp signup, set `WHATSAPP_EMBEDDED_SIGNUP_APP_ID` and `WHATSAPP_EMBEDDED_SIGNUP_CONFIG_ID`
  (needs a Meta app approved for Embedded Signup). Without them, businesses enter credentials by hand.

## 4. Before the first real customer

- [ ] `ENVIRONMENT=production` and the API starts with no warnings you haven't accepted.
- [ ] Database backups are on (daily, kept at least 7 days) and you have restored one once to check it works.
- [ ] Log in, use "Forgot your password?" and confirm the email arrives with a working link.
- [ ] Book through the website chat on a real site; confirm the owner alert email and the customer confirmation.
- [ ] Only one API container is running.
- [ ] Error monitoring: forward container logs somewhere you'll see them (the API logs JSON; every unexpected error
      is logged as `unhandled exception on METHOD /path`).

## 5. Customer data

Real conversation exports (`backend/scripts/pull_real_conversations.py`) contain customers' names, phone numbers and
emails. They are git-ignored; keep them off shared drives and delete them when an evaluation is done. Earlier exports
are still in this repository's history; purging them needs `git filter-repo` and a force push, which rewrites history
for everyone and should be planned with the team.
