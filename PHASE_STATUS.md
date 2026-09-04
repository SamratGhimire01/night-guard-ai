# Night Guard AI — Phase Status Log

## Phase 0 — Development Environment

**Date:** 2026-09-03

**Required:**
- Check installed versions of git, docker, docker compose, python (3.11+ preferred), node.js — do not install anything missing without asking first.
- Initialize a git repository if one doesn't exist.
- Create a .gitignore for a Python/FastAPI + Node project (venvs, `__pycache__`, `.env`, `node_modules`, docker volumes, etc).
- Create a top-level README.md with a one-paragraph project description.
- Create PHASE_STATUS.md and log Phase 0.
- Do not scaffold the app itself yet.

**Implemented:**
- Verified tool versions (see Verification output below). No installations were performed.
- Ran `git init` in `/home/samrat01/Night_Guard_AI` (new repo, branch `master`, no commits yet).
- Created `.gitignore` covering Python (`__pycache__`, `.venv`, etc.), `.env` files, Node (`node_modules`, build output), Docker volume/data directories, and common IDE/OS/log clutter.
- Created `README.md` with the one-paragraph project description.
- Created this `PHASE_STATUS.md` file.

**Verification output (actual, run 2026-09-03):**
```
$ git --version
git version 2.34.1

$ docker --version
Docker version 29.1.3, build 29.1.3-0ubuntu3~22.04.2

$ docker compose version
Docker Compose version v5.5.0

$ python3 --version
Python 3.10.12

$ node --version
v20.20.2

$ npm --version
10.8.2
```

**Result / Acceptance criteria:**
| Criterion | Status |
|---|---|
| git repo initialized | ✓ Pass |
| git version confirmed | ✓ Pass (2.34.1) |
| docker version confirmed | ✓ Pass (29.1.3) |
| docker compose version confirmed | ✓ Pass (v5.5.0) |
| python version confirmed | ⚠ Pass with caveat — 3.10.12 installed, 3.11+ preferred but not installed |
| node version confirmed | ✓ Pass (v20.20.2) |
| .gitignore created | ✓ Pass |
| README.md created | ✓ Pass |
| PHASE_STATUS.md created and Phase 0 logged | ✓ Pass |

**Known issues:**
- Python installed is 3.10.12, below the 3.11+ preference stated in the phase objective. No action taken pending user decision (e.g. install 3.11+ via pyenv/deadsnakes, or proceed with 3.10). Note: this is moot for the app itself — the Phase 1 Dockerfile uses `python:3.11-slim`, so the backend always runs on 3.11 regardless of the host's Python.
- No commit has been made yet — awaiting user confirmation of this verification output per working rule #6.

---

## Phase 1 — Architecture Foundation

**Date:** 2026-09-03

**Required:**
- Skeleton project structure (`backend/`, `frontend/`, `docs/`) with a running FastAPI + PostgreSQL setup via Docker. No business features/tables yet.
- Dockerfile on `python:3.11-slim`+; `docker-compose.yml` with `backend` + `postgres` (16.x) services, a named volume for Postgres data, env vars sourced from `.env`.
- `.env.example` listing every required env var with dummy values; no real secrets committed anywhere.
- `app/core/config.py` (pydantic-settings), `app/core/logging.py` (structured logging), `app/core/exceptions.py` (custom exception hierarchy + consistent JSON error handler).
- API versioning under `/api/v1/`; `GET /api/v1/health` that actually checks the DB (`SELECT 1`) and returns non-200 with a clear error if unreachable, instead of a fake "ok".
- `app/db/database.py` with SQLAlchemy engine/session, no business tables yet.
- `docs/architecture.md` (layered architecture) and `docs/development.md` (how to run locally).

**Implemented:**
- Full directory skeleton exactly as specified (`backend/app/{api,core,db,schemas,services,llm,memory,rag,workers}`, `backend/tests/{unit,integration,security}`, `frontend/`, `docs/`), each Python package as an empty `__init__.py` placeholder — no business logic added.
- `backend/Dockerfile`: `python:3.11-slim`, installs `requirements.txt`, runs `uvicorn app.main:app`.
- `backend/requirements.txt`: fastapi, uvicorn[standard], sqlalchemy, psycopg2-binary, pydantic, pydantic-settings, alembic, ruff (pinned versions).
- `docker-compose.yml`: `backend` + `postgres:16-alpine` services, both configured via `env_file: ./backend/.env` (no hardcoded credentials), named volume `postgres_data` for Postgres persistence. Backend host port is `${BACKEND_PORT:-8010}:8000` — see "Known issues" for why 8000/5432 weren't used directly.
- `backend/.env.example`: `POSTGRES_USER`, `POSTGRES_PASSWORD`, `POSTGRES_DB`, `DATABASE_URL`, `SECRET_KEY`, `ENVIRONMENT`, `LOG_LEVEL` — all placeholder values, no real secrets.
- `app/core/config.py`: `pydantic-settings` `BaseSettings` loading from environment / `.env`, no hardcoded values.
- `app/core/logging.py`: stdlib `logging` with a custom `JSONFormatter`, configured via `configure_logging()` — structured JSON to stdout, no bare `print()`.
- `app/core/exceptions.py`: `NightGuardError` base class, `ServiceUnavailableError` / `NotFoundError` subclasses, FastAPI exception handlers registered via `register_exception_handlers()` returning a consistent `{"error": {"type", "message"}}` JSON shape for both known and unhandled exceptions.
- `app/core/security.py`: placeholder module (reads `SECRET_KEY` from settings); no auth scheme yet — intentionally deferred.
- `app/db/database.py`: SQLAlchemy engine (`create_engine` with `pool_pre_ping=True`), `SessionLocal`, `Base` (`DeclarativeBase`) with **no models registered**, and a `get_db()` dependency generator. No business tables.
- `app/api/routes/health.py`: `GET /api/v1/health` — runs `SELECT 1` against the real engine; on success returns `{"status": "ok", "database": "connected"}` (200); on `SQLAlchemyError` raises `ServiceUnavailableError` → 503 with a JSON error body. Verified live in both directions (see below).
- `app/main.py`: creates the `FastAPI` app, configures logging on import, registers exception handlers, mounts the health router under `/api/v1`.
- Alembic scaffold: `backend/alembic.ini` (`script_location = app/db/migrations`), `app/db/migrations/env.py` (wired to `settings.database_url` and `Base.metadata`), `script.py.mako`, empty `versions/` — no migrations generated (no models exist yet).
- `docs/architecture.md`: layered flow (Channel → FastAPI → Conversation/Orchestration → LLM → Python validation → Business logic → PostgreSQL), including the explicit rule that the LLM never gets direct write access to business data.
- `docs/development.md`: `cp backend/.env.example backend/.env`, `docker compose up --build`, how to curl the health endpoint, how to tear down.
- Created a local `backend/.env` (copied from `.env.example`, dummy dev values only) purely to run the verification below — it is git-ignored and was never staged.

**Deviation from the literal spec (flagged, not hidden):** the acceptance criteria said "`docker compose up` from a clean checkout" using the default ports. Host ports 8000 and 5432 were already occupied by *other, unrelated* pre-existing Docker containers on this machine (`nightguard-ai-backend-1`, `nightguard-ai-postgres-1`, `nightguard-ai-n8n-1`, apparently from separate prior work) — not by anything in this repo. Rather than stopping someone else's running containers, `docker-compose.yml` was adjusted to: (a) not publish Postgres's port to the host at all (the backend reaches it over the internal Docker network only — the app never needed host access to it), and (b) publish the backend on host port `8010` by default (`${BACKEND_PORT:-8010}`, overridable via env var). This is a real, permanent change to the compose file, not a one-off workaround — documented here and in `docs/development.md` implicitly via the health-check example URL below.

**Verification output (actual, run 2026-09-03):**

1. `docker compose up --build -d` — succeeded after the port adjustment above:
```
 Container night_guard_ai-postgres-1 Started
 Container night_guard_ai-backend-1 Starting
 Container night_guard_ai-backend-1 Started
```
Backend log tail:
```
backend-1  | INFO:     Started server process [1]
backend-1  | INFO:     Waiting for application startup.
backend-1  | INFO:     Application startup complete.
backend-1  | INFO:     Uvicorn running on http://0.0.0.0:8000 (Press CTRL+C to quit)
```
Postgres log tail:
```
postgres-1  | 2026-09-03 17:19:11.603 UTC [1] LOG:  database system is ready to accept connections
```
`docker compose ps`:
```
NAME                        SERVICE    STATUS          PORTS
night_guard_ai-backend-1    backend    Up              0.0.0.0:8010->8000/tcp
night_guard_ai-postgres-1   postgres   Up              5432/tcp (internal only)
```

2. `curl -i http://localhost:8010/api/v1/health` (DB up):
```
HTTP/1.1 200 OK
content-type: application/json

{"status":"ok","database":"connected"}
```

3. Negative-path check (not explicitly required, run anyway to prove the health check is real): stopped the `postgres` container and re-curled:
```
HTTP/1.1 503 Service Unavailable
content-type: application/json

{"error":{"type":"service_unavailable","message":"Database is unreachable."}}
```
Restarted `postgres`; health returned to `{"status":"ok","database":"connected"}` within ~3s.

4. Secret scan — `git status`, `git ls-files | grep '\.env$'`, and a grep for `api[_-]?key|secret|password|token|BEGIN ... PRIVATE KEY|AKIA...` across tracked file types:
```
no .env files tracked
docs/development.md:18:...backend's `DATABASE_URL` / `SECRET_KEY`.
backend/app/core/security.py:1:"""Security primitives...
backend/app/core/security.py:10:SECRET_KEY = settings.secret_key
backend/app/core/config.py:12:    secret_key: str
```
Only field/variable *names* appear — no actual secret values. Clean.

5. `.env` git-ignore check:
```
$ git check-ignore -v backend/.env
.gitignore:21:.env	backend/.env

$ git add -n .   (dry run)
backend/.env would NOT be staged by git add .
```

6. Lint — `docker compose exec backend ruff check .`:
```
All checks passed!
```

7. Sanity check — `docker compose exec backend alembic current` (confirms the Alembic config actually connects, with zero migrations applied, as expected since no models exist yet):
```
INFO  [alembic.runtime.migration] Context impl PostgresqlImpl.
INFO  [alembic.runtime.migration] Will assume transactional DDL.
```

**Result / Acceptance criteria:**
| Criterion | Status |
|---|---|
| `docker compose up` succeeds from a clean checkout | ✓ Pass (ports adjusted — see Deviation note above) |
| `curl .../api/v1/health` returns 200 with DB confirmed | ✓ Pass |
| Health endpoint returns non-200 with clear error when DB is down | ✓ Pass (503, verified live) |
| No secrets committed anywhere | ✓ Pass (grep clean, only field names matched) |
| `.env` in `.gitignore` and not tracked by git | ✓ Pass |
| Basic lint (ruff) runs clean | ✓ Pass |

**Known issues:**
- Host ports 8000 and 5432 could not be used directly because unrelated, pre-existing Docker containers on this machine already hold them. Backend now defaults to host port 8010 (`BACKEND_PORT` env var to override); Postgres is not exposed to the host at all. This is a permanent decision, not a temporary patch — flagging in case a different fixed port is preferred.
- No authentication/security scheme exists yet (`app/core/security.py` is a placeholder) — expected at this phase, not a defect.
- No business tables or Alembic migrations exist yet — expected per Phase 2 scope.
- No commit has been made yet — awaiting user confirmation of this verification output per working rule #6.

---

## Phase 2 — Database Foundation

**Date:** 2026-09-03

**Required:**
- SQLAlchemy models + Alembic migration for the operational schema (17 entities listed in the prompt). Schema only — no business logic, no API endpoints.
- UUID primary keys throughout (multi-tenant SaaS); every tenant-owned table gets an indexed `business_id` FK.
- Cross-tenant referential-integrity check where it matters most (e.g. `Appointment.business_id` must match `Customer`/`Service`'s), or an explicit documented gap if impractical at the DB level.
- Generate and apply the initial migration against the running Docker Postgres.

**Implemented:**
- **Alembic wiring** (already set up in Phase 1, confirmed still correct): `app/db/migrations/env.py` reads `DATABASE_URL` from `app.core.config.settings`, not a hardcoded string. Added one line — `from app.db import models` — so autogenerate actually sees the new tables (previously `Base.metadata` had nothing registered).
- **Mixins** (`app/db/models/mixins.py`): `UUIDPrimaryKeyMixin` (Postgres-generated UUID PK via `gen_random_uuid()` — no sequential integers anywhere), `CreatedAtMixin`, `UpdatedAtMixin`, `TenantMixin` (adds a required, indexed `business_id` FK to `businesses.id`). Used consistently so every tenant table gets the same indexed FK instead of hand-repeating it 13 times.
- **17 tables**, one SQLAlchemy 2.0 declarative model each, split across 12 files by domain (`business.py`, `customer.py`, `staff.py`, `service.py`, `conversation.py`, `appointment.py`, `knowledge.py`, `notification.py`, `integration.py`, `audit_log.py`, `handoff.py`, `follow_up.py`), all re-exported from `app/db/models/__init__.py`: Business, BusinessUser, Customer, Staff, Service, BusinessHours, Conversation, Message, Appointment, AppointmentParticipant, KnowledgeDocument, KnowledgeChunk, Notification, Integration, AuditLog, HumanHandoff, FollowUp. Columns match the spec exactly — no extra fields invented, no timestamps added to tables that weren't specced with them (e.g. `BusinessHours`, `AppointmentParticipant`, `KnowledgeChunk` intentionally have none, per the literal spec).
- **Multi-tenancy indexes**: every table that has a `business_id` column (13 of them) has a dedicated `ix_<table>_business_id` index, verified by direct SQL query (see Verification §3) — not just asserted.
- **Cross-tenant referential integrity — implemented at the DB level**, not just noted as a gap, using Postgres composite foreign keys: `customers`, `services`, `staff`, `conversations`, and `appointments` each got a `UNIQUE(id, business_id)` constraint (required by Postgres as the FK target), and the following composite `ForeignKeyConstraint`s enforce "referenced row must belong to the same business_id":
  - `appointments` → `customers`, `services`, `staff` (staff nullable — Postgres's default MATCH SIMPLE correctly skips the check when `staff_id` is NULL)
  - `conversations` → `customers`
  - `notifications` → `appointments` (nullable, same MATCH SIMPLE behavior)
  - `human_handoffs` → `conversations`
  - `follow_ups` → `customers` and `conversations`
  Verified live (not just by reading the DDL): inserted a customer+service under Business A, a valid same-tenant appointment succeeded, then an appointment attempting to attach Business A's customer to Business B was **rejected** by Postgres with `violates foreign key constraint "fk_appointments_customer_same_tenant"` (full output in Verification §6 below). Redundant single-column FKs that autogenerate would otherwise have produced alongside these composite ones were removed from the models so each relationship has exactly one FK definition.
- **Documented gap** (not enforced at the DB level, by deliberate scope decision, not oversight): `KnowledgeDocument.approved_by` references `business_users.id` directly without a same-tenant composite check. Extending the same pattern here was straightforward but was left out to bound scope — this is a real gap, not a "can't do it," and should be closed before production (add `UNIQUE(id, business_id)` on `business_users` and a composite FK on `knowledge_documents`). `AuditLog.resource_type`/`resource_id` are a generic polymorphic reference (they can point at any table) — no FK is possible there by design, not a gap.
- **pgvector for `KnowledgeChunk.embedding`**: it was reasonably easy to add, so it's real, not a placeholder. Switched the `postgres` image in `docker-compose.yml` from `postgres:16-alpine` to `pgvector/pgvector:pg16` (verified the `vector` extension is available — see Verification §0), added the `pgvector` Python package, and the migration runs `CREATE EXTENSION IF NOT EXISTS vector` before creating the table. `embedding` is `Vector(1536)`, nullable — 1536 is a placeholder dimension matching common current embedding models; revisit once an actual embedding model is chosen (Phase 5/6), noted in a code comment.
- Enums use native Postgres `ENUM` types via SQLAlchemy `Enum` (`business_user_role`, `appointment_status`, `knowledge_document_status`, `message_sender_type`, `notification_status`) for the fields the spec explicitly enumerated values for. Fields the spec left as unenumerated free text (`Conversation.status`, `HumanHandoff.status`, `FollowUp.status`, `AuditLog.result`, `Integration.type`, channel fields) were kept as plain `String` — not inventing allowed values that weren't given.
- `Integration.config` uses Postgres `JSONB` (spec said "JSON"; used the Postgres-native, indexable variant).
- **Migration file** `backend/app/db/migrations/versions/371630166e11_initial_schema.py`, generated via `alembic revision --autogenerate`, then hand-fixed for two real bugs autogenerate produced (see Verification below for how each was caught): missing `import pgvector.sqlalchemy` (the generated `embedding` column referenced the type without importing it — would have crashed on next run), and a `downgrade()` that dropped tables but not the 5 native enum types those tables' columns created, which broke a repeat `upgrade head` after a `downgrade base`. Both are fixed in the committed migration file.
- Deleted the leftover `versions/.gitkeep` now that a real migration exists.
- Added `volumes: - ./backend:/app` to the `backend` service in `docker-compose.yml` so generated files (like this migration) land on the host instead of being trapped inside the container — needed because Phase 1's compose file only baked code in at build time with no bind mount.

**Verification output (actual, run 2026-09-03):**

0. pgvector extension available in the new Postgres image:
```
$ docker compose exec postgres psql -U nightguard -d nightguard -c "SELECT * FROM pg_available_extensions WHERE name='vector';"
  name  | default_version | installed_version |                       comment
--------+-----------------+--------------------+-------------------------------------------------------
 vector | 0.8.6           |                    | vector data type and ivfflat and hnsw access methods
```

1. `alembic upgrade head` (clean run against the Docker Postgres):
```
INFO  [alembic.runtime.migration] Context impl PostgresqlImpl.
INFO  [alembic.runtime.migration] Will assume transactional DDL.
INFO  [alembic.runtime.migration] Running upgrade  -> 371630166e11, initial schema
```

2. `\dt` — all 17 model tables plus Alembic's own bookkeeping table exist:
```
                   List of relations
 Schema |           Name           | Type  |   Owner
--------+--------------------------+-------+------------
 public | alembic_version          | table | nightguard
 public | appointment_participants | table | nightguard
 public | appointments             | table | nightguard
 public | audit_logs               | table | nightguard
 public | business_hours           | table | nightguard
 public | business_users           | table | nightguard
 public | businesses               | table | nightguard
 public | conversations            | table | nightguard
 public | customers                | table | nightguard
 public | follow_ups               | table | nightguard
 public | human_handoffs           | table | nightguard
 public | integrations             | table | nightguard
 public | knowledge_chunks         | table | nightguard
 public | knowledge_documents      | table | nightguard
 public | messages                 | table | nightguard
 public | notifications            | table | nightguard
 public | services                 | table | nightguard
 public | staff                    | table | nightguard
(18 rows)
```

3. Every table with a `business_id` column has a dedicated index on it — verified by querying `information_schema` + `pg_indexes`, not asserted:
```
        table_name        | has_business_id_column | has_dedicated_index
--------------------------+-------------------------+---------------------
 appointment_participants | f                       | f
 appointments             | t                       | t
 audit_logs               | t                       | t
 business_hours           | t                       | t
 business_users           | t                       | t
 businesses               | f                       | f
 conversations            | t                       | t
 customers                | t                       | t
 follow_ups               | t                       | t
 human_handoffs           | t                       | t
 integrations             | t                       | t
 knowledge_chunks         | f                       | f
 knowledge_documents      | t                       | t
 messages                 | f                       | f
 notifications            | t                       | t
 services                 | t                       | t
 staff                    | t                       | t
```
The four `f`/`f` rows are correct, not missed: `businesses` is the tenant itself (no `business_id` on itself), and `appointment_participants` / `knowledge_chunks` / `messages` have no `business_id` per the literal spec — they inherit tenant context through their parent FK (`appointment_id`, `knowledge_document_id`, `conversation_id` respectively).

4. Reversibility — **first attempt failed** (real bug caught, not hidden): `alembic downgrade base` succeeded, but the subsequent `alembic upgrade head` crashed with `psycopg2.errors.DuplicateObject: type "business_user_role" already exists`, because `downgrade()` dropped tables but left the 5 Postgres enum types behind. Fixed by adding explicit `sa.Enum(name=...).drop(op.get_bind(), checkfirst=True)` calls for all 5 enums at the end of `downgrade()`. Full cycle after the fix:
```
=== upgrade head (from empty db) ===
INFO  [alembic.runtime.migration] Running upgrade  -> 371630166e11, initial schema
(18 tables present)

=== downgrade base ===
INFO  [alembic.runtime.migration] Running downgrade 371630166e11 -> , initial schema
(only alembic_version remains; 0 leftover enum types — checked via pg_type)

=== upgrade head again ===
INFO  [alembic.runtime.migration] Running upgrade  -> 371630166e11, initial schema
(18 tables present again — clean, no errors)
```

5. Lint — `docker compose exec backend ruff check .` (covers models and the migration file): `All checks passed!`

6. Functional proof the cross-tenant composite FK actually rejects bad data (run against a fresh upgrade, then reset back to empty via downgrade/upgrade before leaving the DB):
```sql
-- Business A + Business B, a customer/service under Business A, a valid same-tenant appointment:
INSERT ... -- all succeed

-- Attempt to attach Business A's customer to a Business B appointment:
INSERT INTO appointments (..., business_id, customer_id, ...) VALUES (..., 'Business B id', 'Business A customer id', ...);
ERROR:  insert or update on table "appointments" violates foreign key constraint "fk_appointments_customer_same_tenant"
DETAIL:  Key (customer_id, business_id)=(33333333-..., 22222222-...) is not present in table "customers".
```
Database was reset (`alembic downgrade base` → `alembic upgrade head`) after this test, confirmed empty (`SELECT count(*) FROM businesses` → `0`) before being left for the user.

7. Health endpoint still passes throughout (backend never stopped working while the schema changed): `{"status":"ok","database":"connected"}`.

8. Secrets/`.env` re-checked after all Phase 2 changes — still clean (only field names like `secret_key`/`hashed_password` match, no values; `backend/.env` still untracked).

**Result / Acceptance criteria:**
| Criterion | Status |
|---|---|
| `alembic upgrade head` runs cleanly against Docker Postgres | ✓ Pass |
| `\dt` shows every table from the spec | ✓ Pass (17/17 + alembic's own table) |
| Every tenant table has `business_id` + an index on it, verified by query | ✓ Pass |
| `alembic downgrade base` then `alembic upgrade head` works cleanly | ✓ Pass (only after fixing a real enum-type-leak bug found during this exact test — see §4) |
| Lint/typecheck still clean | ✓ Pass (ruff; no typechecker configured in this project yet) |

**Known issues / gaps for later phases:**
- `KnowledgeDocument.approved_by` is not tenant-cross-checked at the DB level (see "Documented gap" above) — a real, scoped-out gap, not a false claim of completion. Should be closed before production.
- No typechecker (mypy/pyright) is configured yet — "lint" above means ruff only, since that's what Phase 1 set up. Flagging in case static typechecking is expected before production.
- `KnowledgeChunk.embedding` dimension (1536) is a placeholder guess, not tied to any chosen embedding model yet.
- Postgres image change (`postgres:16-alpine` → `pgvector/pgvector:pg16`) required wiping the dev volume (`docker compose down -v`) since it was done from a fresh Phase 1 state with no real data — flagging in case this matters for any other local environment already running the old image.
- No commit has been made yet — awaiting user confirmation of this verification output per working rule #6.

---

## Phase 3 — Authentication + Multi-Tenancy

**Date:** 2026-09-03

**Required:**
- Password hashing (bcrypt/argon2), never plaintext/weak hashes.
- `POST /api/v1/auth/register` — creates Business + first BusinessUser (role=owner) in one transaction, validates email format/password strength/uniqueness.
- `POST /api/v1/auth/login` — verifies credentials, returns a JWT with `business_id` + `role` in the payload; client-supplied `business_id` must never be trusted for any authenticated endpoint from now on.
- `get_current_user` dependency validating the JWT and loading the `BusinessUser`; document the "every business-data endpoint scopes by this" convention in `docs/architecture.md`.
- `require_role([...])` RBAC mechanism, proven with at least one test route.
- JWT secret from env config, documented in `.env.example`; reasonable access-token TTL; refresh-token strategy noted or explicitly punted.
- Login rate limiting (in-memory acceptable) or an explicit documented gap.
- **The critical test**: register two businesses, prove Business A's token cannot read/modify Business B's data — real output, fail-closed or stop and say so.

**Implemented:**
- **Password hashing** (`app/core/security.py`): `bcrypt.hashpw`/`bcrypt.checkpw` directly (not passlib, to sidestep passlib's known compatibility warnings with bcrypt ≥4.1 — same underlying algorithm, one fewer dependency). Verified in the DB: stored value for a real registered user is `$2b$12$il/S.WyYgZ7l1OZ.jRzfIuRxyt3pXj13VEpyVdehE3R..6L07BU.C` — a real bcrypt hash (`$2b$` = bcrypt, `12` = cost factor, followed by salt+hash), not plaintext, not unsalted SHA256 (full query output in Verification §4).
- **`POST /api/v1/auth/register`** (`app/api/routes/auth.py` → `app/services/auth_service.register_business`): creates `Business` then `BusinessUser(role=OWNER)` in one transaction (`db.flush()` to get `business.id` without committing, single `db.commit()` at the end — if user creation failed, the business insert would roll back too). Validates: email format via Pydantic `EmailStr` (`email-validator` package), password strength via a custom validator (min 8 chars, at least one letter, one digit — spec didn't specify exact rules beyond "minimum strength," kept it to widely-accepted minimums rather than inventing arbitrary complexity rules), and email-not-already-registered (checked at the app level for a clean 409, backed by a **new DB-level unique constraint** — see migration below — as the actual race-condition-proof enforcement).
- **`POST /api/v1/auth/login`** (`app/services/auth_service.authenticate`): verifies email+password, returns `TokenResponse{access_token, token_type: "bearer", expires_in}`. The JWT payload (`app/core/security.create_access_token`) is `{sub: user_id, business_id, role, iat, exp}` — verified by direct inspection of a real issued token during manual testing (Verification §2).
- **`get_current_user`** (`app/api/dependencies.py`): `HTTPBearer` extracts the token, `decode_access_token` verifies signature+expiry, then the `BusinessUser` is loaded from the DB by the token's `sub`. Returns the ORM object directly (it already carries `.business_id`/`.role` — no extra dataclass needed). Documented as the mandatory scoping convention in `docs/architecture.md` under "Authentication and tenant-scoping convention," with `app/api/routes/customers.py` cited as the reference implementation.
- **`require_role(allowed_roles)`** (`app/api/dependencies.py`): dependency factory; raises `ForbiddenError` (403) if `current_user.role` isn't in the allowed set. Proven against a real staff user in the automated test (Verification §3) — not just asserted to exist.
- **Proof-of-mechanism routes** (`app/api/routes/customers.py`, backed by `app/services/customer_service.py`): `POST /api/v1/customers` (any authenticated user, scoped to `current_user.business_id`), `GET /api/v1/customers/{id}` (scoped lookup — a cross-tenant ID returns 404, not 403, so existence isn't leaked either), `DELETE /api/v1/customers/{id}` (gated by `require_role(["owner","admin"])`). These are intentionally minimal — full Customer CRUD is not this phase's job, they exist to make the auth/tenancy mechanism testable end-to-end.
- **JWT config**: `SECRET_KEY` (already existed from Phase 1), plus new `JWT_ALGORITHM` (default `HS256`) and `ACCESS_TOKEN_EXPIRE_MINUTES` (default `30`) in `app/core/config.py`, documented with placeholders in `backend/.env.example`.
- **Token TTL / refresh strategy**: access tokens expire after 30 minutes (configurable). **Refresh tokens are punted to a later phase, explicitly** — not faked. A stateless JWT refresh token would be easy to mint, but doing it *safely* needs a persistent revocation store (so a stolen refresh token can be invalidated) which doesn't exist in the schema yet; adding one now would be scope creep beyond "implement auth." Noted in `docs/architecture.md` and below.
- **Login rate limiting** (`app/core/rate_limit.py`): a simple in-memory fixed-window limiter (5 attempts / 60 seconds, keyed by email), wired into the login route before credentials are even checked. Chosen over skipping it, since the ticket explicitly allowed "even a simple in-memory limiter." **Known, documented limitation**: state is per-process — it resets on restart and is not shared across multiple backend replicas, so it should be replaced with a Redis-backed limiter before running more than one backend process. Verified live (Verification §5): 401 for the first attempts, then 429 once the window filled.
- **New migration** `backend/app/db/migrations/versions/5588d67a7cf6_add_unique_constraint_on_business_users_.py`: adds `uq_business_users_email` (global uniqueness — login resolves a user by email alone, with no `business_id` available yet at that point, so it can't be scoped per-tenant). Autogenerate produced an unnamed constraint (`op.create_unique_constraint(None, ...)`) that would have failed on `downgrade()` (`op.drop_constraint(None, ...)` needs a name) — fixed by naming it explicitly in both the model (`UniqueConstraint("email", name=...)` in `__table_args__`) and the migration, and confirmed via `alembic check` that model and DB now agree with no drift.
- **Docs**: `docs/architecture.md` updated with a new "Authentication and tenant-scoping convention" section (the mandatory rule, plus where to look for the reference implementation) and a refreshed "Current state" section.

**CRITICAL SECURITY TEST — full output, not summarized:**

Automated test suite `backend/tests/integration/test_tenant_isolation.py`, run for real against the live Docker Postgres via FastAPI's `TestClient` (not mocked):

```
$ docker compose exec backend python -m pytest tests/integration/test_tenant_isolation.py -v
============================= test session starts ==============================
platform linux -- Python 3.11.16, pytest-8.3.3, pluggy-1.6.0 -- /usr/local/bin/python
rootdir: /app
plugins: anyio-4.15.0
collected 4 items

tests/integration/test_tenant_isolation.py::test_business_a_cannot_read_business_bs_customer PASSED [ 25%]
tests/integration/test_tenant_isolation.py::test_business_a_cannot_delete_business_bs_customer PASSED [ 50%]
tests/integration/test_tenant_isolation.py::test_unauthenticated_request_is_rejected PASSED [ 75%]
tests/integration/test_tenant_isolation.py::test_role_based_access_control_blocks_staff_from_delete PASSED [100%]

========================= 4 passed, 1 warning in 3.77s =========================
```

What each test actually does:
- **`test_business_a_cannot_read_business_bs_customer`** (the one the ticket calls "the single most important test"): registers Business A/User A and Business B/User B for real via `/auth/register`, logs both in for real tokens, creates a `Customer` under Business B, confirms Business B can read its own customer (200), then uses **Business A's token** to `GET /api/v1/customers/{business_B_customer_id}` — asserts the response is `404` with `{"error":{"type":"not_found",...}}`, not `200` and not a 403 that would confirm the resource exists. This matches the spec's scenario exactly: create a customer under one business, then attempt to access it via ID guessing/enumeration using the other business's token.
- **`test_business_a_cannot_delete_business_bs_customer`**: same setup, but Business A attempts `DELETE` on Business B's customer — asserts 404, then re-fetches with Business B's own token to confirm the customer was **not** actually deleted.
- **`test_unauthenticated_request_is_rejected`**: no `Authorization` header at all — asserts 403 "Not authenticated" (matches manual curl output below).
- **`test_role_based_access_control_blocks_staff_from_delete`**: inserts a `staff`-role `BusinessUser` directly (no staff-invite endpoint exists yet, so this is the only way to get one) under Business A, mints a token for it the same way login does, asserts the staff token gets `403` on `DELETE /api/v1/customers/{id}`, then confirms the **owner** token for the same business successfully deletes it (`204`) — proving `require_role` actually discriminates by role, not just by tenant.

The test fixture registers real businesses/users/customers against the real dev database and deletes them (`ON DELETE CASCADE` from Phase 2) in teardown — confirmed clean afterward: `SELECT count(*) FROM businesses/customers/business_users` all return `0` (Verification §6).

This test did **not** need a "stop and tell you" moment — it passed on the first real run once the customer routes were scoped by `current_user.business_id`. No security failure was found or hidden.

**Verification output (actual, run 2026-09-03):**

1. Register + login end-to-end via curl:
```
$ curl -i -X POST .../auth/register -d '{"business_name":"Bright Smile Dental","timezone":"America/New_York","email":"ownerA@example.com","password":"correcthorse1"}'
HTTP/1.1 201 Created
{"business_id":"ca7af25a-...","user_id":"6aaf338f-...","email":"ownerA@example.com","role":"owner"}

$ curl -i -X POST .../auth/register  (same email again)
HTTP/1.1 409 Conflict
{"error":{"type":"conflict","message":"This email is already registered."}}

$ curl -i -X POST .../auth/register  (password "abc")
HTTP/1.1 422 Unprocessable Entity
{"detail":[{"...","msg":"Value error, Password must be at least 8 characters long.",...}]}

$ curl -i -X POST .../auth/register  (email "not-an-email")
HTTP/1.1 422 Unprocessable Entity
{"detail":[{"...","msg":"value is not a valid email address: ...",...}]}

$ curl -X POST .../auth/login -d '{"email":"ownerA@example.com","password":"correcthorse1"}'
{"access_token":"eyJhbGc...","token_type":"bearer","expires_in":1800}

$ curl -i -X POST .../auth/login  (wrong password)
HTTP/1.1 401 Unauthorized
{"error":{"type":"unauthorized","message":"Invalid email or password."}}

$ curl -i .../auth/me -H "Authorization: Bearer <token>"
HTTP/1.1 200 OK
{"user_id":"6aaf338f-...","business_id":"ca7af25a-...","email":"ownerA@example.com","role":"owner"}
```

2. JWT contents / tampered / missing / garbage / expired tokens all rejected (real requests, real responses):
```
$ curl -i .../auth/me -H "Authorization: Bearer <last char of valid token flipped>"
HTTP/1.1 401 Unauthorized
{"error":{"type":"unauthorized","message":"Invalid token."}}

$ curl -i .../auth/me   (no Authorization header)
HTTP/1.1 403 Forbidden
{"detail":"Not authenticated"}

$ curl -i .../auth/me -H "Authorization: Bearer not.a.jwt"
HTTP/1.1 401 Unauthorized
{"error":{"type":"unauthorized","message":"Invalid token."}}

# token minted with expires_minutes=-5 (already expired on arrival):
$ curl -i .../auth/me -H "Authorization: Bearer <expired token>"
HTTP/1.1 401 Unauthorized
{"error":{"type":"unauthorized","message":"Token has expired."}}
```
Decoded payload of a real issued token (base64-decoded manually, not asserted): `{"sub":"6aaf338f-ee87-4bcc-9154-3e67100335a0","business_id":"ca7af25a-7f4e-4a3c-a71d-1c2966a8c5a3","role":"owner","iat":1788457258,"exp":1788459058}` — confirms `business_id` and `role` are present exactly as required.

3. The critical cross-tenant test: see full section above — `4 passed` including `test_business_a_cannot_read_business_bs_customer` and the RBAC test.

4. Password hash in the DB (not plaintext):
```
$ docker compose exec postgres psql -U nightguard -d nightguard -c "SELECT email, hashed_password FROM business_users WHERE email='ownerA@example.com';"
       email        |                       hashed_password
--------------------+--------------------------------------------------------------
 ownerA@example.com | $2b$12$il/S.WyYgZ7l1OZ.jRzfIuRxyt3pXj13VEpyVdehE3R..6L07BU.C
```

5. Rate limiting on login (real, not staged — the count below is cumulative with earlier manual test calls against the same email within the same 60s window, which is exactly the intended behavior of a fixed window):
```
attempt 1 -> HTTP 401
attempt 2 -> HTTP 401
attempt 3 -> HTTP 429
attempt 4 -> HTTP 429
attempt 5 -> HTTP 429
attempt 6 -> HTTP 429
attempt 7 -> HTTP 429

$ curl -i .../auth/login  (while blocked)
HTTP/1.1 429 Too Many Requests
{"error":{"type":"too_many_requests","message":"Too many login attempts. Try again later."}}
```

6. Lint: `docker compose exec backend ruff check .` → `All checks passed!` (one real issue was caught and fixed along the way: an unused `sqlalchemy.select` import in the test file).

7. DB left clean after all manual + automated testing:
```
$ psql -c "SELECT count(*) FROM businesses;"   -> 0
$ psql -c "SELECT count(*) FROM customers;"    -> 0
$ psql -c "SELECT count(*) FROM business_users;" -> 0
$ alembic current -> 5588d67a7cf6 (head)
```

**Result / Acceptance criteria:**
| Criterion | Status |
|---|---|
| Register + login flow works end-to-end | ✓ Pass (curl output above) |
| JWT contains `business_id` + `role`; expired/invalid/tampered tokens rejected | ✓ Pass (decoded payload + 4 rejection cases above) |
| Cross-tenant security test passes | ✓ Pass — 4/4, including the critical IDOR test and RBAC |
| Passwords hashed in DB, not plaintext | ✓ Pass (real `$2b$12$...` bcrypt hash shown) |
| Lint clean | ✓ Pass (ruff; caught and fixed one real unused-import issue) |

**Known issues / punted items (explicit, not hidden):**
- **Refresh tokens: punted to a later phase.** Access-token-only for now (30 min TTL). A safe refresh-token implementation needs a persistent revocation store not yet in the schema — adding one now would be scope creep beyond what this phase asked for.
- **Rate limiter is in-memory, single-process only.** Resets on restart; does not share state across multiple backend replicas. Must move to Redis (or similar) before running more than one backend process — flagged in `app/core/rate_limit.py` and here, not silently shipped as if production-ready.
- **`KnowledgeDocument.approved_by` still not tenant-cross-checked at the DB level** (carried over from Phase 2, unrelated to this phase's scope — still open).
- No business-user management endpoints exist yet (inviting additional staff/admin accounts to an existing business) — the RBAC test had to insert a staff user directly via the ORM because no such endpoint exists. This is expected: Phase 3 asked for the *mechanism*, not the full user-management surface.
- No typechecker configured (carried over from Phase 2) — "lint clean" means ruff only.
- No commit has been made yet — awaiting user confirmation of this verification output per working rule #6.

---

## Phase 4 — Business Configuration

**Date:** 2026-09-03

**Required:**
- Authenticated, tenant-scoped CRUD for business profile, services, staff, and business hours — never trusting a client-supplied `business_id`.
- RBAC where it matters.
- Full CRUD verified with real re-fetches, cross-tenant IDOR test, RBAC test, validation returning 422 not 500, lint clean.

**Implemented:**

- **Business profile expanded** (`app/db/models/business.py`): added `description` (`Text`), `languages` (Postgres `ARRAY(String(16))`, e.g. `["en","es"]`), `tone` (`String(100)`) to `Business`. `name`/`timezone`/`address`/`phone`/`email`/`website` already existed from Phase 2.
  - `GET /api/v1/business/me` (any authenticated role) / `PATCH /api/v1/business/me` (owner/admin only) — `app/api/routes/business.py` → `app/services/business_service.py`.
  - **PATCH semantics, deliberately simple**: `model_dump(exclude_unset=True, exclude_none=True)` — only fields actually sent are touched, and an explicit `null` for a field is treated as "don't change" rather than "clear it." This was the lazy, safe choice: `name`/`timezone` are `NOT NULL` in the DB, so without `exclude_none` a client sending `{"name": null}` would reach the DB as an `IntegrityError` → 500, violating the "no 500s" requirement. To actually clear a nullable field (e.g. `address`), send `""` instead of `null`. Noted here as a real, minor limitation, not hidden.

- **Services CRUD** (`app/db/models/service.py`, `app/schemas/service.py`, `app/services/service_service.py`, `app/api/routes/services.py`): `GET /api/v1/services` (list, any role) / `POST` (owner/admin) / `PATCH /{id}` (owner/admin) / `DELETE /{id}` (owner/admin), all scoped by `current_user.business_id`.
  - **Staff assignment added** ("if applicable" per the ticket): `Service.staff_id` — nullable, with the same composite-FK same-tenant pattern already used for `Appointment` (`fk_services_staff_same_tenant`: `(staff_id, business_id)` → `(staff.id, staff.business_id)`), so a service can never be assigned to another business's staff member even at the DB level.
  - **Validation**: `price` must be ≥ 0, `duration_minutes` must be > 0 — enforced in Pydantic (`app/schemas/service.py`) so bad input is a clean 422, not a DB constraint violation surfacing as 500.

- **Staff CRUD** (`app/db/models/staff.py` unchanged from Phase 2, `app/schemas/staff.py`, `app/services/staff_service.py`, `app/api/routes/staff.py`): `GET /api/v1/staff` (list, any role) / `POST` / `PATCH /{id}` / `DELETE /{id}` (owner/admin), scoped by `business_id`.
  - **Validation**: `name`/`role` rejected if blank/whitespace-only.

- **Business hours** (`app/db/models/business.py`):
  - `BusinessHours` extended: added `closed: bool` (default `false`), and `open_time`/`close_time` are now **nullable** (required only when not closed). Added `UniqueConstraint(business_id, day_of_week)` and a new `CheckConstraint` `ck_business_hours_valid_range`: `closed OR (open_time IS NOT NULL AND close_time IS NOT NULL AND close_time > open_time)` — enforced at the DB level as a safety net, with the same rule also validated in Pydantic (`app/schemas/business_hours.py`) so the client-facing error is a clean 422.
  - `GET /api/v1/business/hours` — returns `{"weekly": [...], "exceptions": [...]}` for the authenticated business (any role).
  - `PUT /api/v1/business/hours` (owner/admin) — **replaces the entire week in one call**: deletes all existing `BusinessHours` rows for the business, inserts the new set (`app/services/business_hours_service.py::replace_hours`). Duplicate `day_of_week` values in one request are rejected with 422 before any DB write.
  - **Holidays/exceptions — new lightweight model added**, since none existed from Phase 2: `BusinessHoursException` (`business_hours_exceptions` table) — `date` (unique per business), `closed` (default `true`), optional `open_time`/`close_time` for a custom-hours override. Same valid-range check constraint as `BusinessHours`.
    - `POST /api/v1/business/hours/exceptions` (owner/admin, 409 if that date already has an exception) / `DELETE /api/v1/business/hours/exceptions/{id}` (owner/admin, 404 if not found or not this business's).
    - Scope decision: full PATCH/list-alone endpoints for exceptions were not added — "support" was read as create/view/remove being enough; a business changes its mind about a holiday by deleting and re-creating, not editing in place. Flagging in case in-place edit is wanted later.

- **RBAC policy — stated explicitly, not left ambiguous**: for every resource in this phase (business profile, services, staff, business hours + exceptions), **all reads are allowed to any authenticated role** (`owner`, `admin`, `staff`) and **all writes (create/update/delete) require `owner` or `admin`** via the existing `require_role(["owner", "admin"])` dependency from Phase 3. `staff` role is read-only across this entire phase's surface. This mirrors the Phase 3 `customers` reference implementation's delete-gating, extended consistently to every write here. Verified live against a real minted staff token (Verification §7 below) — every read returned 200, every write returned 403, and the same owner token succeeded on the same write immediately after, proving it's a role gate and not a blanket failure.

- **Migration** `backend/app/db/migrations/versions/be989d8a4be3_business_configuration.py` (`down_revision = 5588d67a7cf6`), generated via `alembic revision --autogenerate`, then hand-fixed for one real, expected gap in autogenerate (caught, not hidden): **autogenerate does not diff `CheckConstraint`s on existing tables** (only picks them up on `CREATE TABLE`) — so `ck_business_hours_valid_range` on the pre-existing `business_hours` table had to be added by hand to both `upgrade()` (`op.create_check_constraint(...)`, placed after the column/nullability changes it depends on) and `downgrade()` (`op.drop_constraint(...)`, placed before reverting `open_time`/`close_time` back to `NOT NULL`). The equivalent constraint on the brand-new `business_hours_exceptions` table *was* autogenerated correctly, since it's part of that table's `CREATE TABLE`.

**Verification output (actual, run 2026-09-03):**

1. `alembic upgrade head` from Phase 3's head, `alembic check` confirms model/DB agreement, and a full reversibility cycle:
```
$ docker compose exec backend alembic upgrade head
INFO  [alembic.runtime.migration] Running upgrade 5588d67a7cf6 -> be989d8a4be3, business configuration

$ docker compose exec backend alembic check
No new upgrade operations detected.

$ docker compose exec backend alembic downgrade base && docker compose exec backend alembic upgrade head
Running downgrade be989d8a4be3 -> 5588d67a7cf6, business configuration
Running downgrade 5588d67a7cf6 -> 371630166e11, add unique constraint on business_users email
Running downgrade 371630166e11 -> , initial schema
Running upgrade  -> 371630166e11, initial schema
Running upgrade 371630166e11 -> 5588d67a7cf6, add unique constraint on business_users email
Running upgrade 5588d67a7cf6 -> be989d8a4be3, business configuration
```
(all clean, no errors, no leftover-type issues this time since no new enums were added)

2. Full CRUD cycle for **services** via curl, with re-fetch after every write (business A, real requests against the live Docker backend):
```
$ curl -X POST .../services -d '{"name":"Dental Cleaning","description":"Standard cleaning","price":"75.00","duration_minutes":30}'
{"id":"232c3460-...","business_id":"5bc95eac-...","name":"Dental Cleaning","price":"75.00","duration_minutes":30,"staff_id":null}

$ curl .../services   # list
[{"id":"232c3460-...", ..., "price":"75.00","duration_minutes":30}]

$ curl -X PATCH .../services/232c3460-... -d '{"price":"85.00","duration_minutes":45}'
{"id":"232c3460-...", ..., "price":"85.00","duration_minutes":45}

$ curl .../services   # re-fetch — confirms the PATCH actually persisted
[{"id":"232c3460-...", ..., "price":"85.00","duration_minutes":45}]

$ curl -X DELETE .../services/232c3460-...
HTTP/1.1 204 No Content

$ curl .../services   # re-fetch — confirms the DELETE actually persisted
[]
```

3. Full CRUD cycle for **staff** via curl, same re-fetch-after-every-write pattern:
```
$ curl -X POST .../staff -d '{"name":"Dr. Jane Doe","role":"dentist"}'
{"id":"0cd74e30-...","name":"Dr. Jane Doe","role":"dentist"}
$ curl .../staff  → [{"id":"0cd74e30-...","role":"dentist"}]
$ curl -X PATCH .../staff/0cd74e30-... -d '{"role":"lead dentist"}'
{"id":"0cd74e30-...","role":"lead dentist"}
$ curl .../staff  → [{"id":"0cd74e30-...","role":"lead dentist"}]   # PATCH persisted
$ curl -X DELETE .../staff/0cd74e30-...  → HTTP/1.1 204
$ curl .../staff  → []   # DELETE persisted
```

4. Business hours PUT (full week replace) + holiday exception, with re-fetch:
```
$ curl .../business/hours   → {"weekly":[],"exceptions":[]}
$ curl -X PUT .../business/hours -d '{"days":[{"day_of_week":0,"open_time":"09:00:00","close_time":"17:00:00"}, ... 6 more days incl. two "closed":true]}'
[{"day_of_week":0,"closed":false,"open_time":"09:00:00","close_time":"17:00:00"}, ...]
$ curl .../business/hours   → same 7 days, confirmed persisted
$ curl -X POST .../business/hours/exceptions -d '{"date":"2026-12-25","closed":true}'
{"id":"6e02869e-...","date":"2026-12-25","closed":true,"open_time":null,"close_time":null}
$ curl .../business/hours   → exceptions now includes 2026-12-25, confirmed persisted
$ curl -X DELETE .../business/hours/exceptions/6e02869e-...  → HTTP/1.1 204
$ curl .../business/hours   → exceptions:[] again, confirmed persisted
```

5. Business profile GET/PATCH with re-fetch:
```
$ curl .../business/me  → {"name":"Bright Smile Dental","description":null,...}
$ curl -X PATCH .../business/me -d '{"description":"A friendly neighborhood dental clinic","address":"123 Main St","phone":"555-1234","website":"https://brightsmile.example","languages":["en","es"],"tone":"friendly"}'
{"description":"A friendly neighborhood dental clinic", ..., "languages":["en","es"],"tone":"friendly"}
$ curl .../business/me  → identical to the PATCH response — confirmed persisted
```

6. **Cross-tenant test** (Business A vs Business B, real registered businesses, real tokens, same IDOR-guessing pattern as Phase 3's critical test): Business A creates a service and a staff member; Business B attempts PATCH/DELETE on both by ID:
```
$ curl -X PATCH .../services/{business_A_service_id}  (token B)
HTTP/1.1 404 Not Found   {"error":{"type":"not_found","message":"Service not found."}}
$ curl -X DELETE .../services/{business_A_service_id}  (token B)
HTTP/1.1 404 Not Found   {"error":{"type":"not_found","message":"Service not found."}}
$ curl -X PATCH .../staff/{business_A_staff_id}  (token B)
HTTP/1.1 404 Not Found   {"error":{"type":"not_found","message":"Staff member not found."}}
$ curl -X DELETE .../staff/{business_A_staff_id}  (token B)
HTTP/1.1 404 Not Found   {"error":{"type":"not_found","message":"Staff member not found."}}
```
Re-fetched with Business A's own token afterward — service/staff both still present and unmodified. Also tested: Business B `PATCH .../business/me` with a `business_id` field stuffed into the body (ignored — not a schema field on `BusinessUpdate`, so it can only ever touch B's own business, per the mandatory `current_user.business_id`-scoping convention); Business B `DELETE` on Business A's hours-exception id → 404, A's exception confirmed still present after.

7. **RBAC test** — a real `staff`-role `BusinessUser` inserted directly (no staff-invite endpoint exists yet, same limitation noted in Phase 3) and a token minted for it the same way login does:
```
Reads (staff token):
GET /business/me        → 200
GET /services            → 200
GET /staff                → 200
GET /business/hours       → 200

Writes (staff token) — all blocked:
PATCH /business/me       → 403 {"error":{"type":"forbidden",...}}
POST  /services           → 403
PATCH /services/{id}      → 403
DELETE /services/{id}     → 403
POST  /staff               → 403
DELETE /staff/{id}         → 403
PUT   /business/hours      → 403
```
**Policy, stated explicitly**: staff role = read-only across business profile, services, staff, and business hours/exceptions; owner/admin = full read+write. Not ambiguous, not left to guesswork.

8. **Validation test** — one clearly invalid payload per resource type, all 422 (never 500):
```
POST /services  {"price":"-10.00", ...}                          → 422 "Price must not be negative."
POST /services  {"duration_minutes":-5, ...}                      → 422 "Duration must be a positive number of minutes."
POST /staff     {"name":"   ", ...}                                → 422 "This field must not be blank."
PUT  /business/hours  close_time before open_time                 → 422 "close_time must be after open_time."
PUT  /business/hours  day_of_week: 9                                → 422 "day_of_week must be between 0 (Monday) and 6 (Sunday)."
POST /business/hours/exceptions  closed:false, no times             → 422 "open_time and close_time are required unless the day is closed."
```

9. **Automated regression suite** — `backend/tests/integration/test_business_configuration.py` (new, 10 tests: profile CRUD, service full cycle, staff full cycle, hours PUT-replace, cross-tenant isolation, RBAC, and a parametrized 422 sweep), run alongside the existing Phase 3 suite, all against the real live Docker Postgres via `TestClient`:
```
$ docker compose exec backend python -m pytest tests/ -v
tests/integration/test_business_configuration.py::test_business_profile_crud PASSED
tests/integration/test_business_configuration.py::test_service_full_crud_cycle PASSED
tests/integration/test_business_configuration.py::test_staff_full_crud_cycle PASSED
tests/integration/test_business_configuration.py::test_business_hours_put_replaces_full_week PASSED
tests/integration/test_business_configuration.py::test_cross_tenant_service_and_staff_are_isolated PASSED
tests/integration/test_business_configuration.py::test_rbac_staff_role_can_read_but_not_write PASSED
tests/integration/test_business_configuration.py::test_invalid_payloads_return_422_not_500[...] PASSED (x4)
tests/integration/test_tenant_isolation.py::test_business_a_cannot_read_business_bs_customer PASSED
tests/integration/test_tenant_isolation.py::test_business_a_cannot_delete_business_bs_customer PASSED
tests/integration/test_tenant_isolation.py::test_unauthenticated_request_is_rejected PASSED
tests/integration/test_tenant_isolation.py::test_role_based_access_control_blocks_staff_from_delete PASSED

======================== 14 passed, 1 warning in 13.54s ========================
```

10. Lint: `docker compose exec backend ruff check .` → `All checks passed!`

11. DB left clean after all manual curl testing + automated tests (pytest fixtures self-clean; the manual-curl businesses were deleted by hand afterward):
```
$ psql -c "SELECT count(*) FROM businesses;"                    → 0
$ psql -c "SELECT count(*) FROM services;"                      → 0
$ psql -c "SELECT count(*) FROM staff;"                          → 0
$ psql -c "SELECT count(*) FROM business_hours;"                 → 0
$ psql -c "SELECT count(*) FROM business_hours_exceptions;"      → 0
$ psql -c "SELECT count(*) FROM business_users;"                 → 0
```

**Result / Acceptance criteria:**
| Criterion | Status |
|---|---|
| Full CRUD cycle for services + staff, re-fetched after each write | ✓ Pass (curl output above) |
| Cross-tenant test: Business A cannot read/update/delete Business B's services/staff/hours | ✓ Pass — 404 on every attempt, verified unmodified afterward |
| RBAC test: staff role allowed reads, blocked writes; policy stated explicitly | ✓ Pass — 4x 200 reads, 7x 403 writes, then owner succeeds on the same write |
| Validation test: ≥1 invalid payload per resource type → 422, not 500 | ✓ Pass — 6 cases covered (price, duration, blank name, bad time range, bad day_of_week, missing times) |
| Lint clean | ✓ Pass (ruff) |

**Known issues / punted items (explicit, not hidden):**
- ~~PATCH on business/service/staff treats an explicit `null` as "leave unchanged," not "clear this field."~~ **Fixed — see "PATCH no-op-null fix" below.**
- **No staff-user invite/management endpoint exists yet** (carried over from Phase 3) — the RBAC test again had to insert a `staff`-role `BusinessUser` directly via the ORM, because there is still no API path to create one. This phase's `staff` table (dentists/hygienists, bookable resources) is unrelated to `business_users` (login accounts) — worth flagging in case that distinction gets confused later.
- **Business hours exceptions have no PATCH/list-by-id** — only create/list-all/delete. A changed-mind holiday is handled by delete + re-create, not in-place edit. Flagging in case in-place edit is wanted.
- **`Business.email`/`website`/`phone` are plain strings, not format-validated** — consistent with how Phase 2's model originally defined them; not newly introduced here, just carried forward.
- No typechecker configured (carried over from Phase 2/3) — "lint clean" still means ruff only.
- No commit has been made yet — awaiting user confirmation of this verification output per working rule #6.

---

## Fix — PATCH no-op-null bug (from Phase 4)

**Date:** 2026-09-03

**Bug:** Phase 4's `update_*` service functions used `model_dump(exclude_unset=True, exclude_none=True)`. `exclude_unset` correctly left omitted fields alone, but `exclude_none` went further and silently ignored an *explicit* `null` too — so there was no way for a client to actually clear a nullable field (`address`, `description`, etc.). That's the wrong behavior: omission and explicit-null are two different client intents and were being collapsed into one.

**Fix:**
- `app/services/business_service.py`, `service_service.py`, `staff_service.py`: `update_*` now calls `payload.model_dump(exclude_unset=True)` only (no `exclude_none`). An omitted field is absent from `model_fields_set` regardless of its default, so it's still excluded and left alone; an explicit `null` is present in the dump and reaches the DB as `NULL`.
- To keep that safe against `NOT NULL` columns (`Business.name`/`timezone`, `Service.name`/`price`/`duration_minutes`, `Staff.name`/`role`), each `*Update` schema (`app/schemas/business.py`, `service.py`, `staff.py`) got a `field_validator` on those specific fields that raises if the value is `None`. Pydantic v2 does **not** run field validators on a field that was never supplied (`validate_default` is off by default) — only on a field actually present in the request body — so this validator fires exactly on "client explicitly sent null," never on "client omitted it," which is the precise distinction needed. The net effect: omit → unchanged; explicit null on a nullable field → cleared; explicit null on a required field → clean 422, never a DB `IntegrityError`.
- `Staff` has no nullable field at all (`name`/`role` both `NOT NULL`), so its validator rejects explicit null on both — there's nothing on Staff that can be cleared via null, which is correct given the schema, not an oversight.

**Verification output (actual, run 2026-09-03 — after restarting the backend container, since the Dockerfile runs `uvicorn` without `--reload` and the first test pass was silently against stale pre-fix code; caught by getting 200s where 422s were expected, not from re-reading the diff):**

1. **PATCH omits everything except one field — the rest must be unchanged** (Service, then Staff):
```
BEFORE (Service): {"name":"Root Canal","description":"Full endodontic treatment","price":"500.00","duration_minutes":60,"staff_id":"475ccab4-..."}

$ curl -X PATCH .../services/{id} -d '{"price": 100}'
AFTER:  {"name":"Root Canal","description":"Full endodontic treatment","price":"100.00","duration_minutes":60,"staff_id":"475ccab4-..."}
```
Only `price` changed (500.00 → 100.00); `name`, `description`, `duration_minutes`, `staff_id` are byte-for-byte identical before/after.
```
BEFORE (Staff): {"name":"Dr. Assigned","role":"dentist"}
$ curl -X PATCH .../staff/{id} -d '{"role": "lead dentist"}'
AFTER:  {"name":"Dr. Assigned","role":"lead dentist"}
```
`name` unchanged, only `role` changed. Two of the four Phase 4 resources confirmed, per the requirement.

2. **Explicit null clears a nullable field; explicit null on a required field is rejected with 422** (Service and Business):
```
$ curl -X PATCH .../services/{id} -d '{"description": null, "staff_id": null}'
HTTP/1.1 200 OK
{"name":"Root Canal","description":null,"price":"100.00","duration_minutes":60,"staff_id":null}
# name/price/duration_minutes untouched, description+staff_id actually cleared to null

$ curl -X PATCH .../services/{id} -d '{"price": null}'
HTTP/1.1 422 Unprocessable Entity
{"detail":[{"loc":["body","price"],"msg":"Value error, This field is required and cannot be cleared to null."}]}

$ curl -X PATCH .../services/{id} -d '{"name": null}'
HTTP/1.1 422 Unprocessable Entity
{"detail":[{"loc":["body","name"],"msg":"Value error, This field is required and cannot be cleared to null."}]}

# confirmed: the service record is completely unmodified by either rejected request

$ curl .../business/me   → {"description":null,...}
$ curl -X PATCH .../business/me -d '{"description":"will be cleared"}'   → 200, description set
$ curl -X PATCH .../business/me -d '{"description": null}'                → 200, description now null again
$ curl -X PATCH .../business/me -d '{"name": null}'                       → 422 "This field is required and cannot be cleared to null."
$ curl -X PATCH .../business/me -d '{"timezone": null}'                   → 422 same message
# name/timezone confirmed untouched afterward

$ curl -X PATCH .../staff/{id} -d '{"name": null}'   → 422 (Staff has no nullable field to clear)
$ curl -X PATCH .../staff/{id} -d '{"role": null}'   → 422
```

3. **Automated regression tests added** to `test_business_configuration.py`: `test_patch_omitted_fields_are_left_unchanged` and `test_patch_explicit_null_clears_nullable_field_but_rejects_on_required_field`, covering Service, Staff, and Business. Full suite:
```
$ docker compose exec backend python -m pytest tests/ -v
...
tests/integration/test_business_configuration.py::test_patch_omitted_fields_are_left_unchanged PASSED
tests/integration/test_business_configuration.py::test_patch_explicit_null_clears_nullable_field_but_rejects_on_required_field PASSED
...
16 passed, 1 warning in 15.32s
```

4. Lint: `ruff check .` → `All checks passed!`

**Result:** Fixed and verified — omission preserves, explicit null clears (where the column allows it) or 422s (where it doesn't), for all four Phase 4 resources that have a PATCH endpoint (Business, Service, Staff; `BusinessHours` uses full-replace `PUT`, not `PATCH`, so it was never affected by this bug).

**Process note (flagging, not hiding):** Phase 4 itself was never actually committed — `git log` still showed `feat: phase 3` as HEAD when this session started, despite Phase 4's `PHASE_STATUS.md` write-up describing it as done. All Phase 4 files were intact and correct in the working tree (uncommitted), so no work was lost, but the commit prompt at the end of this session should include both Phase 4 and this fix.

---

## Phase 5 — Knowledge Base

**Date:** 2026-09-03

**Required:**
- Structured knowledge entry (manual text) with full CRUD + a draft → approved → archived status lifecycle, `approved_by`/timestamp recorded on approval.
- File upload (PDF/txt) → text extraction → `KnowledgeDocument` with `source="upload"`.
- Clean rejection (not a crash) for bad file type/size.
- Authenticated + tenant-scoped + RBAC per the Phase 4 policy (read: any role, write: owner/admin) unless diverging with a stated reason. **No divergence was needed or made** — every `/knowledge*` endpoint uses exactly the same `get_current_user` (read) / `require_role(["owner","admin"])` (write) split as Phase 4, including approve/archive/delete, which are just PATCH/DELETE like everything else.
- Explicitly NOT this phase: embeddings, chunking, vector search (Phase 6).

**Implemented:**

- **`KnowledgeDocument` model extended** (`app/db/models/knowledge.py`, already existed from Phase 2 with `title`/`source`/`status`/`version`/`approved_by`): added `content` (`Text`, `NOT NULL`, the raw ingested text — Phase 6 will chunk this into the already-existing `KnowledgeChunk` table for embeddings, but this column stays the source of truth for "what was actually submitted") and `approved_at` (`DateTime(timezone=True)`, nullable). `KnowledgeChunk` itself is untouched — it stays empty until Phase 6's chunking/embedding step.

- **Manual entry CRUD** (`app/schemas/knowledge.py`, `app/services/knowledge_service.py`, `app/api/routes/knowledge.py`):
  - `POST /api/v1/knowledge` (owner/admin) — `title`+`content` required and non-blank, `source` forced to `"manual"` server-side (never client-controlled), `status` always starts `"draft"`.
  - `GET /api/v1/knowledge` (any role) — lists the business's documents, newest first, with an optional `?status=draft|approved|archived` query filter.
  - `GET /api/v1/knowledge/{id}` (any role) — tenant-scoped lookup, 404 (not 403) if it belongs to another business or doesn't exist, same IDOR-safe pattern as every other Phase 3/4 resource.
  - `PATCH /api/v1/knowledge/{id}` (owner/admin) — can edit `content`, `title`, and/or `status` in the same call. Follows the exact PATCH no-op-null convention just fixed above: omitted fields untouched, explicit null on `title`/`content`/`status` (all `NOT NULL`) rejected with 422.
    - **Approving sets `approved_by`/`approved_at`**: whenever the new `status` is `APPROVED`, the service layer stamps `approved_by = current_user.id` and `approved_at = now()` in the same transaction — verified live (a real user id and a real timestamp came back, not nulls).
    - **Archiving does not erase approval history**: moving `approved → archived` leaves `approved_by`/`approved_at` as they were — an archived document still shows who approved it and when. Not specified either way by the ticket; this was the more useful default (an audit trail costs nothing extra to keep).
    - **Lightweight versioning**: any PATCH that includes `content` increments the `version` counter by 1 (verified: `1 → 2` after one content edit). No separate revision-history/snapshot table — that would be speculative scope beyond "structured, versioned, gated by approval status," which just needs a version *number* changing, not full diffable history.
  - `DELETE /api/v1/knowledge/{id}` (owner/admin) — tenant-scoped, 404 if not found/not this business's.

- **File upload** (`POST /api/v1/knowledge/upload`, owner/admin, in `app/api/routes/knowledge.py`):
  - Accepts `multipart/form-data` (`python-multipart` added to `requirements.txt` — required by FastAPI/Starlette for any `UploadFile`/`File(...)` parameter; there was no way around this dependency, it's not something a few lines of code replaces).
  - File type is decided by the filename's extension (`.pdf` / `.txt`) rather than trusting the client-supplied `Content-Type` header, since that header is client-controlled and not reliably set by every HTTP client — extension-sniffing is simple and matches "keep extraction simple" from the ticket.
  - **PDF**: extracted via `pypdf` (`PdfReader(...).pages[i].extract_text()`, pages joined with `\n`) — added `pypdf` to `requirements.txt`. A corrupt/unparseable PDF is caught (`pypdf.errors.PdfReadError`) and turned into a clean 422, not a 500.
  - **.txt**: decoded as UTF-8; a non-UTF-8 file raises a clean 422 (`UnicodeDecodeError` caught), not a crash.
  - A file that parses successfully but yields no non-whitespace text (e.g. an image-only PDF with no text layer) is rejected with 422 — "no extractable text," not silently creating an empty document.
  - **Size limit**: 10 MB, checked after reading the upload into memory (`len(raw) > _MAX_UPLOAD_BYTES` → 413). Simple, not streamed — a real streaming-upload limit would matter at a scale this phase doesn't need yet; flagged below as the honest trade-off.
  - Created document: `title` = the uploaded filename, `content` = extracted text, `source="upload"`, `status="draft"` — same downstream lifecycle as a manual entry from here.
  - **New exception types added** (`app/core/exceptions.py`), matching the existing `NightGuardError` pattern (clean JSON body, correct status code, never a bare 500): `UnsupportedMediaTypeError` (415, bad extension), `PayloadTooLargeError` (413, oversized), `UnprocessableEntityError` (422, parses but is otherwise invalid — reused for "corrupt PDF," "non-UTF-8 text," and "no extractable text").

- **RBAC — no divergence from the Phase 4 policy, confirmed explicitly with tests** (Verification §6 below): reads (`GET /knowledge`, `GET /knowledge/{id}`) allowed to any authenticated role including `staff`; every write — create, edit, **approve**, **archive**, delete, upload — requires `owner`/`admin`. The ticket specifically asked to "confirm this explicitly with a test" for approve/archive, since those are new state-transition actions, not just CRUD — done (a `staff` token got 403 on both `status: approved` and `status: archived` PATCH calls against the same document an owner token then successfully approved).

- **Migration** `backend/app/db/migrations/versions/aa23ade02a4c_knowledge_base_ingestion.py` (`down_revision = be989d8a4be3`) — autogenerated cleanly this time (adds `content` with `server_default=''` so it's safe against any pre-existing rows, and nullable `approved_at`), no hand-fixes needed. Confirmed reversible (`downgrade base` → `upgrade head` full cycle, plus `alembic check` reports no drift).

**Verification output (actual, run 2026-09-03):**

1. Migration applied + reversibility:
```
$ docker compose exec backend alembic upgrade head
Running upgrade be989d8a4be3 -> aa23ade02a4c, knowledge base ingestion
$ docker compose exec backend alembic check
No new upgrade operations detected.
$ docker compose exec backend alembic downgrade base && docker compose exec backend alembic upgrade head
(full cycle back to aa23ade02a4c, clean, no errors)
```

2. **Full manual-entry lifecycle**, draft → content edit → approved → archived → deleted, with re-fetch after every write:
```
$ curl -X POST .../knowledge -d '{"title":"Cancellation Policy","content":"...24 hours..."}'
{"status":"draft","version":1,"approved_by":null,"approved_at":null,...}

$ curl -X PATCH .../knowledge/{id} -d '{"content":"...48 hours..."}'
{"content":"...48 hours...","version":2,...}          # version bumped
$ curl .../knowledge/{id}   → same content/version — persisted

$ curl -X PATCH .../knowledge/{id} -d '{"status":"approved"}'
{"status":"approved","approved_by":"554d556d-...","approved_at":"2026-09-03T18:09:49.011987Z",...}
$ curl .../knowledge/{id}   → identical — persisted

$ curl ".../knowledge?status=approved"   → [the document]
$ curl ".../knowledge?status=draft"      → []   # filter works

$ curl -X PATCH .../knowledge/{id} -d '{"status":"archived"}'
{"status":"archived","approved_by":"554d556d-...","approved_at":"2026-09-03T18:09:49.011987Z",...}   # history retained

$ curl -X DELETE .../knowledge/{id}   → HTTP/1.1 204
$ curl .../knowledge/{id}   → HTTP/1.1 404 {"error":{"type":"not_found",...}}   # deletion persisted
```

3. **Real file upload — .txt**:
```
$ printf 'Night Guard AI Dental Clinic Hours\nMonday-Friday: 9am - 5pm\n...' > hours.txt
$ curl -F "file=@hours.txt;type=text/plain" .../knowledge/upload
{"title":"hours.txt","source":"upload","status":"draft",
 "content":"Night Guard AI Dental Clinic Hours\nMonday-Friday: 9am - 5pm\nSaturday: 10am - 2pm\nSunday: Closed\nWe are located at 42 Wallaby Way.\n"}
```
Extracted `content` is an exact match of the uploaded file's bytes.

4. **Real file upload — .pdf** (generated with `reportlab` on the host purely as a test fixture, containing real drawn text — not a text file renamed to `.pdf`):
```
$ curl -F "file=@policy.pdf;type=application/pdf" .../knowledge/upload
{"title":"policy.pdf","source":"upload","status":"draft",
 "content":"Night Guard AI Refund Policy\nAll refunds are processed within 5 to 7 business days.\nContact support at support@nightguard.example for disputes.\n"}
```
The extracted text is an exact match of the three lines drawn into the PDF — real `pypdf` extraction, not a stub.

5. **Invalid upload rejection**:
```
$ curl -F "file=@malware.exe" .../knowledge/upload
HTTP/1.1 415 Unsupported Media Type
{"error":{"type":"unsupported_media_type","message":"Unsupported file type '.exe'. Only .pdf and .txt are accepted."}}

$ curl -F "file=@huge.txt" .../knowledge/upload   # 11MB file, limit is 10MB
HTTP/1.1 413 Request Entity Too Large
{"error":{"type":"payload_too_large","message":"File exceeds the 10MB upload limit."}}

$ curl .../knowledge   → [only the earlier .txt/.pdf uploads — neither rejected upload created a document]
```

6. **Cross-tenant test** (Business A vs Business B, real registered businesses/tokens, same IDOR pattern as every prior phase): Business B tries to read/edit/approve/delete Business A's knowledge document by ID:
```
$ curl .../knowledge/{business_A_doc_id}                                      (token B) → 404
$ curl -X PATCH .../knowledge/{id} -d '{"content":"hacked"}'                   (token B) → 404
$ curl -X PATCH .../knowledge/{id} -d '{"status":"approved"}'                  (token B) → 404
$ curl -X DELETE .../knowledge/{id}                                            (token B) → 404
```
Re-fetched with Business A's own token afterward — document unmodified (still `draft`, original content intact). Business B's own `GET /knowledge` list is `[]` — A's documents are completely invisible, not just inaccessible.

7. **RBAC test** — real minted `staff`-role token (no staff-invite endpoint yet, same limitation as every prior phase):
```
Reads (staff token): GET /knowledge → 200, GET /knowledge/{id} → 200

Writes (staff token) — all blocked:
POST   /knowledge                          → 403
PATCH  /knowledge/{id} {"status":"approved"} → 403
PATCH  /knowledge/{id} {"status":"archived"} → 403
DELETE /knowledge/{id}                      → 403
POST   /knowledge/upload                    → 403

# document confirmed still draft/unmodified after all 5 blocked attempts

# the SAME approve action, with the owner token, on the SAME document:
$ curl -X PATCH .../knowledge/{id} -d '{"status":"approved"}'   (token A, owner)
HTTP/1.1 200 OK   {"status":"approved","approved_by":"...",...}
```
Confirms this is a role gate, not a blanket failure — and specifically confirms approve/archive are gated exactly like every other write, per the ticket's explicit ask.

8. **Automated regression suite** — `backend/tests/integration/test_knowledge_base.py` (new, 9 tests, including a real `.pdf` fixture at `backend/tests/fixtures/sample.pdf`), run alongside every prior phase's suite:
```
$ docker compose exec backend python -m pytest tests/ -v
tests/integration/test_knowledge_base.py::test_manual_entry_full_lifecycle PASSED
tests/integration/test_knowledge_base.py::test_upload_txt_extracts_content PASSED
tests/integration/test_knowledge_base.py::test_upload_pdf_extracts_content PASSED
tests/integration/test_knowledge_base.py::test_upload_rejects_invalid_type_and_oversized_file PASSED
tests/integration/test_knowledge_base.py::test_cross_tenant_knowledge_documents_are_isolated PASSED
tests/integration/test_knowledge_base.py::test_rbac_staff_can_read_but_not_approve_archive_or_delete PASSED
tests/integration/test_knowledge_base.py::test_create_rejects_blank_fields_with_422[body0] PASSED
tests/integration/test_knowledge_base.py::test_create_rejects_blank_fields_with_422[body1] PASSED
... (plus all 14 pre-existing tests from Phases 3/4, and the 2 new PATCH-null-fix tests)
======================== 24 passed, 1 warning in 23.08s ========================
```

9. Lint: `docker compose exec backend ruff check .` → `All checks passed!`

10. DB left clean after all manual curl testing + automated tests:
```
$ psql -c "SELECT count(*) FROM businesses;"           → 0
$ psql -c "SELECT count(*) FROM knowledge_documents;"  → 0
$ psql -c "SELECT count(*) FROM business_users;"       → 0
```

**Result / Acceptance criteria:**
| Criterion | Status |
|---|---|
| PATCH no-op-null fix verified for ≥2 resources | ✓ Pass — Service, Staff, and Business all verified (3, exceeding the ≥2 ask) |
| Full CRUD + status lifecycle (draft→approved→archived) with re-fetch | ✓ Pass (curl output above) |
| File upload works for a real PDF and a real .txt, extracted content lands in the document | ✓ Pass — exact-text-match verified for both |
| Upload rejects invalid type/oversized file cleanly, not a 500 | ✓ Pass — 415 for `.exe`, 413 for an 11MB file |
| Cross-tenant test: A cannot read/edit/delete/approve B's documents | ✓ Pass — 404 on all four actions, verified unmodified/invisible afterward |
| RBAC test: non-owner/admin blocked from approve/archive/delete | ✓ Pass — 5 writes blocked (incl. approve/archive), owner succeeds on the same action immediately after |
| Lint clean, migration reversible | ✓ Pass (ruff clean; `alembic check` + full downgrade/upgrade cycle clean) |

**Known issues / punted items (explicit, not hidden):**
- **Upload size limit is enforced after reading the whole file into memory**, not via a streaming/request-level cap. Fine at the 10MB scale used here; a genuinely adversarial oversized upload (e.g. gigabytes) would still cost memory/time to read before being rejected. A reverse-proxy or ASGI-level max-body-size guard would close this properly — flagged, not built, since it's infrastructure-level and out of scope for an application-layer phase.
- **File type is decided by filename extension, not by sniffing actual file bytes** (e.g. a magic-byte/MIME check). A `.txt`-renamed PDF would be fed through the text decoder and fail as a `UnicodeDecodeError` → clean 422 either way, so this doesn't create a crash risk, just a slightly less precise error message in that edge case.
- **No OCR / image-only-PDF text extraction** — explicitly out of scope per the ticket ("keep extraction simple... don't build a fancy OCR pipeline"). An image-only PDF is correctly rejected as "no extractable text," not silently accepted as empty.
- **`KnowledgeChunk` (embeddings table) is untouched and still empty** — by design, this is Phase 6's job.
- **`KnowledgeDocument.approved_by` still not tenant-cross-checked at the DB level** (carried over from Phase 2, still an open, documented gap — unrelated to this phase's scope).
- **Versioning is a bare counter, not a snapshot/history table** — a PATCH that changes `content` bumps `version` but the previous content is not retained anywhere. If revision history/rollback is wanted later, that's a real, separate feature, not implied by "versioned" as read here.
- No typechecker configured (carried over from Phase 2/3/4) — "lint clean" still means ruff only.
- No commit has been made yet — awaiting user confirmation of this verification output per working rule #6.

---

## Phase 6 — RAG + Knowledge Governance

**Date:** 2026-09-04

**Required:**
- LLM-agnostic `EmbeddingProvider`/`ChatProvider` abstraction under `app/llm/`; env vars for Azure OpenAI added as placeholders only.
- Chunking on approve/re-approve; embeddings stored in the pgvector column; dimension confirmed against the real model (fix migration if it doesn't match 1536).
- `POST /api/v1/knowledge/search` — tenant-scoped, `status="approved"`-only pgvector similarity search.
- Re-chunking on edit of an approved document (invalidate + regenerate, no stale chunks).
- Draft/archived documents have zero eligible chunks — verified directly.
- Real API acceptance tests (approve → real embeddings, real search with scores, cross-tenant, status change, edit-invalidation, secrets grep), lint clean, migration reversible.

**Implemented so far:**

- **`backend/.env.example`**: added `AZURE_OPENAI_API_KEY`, `AZURE_OPENAI_ENDPOINT`, `AZURE_OPENAI_DEPLOYMENT` (chat, for Phase 7+), `AZURE_OPENAI_EMBEDDING_DEPLOYMENT` (embeddings, used by this phase) — all placeholder values. `app/core/config.py` reads these with empty-string defaults so the app still boots and every non-LLM route still works with no keys set.
- **`app/llm/base.py`**: `EmbeddingProvider`/`ChatProvider` ABCs — `embed(texts) -> list[list[float]]`, `chat(messages) -> str`. No Azure-specific types leak into this interface.
- **`app/llm/azure_openai.py`**: `AzureEmbeddingProvider`/`AzureChatProvider`. **Real-world correction, found only by actually calling the API (not guessable from docs alone):** the user's Azure resource (`*.services.ai.azure.com`) is an **Azure AI Foundry** unified endpoint, not a classic Azure OpenAI resource (`*.openai.azure.com`). Foundry exposes a different REST path — `{endpoint}/models/embeddings` / `{endpoint}/models/chat/completions` with `model=<deployment name>` in the body — instead of the classic `{endpoint}/openai/deployments/{name}/embeddings`. The `openai` SDK's `AzureOpenAI` client only targets the classic path, so it was dropped in favor of a direct `httpx` call (already a project dependency, no new one added — `openai==1.54.4` was added then removed from `requirements.txt` once this became clear). **Also found by real testing**: this specific resource intermittently 404s (`DeploymentNotFound`) on a confirmed-live, "Succeeded" deployment — roughly half of raw back-to-back requests failed this way, almost certainly an Azure-side propagation inconsistency across backend nodes, not a real missing deployment (retrying always eventually succeeds). `_post()` therefore retries up to 4 times with a 3s delay **only** on a 404 — any other status is raised immediately, not masked. Confirmed by direct testing: `2024-05-01-preview` is the working `api-version` for this endpoint shape (the doc-plausible default `2024-06-01`, which is correct for classic Azure OpenAI, 404s here) — set as the new `azure_openai_api_version` default, overridable via `.env`.
- **`app/llm/__init__.py`**: `get_embedding_provider()` / `get_chat_provider()` — the single swap point. Business logic (`knowledge_service.py`) only ever calls these two functions, never imports Azure-specific code directly, so a future provider swap is a one-file change.
- **`app/rag/chunking.py`**: `chunk_text()` — word-count-based sliding window, ~500 words per chunk with 50-word overlap (word count is a cheap proxy for token count, not exact — flagged with a `ponytail:` comment; swap for a real tokenizer like `tiktoken` if a model's hard token limit is ever actually hit). Stdlib only, no new dependency for this part.
- **`app/services/knowledge_service.py`**:
  - `_regenerate_chunks(db, document)`: always deletes existing chunks for the document first, then — only if the document's status is `APPROVED` — chunks + embeds the current content and inserts fresh `KnowledgeChunk` rows. This single function is what enforces "only approved docs have chunks," not just a query-time filter.
  - `update_document()` now calls `_regenerate_chunks` whenever `content` was part of the PATCH or `status` changed — skipped entirely for a title-only edit on an already-approved doc, so no embedding calls are wasted on no-op-for-retrieval changes.
  - `search_chunks(db, business_id, query_vector, top_k)`: joins `KnowledgeChunk` → `KnowledgeDocument`, filters `business_id` AND `status == APPROVED`, orders by pgvector cosine distance (`<=>` via `Vector.cosine_distance()`), returns `(chunk, document, similarity)` tuples.
- **`app/schemas/knowledge.py`**: `KnowledgeSearchRequest` (`query`, `top_k` 1–20, default 5), `KnowledgeSearchResult`, `KnowledgeSearchResponse`.
- **`app/api/routes/knowledge.py`**: `POST /api/v1/knowledge/search` — any authenticated role (read-tier, same as `GET /knowledge`), embeds the query via `get_embedding_provider()`, calls `search_chunks` scoped to `current_user.business_id`.
- **Existing regression suite updated** (`backend/tests/integration/test_knowledge_base.py`): added an autouse fixture that monkeypatches `knowledge_service.get_embedding_provider` with a deterministic zero-cost fake (`[0.01] * 1536` vectors) — the two tests that approve a document (which now triggers real chunking/embedding) would otherwise make real, credential-requiring API calls on every CI run. This suite proves the approve/edit/archive → chunk lifecycle wiring is correct without spending real API calls; real embedding/search behavior is verified separately below, against the real Azure API.
- **`app/core/logging.py`**: `logging.getLogger("httpx").setLevel(logging.WARNING)` added to `configure_logging()`. **Found by direct testing, not anticipated in advance**: `httpx` logs the full request URL — including the Azure endpoint — at INFO level by default, and the app's structured-JSON logging config propagates that straight to stdout. The API key itself never appeared (it's a header, which `httpx` doesn't log), but the endpoint hostname did, which the acceptance criteria explicitly rules out. One-line fix at the central logging config, verified below.

**Real Azure OpenAI credentials — setup issues hit and fixed along the way (each found only by actually calling the real API, not guessable up front):**
1. First real call: `AZURE_OPENAI_EMBEDDING_DEPLOYMENT` was accidentally set to an API-version-shaped string, then to a key-shaped string — both `DeploymentNotFound`/clearly-wrong-shape, caught and corrected by the user.
2. Once a real deployment name (`text-embedding-3-small`) was in place: still `404 DeploymentNotFound`, consistently, at `{endpoint}/openai/deployments/{name}/embeddings` (the classic Azure OpenAI path the `openai` SDK's `AzureOpenAI` client always uses).
3. Diagnosed by raw `httpx` calls (bypassing the SDK): the resource's `/openai/deployments` listing path itself returns `404 Resource not found` regardless of API version — meaning this isn't a classic Azure OpenAI resource at all. Confirmed the resource is Azure AI Foundry (`*.services.ai.azure.com`) by successfully hitting its unified path instead: `POST {endpoint}/models/embeddings?api-version=2024-05-01-preview` with `{"input": [...], "model": "<deployment>"}` → real `200`, real vector, dimension `1536`.
4. Provider rewritten to call that path directly via `httpx` (see above); config default `api_version` updated from `2024-06-01` to `2024-05-01-preview` to match.
5. Even after that fix, the same real deployment intermittently 404s (~50% of back-to-back identical requests) — handled with the bounded retry described above.

**Real-API acceptance verification (actual output, run 2026-09-03/04, two real registered businesses, real Azure calls):**

1. Dimension check — real embed call:
```
count: 2
dimension: 1536 1536
sample values: [-0.0286712646484375, 0.04974365234375, 0.024810791015625, 0.01486968994140625, -0.038421630859375]
```
1536 matches the Phase 2 pgvector column exactly — **no migration change needed**. `alembic check` re-confirmed: `No new upgrade operations detected.`

2. **Approve a real document → real chunk + non-null embedding in the DB:**
```
$ curl -X PATCH .../knowledge/{id} -d '{"status":"approved"}'   (Business A: "Cancellation Policy")
{"status":"approved","approved_by":"0bbd5d7a-...","approved_at":"2026-09-03T18:59:09.605527Z",...}

$ psql -c "SELECT id, left(content,60), embedding IS NOT NULL AS has_vector, vector_dims(embedding) FROM knowledge_chunks WHERE knowledge_document_id='{id}';"
                  id                  |                       content_preview                        | has_vector | dims
--------------------------------------+--------------------------------------------------------------+------------+------
 c413c8d1-1355-4c4a-8420-b5633ee77055 | Appointments must be cancelled at least 24 hours in advance  | t          | 1536

$ psql -c "SELECT embedding::text FROM knowledge_chunks LIMIT 1;"
[-0.017700195,0.002357483,0.040496826,0.018325806,-0.039154053,-0.019134521,-0.0066108704,...]   # real, non-zero floats
```

3. **Real search, ranked by real similarity scores** — Business A had two approved docs ("Cancellation Policy" and "Business Hours"); query about cancellation fees correctly ranks the relevant one far higher:
```
$ curl -X POST .../knowledge/search -d '{"query":"how much is the fee if I cancel my appointment late","top_k":5}'
{
  "results": [
    {"document_title": "Cancellation Policy", "similarity": 0.652140964559582, ...},
    {"document_title": "Business Hours",      "similarity": 0.1863051234363935, ...}
  ]
}
```

4. **Cross-tenant test — real near-duplicate content across two real businesses**, the hardest version of this test (not just different data, near-identical text): Business B was given a "Cancellation Policy" document with nearly the same wording as Business A's. Business A searched for cancellation content:
```
document_ids returned to Business A: ['5c9d7a95-...' (own doc), '5e228a00-...' (own doc)]
Business B doc id: 76ac07b9-...
LEAK? False
```
Business B's own search for the identical query returned only its own document (`similarity: 0.585...`), never Business A's.

5. **Status test — archive stops appearing in search, before/after:**
```
BEFORE archive: ['Cancellation Policy', 'Business Hours']
$ curl -X PATCH .../knowledge/{id} -d '{"status":"archived"}'   -> {"status":"archived",...}
$ psql -c "SELECT count(*) FROM knowledge_chunks WHERE knowledge_document_id='{id}';"   -> 0
AFTER archive:  ['Business Hours']
```

6. **Edit-invalidation test — real content edit on a re-approved doc, old chunk gone, new one reflects the new content:**
```
old chunk id (before edit): 2608cd37-7c62-4af0-8b48-32ef276fa818  (content: "Appointments must be cancelled...")
$ curl -X PATCH .../knowledge/{id} -d '{"content":"UPDATED: Appointments now require 48 hours notice ... $40 fee ..."}'
  -> version: 2

new chunk id (after edit): 8917d285-4167-4684-b53e-03f5fa3ffb35  (content: "UPDATED: Appointments now require 48 hours notice...")
$ psql -c "SELECT count(*) FROM knowledge_chunks WHERE id='2608cd37-...';"   -> 0   # old chunk confirmed gone
$ psql -c "SELECT embedding IS NOT NULL, vector_dims(embedding) FROM knowledge_chunks WHERE knowledge_document_id='{id}';"  -> t, 1536

$ curl -X POST .../knowledge/search -d '{"query":"how many hours notice do I need to cancel","top_k":3}'
  -> top result content: "UPDATED: Appointments now require 48 hours notice to cancel without a $40 fee...", similarity 0.585
     (reflects the NEW content, not the old 24h/$25 policy)
```

7. **Draft-document zero-eligibility — verified directly, not assumed from the query filter**: created a fresh draft document containing a unique, unmistakable string (`XYZQUANTUM117`), left it in `draft` (never approved):
```
$ psql -c "SELECT count(*) FROM knowledge_chunks WHERE knowledge_document_id='{draft_id}';"   -> 0
$ curl -X POST .../knowledge/search -d '{"query":"XYZQUANTUM117 unique unreleased promo code","top_k":5}'
  -> results: [('Cancellation Policy', 0.158...), ('Business Hours', 0.053...)]   # draft doc never appears, even for its own exact content
draft doc leaked? False
```

8. **Secrets check — after the `httpx` logging fix**:
```
$ git ls-files | grep -E '\.env$'          -> none tracked
$ git grep -nE 'AZURE_OPENAI_(API_KEY|ENDPOINT)\s*=\s*[A-Za-z0-9]' -- . ':!backend/.env.example'  -> only placeholder lines in .env.example matched
$ docker compose logs backend --tail=100 | grep -iE "api.key|samrat-g01|services\.ai\.azure"   -> clean, no match (BEFORE the fix, this same grep DID match the endpoint hostname in httpx's request logs — real leak, found and fixed, see above)
```

9. Lint: `docker compose exec backend ruff check .` → `All checks passed!` (re-run after every change, including the provider rewrite and logging fix).

10. Full regression suite (stubbed provider, unaffected by any of the above):
```
======================== 24 passed, 1 warning in 25.95s ========================
```

11. DB left clean after all real-API testing (both test businesses deleted, cascade):
```
$ psql -c "SELECT count(*) FROM businesses;"            -> 0
$ psql -c "SELECT count(*) FROM knowledge_documents;"   -> 0
$ psql -c "SELECT count(*) FROM knowledge_chunks;"      -> 0
$ psql -c "SELECT count(*) FROM business_users;"        -> 0
```

**Result / Acceptance criteria:**
| Criterion | Status |
|---|---|
| Approve a real document → real chunks + non-null vector data in the DB | ✓ Pass — real 1536-dim floats shown |
| Real search, semantically ranked with real scores | ✓ Pass — 0.652 (relevant) vs. 0.186 (irrelevant) |
| Cross-tenant: never returns another business's chunks, even near-identical content | ✓ Pass — `LEAK? False`, tested with deliberately near-duplicate text |
| Archive stops appearing in search (before/after) | ✓ Pass |
| Edit invalidates old chunks, regenerates from new content | ✓ Pass — old chunk id confirmed gone, new chunk reflects new content |
| Draft documents have zero eligible chunks, verified directly | ✓ Pass — 0 chunks, and a search for the draft's own unique text returns nothing from it |
| No API key/endpoint in logs, errors, or committed files | ✓ Pass — after fixing a real `httpx`-logged-endpoint leak found during this exact test |
| Lint clean, migration reversible | ✓ Pass (ruff clean; dimension matched so no new migration was needed; `alembic check` clean) |

**Known issues / punted items:**
- Chunking uses word count as a token-count proxy, not `tiktoken` — acceptable at the scale here (10MB doc cap from Phase 5), flagged as a `ponytail:` comment at the source.
- `ChatProvider`/`AzureChatProvider` exist per your explicit request for the LLM-agnostic seam but are not called anywhere yet — Phase 7+'s job. Only `embed()` was exercised against the real API this phase; `chat()` uses the same Foundry `/models/chat/completions` path but hasn't been called for real yet since nothing calls it until Phase 7.
- The user's specific Azure AI Foundry resource intermittently 404s on a live deployment (~50% of raw requests) — handled with a bounded retry (4 attempts, 3s delay) in `app/llm/azure_openai.py`. If this resource's reliability doesn't improve, that retry budget may need tuning; flagged, not silently hidden behind an infinite retry.
- `KnowledgeDocument.approved_by` still not tenant-cross-checked at the DB level (carried over from Phase 2, still open, unrelated to this phase).
- No commit has been made yet — awaiting your confirmation of this verification output per working rule #6.

---

## Phase 7 — Conversation Memory

**Date:** 2026-09-04

**Required:**
- `app/memory/`: short-term recall, customer profile memory, appointment memory (bounded), conversation summarization via Phase 6's `ChatProvider`, and a single `assemble_context()` combining all of it — bounded, with an approximate size logged/returned. No RAG-knowledge injection here (Phase 8's job). Tenant-scoped everywhere.

**Implemented:**

- **`app/db/models/conversation.py`**: `Conversation` gets two new columns — `summary: str | None` (Text) and `summarized_message_count: int` (default 0). Chose "add fields to `Conversation`" over a separate `ConversationSummary` table: there's exactly one live summary per conversation at a time (it's replaced/extended, never versioned/kept as history), so a second table would only add a join for no real benefit. `summarized_message_count` is what makes re-summarization incremental — it's how many of the conversation's oldest messages (by `created_at`) are already folded into `summary`, so a later summarization call only sends the *newly* aged-out messages to the LLM, not the whole prefix again.
- **Migration** `ea1b824909b1_conversation_summarization_fields.py` (`down_revision = aa23ade02a4c`) — clean autogenerate, no hand-fixes needed. `alembic check`: no drift. Full `downgrade base` → `upgrade head` cycle verified clean.
- **`app/memory/conversations.py`**: `get_conversation(db, conversation_id, business_id)` — the one tenant-scoped lookup every other memory module shares, so "not found" and "not yours" collapse to the same `None`/`[]` response everywhere (no existence-leaking).
- **`app/memory/short_term.py`**: `get_recent_messages(db, conversation_id, business_id, limit)` — last `limit` messages, returned oldest-first (natural reading/LLM-context order, not reverse-chronological). Tenant-scoped via `get_conversation`; returns `[]` (not an error) for a conversation that doesn't exist or belongs to another business.
- **`app/memory/customer_context.py`**: `get_customer_context(db, customer_id, business_id)` — compact dict (`id`, `name`, `phone`, `email`, `preferred_language`) off the existing `Customer` model from Phase 3. `None` if tenant mismatch.
- **`app/memory/appointment_context.py`**: `get_appointment_context(db, customer_id, business_id)` — `{"active": [...], "recent_past": [...]}`. `active` = `PENDING`/`CONFIRMED` status, **always all of them, no limit** (per the explicit requirement — an upcoming appointment must never silently drop off). `recent_past` = `COMPLETED`/`CANCELLED`, ordered most-recent-first, **hard-capped at 3** regardless of how many the customer actually has. Each entry joins in the service name (and staff name, if assigned) so the context is directly useful for prompt injection, not just raw IDs.
- **`app/memory/summarization.py`**: `maybe_summarize_conversation(db, conversation_id, business_id, threshold=20, keep_recent=10)`. No-op (returns the conversation unchanged, no LLM call) if total messages ≤ threshold, or if nothing new has aged past the `keep_recent` window since the last summarization. Otherwise: pulls exactly the newly-aged-out messages (`offset=summarized_message_count, limit=boundary-summarized_message_count`), builds a prompt that includes the *existing* summary (if any) plus just those new messages, calls `get_chat_provider().chat(...)` from Phase 6 — **never a hardcoded Azure call** — and advances `summarized_message_count`. This is what keeps summarization cost bounded as a conversation grows: each call only ever re-sends the delta, not the whole history.
- **`app/memory/context.py`**: `assemble_context(db, conversation_id, business_id, recent_limit=10)` — combines `summary` + `recent_messages` (bounded to `recent_limit`, always, whether or not a summary exists) + `customer` + `appointments` into one dict. Computes an approximate word count across every text field in the structure, converts to a rough token estimate (`words / 0.75`, same order-of-magnitude proxy as Phase 6's chunker — flagged with a `ponytail:` comment, not exact), returns it as `_approx_size`, and **logs it** (`logger.info(...)` in `app/memory/context.py`) so unbounded growth would be visible in production logs, not just in a return value nobody looks at. Deliberately does not touch Phase 6's knowledge search — that's Phase 8's job to combine separately.
- **`app/memory/__init__.py`**: re-exports the five public functions, same pattern as Phase 6's `app/llm/__init__.py`.
- **No new HTTP endpoints** — the ticket scoped this to "the memory layer a future conversation engine will query," i.e. internal functions for Phase 8 to call directly, not an API surface. Since no conversation/message/appointment-creation endpoints exist yet either (out of scope for Phases 1–6), all test/verification data below was created directly via the ORM (`SessionLocal`), the same established pattern used for the `staff`-role test users in every prior phase's RBAC tests.
- **`backend/tests/integration/test_memory.py`** (new, 10 tests): short-term ordering + cross-tenant, customer context + cross-tenant, appointment bound (7 past appointments in the fixture, asserts exactly 3 come back and they're the 3 most recent), summarization no-op-below-threshold / incremental-boundary / cross-tenant, `assemble_context` bounded-and-sized / cross-tenant, and one **real-API test gated behind `RUN_REAL_LLM_TESTS=1`** (skipped by default, per the ticket's "use it sparingly in tests" — it's not part of the default `pytest tests/` run, so it never costs real API money in normal CI, but it exists and is exercised below to prove the real integration works). All others use a `_StubChatProvider` monkeypatched onto `app.memory.summarization.get_chat_provider`, matching Phase 6's stubbing pattern for `get_embedding_provider`.

**Real-API verification (actual output, run 2026-09-03/04, two real registered businesses):**

1. **`get_recent_messages` — correct order, real timestamps** (25 real messages inserted one commit at a time — Postgres `now()` is transaction-time, not statement-time, so messages must be committed individually for `created_at` to actually advance; noted as a real gotcha, not assumed):
```
[2026-09-03T19:12:57.005022] customer: One more question — do you accept Delta Dental insurance?
[2026-09-03T19:12:57.006432] agent: Yes, we accept Delta Dental. Bring your card to the appointment.
[2026-09-03T19:12:57.007830] customer: Great, will do.
[2026-09-03T19:12:57.010798] agent: See you soon!
[2026-09-03T19:12:57.012326] customer: Thanks, bye!
```
Correct chronological order (oldest→newest), correctly limited to the last 5 of 25.

2. **Cross-tenant — Business B calling with Business A's real (guessed) `conversation_id`:**
```
Business B result (must be empty): []
```

3. **Customer context — real profile, tenant-scoped:**
```json
{"id": "62beccec-3997-4f95-a4f9-18170a763479", "name": "Alex Rivera", "phone": "555-0199", "email": "alex.rivera@example.com", "preferred_language": "es"}
```
```
Business B lookup of A's customer (must be None): None
```

4. **Appointment context — bound proven with a customer who has 7 past appointments:**
```
active count: 2 (expect 2)
recent_past count: 3 (expect 3, even though 7 past appointments exist)
```
Full JSON confirmed `recent_past` contains exactly the 3 most-recent past appointments (Aug 24 cancelled, Aug 4 completed, Jul 5 completed) — not the oldest 3, not all 7 — while both `active` (Sep 6 confirmed, Sep 17 pending) were included with no cap.

5. **Real summarization** — 25-message realistic dental-office conversation (toothache → exam booked → rescheduled 10am→11am → insurance question), threshold=20 crossed:
```
BEFORE: summary: None, summarized_message_count: 0

REAL GENERATED SUMMARY (via the real Azure/Foundry ChatProvider):
"Customer reports a sharp, bite-triggered tooth pain on the lower right for several
days and requested an ASAP exam; agent suggested a possible root canal evaluation.
Appointment confirmed for tomorrow at 11:00 AM (initially booked for 10:00 AM then
moved), and agent advised OTC ibuprofen for pain until the visit."

summarized_message_count: 15 (expect 25-10=15)
```
Accurate — correctly captures the pain description, the reschedule, and the advice given, from real messages it was never told the "point" of in advance.

6. **Proof the summary REPLACES old messages, not sits alongside them:**
```
Total raw messages in conversation: 25
recent_messages count in assembled context: 10
Early messages (from the summarized portion) found in raw recent_messages: [] (expect [])
Same content present in summary instead: True
```

7. **Full `assemble_context` output** (paste in full, as requested):
```json
{
  "conversation_id": "f0ef4a4a-f3e0-4b34-befe-1e4259bea1f4",
  "summary": "Customer reports a sharp, bite-triggered tooth pain on the lower right for several days and requested an ASAP exam; agent suggested a possible root canal evaluation. Appointment confirmed for tomorrow at 11:00 AM (initially booked for 10:00 AM then moved), and agent advised OTC ibuprofen for pain until the visit.",
  "recent_messages": [
    {"sender_type": "agent", "content": "Anytime! Let us know if the pain gets worse before then.", "created_at": "2026-09-03T19:12:56.993465"},
    {"sender_type": "customer", "content": "It's actually feeling a bit better today.", "created_at": "2026-09-03T19:12:56.995263"},
    {"sender_type": "agent", "content": "Good to hear, but we'll still take a look tomorrow to be safe.", "created_at": "2026-09-03T19:12:56.996799"},
    {"sender_type": "customer", "content": "Sounds good.", "created_at": "2026-09-03T19:12:57.001522"},
    {"sender_type": "agent", "content": "See you at 11am!", "created_at": "2026-09-03T19:12:57.003559"},
    {"sender_type": "customer", "content": "One more question — do you accept Delta Dental insurance?", "created_at": "2026-09-03T19:12:57.005022"},
    {"sender_type": "agent", "content": "Yes, we accept Delta Dental. Bring your card to the appointment.", "created_at": "2026-09-03T19:12:57.006432"},
    {"sender_type": "customer", "content": "Great, will do.", "created_at": "2026-09-03T19:12:57.007830"},
    {"sender_type": "agent", "content": "See you soon!", "created_at": "2026-09-03T19:12:57.010798"},
    {"sender_type": "customer", "content": "Thanks, bye!", "created_at": "2026-09-03T19:12:57.012326"}
  ],
  "customer": {"id": "62beccec-3997-4f95-a4f9-18170a763479", "name": "Alex Rivera", "phone": "555-0199", "email": "alex.rivera@example.com", "preferred_language": "es"},
  "appointments": {
    "active": [
      {"id": "7d5e2daf-...", "service": "Root Canal", "staff": null, "scheduled_at": "2026-09-06T19:12:41.104236+00:00", "duration_minutes": 60, "status": "confirmed"},
      {"id": "21a1bc5b-...", "service": "Root Canal", "staff": null, "scheduled_at": "2026-09-17T19:12:41.104236+00:00", "duration_minutes": 60, "status": "pending"}
    ],
    "recent_past": [
      {"id": "b0e32e75-...", "service": "Root Canal", "staff": null, "scheduled_at": "2026-08-24T19:12:41.104236+00:00", "duration_minutes": 60, "status": "cancelled"},
      {"id": "a66f359b-...", "service": "Root Canal", "staff": null, "scheduled_at": "2026-08-04T19:12:41.104236+00:00", "duration_minutes": 60, "status": "completed"},
      {"id": "e82bdf0d-...", "service": "Root Canal", "staff": null, "scheduled_at": "2026-07-05T19:12:41.104236+00:00", "duration_minutes": 60, "status": "completed"}
    ]
  },
  "_approx_size": {"words": 152, "tokens_estimate": 203}
}
```
Reasonably bounded: 152 words / ~203 estimated tokens total, independent of the fact that the underlying conversation had 25 raw messages and 7 past appointments.

8. **Size logging confirmed** (re-run with `configure_logging()` actually invoked, matching how `app.main` initializes it for the real app — a standalone script that doesn't import `app.main` never configures logging at all, and Python's root logger silently drops `INFO` by default; this was caught by the log line not appearing on the first attempt, not assumed away):
```json
{"timestamp": "2026-09-03T19:13:59.337315+00:00", "level": "INFO", "logger": "app.memory.context", "message": "assembled conversation context: conversation_id=f0ef4a4a-f3e0-4b34-befe-1e4259bea1f4 approx_words=152 approx_tokens=203 recent_messages=10 has_summary=True"}
```

9. **Secrets check — after the real summarization call:**
```
$ git ls-files | grep -E '\.env$'  -> none tracked
$ git grep -nE 'AZURE_OPENAI_(API_KEY|ENDPOINT)\s*=\s*[A-Za-z0-9]' -- . ':!backend/.env.example'  -> only placeholder lines matched
$ docker compose logs backend --tail=200 | grep -iE "api.key|samrat-g01|services\.ai\.azure"  -> clean, no match (Phase 6's httpx logger suppression covers this call too, since it's the same _post() helper)
```

10. Lint: `docker compose exec backend ruff check .` → `All checks passed!`

11. Full regression suite (real-API test correctly skipped by default):
```
$ docker compose exec backend python -m pytest tests/ -v
...
================== 33 passed, 1 skipped, 1 warning in 31.48s ===================
```
Real-API test run explicitly: `docker compose exec -e RUN_REAL_LLM_TESTS=1 backend python -m pytest tests/integration/test_memory.py::test_summarization_real_api -v -s` → `1 passed`, real summary printed (a realistic booking/reschedule conversation, correctly summarized).

12. `alembic check`: `No new upgrade operations detected.` Full `downgrade base` → `upgrade head` cycle clean (see above).

13. DB left clean after all real-API testing:
```
$ psql -c "SELECT count(*) FROM businesses;"     -> 0
$ psql -c "SELECT count(*) FROM conversations;"  -> 0
$ psql -c "SELECT count(*) FROM messages;"       -> 0
$ psql -c "SELECT count(*) FROM appointments;"   -> 0
$ psql -c "SELECT count(*) FROM customers;"      -> 0
$ psql -c "SELECT count(*) FROM services;"       -> 0
$ psql -c "SELECT count(*) FROM business_users;" -> 0
```

**Result / Acceptance criteria:**
| Criterion | Status |
|---|---|
| `get_recent_messages` correct order + tenant-scoped, cross-tenant checked with a guessed `conversation_id` | ✓ Pass |
| Customer/appointment context correct + bounded, proven with a customer with many past appointments (7 → capped at 3, active never capped) | ✓ Pass |
| Real summarization triggered via real `ChatProvider`, actual summary pasted, old raw messages confirmed replaced (not duplicated) in `assemble_context` | ✓ Pass |
| Full `assemble_context` output pasted with approximate size logged | ✓ Pass — 152 words / ~203 tokens, logged via `app.memory.context` |
| No secrets/endpoints in logs during the real summarization call | ✓ Pass |
| Lint clean, migration reversible | ✓ Pass (ruff clean; `alembic check` clean; full downgrade/upgrade cycle clean) |

**Known issues / punted items:**
- Token estimate is `words / 0.75`, the same order-of-magnitude proxy used in Phase 6's chunker, not an exact tokenizer count — flagged with a `ponytail:` comment at the source; swap for `tiktoken` if exact budgeting is ever needed.
- No HTTP endpoints were added for conversations/messages/appointments — none existed before this phase either, and the ticket scoped this to the internal memory-query layer for Phase 8, not a new API surface. All verification data was created directly via the ORM, same pattern as prior phases' RBAC test fixtures.
- `Conversation.summary` is a single rolling field, not a versioned/audit-trailed history of past summaries — matches "your call" in the ticket; flagged in case Phase 8+ wants summary history for debugging/QA.
- The real-API summarization test is gated behind `RUN_REAL_LLM_TESTS=1` and does not run in the default `pytest tests/` suite — deliberate, per the ticket's "use it sparingly in tests," but flagging so it's not mistaken for missing coverage.
- No commit has been made yet — awaiting your confirmation of this verification output per working rule #6.

---

## Phase 8 — Conversation Orchestrator

**Date:** 2026-09-04

**Required:**
- `app/services/conversation/`: intent detection via `ChatProvider`, full orchestration flow (context → knowledge search → intent+response → persist messages), a tool-calling scaffold (no real tools yet — booking/rescheduling/cancellation intents must be handled honestly, never fabricated as completed), a never-invent-information guardrail, and `POST /api/v1/conversations/{id}/messages` to drive it end-to-end for testing. No actual booking/cancel/reschedule mutation this phase.

**Implemented:**

- **`app/schemas/conversation.py`**: `ConversationIntent` enum (all 14 values from the ticket, exactly), `IncomingMessageCreate`, `OrchestratedMessageResponse`.
- **`app/services/conversation/tools.py`**: `ConversationTool` ABC (`name`, `handles_intents`, `run(db, *, business_id, customer_id, **kwargs) -> dict`) and `TOOL_REGISTRY: dict[ConversationIntent, ConversationTool]` — **deliberately empty in Phase 8**. `find_tool(intent)` is the only way the orchestrator ever touches this registry. This is the tool-calling interface the ticket asked to establish now: the LLM never gets a write path of its own — only `tool.run()` would mutate data, and only the orchestrator ever calls it. Phase 10+ registers real tools here (`BookAppointmentTool`, etc.) and nothing else in the orchestrator needs to change.
- **`app/services/conversation/intent.py`**: `classify_and_respond(business, context, knowledge_results, customer_message)` — **one LLM call does both intent classification and response drafting**, not two. Documented reasoning: a second, separate classification call could disagree with the response it never saw being drafted (e.g. classify "booking" while the drafted reply reads like a confirmation) — one call keeps intent and response consistent with each other by construction, and it's half the real API cost/latency of two calls. The system prompt (`_SYSTEM_PROMPT_TEMPLATE`) carries: business name/description/tone (Phase 4 data, for "warm, concise, professional, human-like" tone per the master plan), the never-invent-information rule, the honesty-about-booking-capability rule, and an instruction to reply with only a single JSON object (`{"intent": ..., "response": ...}`). `_parse_response()` handles real-world LLM output rough edges — strips markdown code fences, falls back to `ConversationIntent.UNKNOWN` + the raw text (not a crash) if the JSON is malformed or the intent value isn't one of the 14 valid ones. Covered by 4 unit tests (valid JSON, fenced JSON, malformed fallback, invalid-intent fallback).
- **`app/services/conversation/orchestrator.py`**: `handle_incoming_message(db, conversation_id, business_id, content)` — the full flow: tenant-scoped conversation lookup (`None` → route 404s, same IDOR-safe pattern as every prior phase) → `maybe_summarize_conversation` (Phase 7, keeps context bounded turn over turn) → `assemble_context` (Phase 7) → embed the customer's raw message and run `knowledge_service.search_chunks` (Phase 6, `top_k=3`, no query reformulation — the raw message is used directly, a deliberate simplicity choice, documented here) → `classify_and_respond` → `find_tool(intent)` (always `None` in Phase 8) → persist the customer `Message` then the agent `Message` → return `{intent, response, customer_message_id, agent_message_id}`.
- **`app/api/routes/conversations.py`**: `POST /api/v1/conversations/{conversation_id}/messages` — any authenticated role (matches Phase 3's `POST /customers` precedent: this isn't a business-config write, it's driving/testing the orchestration), tenant-scoped via `current_user.business_id`, 404 for a conversation that doesn't exist or belongs to another business. Not wired to any real channel yet (Phase 22+) — this is the internal testing endpoint the ticket asked for.
- **No new migration** — `Conversation`/`Message` already had everything needed from Phases 2/7.
- **A real bug found and fixed during this phase's own acceptance testing** (see below, not hidden): Phase 7's incremental conversation summarization could **drop a specific fact** (e.g. which tooth, an allergy) when folding a second batch of mostly-irrelevant filler messages into an existing summary, because `_SUMMARY_SYSTEM_PROMPT` never told the LLM to *preserve* facts already in the existing summary — it only said "fold new messages in." Root-caused and fixed in `app/memory/summarization.py` (Phase 7's file, not patched around in Phase 8), then **re-verified against a fresh real conversation built specifically to reproduce the two-fold scenario** — see step 6 below.
- **`backend/tests/integration/test_conversation.py`** (new, 8 tests, stubbed `ChatProvider`/`EmbeddingProvider` — no real API cost): message persistence + correct sender types, cross-tenant rejection (404, and confirms zero messages were written), unknown-`conversation_id` rejection, `TOOL_REGISTRY` is empty and `find_tool` returns `None` for all three booking-family intents, and 4 tests for `_parse_response`'s JSON handling including its fallback paths. Real end-to-end acceptance (actual LLM calls) is below, run manually against the real Azure/Foundry API — same pattern as Phases 6/7, not re-run on every `pytest tests/`.

**Real-API acceptance verification (actual output, run 2026-09-04, real registered businesses, real knowledge document, real multi-turn conversation):**

Business: "Willow Creek Family Dentistry", tone set to "warm and reassuring", description "a family dental practice" (Phase 4 fields, used in the system prompt). One real approved knowledge document ("Pricing": cleaning $95, filling $150-$300, root canal $700+, 10% senior/student discount).

1. **Turn 1 — greeting/opening, establishes a detail to test memory recall on later** (customer: "Hi! My name is Jordan... I am allergic to penicillin. I have been having some pain in my lower right molar."):
```json
{"intent": "service_question", "response": "Hi Jordan — thanks for letting us know about your penicillin allergy, and I'm sorry you're in pain. Dental pain in a lower molar should be evaluated soon. Can you tell me how long you've had the pain, your pain level (0–10), and whether you have any swelling or fever or recent dental work? Are you an existing patient with us? I can connect you with our team to arrange an exam and make sure your allergy is added to your record — would you like that?"}
```
Warm, on-tone, asks clarifying questions like a real receptionist would — never claims an appointment exists yet.

2. **Turn 2 — pricing question, answered correctly from the real approved knowledge document** (customer: "How much does a cavity filling cost?"), after 20 padding messages pushed the conversation past the summarization threshold (this turn's own call triggered the first real summarization fold — see below):
```json
{"intent": "pricing_question", "response": "A cavity filling typically costs between $150 and $300 depending on the size of the filling. We also offer a 10% discount for seniors and students. If you'd like a personalized estimate or to arrange an exam, I can connect you with our team—would you like me to do that?"}
```
Exact match to the real knowledge document's figures ($150–$300, 10% discount) — not invented. `summarized_message_count` confirmed `12` in the DB immediately after, `summary` correctly included "penicillin allergy" and "pain in the lower right molar."

3. **Turn 3 — booking intent, the hallucination-risk test** (customer: "Okay, please book me an appointment for the filling next Tuesday at 2pm."):
```json
{"intent": "booking", "response": "I can help with that — I don't have the ability to book directly, but I can connect you with our team to request next Tuesday at 2:00 PM. Before I connect, could you please confirm: 1) Are you an existing patient? ... I'll also make sure your penicillin allergy is added. Would you like me to connect you now?"}
```
**Passes**: intent correctly classified `booking`; the response explicitly states "I don't have the ability to book directly" and at no point says or implies an appointment was booked/confirmed/scheduled — it only offers to *connect* the customer with the team, which is honest and immediately actionable (no fabricated future promise).

4. **Turn 4 — question with zero matching approved knowledge, the never-invent-information test** (customer: "Do you offer laser teeth whitening, and if so what brand of laser equipment do you use?"):
```json
{"intent": "service_question", "response": "Thanks for asking — I don't have info in the materials I was given about laser teeth whitening or the brand of laser equipment we use. Would you like me to connect you with our team to confirm availability, brand, and pricing? If so, please confirm the best phone number and email or say if you'd like me to connect you now."}
```
**Passes**: explicitly says it doesn't have the information and offers human handoff, does not invent a brand name or claim the service exists. Checked what was actually retrieved for this query (real `POST /knowledge/search`): the Pricing chunk came back as the (only, irrelevant) result at `similarity: 0.289` — confirming the guardrail is working by the LLM's own judgment of relevance against the system prompt's instruction, not because nothing was retrieved (there is no hard similarity cutoff in `search_chunks` — it always returns the top-k nearest neighbors regardless of absolute quality). Flagged as a real design detail, not assumed.

5. **Turn 5 — natural continuation** ("This has been really helpful, thank you.") — `intent: "follow_up"`, still correctly declines to claim the Tuesday booking is confirmed, still tracks the allergy.

6. **Turn 6 — memory recall test, THE FIRST REAL RUN FOUND A REAL BUG (not hidden — see fix above):**
   - First attempt: asked "which tooth did I originally say was hurting?" after the conversation had gone through incremental summarization twice. **Failed**: the agent replied "I don't see a note in our conversation that says which tooth was hurting." Root cause diagnosed by inspecting the actual stored `summary` — the second incremental fold had dropped "lower right molar" while keeping the allergy fact, because the summarization prompt never said to *preserve* existing facts. Fixed in `app/memory/summarization.py` (see above).
   - **Re-verified against a fresh conversation, built specifically to reproduce two incremental summarization folds** (Turn A states an isolated fact → 20 filler messages → Turn B triggers fold #1, confirmed in the DB: `summarized_message_count: 12`, summary correctly says *"Sam reported chipping his upper left canine while playing basketball yesterday"* → 10 more filler messages → Turn C triggers fold #2, confirmed in the DB: `summarized_message_count: 24`, summary **still** says *"Sam reported chipping his upper left canine while playing basketball yesterday"* — the fact survived the second merge this time):
```
Confirmed via get_recent_messages: "canine"/"basketball" mentioned in raw last-10 window: False
(i.e. the only way the agent could know this is from the summary)

TURN D (real): "Just to confirm before I go — which tooth did I say was chipped, and how did it happen?"
{"intent": "follow_up", "response": "You said you chipped your upper left canine while playing basketball yesterday. Would you like a team member to call you now to arrange urgent care and confirm walk-in availability? Also, could you let us know if you're in pain or bleeding, if the tooth is loose, if you recovered the broken piece, and whether you're an existing patient or have dental insurance?"}
```
**Passes, after the fix**: correctly recalls a fact that exists only in `conversation.summary`, not in any raw message within the last-10 window — real, verified proof that Phase 7's memory is actually being used by the Phase 8 orchestrator, and that the incremental-summarization bug found by this exact test is now fixed.

7. **Cross-tenant test — real rejection:**
```
$ curl -i -X POST .../conversations/{business_A_conversation_id}/messages  (Business B's real token)
HTTP/1.1 404 Not Found
{"error":{"type":"not_found","message":"Conversation not found."}}
```
Message count for Business A's conversation confirmed unchanged (32 before and after) — the rejected request wrote nothing.

8. **Secrets check** (after all real LLM calls in this phase):
```
$ git ls-files | grep -E '\.env$'  -> none tracked
$ git grep -nE 'AZURE_OPENAI_(API_KEY|ENDPOINT)\s*=\s*[A-Za-z0-9]' -- . ':!backend/.env.example'  -> only placeholder lines matched
$ docker compose logs backend --tail=300 | grep -iE "api.key|samrat-g01|services\.ai\.azure"  -> clean, no match
```

9. Lint: `docker compose exec backend ruff check .` → `All checks passed!` (re-run after the summarization prompt fix too).

10. Full regression suite (all real-API-dependent tests remain stubbed/gated, so this stays fast and free):
```
$ docker compose exec backend python -m pytest tests/ -v
...
================== 41 passed, 1 skipped, 1 warning in 33.94s ===================
```

11. No migration this phase — N/A for reversibility.

12. DB left clean after all real-API testing:
```
$ psql -c "SELECT count(*) FROM businesses;"            -> 0
$ psql -c "SELECT count(*) FROM conversations;"         -> 0
$ psql -c "SELECT count(*) FROM messages;"              -> 0
$ psql -c "SELECT count(*) FROM knowledge_documents;"   -> 0
$ psql -c "SELECT count(*) FROM knowledge_chunks;"      -> 0
$ psql -c "SELECT count(*) FROM customers;"              -> 0
$ psql -c "SELECT count(*) FROM business_users;"         -> 0
```

**Result / Acceptance criteria:**
| Criterion | Status |
|---|---|
| Realistic 5+ turn conversation through the real endpoint, incl. greeting + pricing answered from real approved knowledge + booking intent | ✓ Pass — 6 real turns pasted above (10 total counting the memory-recall re-verification conversation) |
| Booking-intent turn does not claim a booking succeeded | ✓ Pass — explicitly says "I don't have the ability to book directly," only offers to connect |
| No-matching-knowledge case says it doesn't know / offers handoff, doesn't invent | ✓ Pass — explicit "I don't have info in the materials I was given," offered handoff |
| Cross-tenant: Business A cannot post into / read Business B's conversation via guessed `conversation_id` | ✓ Pass — real 404, zero messages written |
| Phase 7 memory (summary) actually used and correct across turns | ⚠ Pass, but only after a real bug was found and fixed during this exact test — see full account above; re-verified clean afterward |
| Secrets grep clean | ✓ Pass |
| Lint clean, migration reversible if applicable | ✓ Pass (ruff clean; no migration needed this phase) |

**Known issues / punted items:**
- **The incremental-summarization fact-dropping bug is fixed, but the underlying mechanism is still "ask an LLM to merge text and hope it listens to an instruction."** The fix (explicit "preserve every fact" instruction) worked on real re-testing, but there's no hard guarantee an LLM never drops something in a future case the ticket's tests didn't happen to cover — flagging as a real, inherent limitation of LLM-based summarization, not something a prompt tweak can categorically rule out. Worth a periodic real-world spot-check as the system matures, not a blocking gap.
- **Knowledge search has no hard similarity-score cutoff** — `search_chunks` always returns the top-k nearest chunks regardless of how irrelevant they are; the never-invent-information guardrail currently relies entirely on the LLM correctly judging low-similarity results as irrelevant (verified working in the real test above, similarity 0.289 was correctly ignored) rather than on a numeric threshold. Flagging as a design choice that worked in this test, not a certainty for every future query — a minimum-similarity filter would be a cheap, real hardening if this ever fails in practice.
- **No query reformulation** before the knowledge search — the raw customer message is embedded directly. Simpler and it worked in every real test here; a reformulation step (e.g. resolving "it" or "that" via conversation context before embedding) would help multi-turn queries where the current message alone is ambiguous, but wasn't needed for anything tested this phase.
- **Tool-calling scaffold exists but is provably inert** (`TOOL_REGISTRY == {}`, tested directly) — by design, this is exactly what Phase 8 was supposed to deliver; Phase 10+ is expected to register real tools without changing the orchestrator.
- No commit has been made yet — awaiting your confirmation of this verification output per working rule #6.

---

## Phase 9 — Human-Like Communication Layer

**Date:** 2026-09-04

**Required:**
- Revise Phase 8's system prompt to encode: brief non-clinical acknowledgment of frustration, no "as I mentioned earlier" on repeated questions, default conciseness, and language-matching (English / Nepali / Romanized Nepali / code-mixed) — with a few-shot block covering all four. A 10-15 case real-API eval set, full transcript pasted for review, with at least one documented before/after prompt iteration.

**Implemented:**

- **`app/services/conversation/intent.py`** — `_SYSTEM_PROMPT_TEMPLATE` rewritten. Added, as explicit numbered rules (not vague vibes): (4) frustration handling — brief natural acknowledgment then straight to being useful, with the master plan's own bad example ("I'm deeply sorry that you're experiencing this unfortunate inconvenience") quoted directly in the prompt as what NOT to sound like, plus "I understand how frustrating that is" flagged too (see the real "before" case below — that's exactly the boilerplate Phase 8's original prompt produced); (5) repeated-question handling — just answer again, never say "as I mentioned earlier" or "like I said before"; (6) language-matching — mirror English / Nepali (Devanagari) / Romanized Nepali / code-mixed Nepali-English rather than switching script or forcing English on the customer. Added a four-example few-shot block directly in the system prompt (normal Q&A, frustrated customer, repeated question, code-mixed) so the model has concrete calibration, not just abstract instructions.
- **A real, unrelated bug found and fixed while diagnosing a real test failure** (not hidden): the "booking" eval case hit a real `500`. `app/core/exceptions.py`'s catch-all `unhandled_exception_handler` logged nothing at all, so there was nothing to diagnose it with — fixed by adding `logger.exception(...)` there. That fix then **surfaced a second, more serious real bug**: the underlying `httpx.HTTPStatusError` (from the known Phase-6-documented intermittent Azure `DeploymentNotFound` flakiness, this time exhausting all 4 retry attempts on an `embed()` call) carries the full Azure endpoint URL in its exception message, and logging that exception via `logger.exception()` put the endpoint straight into the structured logs — a real secrets/endpoint leak, and exactly what this project's own acceptance criteria checks for on every phase. **Root-caused and fixed in `app/llm/azure_openai.py`**: `_post()` now raises a sanitized `RuntimeError(f"LLM provider request failed with HTTP {status}")` `from None` instead of calling `httpx`'s `raise_for_status()` — `from None` drops the chained original exception (and its URL) from the traceback entirely, not just the top-level message. Verified with a deterministic forced-404 test (mocking `httpx.post`, not waiting on real flakiness): confirmed the exception `str()` and the *full formatted traceback* (what `logger.exception()` actually emits) contain no endpoint string and no exception chaining. Re-confirmed via a full-history log grep after the fix: clean.
- **No new endpoints or models** — this phase was prompt-only plus the two bug fixes above, exactly as scoped ("unless you find a real structural gap while doing this" — both fixes qualify: one blocked diagnosing a real failure, the other was a real information leak).

**Before/after prompt iteration (documented, per the ticket's requirement) — frustrated customer, identical message, two fresh conversations, before and after the Phase 9 prompt rewrite:**

Customer message (both runs): *"This is the third time I have called about this! No one ever calls me back. I am so frustrated with this clinic."*

**BEFORE** (original Phase 8 prompt, no frustration-handling rule):
> "Hi Priya — I'm very sorry you've had to call multiple times and haven't heard back. I understand how frustrating that is. I can pass this to our team so someone reaches out — could you please confirm the best phone number to call, a good time to reach you, and whether you prefer phone or email? If you'd like, include a brief note about the reason for your call so we can prioritize it."

Judgment: **borderline/bad** — not the master plan's worst-case example, but "I understand how frustrating that is" is exactly the generic, boilerplate-sounding phrasing the master plan warns against. Reads like a script, not a person.

**AFTER** (Phase 9 prompt, frustration rule + few-shot example):
> "Ugh — that's frustrating, Priya. I'm sorry no one has called you back. I can connect you with a team member to sort this out: what's the best phone number and a good time for them to call, and a short note about the issue?"

Judgment: **good** — brief, natural acknowledgment ("Ugh — that's frustrating"), no boilerplate phrase, moves to being useful in the same breath.

**Full evaluation set (real `ChatProvider` output, real orchestrator endpoint, 14 cases / 16 total responses — pasted in full, not summarized, for your review):**

Business: "Maplewood Dental Care," tone "warm, concise, and professional," one real approved knowledge doc (cleaning $90; Mon–Fri 9am–5pm, closed weekends; 221 Maple St, Springfield, next to the public library). Customer: "Priya Sharma."

| # | Case | Customer message | Actual response | Judgment |
|---|------|-------------------|------------------|----------|
| 1 | Frustrated (before) | "This is the third time I have called about this!..." | *(see above)* | Borderline — boilerplate "I understand how frustrating that is" |
| 2 | Frustrated (after) | *(same message)* | *(see above)* | Good — natural, brief, no boilerplate |
| 3 | Plain greeting | "Hi there, how are you today?" | "Hi Priya — I'm doing well, thanks for asking! How can I help you today?" | Good — warm, brief, personalized |
| 4 | Normal Q&A (pricing) | "How much for a cleaning?" | "Hi Priya — a standard dental cleaning is $90. Would you like me to connect you with a team member to schedule or to answer any payment/insurance questions?" | Good — accurate (matches knowledge doc exactly), concise, offers a next step |
| 5 | Business hours | "Are you open on weekends?" | "We're open Monday through Friday, 9am to 5pm — we're closed on weekends." | Good — exactly matches the question, no fluff |
| 6 | Location | "Where are you located?" | "Hi Priya — We're located at 221 Maple St, Springfield, right next to the public library. We're open Monday–Friday, 9am to 5pm if you'd like to visit during business hours." | Good — accurate, adds relevant hours context without being asked |
| 7 | Emotionally loaded complaint | "I came in yesterday and the dentist was 45 minutes late, then rushed through my whole appointment. I am really unhappy about this." | "Ugh, that's frustrating — I'm sorry you had that experience, Priya. I can pass this along to our office manager to investigate and follow up. Would you like them to call or email? If so, please tell me the best number/email and a good time to reach you, and the dentist name or appointment time from yesterday if you have it." | Good — brief natural empathy, concrete escalation path, gathers exactly what's needed |
| 8a | Repeated question, turn 1 | "What are your hours?" | "Hi Priya — we're open Monday through Friday, 9:00 AM to 5:00 PM. We're closed on weekends. Would you like me to connect you with a team member to schedule an appointment?" | Good baseline |
| 8b | Repeated question, turn 2 (same conversation) | "Sorry, what were your hours again?" | "No worries — we're open Monday through Friday, 9:00 AM to 5:00 PM. We're closed on weekends. Would you like me to connect you with a team member to schedule an appointment?" | **Good — zero "as I mentioned"/"like I said before," just answers again naturally** |
| 9 | Nepali (Devanagari) | "नमस्ते, तपाईंको क्लिनिक कति बजे खुल्छ?" (What time does your clinic open?) | "नमस्ते Priya — हाम्रो क्लिनिक सोमबारदेखि शुक्रबार बिहान ९ बजे देखि साँझ ५ बजे सम्म खुल्छ। हामी शनिबार र आइतबार बन्द हुन्छौं।" | Good — coherent, grammatically correct Nepali, matches the real hours exactly |
| 10 | Romanized Nepali | "Namaste, malai appointment chahiyo, kaha jaane ho?" (Hi, I need an appointment, where do I go?) | "Namaste Priya — hami 221 Maple St, Springfield ma chhau (public library ko taha). Hamro ghanta: Monday–Friday 9:00am–5:00pm; weekend bandha. Ma ahile seedha appointment book garna sakdina, tara team sanga connect garna madat garchu — kun din/kun samaya ramro huncha ani kun sewa chahanu huncha (jasta cleaning, dantko dard, adi)? Best contact number pani dinuhola." | Good — matches Romanized style, accurate location/hours, AND correctly disclaims booking capability in the same language ("Ma ahile seedha appointment book garna sakdina") |
| 11 | Code-mixed Nepali/English | "Hello, mero tooth mai dukheko cha, kasari book garne appointment?" (my tooth hurts, how do I book an appointment?) | "Namaste Priya — dukhai bhako suni dukha lagyo. Ma ahile seedha appointment book garna sakdina, tara team sanga connect garna madat garna sakchhu. Ke yo tez/teekhe dukhai ho? Tapai lai kun din/samaya ramro huncha (hamro ghanta: Mon–Fri 9am–5pm)? Kripaya best phone number ra phone/text kun prefer garnuhunchha bhanera dinuhola, ma team lai contact garna bhannechu." | Good — mirrors the exact code-mixed style, brief empathy ("dukha lagyo" = sorry to hear), honest about booking, useful clarifying questions |
| 12 | Code-mixed + frustrated | "Yar, mero appointment cancel vayo re, ma ekdum frustrated chu!" (My appointment got cancelled, I'm so frustrated!) | "Priya — ugh, naramro lagyo, yo sunera. K tapaiko appointment ko date ra time bhannu saknu huncha? Tapaiko phone number ra best time dinuhos; ma team sanga connect garera yo kura chito milaauna bhanidinchu. (Ma ahile yo chat bata direct cancel/reschedule garna sakdina.)" | Good — the "Ugh" natural-acknowledgment pattern carried over correctly into code-mixed Nepali ("ugh, naramro lagyo" ≈ "ugh, that's bad"), AND still honestly states it can't cancel/reschedule directly |
| 13 | Curt/short message | "hours?" | "Hi Priya — we're open Monday through Friday, 9am to 5pm and closed on weekends. Would you like me to connect you with a team member to book an appointment?" | Good — answers the one-word question directly without over-explaining |
| 14 | Booking intent | "Can you book me in for next week, take two?" | "Hi Priya — I can help with that. I can't book appointments directly here, but I can pass your request to our team so they can schedule it. When you say "take two," do you mean two appointments for you or two people? Also what days/times next week work best (morning or afternoon), and what service do you need (e.g., standard cleaning — $90)? Finally, what's the best phone number or email for them to reach you?" | Good — honest about the booking limitation (consistent with Phase 8), asks smart clarifying questions including noticing the odd "take two" phrasing |
| 15 | Thank you / closing | "Thanks so much, bye!" | "You're welcome, Priya — take care! If you need anything else, just let us know." | Good — warm, brief, appropriate close |

**Explicit acceptance-criteria confirmations:**
- **Repeated-question case (#8b) does not say "as I mentioned" or similar** — confirmed by direct read of the actual response text above: *"No worries — we're open Monday through Friday..."*
- **Frustrated-customer case acknowledges briefly without being robotic/over-apologetic — actual line quoted**: *"Ugh — that's frustrating, Priya. I'm sorry no one has called you back."* (case #2) and *"Ugh, that's frustrating — I'm sorry you had that experience, Priya."* (case #7).
- **Nepali/Romanized Nepali/code-mixed cases get coherent, appropriately-languaged responses** — all three (#9, #10, #11) pasted in full above, each grammatically coherent and matching the customer's own script/style.

**Verification output:**

1. Lint: `docker compose exec backend ruff check .` → `All checks passed!` (re-run after the prompt rewrite and both bug fixes).
2. Full regression suite (unaffected by prompt-only changes; stubbed tests don't depend on prompt content):
```
$ docker compose exec backend python -m pytest tests/ -v
...
================== 41 passed, 1 skipped, 1 warning in 34.99s ===================
```
3. Deterministic leak-fix verification (forced 404 via mocked `httpx.post`, not real flakiness — so this is reproducible, not a one-off):
```
Exception str(): 'LLM provider request failed with HTTP 404'
Full formatted traceback contains endpoint? False
Full formatted traceback contains exception chaining ('direct cause'/'During handling')? False
```
4. Secrets check (after all real LLM calls in this phase, including the one that triggered the leak before it was fixed):
```
$ git ls-files | grep -E '\.env$'  -> none tracked
$ git grep -nE 'AZURE_OPENAI_(API_KEY|ENDPOINT)\s*=\s*[A-Za-z0-9]' -- . ':!backend/.env.example'  -> only placeholder lines matched
$ docker compose logs backend | grep -iE "api.key|samrat-g01|services\.ai\.azure"  -> clean (current, post-fix, post-recreate container logs)
```
Historical note, not hidden: an EARLIER log capture, taken before the `_post()` fix, DID contain the endpoint (that's how the leak was found — real output, not assumed). It was only ever in this local container's transient stdout, never in a committed file or sent anywhere external; the container was recreated after the fix and current logs are clean.
5. DB left clean after all real-API testing:
```
$ psql -c "SELECT count(*) FROM businesses;"            -> 0
$ psql -c "SELECT count(*) FROM conversations;"         -> 0
$ psql -c "SELECT count(*) FROM messages;"              -> 0
$ psql -c "SELECT count(*) FROM knowledge_documents;"   -> 0
$ psql -c "SELECT count(*) FROM knowledge_chunks;"      -> 0
$ psql -c "SELECT count(*) FROM customers;"              -> 0
$ psql -c "SELECT count(*) FROM business_users;"         -> 0
```

**Result / Acceptance criteria:**
| Criterion | Status |
|---|---|
| Full eval set transcript (10-15 real cases) pasted for review | ✓ Pass — 14 cases / 16 responses, full table above |
| At least one documented before/after iteration | ✓ Pass — frustration case, quoted in full both ways |
| Repeated-question case doesn't say "as I mentioned" | ✓ Pass — confirmed by direct read of the actual text |
| Frustrated-customer case briefly acknowledges, not robotic/over-apologetic, actual line quoted | ✓ Pass — two real quoted lines |
| At least one Nepali/Romanized/code-mixed case gets a coherent, appropriately-languaged response | ✓ Pass — all three pasted in full |
| Secrets grep clean | ✓ Pass, after fixing a real leak found during this exact phase's testing |
| Lint clean | ✓ Pass |

**Known issues / punted items:**
- **Tone quality is inherently subjective and was judged by me (the agent), not an automated assertion** — per the ticket's own framing ("tone is subjective... something I need to judge myself"), every judgment above is a read for you to confirm or overrule, not a claimed objective pass/fail. If any of the 16 responses read differently to you, that's exactly the kind of feedback this phase is designed to surface.
- **The eval set is not wired into the automated test suite** (no pytest assertions on tone) — deliberate, matches "not necessarily automated pass/fail" from the ticket. If a regression-detection mechanism is wanted later (e.g. a fixed eval set re-run on a schedule with manual review), that's a separate, explicit ask.
- **The Azure/Foundry intermittent `DeploymentNotFound` flakiness (documented since Phase 6) is still present and unfixed at the retry-budget level** — this phase only fixed the consequence (a secrets leak when it happens), not the underlying flakiness itself, which remains an operational characteristic of the user's Azure resource, not this codebase.
- **Post-review revision (same day, before commit):** manual review of this exact eval table surfaced two recurring tics the per-case "Good" judgments above missed because each case was read in isolation, not across the set: (1) the "Ugh" opener in cases #2, #7, #12 is the *same* acknowledgment reused verbatim every time — not natural variation, a new fixed phrase; (2) the customer's name opens nearly every response, including low-stakes ones (#5, #13), as a default sentence-starter rather than a deliberate choice. `_SYSTEM_PROMPT_TEMPLATE` (`app/services/conversation/intent.py`) revised: rule 4 now asks for varied, situation-specific frustration openers (no fixed phrase given as the model to copy) and a new rule 5 restricts name usage to first greeting / real warmth-or-empathy moments / after a gap. Re-run for real against representative frustration and short-message cases (before/after, real Azure calls): frustration openers came back genuinely different per case ("That's not okay...", "40 minutes with no update isn't okay...", "Anita — that's not right...") instead of a second fixed phrase, and the name was correctly dropped for the low-stakes "cool, address?" case while still appearing at real empathy moments. Language-matching, booking-honesty, and repeated-question handling untouched and not re-tested (no prompt text affecting them changed). This revision is folded into the code Phase 10 builds on; the case-by-case judgments in the table above should be read as superseded on these two points.
- No commit has been made yet — awaiting your confirmation of this verification output per working rule #6, same as Phase 10 below.

---

## Phase 10 — Booking Engine

**Date:** 2026-09-04

**Required:**
- Real, deterministic appointment booking: `get_available_slots` (pure business logic, no LLM), a real `book_appointment` tool wired into Phase 8's orchestrator, `POST /api/v1/appointments` (also the tool's underlying implementation) with full tenant/validity checks, orchestrator integration where the LLM's response reflects the REAL tool result (never its own claim), `GET /api/v1/appointments`/`GET /api/v1/appointments/{id}`. Explicit acceptance bar: slot-exclusion proof, a full real LLM-driven booking end-to-end, a hallucination-proof test, a **real concurrent** race-condition test, cross-tenant isolation, and validation tests — all with real pasted output.

**Implemented:**

- **`app/services/booking_service.py`** (new): `get_available_slots(db, *, business_id, service_id, staff_id=None, date_from, date_to)` — generates candidate slots on a fixed 15-minute grid (`SLOT_GRANULARITY_MINUTES`, `ponytail`-flagged as a deliberate simplification — real receptionists mostly work off one shared grid; add a per-business setting if a service ever genuinely needs a different one) within each date's real hours (a `BusinessHoursException` for that date wins over the weekly `BusinessHours` row; a day with neither an exception nor a non-closed weekly row yields zero slots), excluding anything overlapping an existing non-cancelled `Appointment` for the *resolved* staff resource, and excluding anything already in the past. **Staff resolution**: an explicit `staff_id` param wins, else the service's own fixed `staff_id`, else `None` — a `None`-resolved booking is treated as occupying **one shared per-business resource** (flagged below as a real, deliberate limitation given this schema has no staff-capacity-pool concept). `create_appointment(db, *, business_id, customer_id, service_id, staff_id, scheduled_at)` is the **only** function that writes an `Appointment` row: validates service/staff/customer exist and belong to the tenant, re-derives real availability via `get_available_slots` (never trusts a caller's claim — including the LLM's), and only then inserts — see the migration below for why that's still not sufficient by itself for the race guarantee. `get_appointment`/`list_appointments` (tenant-scoped, filterable by customer/status/date-range, timezone-aware against the real `Business.timezone`, not assumed UTC).
- **`app/schemas/appointment.py`** (new): `AppointmentCreate` (client sends `customer_id`, `service_id`, optional `staff_id`, `scheduled_at` — **not** `duration_minutes`; Python derives that from the service, the same "never trust the caller for a fact the system itself owns" rule applied one level further — plus a validator rejecting a timezone-naive `scheduled_at`), `AppointmentRead`.
- **`app/api/routes/appointments.py`** (new): `POST /appointments`, `GET /appointments` (filterable), `GET /appointments/{id}` — all tenant-scoped via `current_user.business_id`, same IDOR-safe 404 pattern as every prior phase. `POST /appointments` is literally what the booking tool calls — one implementation, two callers, not two copies of the validation logic.
- **Migration `c54ef41b197d_appointment_booking_race_protection.py`** — the actual race-condition guarantee, entirely at the DB level (app-level "check then insert," which is all `create_appointment` does on its own, is provably not enough under concurrency — see the real race test below):
  - `CREATE EXTENSION IF NOT EXISTS btree_gist` (ships with Postgres, no new dependency).
  - A small `IMMUTABLE` SQL wrapper function `appointment_range(scheduled_at, duration_minutes) RETURNS tstzrange` — needed because a GiST index expression must be `IMMUTABLE`, and the built-in `timestamptz + interval` operator is only `STABLE` (an `interval` can carry month/day components whose result depends on the session's `TimeZone` setting); safe to mark `IMMUTABLE` here specifically because every caller only ever passes a pure-minutes interval, which has no such ambiguity.
  - `EXCLUDE USING gist (business_id WITH =, COALESCE(staff_id, business_id) WITH =, appointment_range(...) WITH &&) WHERE (status <> 'CANCELLED')` on `appointments` — two overlapping appointments for the same `(business_id, resolved staff resource)` can never both commit, full stop, regardless of what any application code checked beforehand. Also `ix_appointments_business_id_scheduled_at` (autogenerate caught this one on its own).
  - Also reflected in `app/db/models/appointment.py` via SQLAlchemy's `ExcludeConstraint` (confirmed `alembic check` reports no drift between model and DB).
- **`app/services/conversation/booking_tool.py`** (new): `BookAppointmentTool(ConversationTool)`, registered against `ConversationIntent.BOOKING` in `TOOL_REGISTRY` (still empty for `RESCHEDULING`/`CANCELLATION` — out of this phase's scope, so Phase 8/9's honest-refusal behavior for those two is unchanged and still real). `run()` calls `booking_service.create_appointment` for real and turns the outcome into a structured `{success, appointment, message, alternative_slots}` dict — on failure, `alternative_slots` comes from a **fresh** `get_available_slots` call (never the LLM's guess) over the next 7 days.
- **`app/services/conversation/intent.py`** extended (not replaced): the same single LLM call now also extracts a `booking_request` (`{"service", "date", "time"}` or `null`) when intent is `booking` and the customer has given enough to act on — the prompt requires the extracted `service` to be copied verbatim from a real `Available services` list now injected into the user prompt (so Python's exact-match resolution has a real chance of succeeding), and relative dates are resolved against a real `Today's date` line computed from the business's own timezone. Critically, rule 9 tells the model: **whatever it writes in `response`, never say the appointment is booked/confirmed/scheduled** — the real confirmation or failure is composed separately (see orchestrator below), so even if the model ignores this instruction on a given call, the actual customer-facing text is architecturally incapable of reflecting anything the model wrote for that outcome.
- **`app/services/conversation/orchestrator.py`**: when intent is `booking` and a `booking_request` came back, Python — never the LLM — resolves the service by an **exact, case-insensitive** name match against the business's real services (no fuzzy matching: an ambiguous or unresolvable name is treated as "not enough info," not a guess) and parses `date`+`time` into a real business-timezone-aware `datetime`. Only if **both** resolve does the tool actually run; the customer-facing `response` for that turn is then **entirely overwritten** by `_format_booking_result()` — a plain deterministic Python string builder reading only the tool's real result dict (real service name, real formatted local date/time, real DB-generated booking ID on success; a real fresh alternatives list on failure). If resolution fails (bad service name, unparseable date/time) the orchestrator falls back to a short deterministic clarifying question rather than reusing the LLM's placeholder-style `response` text (which was written on the assumption the tool would run). This is what makes "the LLM must never be trusted to directly report booked" true **by construction**, not just by prompt instruction — nothing about the actual confirmation/failure sentence is LLM-authored.
- **Design decision, not a corner cut**: the ticket's "customer info" requirement is satisfied structurally, not by chat extraction — a `Conversation` already has a non-nullable `customer_id` pointing at a real, pre-registered `Customer` row (name always present, phone/email optional), so there was never a need to ask the LLM to extract contact details from free text; Python already has real, correct customer identity for every booking attempt.
- **`app/db/models/appointment.py`**: also added `Index("ix_appointments_business_id_scheduled_at", ...)` — every slot/list query filters by `business_id` + a `scheduled_at` range.

**Real bugs found and fixed during this phase's own testing (not hidden):**
1. **The `EXCLUDE` constraint's `WHERE (status <> 'cancelled')` failed against the real DB** (`invalid input value for enum appointment_status: "cancelled"`) — turned out SQLAlchemy's `Enum(AppointmentStatus)` stores the Python enum **member name** (`'CANCELLED'`) as the Postgres label, not `member.value` (`'cancelled'`), confirmed directly against `pg_enum` (and cross-checked against `message_sender_type`, same pattern) before fixing both the migration and the model to say `'CANCELLED'`. This only affects the two places writing raw SQL text — every other place in the codebase compares `AppointmentStatus.CANCELLED` as a Python value and SQLAlchemy's own bind-parameter handling does the translation transparently.
2. **The first version of the exclusion constraint failed to even create** (`functions in index expression must be marked IMMUTABLE`) — `timestamptz + interval` is only `STABLE`. Fixed with the `appointment_range()` `IMMUTABLE` SQL wrapper described above; verified safe given this table only ever adds a minutes-only interval (no month/day ambiguity), not just declared and hoped.
3. **The FastAPI `TestClient`-based version of the race-condition pytest test could not reliably force the true DB-level race** — a first attempt asserting `[201, 409]` failed with `[201, 422]`: the second in-process thread's request landed *after* the first had already committed, so it lost at `booking_service`'s own pre-check (a real, honest 422) rather than at the database's exclusion constraint (a real, honest 409). Both are correct "never both succeed" outcomes, so the pytest regression test now accepts either — but this is exactly why the **authoritative** race proof below was run as genuine concurrent HTTP requests against the actual live server, not through the in-process test harness.
4. **The running `backend` container didn't pick up the new `/appointments` routes** until restarted — `docker-compose.yml` bind-mounts `./backend:/app`, so file changes are live, but `app.main`'s router registration only runs once at process start. Restarted (`docker compose restart backend`) before any real verification below; a real, mundane deployment fact, not hidden.

**Verification output (all real, run 2026-09-04):**

1. **Migration, applied and reversed for real:**
```
$ docker compose exec backend alembic upgrade head
INFO  Running upgrade ea1b824909b1 -> c54ef41b197d, appointment booking race protection
$ docker compose exec backend alembic check
No new upgrade operations detected.
$ docker compose exec postgres psql -c "\d appointments" | grep exclu
"excl_appointments_no_overlap" EXCLUDE USING gist (business_id WITH =, COALESCE(staff_id, business_id) WITH =, appointment_range(scheduled_at, duration_minutes) WITH &&) WHERE (status <> 'CANCELLED'::appointment_status)
$ docker compose exec backend alembic downgrade -1   # constraint, function, extension-created-index, all gone; confirmed via pg_proc/\d
$ docker compose exec backend alembic upgrade head   # clean re-apply
$ docker compose exec backend alembic check
No new upgrade operations detected.
```
2. **`get_available_slots` exclusions — real data, real before/after (Demo Clinic, Mon–Sat 9am–5pm UTC, 30-min "Cleaning" service):**
```
BEFORE booking 10:00 slot -- is 10:00 in available slots? True
total slots that day (before): 31
booked 10:00 slot -> 201 50e5a6d3-01fc-4c93-ae30-04a8012082e1
AFTER booking 10:00 slot -- is 10:00 in available slots? False
is 10:30 (back-to-back, no overlap) still available? True
total slots that day (after): 28    # 09:45, 10:00, 10:15 all overlap the new 10:00-10:30 appointment — exactly 3 removed

--- holiday exclusion (Tuesday) ---
Tuesday slots BEFORE holiday exception: 31
created holiday exception -> 201 {'date': '2026-09-08', 'closed': True, ...}
Tuesday slots AFTER holiday exception: 0

--- outside-hours proof ---
earliest slot: 2026-09-07 09:00:00+00:00
latest slot:   2026-09-07 16:30:00+00:00   (+30 min duration ends exactly at close_time 17:00 — never later)
```
3. **Full real conversation, real LLM, real DB write, real confirmation (Willow Creek Family Dentistry, "Cleaning" $95/30min, customer "Jordan Lee"):**
```
POST /conversations/{id}/messages  {"content": "Hi, I'd like to book a cleaning next Monday at 2pm please."}
STATUS 201
{
  "intent": "booking",
  "response": "You're all set, Jordan Lee! I've booked Cleaning for Monday, September 7 at 2:00 PM (30 min). Your booking ID is f71c9c8c-9524-46c9-aa21-e7d21db5d406."
}
```
Real DB row, queried directly, id matches the response exactly:
```
f71c9c8c-9524-46c9-aa21-e7d21db5d406 | service_id=1cbd2f42... | staff_id=None | scheduled_at=2026-09-07 18:00:00+00:00 | 30 min | AppointmentStatus.CONFIRMED
```
(business timezone `America/New_York`; 2:00 PM EDT in September = 18:00 UTC — correct.) The LLM's own drafted placeholder text for this turn ("Let me check that.") never reached the customer — confirmed by direct string search, it's not in the response.
4. **Hallucination-proof test — real LLM, real second attempt at the identical now-taken slot, in the same real conversation:**
```
Customer: "Can I also get a cleaning next Monday at 2pm? Same time as before."
STATUS 201
{
  "intent": "booking",
  "response": "That time isn't available anymore, Jordan Lee — requested time is not available (outside business hours, on a closed date, in the past, or already booked). Here are some other openings for Cleaning: Monday, September 7 at 9:00 AM, Monday, September 7 at 9:15 AM, Monday, September 7 at 9:30 AM, Monday, September 7 at 9:45 AM, Monday, September 7 at 10:00 AM. Would any of those work?"
}
```
Real DB check immediately after: **still exactly 1** appointment row for this business (the original), the failed second attempt wrote nothing. A deterministic version of this exact scenario (stubbed LLM claiming "You're all set for 2pm Monday!" while the tool actually fails) is also now a permanent pytest regression test — see `test_booking_tool_failure_is_never_reported_as_success` below.
5. **Race condition — real concurrent HTTP requests against the live running server** (`threading.Barrier` releasing two real HTTP client threads at the same instant, hitting `http://localhost:8010`, not `TestClient`), run 3 times:
```
--- request 0 ---  201  {"id":"70335c79-...","scheduled_at":"2026-09-07T13:00:00Z",...}
--- request 1 ---  409  {"error":{"type":"conflict","message":"This slot was just booked by someone else — please choose another time."}}
statuses: [201, 409]
appointment rows in DB for this customer: 1
RACE TEST PASSED
```
(Repeated twice more with fresh businesses/slots: `[201, 409]` both times, 1 DB row both times — not a one-off.) This is the real proof; the in-process pytest version (`test_concurrent_booking_race_exactly_one_succeeds`) is a regression backstop that accepts `[201, 409]` or `[201, 422]` for the reason explained in bug #3 above.
6. **Cross-tenant — real rejection, real IDs, run against the live server:**
```
--- GET business A's real appointment with business B's real token ---
404 {"error":{"type":"not_found","message":"Appointment not found."}}
--- POST booking against business A's real service_id with business B's real token ---
404 {"error":{"type":"not_found","message":"Service not found."}}
```
7. **Validation — nonexistent service / outside hours / holiday, each cleanly rejected, none 500 (pytest, real DB, real HTTP via `TestClient`):**
```
test_create_appointment_rejects_nonexistent_service           PASSED  (404)
test_create_appointment_rejects_slot_outside_business_hours   PASSED  (422)
test_create_appointment_rejects_holiday                       PASSED  (422)
test_create_appointment_rejects_already_booked_slot           PASSED  (422 — sequential double-book, not a race; see #5 for the true race path)
```
8. **Secrets check** (after all real LLM calls and real HTTP traffic in this phase):
```
$ git ls-files | grep -E '\.env$'  -> none tracked
$ git grep -nE 'AZURE_OPENAI_(API_KEY|ENDPOINT)\s*=\s*[A-Za-z0-9]' -- . ':!backend/.env.example'  -> only placeholder lines matched
$ docker compose logs backend --tail=500 | grep -iE "api.key|services\.ai\.azure|correcthorse1"  -> clean, no match
```
9. Lint: `docker compose exec backend ruff check .` → `All checks passed!`
10. Full regression suite (10 new booking tests + 6 new conversation/booking-tool tests, all real DB, LLM stubbed for cost/determinism — real-LLM proof is the manually-run output above):
```
$ docker compose exec backend python -m pytest tests/ -v
...
================== 56 passed, 1 skipped, 1 warning in 46.51s ===================
```
11. DB left clean after all real testing (every test business deleted, cascades to everything hanging off it):
```
businesses=0  appointments=0  conversations=0  messages=0  customers=0  services=0  staff=0
```

**Result / Acceptance criteria:**
| Criterion | Status |
|---|---|
| `get_available_slots` excludes already-booked / outside-hours / holiday, real data pasted | ✓ Pass — §2 above |
| Full real conversation: LLM tool call → real DB write → real confirmation with actual booking ID | ✓ Pass — §3 above, DB row id matches response exactly |
| Hallucination-proof test: real tool failure, response honestly reflects it | ✓ Pass — §4 above (real) + permanent pytest regression test |
| Race condition: real concurrent requests, exactly one succeeds, DB shows one row | ✓ Pass — §5 above, run 3 times against the live server, not simulated |
| Cross-tenant: cannot book against / read another business's data, even by guessed ID | ✓ Pass — §6 above (real) + pytest coverage |
| Validation: nonexistent service / outside hours / holiday all cleanly rejected, never 500 | ✓ Pass — §7 above |
| Secrets grep clean | ✓ Pass |
| Lint clean, migration reversible | ✓ Pass — ruff clean; full `downgrade`/`upgrade` cycle clean, twice |

**Known issues / punted items:**
- **A booking with no staff resolved (no `staff_id` given and the service has none fixed) is treated as occupying a single shared per-business resource, not "any of N available staff."** This schema has no staff-capacity/service-eligibility model (a `Service` can pin exactly one `staff_id`, nothing more), so this is the conservative, correctness-preserving default: it can never double-book, but a multi-staff business with unassigned services could see fewer concurrently-bookable staff-less slots than physically exist. A real staff-capacity model would need new tables/relationships this ticket didn't ask for — flagging as a real, deliberate scope boundary, not an oversight.
- **The slot grid is a fixed 15 minutes for every business/service** (`SLOT_GRANULARITY_MINUTES`, `ponytail`-marked in `booking_service.py`) — simple and matched every real test here; a business needing a finer or coarser grid would need this to become configurable.
- **Service-name extraction requires an exact (case-insensitive) match against the real services list given to the LLM** — deliberately no fuzzy matching, so a genuinely ambiguous or misspelled name falls back to a clarifying question rather than a guess. Real-tested working correctly with "Cleaning" in both the success and the falls-back-to-clarify test.
- **`RESCHEDULING`/`CANCELLATION` still have no registered tool** — out of this phase's explicit scope; Phase 8/9's honest "I can't do that yet" behavior for those two intents is unchanged and still real (verified again by `test_tool_registry_has_only_booking_in_phase_10`).
- **The in-process `TestClient` race-condition pytest test cannot force the true DB-constraint path on demand** (see bug #3) — it's a legitimate regression backstop (never lets both succeed) but the authoritative proof of the actual exclusion-constraint race guarantee is the real-server run in §5, not the pytest suite.
- No commit has been made yet — awaiting your confirmation of this verification output per working rule #6.

---

## Phase 11 — Cancellation + Rescheduling

**Date:** 2026-09-04

**Required:**
- Real cancellation: `cancel_appointment`, wired into a `CancelAppointmentTool` on the Phase 8 orchestrator, `.../{id}/cancel` endpoint, releases the slot, tenant-scoped.
- Real rescheduling: `reschedule_appointment` (reuses Phase 10's `get_available_slots`/DB guarantee), `RescheduleAppointmentTool`, `.../{id}/reschedule` endpoint, an auditable trace of the move.
- A `Notification` row queued on both actions.
- Same architectural discipline as Phase 10: Python/DB is the source of truth, the LLM extracts intent + which appointment, never authors the confirmation text itself.
- Full acceptance bar: real booking→cancel and booking→reschedule conversations with DB proof, freed-slot-rebookable proof, hallucination-proof tests (nonexistent/already-cancelled/taken-slot), an ambiguous-appointment clarification test, cross-tenant rejection, and a real concurrent-HTTP reschedule race test.

**Implemented:**

- **`app/services/booking_service.py`** (extended, no new file): `cancel_appointment(db, *, business_id, appointment_id)` — tenant-scoped lookup (404 if missing/cross-tenant), rejects a non-cancellable status (`already {status} and cannot be cancelled`, 422) via a new `_CANCELLABLE_STATUSES = (PENDING, CONFIRMED)` guard, sets `status=CANCELLED`, and queues a `Notification`. No race-condition handling needed here: the Phase 10 exclusion constraint's `WHERE (status <> 'CANCELLED')` clause means moving a row *into* `CANCELLED` can never itself violate the constraint — the slot is provably free the instant this commits.
  `reschedule_appointment(db, *, business_id, appointment_id, new_scheduled_at)` — same tenant/status guard, then re-derives real availability via `get_available_slots` for the *new* time (422 if not actually open/free), then **updates the same `Appointment` row in place** (not cancel-old/create-new): `appointment.scheduled_at = new_scheduled_at`. **Design decision, not a corner cut**: the ticket allowed either approach ("your call"); update-in-place was chosen because (a) the booking ID never changes — zero linkage bookkeeping needed, satisfying "booking ID continuity" the simplest possible way, and (b) the Phase 10 exclusion constraint is enforced by Postgres on `UPDATE` exactly like it is on `INSERT` (confirmed empirically, see the real race test below), so the identical race-proof guarantee is reused with no new DB object and no new migration. An `AuditLog` row (`action="appointment_rescheduled"`, `resource_type="appointment"`, `resource_id=<appointment id>`, `result="moved_from=<old ISO timestamp>"`) is written in the same transaction — this is the "audit trail, not a silent mutation" the ticket asked for: the row itself shows what it moved *to*, the `AuditLog` entry shows what it moved *from* and when. Also queues a `Notification`. On an `IntegrityError` at commit (the real race path), rolls back and raises `ConflictError` — identical pattern to Phase 10's `create_appointment`.
  Both functions are the *only* code paths allowed to write these transitions, mirroring Phase 10's "one implementation, two callers" rule.
- **No new migration.** `Notification` and `AuditLog` already existed, untouched, since Phase 2 — this phase is the first to actually write to either. `alembic check` confirms zero model/DB drift; `alembic current` is unchanged at `c54ef41b197d (head)` (Phase 10's).
- **`app/schemas/appointment.py`**: added `AppointmentReschedule` (`scheduled_at`, tz-aware validator) alongside the existing `AppointmentCreate`; factored the shared "must be tz-aware" check into one `_require_tz_aware()` helper used by both validators instead of duplicating it.
- **`app/api/routes/appointments.py`**: `PATCH /appointments/{id}/cancel` and `PATCH /appointments/{id}/reschedule` (PATCH chosen over DELETE — a state transition, not a deletion, matching this codebase's existing PATCH-for-partial-mutation convention for `/business/me`, `/services/{id}`, `/staff/{id}`). No role restriction, matching the existing `/appointments` routes (any authenticated business user, not owner/admin-gated). Both are literally what the two new tools call — one implementation, two callers, exactly like Phase 10's `POST /appointments`.
- **`app/services/conversation/appointment_tools.py`** (new file): `CancelAppointmentTool` and `RescheduleAppointmentTool`, registered against `ConversationIntent.CANCELLATION`/`RESCHEDULING` in the Phase 8 `TOOL_REGISTRY` — the registry and `find_tool()` needed zero changes, exactly as Phase 8/10 designed. Both `run()` methods never trust their caller; they call the real `booking_service` functions and turn the outcome into a `{success, appointment, message}` dict, same shape discipline as Phase 10's `BookAppointmentTool`.
- **`app/services/conversation/intent.py`** extended (not replaced):
  - Rule 2 rewritten: it previously said the system "does NOT currently have the ability" to book/reschedule/cancel (true through Phase 9, false since Phase 10). Now says the system *can* really do all three, but the LLM must never claim success in `response` — the real result is composed separately. This is the same discipline Phase 10 already applied to booking, now stated once for all three.
  - Two new extraction rules (10, 11): for `cancellation`, extract `cancellation_request: {"appointment_id": "<id copied verbatim from the appointments list>"}` or `null` if the customer has 2+ active appointments and didn't say which (ask in `response` instead — never guess); for `rescheduling`, extract `reschedule_request: {"appointment_id", "date", "time"}` the same way, plus the new time (same date/time extraction rule as booking).
  - `_format_appointments` now includes each appointment's real `id` (with an explicit instruction never to read it aloud to the customer — it's for the model to copy, not speak) so the model has something to reference.
  - **A real bug found and fixed during this phase's own testing (not hidden)**: `_format_appointments` was printing `scheduled_at` as the raw UTC ISO string from the DB (`Appointment.scheduled_at.isoformat()`), not the business's local time. In the real ambiguous-cancellation test below, the model correctly *listed two distinct real appointments* (never guessed) but *misstated one's local time* (said "3:00 PM" for an appointment actually at 11:00 AM America/New_York, because it had no reliable way to convert a bare `+00:00` UTC string itself). Root-caused and fixed by threading the business's `ZoneInfo` through `_build_user_prompt` → `_format_appointments`, which now converts each appointment to real business-local time (`"%A, %B %-d at %-I:%M %p"`, the same format `_format_local` already uses for composing deterministic confirmations) before it ever reaches the prompt. Re-verified against a fresh real conversation after the fix — see the ambiguous-appointment transcript below, now correct (11:00 AM / 10:00 AM, matching the real DB rows exactly).
  - Two few-shot examples added (single active appointment → resolves and cancels; two active appointments, customer didn't specify → asks, `cancellation_request: null`) and the final JSON schema instruction extended with the two new optional fields.
  - `_parse_response`'s return type changed from a 3-tuple to a `ClassificationResult` `NamedTuple` (`intent, response, booking_request, cancellation_request, reschedule_request`) — a 5-tuple would have made every call site an unreadable positional unpack; `classify_and_respond`'s return type changed to match. All existing call sites (orchestrator, tests) updated to attribute access.
- **`app/services/conversation/orchestrator.py`**: `_resolve_known_appointment(context, appointment_id_str)` — exact-match resolution against this customer's own `context["appointments"]["active"] + ["recent_past"]` (both already tenant/customer-scoped by Phase 7). Deliberately includes `recent_past` (not just `active`): this is what lets the "already cancelled" hallucination-proof case actually reach the real tool and get an honest DB-sourced failure, instead of silently falling back to a generic clarifying question. Anything not in either list — ambiguous, or a hallucinated id — resolves to `None`, never a guess, mirroring Phase 10's `_resolve_service_by_name` discipline exactly. `_format_cancellation_result`/`_format_reschedule_result` are the only places a cancellation/reschedule confirmation or failure sentence is composed, off the tool's real result dict — identical discipline to `_format_booking_result`. `handle_incoming_message` gained two new `elif` branches (booking/cancellation/rescheduling are mutually exclusive per turn, matching one-intent-per-message): each resolves its request against real data, runs the matching tool only if fully resolved, and overwrites `response_text`; an unresolved-but-attempted request falls back to a fixed clarifying sentence (`_CANCELLATION_CLARIFY_FALLBACK`/`_RESCHEDULE_CLARIFY_FALLBACK`), never reusing the LLM's placeholder text — same pattern as Phase 10's `_BOOKING_CLARIFY_FALLBACK`. When the LLM itself set the request to `null` because it recognized ambiguity, its own clarifying `response` text is left standing untouched (no tool ran, nothing happened, so there's nothing for Python to override).

**Real bugs found and fixed during this phase's own testing (not hidden):**
1. **Appointment times shown to the LLM were in raw UTC, not business-local** — see the detailed root-cause account above under `intent.py`. Found via the real ambiguous-cancellation conversation (Verification §5 below), fixed, re-verified against a fresh real conversation with correct output.
2. **The running `backend` container needed a restart to pick up both the new `/cancel`/`/reschedule` routes and, separately, the timezone fix** — same mundane fact Phase 10 documented (bind-mount serves file changes live, but route registration and imported module code only load at process start). Restarted both times before the affected verification.

**Verification output (all real, run 2026-09-04):**

1. **Schema — no migration needed, confirmed no drift:**
```
$ docker compose exec backend alembic check
No new upgrade operations detected.
$ docker compose exec backend alembic current
c54ef41b197d (head)
```

2. **Real conversation: book → cancel, real DB proof, real Notification** (Willow Creek Family Dentistry, "Cleaning" $95/30min, customer "Jordan Lee"):
```
POST /conversations/{id}/messages {"content": "Hi, I'd like to book a cleaning next Monday at 2pm please."}
{"intent":"booking","response":"You're all set, Jordan Lee! I've booked Cleaning for Monday, September 7 at 2:00 PM (30 min). Your booking ID is 08ff099f-54b5-4c03-9781-04216b805fa8."}

POST /conversations/{id}/messages {"content": "Actually, I need to cancel that appointment."}
{"intent":"cancellation","response":"Done, Jordan Lee — your appointment on Monday, September 7 at 2:00 PM has been cancelled."}
```
Real DB row:
```
id                                   | status    | scheduled_at
08ff099f-54b5-4c03-9781-04216b805fa8 | CANCELLED | 2026-09-07 18:00:00+00
```
Real Notification row:
```
appointment_id                       | channel | status
08ff099f-54b5-4c03-9781-04216b805fa8 | email   | QUEUED
```

3. **Freed slot immediately rebooked by a DIFFERENT customer:**
```
POST /customers {"name":"Alex Rivera"} -> 201
POST /appointments {"customer_id":"<Alex>","service_id":"<Cleaning>","scheduled_at":"2026-09-07T18:00:00+00:00"}
HTTP/1.1 201 Created
{"id":"bdc86034-2bff-49c4-b9b3-bb6371d8f85e", ..., "scheduled_at":"2026-09-07T18:00:00Z", "status":"confirmed"}
```
The exact slot Jordan just freed, booked by a different real customer, immediately.

4. **Real conversation: book → reschedule, real DB proof (same booking ID), AuditLog, Notification:**
```
POST /conversations/{id}/messages {"content": "Actually can you book me a new cleaning for next Monday at 9am?"}
{"intent":"booking","response":"You're all set, Jordan Lee! I've booked Cleaning for Monday, September 7 at 9:00 AM (30 min). Your booking ID is d73b3223-8bbc-4395-abb1-c07b3663964c."}

POST /conversations/{id}/messages {"content": "Actually can we move that to 11am instead?"}
{"intent":"rescheduling","response":"All set, Jordan Lee — your appointment has been moved to Monday, September 7 at 11:00 AM."}
```
Real DB row — same id, moved:
```
id                                   | status    | scheduled_at
d73b3223-8bbc-4395-abb1-c07b3663964c | CONFIRMED | 2026-09-07 15:00:00+00   -- 11am EDT = 15:00 UTC, correct
```
Real AuditLog row (the "moved, not silently mutated" trace):
```
resource_id                          | action                   | result
d73b3223-8bbc-4395-abb1-c07b3663964c | appointment_rescheduled  | moved_from=2026-09-07T13:00:00+00:00   -- 9am EDT, the real original time
```
Real Notification row: `appointment_id=d73b3223... channel=email status=QUEUED`.

5. **Ambiguous-appointment test — real conversation, gave Jordan a second active appointment, asked to cancel without specifying which:**
```
POST /appointments (direct, Tuesday 10am local) -> 201 (Jordan's second active appointment)

POST /conversations/{id}/messages {"content": "Can you cancel my appointment?"}
```
**First real run (bug found, not hidden)**:
```
{"intent":"cancellation","response":"You have two upcoming appointments — a Cleaning on Monday, Sept 7 at 3:00 PM, and a Cleaning on Tuesday, Sept 8 at 2:00 PM. Which one would you like me to cancel?"}
```
Correctly asked for clarification (never guessed), but **3:00 PM / 2:00 PM are wrong** — the real appointments are at 11:00 AM and 10:00 AM local. Root-caused and fixed (see "real bugs" above), backend restarted, **same conversation re-run**:
```
{"intent":"cancellation","response":"You have two upcoming appointments — a Cleaning on Monday, September 7 at 11:00 AM, and a Cleaning on Tuesday, September 8 at 10:00 AM. Which one would you like me to cancel?"}
```
Correct this time, matching the real DB rows exactly. Neither appointment was touched (DB checked, both still `CONFIRMED`) while the question was pending. Follow-up, customer specifies:
```
POST /conversations/{id}/messages {"content": "The Tuesday one please."}
{"intent":"cancellation","response":"Done, Jordan Lee — your appointment on Tuesday, September 8 at 10:00 AM has been cancelled."}
```
Correctly resolved to the specified one only — the Monday 11am appointment confirmed still `CONFIRMED` afterward.

6. **Hallucination-proof tests — three real/direct cases, all honest, none fabricated:**
```
--- already-cancelled, via real chat (the model itself recalled from conversation memory that it was already cancelled, and offered the customer's actual remaining appointment instead of fabricating a new cancellation or an error) ---
POST /conversations/{id}/messages {"content": "Please cancel my 2pm appointment from earlier that we already talked about cancelling."}
{"intent":"cancellation","response":"That 2:00 PM appointment was already cancelled earlier. You currently have a Cleaning on Monday, September 7 at 11:00 AM — would you like me to cancel that one instead?"}
(Separately, the deterministic tool-failure path for this exact scenario — LLM falsely claims success while targeting an already-cancelled appointment id — is covered by test_cancellation_hallucination_proof_already_cancelled, a permanent pytest regression test, since the real LLM in this run resolved it via memory before ever emitting a cancellation_request.)

--- reschedule into a slot already taken by another real customer (Alex Rivera's real 2pm booking), via real chat ---
POST /conversations/{id}/messages {"content": "Can you move my 11am appointment to 2pm instead?"}
{"intent":"rescheduling","response":"I couldn't reschedule that, Jordan Lee — requested time is not available (outside business hours, on a closed date, in the past, or already booked)."}
DB confirmed: Jordan's appointment still at 15:00 UTC (11am), never moved.

--- nonexistent appointment id, direct API (guessed random UUID) ---
$ curl -i -X PATCH /appointments/<random-uuid>/cancel      -> 404 {"error":{"type":"not_found","message":"Appointment not found."}}
$ curl -i -X PATCH /appointments/<random-uuid>/reschedule   -> 404 {"error":{"type":"not_found","message":"Appointment not found."}}
```

7. **Cross-tenant test — real rejection, real appointment id, real second business:**
```
$ curl -i -X PATCH /appointments/d73b3223.../cancel      -H "Authorization: Bearer <Business B token>"
HTTP/1.1 404 Not Found  {"error":{"type":"not_found","message":"Appointment not found."}}
$ curl -i -X PATCH /appointments/d73b3223.../reschedule   -H "Authorization: Bearer <Business B token>"
HTTP/1.1 404 Not Found  {"error":{"type":"not_found","message":"Appointment not found."}}
```
DB confirmed afterward: Business A's appointment untouched (`CONFIRMED`, `2026-09-07 15:00:00+00`, unchanged).

8. **Race condition — real concurrent HTTP requests against the live running server** (two DIFFERENT appointments, `threading.Barrier`-released real HTTP client threads, both PATCHing `/reschedule` to the identical target slot at the same instant, hitting `http://localhost:8010`, not `TestClient`), run 3 times with fresh appointments each time:
```
run 1: statuses: [200, 422]   -- loser lost at the pre-check (both honest "not available" outcomes)
run 2: statuses: [200, 409]   -- loser lost at the real DB exclusion constraint (the authoritative guarantee)
run 3: statuses: [200, 409]   -- same
```
Real DB check after run 1: exactly 1 appointment row occupying the contested slot; the loser's row confirmed still at its original, untouched time. This is the same never-both-succeed proof as Phase 10's booking race test, now confirmed for `UPDATE` (reschedule) as well as `INSERT` (booking) — the identical `excl_appointments_no_overlap` constraint enforces both.

9. **Secrets check** (after all real LLM calls and real HTTP traffic in this phase):
```
$ git ls-files | grep -E '\.env$'  -> none tracked
$ git grep -nE 'AZURE_OPENAI_(API_KEY|ENDPOINT)\s*=\s*[A-Za-z0-9]' -- . ':!backend/.env.example'  -> clean, only placeholders matched
$ docker compose logs backend --tail=500 | grep -iE "api.key|services\.ai\.azure|correcthorse1"  -> clean, no match
```

10. Lint: `docker compose exec backend ruff check .` → `All checks passed!`

11. Full regression suite (9 new `test_cancel_reschedule.py` tests covering cancel/reschedule/race at the HTTP+DB level, 5 new `test_conversation.py` tool-wiring tests with stubbed LLM, 4 new `_parse_response` extraction tests, `test_tool_registry_has_only_booking_in_phase_10` renamed/extended to assert all three tools are now registered — real-LLM proof is the manually-run output above):
```
$ docker compose exec backend python -m pytest tests/ -v
...
================== 74 passed, 1 skipped, 1 warning in 61.87s ===================
```

12. DB left clean after all real testing (both test businesses deleted, cascades to everything hanging off them):
```
businesses=0  appointments=0  notifications=0  audit_logs=0  conversations=0  customers=0
```

**Result / Acceptance criteria:**
| Criterion | Status |
|---|---|
| Real conversation: book → cancel, real DB row `status=cancelled`, real Notification row | ✓ Pass — §2 above |
| Freed slot immediately bookable by a different customer, real proof | ✓ Pass — §3 above |
| Real conversation: book → reschedule, DB proof (same booking ID, new time), AuditLog trace | ✓ Pass — §4 above |
| Hallucination-proof: nonexistent / already-cancelled / reschedule-into-taken-slot, all honest | ✓ Pass — §6 above (real for 2 of 3 via chat, real+pytest-permanent for the third) |
| Ambiguous-appointment: 2+ active appointments, agent asks rather than guesses | ✓ Pass, after a real bug (wrong local time shown) found and fixed — §5 above |
| Cross-tenant: Business A cannot cancel/reschedule Business B's appointment, even by guessed ID | ✓ Pass — §7 above |
| Race condition: real concurrent requests, exactly one succeeds, run 3 times | ✓ Pass — §8 above; **superseded by the post-review fix below** — after the fix, re-run 5 times, loser is `409` every time, never `422` |
| Secrets grep clean | ✓ Pass |
| Lint clean, migration reversible if applicable | ✓ Pass — ruff clean; no migration this phase (nothing to reverse) |

**Known issues / punted items:**
- **Post-review revision (same day, before commit): the race test's `[200, 422]` vs `[200, 409]` inconsistency across runs was investigated and fixed.** You asked why run 1 of the race test produced `[200, 422]` while runs 2-3 produced `[200, 409]`, and whether that was two different failure reasons or the same conflict surfacing inconsistently.
  - **Root cause, confirmed by reading the code**: `reschedule_appointment`'s pre-check called `get_available_slots` and rejected with a 422 (`UnprocessableEntityError`) if `new_scheduled_at not in available` — and `available` conflated two unrelated conditions into one boolean: "outside business hours / closed day / in the past" AND "overlaps an existing non-cancelled appointment." Under concurrency, whichever thread's `SELECT` (inside `get_available_slots`) happened to run *before* the other thread's `UPDATE` committed would see the slot as free, pass the pre-check, and only then lose at the real `IntegrityError` → `409`. Whichever thread's `SELECT` happened to run *after* the winner's commit would see the slot as already taken *in its own pre-check* and fail with `422` instead — never even reaching the `UPDATE`. **This confirmed it was the same underlying conflict (two requests for the same slot), surfacing as two different HTTP status codes purely due to timing** — not two different failure reasons.
  - **DB guarantee re-confirmed intact in all 3 original runs**: exactly one row occupied the contested slot every time (already shown in §8's original run 1 DB check) — the inconsistency was in the HTTP response shape only, never in correctness of the underlying data.
  - **Fix, `app/services/booking_service.py`**: `get_available_slots` gained an internal `_ignore_conflicts: bool = False` parameter that skips the existing-appointment overlap filter entirely, leaving only the structural checks (hours/closed/past). `reschedule_appointment`'s pre-check now calls it with `_ignore_conflicts=True` — it only ever raises 422 for a genuinely structurally-invalid slot. Any "already booked" case — racy or not — now has no code path to a 422 at all; it can only be caught by the real DB exclusion constraint at commit time, which always raises the same `ConflictError` → `409`. This is also a semantic improvement independent of the race: a slot conflicting with another real appointment is a resource conflict (409), not a client input error (422), even with zero concurrency involved.
  - **Test fallout, all intentional and updated**: `test_reschedule_appointment_rejects_unavailable_new_slot` renamed to `test_reschedule_appointment_rejects_already_taken_slot_with_409` and its expected status changed `422` → `409`; a new `test_reschedule_appointment_rejects_outside_business_hours_with_422` was added to keep the genuinely-422 (structural) path covered now that it's a separate code path from the conflict case; `test_concurrent_reschedule_race_exactly_one_succeeds`'s assertion tightened from `statuses[1] in (409, 422)` to `statuses[1] == 409` (it can no longer be anything else). Full suite re-run clean: `75 passed, 1 skipped`.
  - **Real concurrent-HTTP re-verification, 5 fresh runs against the live server** (fresh business, two distinct real appointments per run, `threading.Barrier`-released, real HTTP via `urllib`, distinct target day each run to avoid cross-run collisions):
```
run 1: request 0 -> 409 {"error":{"type":"conflict","message":"This slot was just booked by someone else — please choose another time."}}
       request 1 -> 200 {"id":"04d6f0b0-...","scheduled_at":"2026-09-08T15:00:00Z",...}
       statuses: [200, 409]
run 2: statuses: [200, 409]
run 3: statuses: [200, 409]
run 4: statuses: [200, 409]
run 5: statuses: [200, 409]
```
  Direct DB check after all 5 runs — exactly one non-cancelled row per contested slot, every time:
```
      scheduled_at      | count
------------------------+-------
 2026-09-08 15:00:00+00 |     1
 2026-09-09 15:00:00+00 |     1
 2026-09-10 15:00:00+00 |     1
 2026-09-11 15:00:00+00 |     1
 2026-09-12 15:00:00+00 |     1
```
  Re-confirmed clean: lint (`ruff check .` → `All checks passed!`), secrets grep, `alembic check` (no migration touched — this was a pure application-logic fix, no schema change), test business deleted afterward.
- **The real-conversation "already cancelled" hallucination case was resolved by the LLM's own conversation memory rather than by the deterministic tool-failure path** — the model correctly recalled (from Phase 7 summary/recent-messages context) that the appointment was already cancelled and never even emitted a `cancellation_request` for it, so the real chat run never exercised `CancelAppointmentTool` returning a failure for this specific scenario. The deterministic path itself (LLM emits a request pointing at an already-cancelled appointment id, tool runs, honestly reports failure) is real and is covered by a real DB-backed permanent pytest test (`test_cancellation_hallucination_proof_already_cancelled`, stubbed LLM only to force the scenario deterministically) — flagging the distinction rather than overstating what the manual real-LLM run happened to hit.
- **Update-in-place rescheduling means there is no separate "old" `Appointment` row** — the full history of a reschedule lives in `AuditLog` (one row per move, `resource_id` + `moved_from=<timestamp>`), not as a queryable chain of appointment rows. This was a deliberate simplicity choice (see "Design decision" above); if a future phase needs to list every historical time a given appointment was ever scheduled for (not just the latest move), that would need to either query `AuditLog` by `resource_id` or move to a cancel-old/create-new model instead.
- **No RBAC restriction on cancel/reschedule** — any authenticated business user (owner/admin/staff) can cancel or reschedule any appointment in their business, matching the existing unrestricted `POST/GET /appointments` convention from Phase 10 (as opposed to the owner/admin-only gate on business-config writes from Phase 4). Flagging as a deliberate consistency choice, not an oversight.
- Carried over from Phase 10, still real and still open: no staff-capacity model (a booking with no resolved staff occupies a single shared per-business resource), fixed 15-minute slot grid, exact-match-only service-name resolution.
- No commit has been made yet — awaiting your confirmation of this verification output per working rule #6.

---

## Phase 12 — Family / Group Bookings

**Date:** 2026-09-04

**Required:** Support one customer booking appointments for multiple people (self + spouse + child, etc.) in one conversational flow, reusing the Phase 2 `AppointmentParticipant` model and the Phase 10 booking engine (`get_available_slots`, the EXCLUDE constraint, the deterministic Python-composed response pattern) — not a parallel booking path. Extract multiple people from one message, run every person's booking through the same real Python validation as Phase 10 (no shortcuts), honestly report partial outcomes, support an explicit "all 3 or none" mode, and let `GET /appointments` show/filter which appointments were booked together.

**Design decision — explicit, not defaulted silently:**

The ticket asked to choose between (a) N separate `Appointment` rows per group booking, or (b) one `Appointment` row with N `AppointmentParticipant` children, and named (a) as the likely better fit. Reading the actual Phase 10 schema before deciding surfaced a real constraint that makes this **neither purely (a) nor purely (b) — a hybrid, derived from how the EXCLUDE constraint actually behaves, not guessed:**

`Appointment`'s exclusion constraint (`excl_appointments_no_overlap`, Phase 10) keys on `(business_id, COALESCE(staff_id, business_id), time range)`. A staff-less service — the common case, since this schema has no staff-capacity model — is treated as occupying **one shared per-business resource**. If "book us all in for a cleaning at 2pm" became **three separate** `Appointment` rows all at 2pm with no `staff_id`, the second and third would collide with the first at the DB level and get rejected as a **false double-booking** — the exact race-protection machinery Phase 10 built would actively break the most common group-booking case. Conversely, forcing **everyone** into one shared `Appointment` row (pure model (b)) can't represent "I want a consultation, my husband wants a cleaning" — one `Appointment` row has exactly one `service_id`/`scheduled_at`, so two different services at two different times structurally cannot live on one row.

**Decision:** cluster the group's requested people by their resolved `(service_id, staff_id, scheduled_at)`. People who land on the **identical** slot share **one** `Appointment` row plus one `AppointmentParticipant` row each (this is what makes the family-cleaning-at-one-time case work without tripping the exclusion constraint). People whose service and/or time differ from everyone else each get their **own** `Appointment` row (this is what makes the different-service-per-person case possible at all — Appointment can't split into two services). Every `Appointment` row written from one group-booking request — whether a shared-slot cluster or a solo one — shares a new `group_booking_id` (Phase 12's only schema change) so the group is queryable/filterable afterward. `AppointmentParticipant` is attached uniformly (even to a "cluster of one") so every group-booking-derived appointment records who it's actually for, distinguishing it from an ordinary Phase-10 solo booking (which has no participant row). This is the smallest model that is actually *correct* against the real EXCLUDE constraint, not just the smallest model that compiles — reusing `AppointmentParticipant` exactly as it already existed, no schema change to it.

**Default atomicity — explicit, not defaulted silently:** partial success. If 2 of 3 people's slots are available, those 2 are booked for real and the third is honestly reported as failed with the real reason — this is the default because most real-world group-booking requests ("get us all in for cleanings") don't actually require lockstep failure, and it's the more useful default for a receptionist to apply. All-or-nothing is opt-in: the LLM sets it only when the customer explicitly says something like "only if you can fit us all in together" / "all or none." Both paths are implemented for real (see below), not one faked on top of the other.

**Implemented:**

- **Migration `e165f433cce9_group_booking_id.py`**: adds `appointments.group_booking_id` (nullable `UUID`, indexed), NULL for every ordinary Phase 10/11 solo booking. Clean autogenerate, no hand-fixes needed this time. `alembic upgrade head` / `downgrade -1` / `upgrade head` / `alembic check` all verified clean (Verification §1).
- **`app/db/models/appointment.py`**: the one new column above. No change to the exclusion constraint, no change to `AppointmentParticipant` (used exactly as it already existed since Phase 2).
- **`app/services/booking_service.py`** (extended, no new file):
  - `create_appointment` gained two internal (not route-exposed) parameters: `group_booking_id` (stamped onto the row, opaque to this function) and `_commit: bool = True` — when `False`, it `db.flush()`s instead of `db.commit()`s (Postgres checks the exclusion constraint on flush, not only at commit, so the race guarantee is unchanged) so a batch of appointments can be written inside one caller-controlled transaction for real all-or-nothing atomicity. Zero behavior change for every existing Phase 10/11 caller (both default to their old behavior).
  - `_cluster_group_people(people)`: pure grouping by `(service_id, staff_id, scheduled_at)`, order-preserving. This is the hybrid model above, expressed as code.
  - `create_group_appointments(db, *, business_id, customer_id, people, all_or_nothing)`: validates `customer_id` once up front (real 404 if it doesn't belong to this tenant — the same customer backs every person in the group, per Phase 10's "Conversation.customer_id is the real account holder" design), clusters, then dispatches to:
    - `_create_group_partial` (default): books each cluster independently via the real `create_appointment` (own commit, own re-validation, no shortcuts) — a failure on one cluster never blocks or rolls back another. `AppointmentParticipant` rows are attached right after each successful cluster.
    - `_create_group_all_or_nothing`: **Pass 1** — a real, fresh `get_available_slots` check per cluster (read-only, no writes) so every person's outcome can be reported honestly even before anything is attempted; if any cluster fails, **nothing is written**, full stop. **Pass 2** (only if Pass 1 was clean) — writes every cluster via `create_appointment(..., _commit=False)` inside one transaction; if a genuine race steals a slot between the two passes, the `IntegrityError` triggers a full `db.rollback()` and every person is reported as not booked — never a partial write. Only on a clean Pass 2 are `AppointmentParticipant` rows attached and one `db.commit()` made for the whole group.
  - `list_appointments` gained an optional `group_booking_id` filter (pure passthrough).
  - `_fresh_alternatives` (private, mirrors `BookAppointmentTool._alternatives`'s logic at the service layer since group clustering lives here) offers real alternative slots for a cluster that failed on its own merits — not for a cluster that was fine but wasn't written because a sibling in an all-or-nothing group failed (that gets an honest explanation instead, since offering alternatives for a slot that was never the problem would be misleading).
- **`app/services/conversation/booking_tool.py`**: `BookAppointmentTool` gained `run_group()` — the ticket's "extend the booking tool" option, chosen over a new class since the existing tool already owns the single-booking write path and group booking is the same responsibility at N. It does nothing but forward to `booking_service.create_group_appointments` — no parallel validation path exists.
- **`app/services/conversation/intent.py`**: new rule 12 + `group_booking_request` field (`{"people": [{"label","service","date","time"}], "all_or_nothing": bool}`) alongside the existing singular `booking_request` — the LLM is told to use one or the other, never both, and to leave `group_booking_request` null (asking a clarifying question instead) unless **every** person's service/date/time is resolved, mirroring rule 9's existing all-or-null discipline exactly. `all_or_nothing` defaults false; the LLM is told to set it true only on an explicit customer statement to that effect. Three new few-shot examples (same-slot family booking, different-service-per-person, missing-info-must-ask). `ClassificationResult` gained a `group_booking_request` field (6-tuple now); every existing call site already used attribute access (Phase 11's `NamedTuple` refactor), so this was a one-line addition per site, not a rewrite.
- **`app/services/conversation/orchestrator.py`**: a new dispatch branch (checked before the existing singular-booking branch) resolves each person's service name and date/time via the *exact same* `_resolve_service_by_name`/`_resolve_booking_datetime` helpers Phase 10 already uses — if **any** person's info doesn't resolve, the whole group falls back to a fixed clarifying sentence (`_GROUP_BOOKING_CLARIFY_FALLBACK`), never booking only the resolvable subset and never reusing the LLM's placeholder text. `_format_group_booking_result()` is the only place a group-booking confirmation/failure sentence is composed — deterministic Python, reading only the tool's real per-cluster result dicts (never LLM narration), same discipline as `_format_booking_result`/`_format_cancellation_result`/`_format_reschedule_result`. It explicitly distinguishes three real outcomes in the intro line: everyone booked, all-or-nothing failed (nobody booked), or a genuine mixed partial outcome — and always lists every person's real, individual result (never collapses or drops one).
- **`app/schemas/appointment.py` / `app/api/routes/appointments.py`**: `AppointmentRead` gained `group_booking_id`; `GET /appointments` gained an optional `group_booking_id` query filter — with `group_booking_id` on every row already in the response, a client can group appointments client-side too, without a second lookup.
- **No new HTTP endpoint for group booking itself** — deliberately scoped out. The ticket's explicit ask was (1) LLM extraction via the tool, (2) real validation, (3) an atomicity option, (4) `GET` grouping — none of which requires a dedicated `POST` route, and `create_group_appointments` is fully exercisable and tested directly at the service layer (same pattern Phase 10 already used for `get_available_slots` in `test_booking.py`). Flagging in case a direct non-conversational group-booking API is wanted later; it would be a thin route calling the exact same service function.

**Real bugs found and fixed during this phase's own testing (not hidden):**
1. **Doubled "not booked" wording** in the all-or-nothing "your slot was fine but a sibling's wasn't" message — `_format_group_booking_result`'s `describe()` already prefixes failures with "not booked — ", and the service-layer message also started with "Not booked — ", producing "not booked — not booked — you asked to book everyone together...". Found in the real all-or-nothing failure transcript below (first run), fixed by dropping the redundant prefix from the two service-layer messages, re-verified on a second real run with clean wording.

**Verification output (all real, run 2026-09-04):**

1. **Migration, applied and reversed for real:**
```
$ docker compose exec backend alembic revision --autogenerate -m "group booking id"
INFO  [alembic.autogenerate.compare] Detected added column 'appointments.group_booking_id'
INFO  [alembic.autogenerate.compare] Detected added index ''ix_appointments_group_booking_id'' on '('group_booking_id',)'
$ docker compose exec backend alembic upgrade head
INFO  Running upgrade c54ef41b197d -> e165f433cce9, group booking id
$ docker compose exec backend alembic check
No new upgrade operations detected.
$ docker compose exec backend alembic downgrade -1   # column + index dropped
$ docker compose exec backend alembic upgrade head   # clean re-apply
$ docker compose exec backend alembic check
No new upgrade operations detected.
```

2. **Real conversation: 3 people, same service/time — real LLM, real DB write, correct participant attribution** (Willow Creek Family Dentistry, "Cleaning" $95/30min, customer "Jordan Lee", business tz America/New_York):
```
POST /conversations/{id}/messages
{"content": "Hi, can you book me, my wife, and my daughter in for cleanings next Monday at 2pm please?"}
STATUS 201
{
  "intent": "booking",
  "response": "You're all set, Jordan Lee! Here's what I booked: Jordan Lee and my wife and my daughter: Cleaning on Monday, September 7 at 2:00 PM (30 min, booking ID 83df2d34-36bf-428e-872f-3364b5134efc)."
}
```
Real DB — ONE Appointment row, real group_booking_id, three real AppointmentParticipant rows correctly attributed:
```
$ psql -c "SELECT id, group_booking_id, service_id, scheduled_at, status FROM appointments WHERE id='83df2d34-...';"
id=83df2d34-36bf-428e-872f-3364b5134efc | group_booking_id=ea9d5f3e-0a61-411e-b179-05493cb1b8cb | scheduled_at=2026-09-07 18:00:00+00 | CONFIRMED
(18:00 UTC = 2:00 PM EDT — correct)

$ psql -c "SELECT appointment_id, name FROM appointment_participants WHERE appointment_id='83df2d34-...';"
 appointment_id                        | name
 83df2d34-36bf-428e-872f-3364b5134efc  | Jordan Lee
 83df2d34-36bf-428e-872f-3364b5134efc  | my wife
 83df2d34-36bf-428e-872f-3364b5134efc  | my daughter
```

3. **Real conversation: partial success — one of two people's slot already taken** (pre-booked a Consultation slot for a different real customer at Tuesday 10am local first):
```
POST /conversations/{id}/messages
{"content": "Can you book me for a cleaning next Tuesday at 11am, and my husband for a consultation next Tuesday at 10am?"}
STATUS 201
{
  "intent": "booking",
  "response": "Here's where things stand, Jordan Lee — some went through, some didn't: the customer: Cleaning on Tuesday, September 8 at 11:00 AM (30 min, booking ID eac53eec-255d-4170-82b4-f1fd8bf98925); my husband: not booked — requested time is not available (outside business hours, on a closed date, in the past, or already booked)."
}
```
Real DB proof — only the successful booking exists, the failed one wrote nothing:
```
$ psql -c "SELECT id, group_booking_id, service_id, scheduled_at, status FROM appointments WHERE customer_id='f7d94f2f-...' ORDER BY created_at;"
 83df2d34-... | ea9d5f3e-... | Cleaning      | 2026-09-07 18:00:00+00 | CONFIRMED   (from step 2)
 eac53eec-... | 3e2597c0-... | Cleaning      | 2026-09-08 15:00:00+00 | CONFIRMED   (the new success)
(2 rows — no Consultation row for "my husband" anywhere)
```

4. **Real conversation: different service per person, both succeed, tied by group_booking_id** (Consultation for the customer, Cleaning for "my son", different times):
```
POST /conversations/{id}/messages
{"content": "Book me a consultation next Wednesday at 9am, and my son a cleaning next Wednesday at 9:30am please."}
STATUS 201
{
  "intent": "booking",
  "response": "You're all set, Jordan Lee! Here's what I booked: the customer: Consultation on Wednesday, September 9 at 9:00 AM (20 min, booking ID c7a6d1e6-c218-4acd-8f26-86fe82944dca); my son: Cleaning on Wednesday, September 9 at 9:30 AM (30 min, booking ID 48634359-1ffe-48a6-9e40-d44ae56073ce)."
}
```
Real DB — two separate Appointment rows, different services/times, ONE shared group_booking_id:
```
 id=c7a6d1e6-... | group_booking_id=573146e3-94cb-44c8-b7b1-a9b3c93d1013 | Consultation | 2026-09-09 13:00:00+00 | participant="the customer"
 id=48634359-... | group_booking_id=573146e3-94cb-44c8-b7b1-a9b3c93d1013 | Cleaning     | 2026-09-09 13:30:00+00 | participant="my son"
```
And `GET /appointments?group_booking_id=573146e3-...` returns exactly these two real rows (verified — see §7 below).

5. **Real conversation: all-or-nothing, one slot unavailable — nothing booked** (pre-booked a Consultation slot for a different real customer at Thursday 4pm local first; re-run after the wording bug fix in "Real bugs" above):
```
POST /conversations/{id}/messages
{"content": "Please book me a cleaning next Thursday at 1pm and my wife a consultation next Thursday at 4pm — but only if you can get us BOTH in, all or nothing, don't book just one of us."}
STATUS 201
{
  "intent": "booking",
  "response": "I wasn't able to get everyone in, Jordan Lee, and since you wanted it all together, I didn't book anyone yet: the customer: not booked — you asked to book everyone together, and not every slot was available; my wife: not booked — requested time is not available (outside business hours, on a closed date, in the past, or already booked)."
}
```
Real DB check immediately after: **zero** rows for either requested Thursday slot — confirmed nothing was written, not even the person whose slot was actually free.

6. **Real conversation: all-or-nothing, both slots free — both booked, same group_booking_id:**
```
POST /conversations/{id}/messages
{"content": "Ok forget that, please book me a cleaning next Friday at 1pm and my wife a consultation next Friday at 2pm — all or nothing please, both or neither."}
STATUS 201
{
  "intent": "booking",
  "response": "You're all set, Jordan Lee! Here's what I booked: the customer: Cleaning on Friday, September 4 at 1:00 PM (30 min, booking ID fb7892b0-d232-46aa-84de-a6ca93ad4703); my wife: Consultation on Friday, September 4 at 2:00 PM (20 min, booking ID 9acdefa3-f5d4-41ea-96c8-9c893d10916a)."
}
```
Real DB: both rows exist, both share group_booking_id `21d31e18-1dfe-4fbe-8711-f784d81d9bbc`.

7. **`GET /appointments?group_booking_id=` filtering, real HTTP:**
```
$ curl .../appointments?group_booking_id=573146e3-94cb-44c8-b7b1-a9b3c93d1013 -H "Authorization: Bearer <token>"
[
  {"id":"c7a6d1e6-...","service_id":"d81360b4-...(Consultation)","scheduled_at":"2026-09-09T13:00:00Z","group_booking_id":"573146e3-..."},
  {"id":"48634359-...","service_id":"d070e66d-...(Cleaning)","scheduled_at":"2026-09-09T13:30:00Z","group_booking_id":"573146e3-..."}
]
```
Exactly the two real rows from step 4, nothing else.

8. **Cross-tenant — real rejection, three angles, real second business ("Rival Dental B2"):**
```
--- Business B GET's Business A's real group_booking_id ---
HTTP/1.1 200 OK
[]   -- correctly scoped: sees nothing, not even an empty-but-visible row

--- Business B POSTs a chat message into Business A's real conversation_id ---
HTTP/1.1 404 Not Found  {"error":{"type":"not_found","message":"Conversation not found."}}

--- Business B tries to book directly against Business A's real service_id/customer_id ---
HTTP/1.1 404 Not Found  {"error":{"type":"not_found","message":"Service not found."}}
```
(The service-layer `create_group_appointments`/`create_appointment` cross-tenant checks used for a chat-driven group booking are the identical `service_service.get_service`/`customer_service.get_customer` tenant-scoped lookups exercised by the third check above and by the permanent pytest cross-tenant tests below — same guarantee, not a separate code path.)

9. **Hallucination-proof, real chat, LLM's own text falsely claims success, real response overrides it** — this is exactly step 3 above in different framing: the (real, unstubbed) LLM's placeholder text for that turn was never inspected for a false claim since Phase 10/11's discipline means the LLM never even attempts to state a specific booking outcome (rule 9/12 tell it not to) — so the deterministic, stubbed-LLM version of "LLM falsely claims full success, tool actually partial-fails" is what proves the airtight case: `test_group_booking_hallucination_proof_partial_failure_is_never_reported_as_full_success` (real DB, stubbed LLM text reading "Great news, you're both all set!" while one slot is actually pre-taken) — asserts the false claim never reaches the customer, both people are individually named, and only the real successful row exists in the DB. Full pytest output in §11.

10. **Secrets check** (after all real LLM calls and real HTTP traffic in this phase):
```
$ git ls-files | grep -E '\.env$'  -> none tracked
$ git grep -nE 'AZURE_OPENAI_(API_KEY|ENDPOINT)\s*=\s*[A-Za-z0-9]' -- . ':!backend/.env.example'  -> clean, only placeholders matched
$ docker compose logs backend --tail=1000 | grep -iE "api.key|services\.ai\.azure|correcthorse1"  -> clean, no match
```

11. Lint: `docker compose exec backend ruff check .` → `All checks passed!`

12. Full regression suite (8 new `test_group_booking.py` service-level tests — clustering, honest partial success, real all-or-nothing atomicity including a forced race-during-write-pass rollback, cross-tenant — 1 new GET-filter test, 4 new `test_conversation.py` group-booking tool-wiring tests including the hallucination-proof one, 5 new `_parse_response` group-booking extraction tests):
```
$ docker compose exec backend python -m pytest tests/ -v
...
================== 92 passed, 1 skipped, 1 warning in 74.92s ===================
```

13. DB left clean after all real testing (all 3 real businesses created during manual verification deleted, cascades to everything hanging off them):
```
businesses=0  appointments=0  appointment_participants=0  notifications=0  conversations=0  customers=0
```

**Result / Acceptance criteria:**
| Criterion | Status |
|---|---|
| Real conversation: 2-3 people, same service/time, real DB rows, correct participant attribution | ✓ Pass — §2 above |
| Real conversation: one person's slot taken, honest partial outcome, DB shows only the successful write | ✓ Pass — §3 above |
| Real conversation: different service per person, DB proof | ✓ Pass — §4 above |
| All-or-nothing: nothing written when any slot fails; everything written when all succeed | ✓ Pass — §5/§6 above (real) + §12 pytest (including the real-race rollback case) |
| Cross-tenant: group booking respects tenant scoping | ✓ Pass — §8 above |
| Hallucination-proof: never reports success for a slot Python actually rejected, holds for the N-person case | ✓ Pass — §9 above (real framing) + permanent pytest test (§12) |
| Secrets grep clean | ✓ Pass |
| Lint clean | ✓ Pass |
| Migration reversible | ✓ Pass — §1 above, full down/up cycle clean |

**Known issues / punted items:**
- **Same-slot clustering is keyed on exact `(service_id, staff_id, scheduled_at)` equality** — two people who both want "a cleaning around 2pm" but whose extracted times differ by even a minute would NOT cluster into one Appointment (they'd become two separate staff-less bookings for nearly-adjacent times, which is correct — not a bug — but means the LLM must extract genuinely identical times for the shared-resource case to engage; the few-shot examples model this).
- **No new HTTP endpoint for group booking** (see "Implemented" above) — the service function and tool are fully real and tested, but there's no non-conversational `POST` entry point yet. Flagging as a deliberate scope boundary, easy to add later as a thin route.
- **`_fresh_alternatives` in `booking_service.py` duplicates `BookAppointmentTool._alternatives`'s ~10 lines** rather than sharing code across the service/tool boundary — a real, small duplication, kept because the two call sites have different natural homes (service-layer batch logic vs. a single tool's failure path) and merging them would mean either the tool importing more of the service's internals or the service depending on the conversation package; flagging rather than hiding it.
- **Group booking always uses `staff_id=None` per person** (never lets the LLM pick a specific staff member) — matches the existing Phase 10/11 convention exactly (the singular booking path does the same), not a new gap.
- Carried over from Phase 10/11, still real and still open: no staff-capacity model, fixed 15-minute slot grid, exact-match-only service-name resolution, in-memory rate limiter, no refresh tokens.
- No commit has been made yet — awaiting your confirmation of this verification output per working rule #6.

---

## Phase 13 — Customer Notifications

**Date:** 2026-09-04

**Required:** Actually send real notifications (email now, SMS as a stubbed/abstracted provider for later) when appointments are booked/cancelled/rescheduled, provider-agnostic (a `NotificationProvider` interface mirroring Phase 6's LLM provider pattern), real Gmail SMTP for email, a dispatch service moving `Notification.status` through real states with bounded retries, wired into the actual booking/cancel/reschedule flows without ever breaking the customer-facing flow on a send failure, deterministic Python-composed email content, and no logging of the Gmail app password.

**Correction to the phase brief's premise (flagged, not silently gone along with):** the brief stated Notification rows were "already being queued on booking/cancel/reschedule." Reading `booking_service.py` before writing anything showed this was only true for cancel/reschedule (Phase 11) — `create_appointment` (Phase 10) never queued a Notification at all, confirmed by re-reading Phase 10/11's own PHASE_STATUS.md text ("this phase [11] is the first to actually write to either [Notification/AuditLog]"). Queuing a real booking-confirmation Notification on every booking is therefore new work in this phase, not pre-existing wiring — implemented below as part of `create_appointment`, the single function every booking path (route, conversational tool, every group-booking cluster) already funnels through.

**Prerequisite env — added to `.env.example` only, real values are the user's own local `.env`:**
```
GMAIL_ADDRESS=changeme@gmail.com
GMAIL_APP_PASSWORD=changeme-16-char-app-password
```
A Gmail **Account App Password** (myaccount.google.com/apppasswords, requires 2-Step Verification), not the normal account password. `app/core/config.py` gained `gmail_address`/`gmail_app_password` (both default `""` — the provider treats missing credentials as a real, non-retryable send failure rather than crashing at import time).

**Implemented:**

- **`app/services/notifications/base.py`**: `NotificationProvider` ABC (`send(*, to, subject, body) -> str`, raises on failure) — mirrors `app/llm/base.py`'s `ChatProvider`/`EmbeddingProvider` seam exactly, per the ticket's explicit ask. `NotificationDeliveryError(message, *, transient: bool)` — the `transient` flag is what lets the dispatch service distinguish "retrying might fix this" (network blip, temporary SMTP error) from "retrying is pointless" (bad/missing recipient, rejected credentials) instead of treating every failure the same.
- **`app/services/notifications/email_provider.py`**: `EmailNotificationProvider` — real Gmail SMTP via `smtplib` (stdlib, no new dependency), `smtp.gmail.com:587`, STARTTLS, `smtp.login(gmail_address, gmail_app_password)`, `smtp.send_message(...)`. `SMTPAuthenticationError`/`SMTPRecipientsRefused`/`SMTPSenderRefused` → permanent (`transient=False`); any other `SMTPException` → transient; `OSError` (host unreachable/DNS/timeout) → transient. Missing credentials or an empty recipient both fail permanently *before* any network call is attempted (proven in a real, un-mocked unit-style test below — no network I/O happens).
  - **Log-scrubbing discipline, extended from Phase 6's Azure-endpoint leak**: the exception handler never logs/stores `exc`'s raw args (a server auth-failure response could echo parts of the AUTH exchange) — only `type(exc).__name__` plus a static description. `smtp.set_debuglevel()` is never called. `settings.gmail_app_password` is referenced in exactly one place in the whole codebase (the `smtp.login(...)` call itself) — confirmed by `grep -rn gmail_app_password app/` (Verification §7).
- **`app/services/notifications/sms_provider.py`**: `SMSNotificationProvider` — stub only, per the master plan (SMS is a later, premium-tier phase). Never contacts a real gateway; logs what it would send and always returns a "simulated" detail string. The dispatch service marks the Notification `SIMULATED`, never `SENT`/`DELIVERED`, for exactly this reason.
- **`app/db/models/notification.py`**: added `NotificationStatus.SIMULATED` (new Postgres enum label, `'SIMULATED'` uppercase — same member-name-not-value convention this codebase already discovered the hard way in Phase 10) and `Notification.event_type: str | None` (`"booking_confirmed"` / `"appointment_cancelled"` / `"appointment_rescheduled"` — the dispatch service needs this to compose the right subject/body; actual content is always composed fresh from the real Appointment/Business/Service rows at send time, never stored). Also added `UpdatedAtMixin` (already existed, reused) so a status transition's timestamp is real and queryable, not just inferred from logs.
- **Migration `f00944fc83c2_notification_dispatch_fields.py`**: `add_column(event_type)`, `add_column(updated_at)` (autogenerated), plus a hand-written `ALTER TYPE notification_status ADD VALUE IF NOT EXISTS 'SIMULATED'` (autogenerate does not detect enum value additions — confirmed, had to add by hand). **Downgrade is a real, working reversal, not a no-op**: Postgres has no `DROP VALUE` for enums, so downgrading first remaps any `SIMULATED` row to `FAILED` (never `SENT` — `SIMULATED` never claimed real delivery, so `FAILED` is the honest target), then rebuilds the enum type from scratch (`RENAME` old → `CREATE` new without the value → `ALTER COLUMN ... USING status::text::notification_status` → `DROP` old). Verified by a real downgrade/upgrade cycle (Verification §1).
- **`app/services/notifications/content.py`**: `compose_email(event_type, appointment, business, service)` — deterministic Python string building, zero LLM involvement (same discipline as `orchestrator.py`'s `_format_*_result` functions), business name/service name/local date-time/booking ID in every message, distinct subject+headline per event type. Duplicates `orchestrator._format_local`'s ~2-line strftime rather than importing across the service/conversation package boundary — same precedent as Phase 12's `_fresh_alternatives` duplication, flagged there and here rather than hidden.
- **`app/services/notifications/dispatch_service.py`**: `dispatch_notification(db, notification)` — resolves the provider by `notification.channel`, loads the real Appointment/Business/Service/Customer rows, composes the email, and for `channel="email"` retries up to `_MAX_SEND_ATTEMPTS=3` times (1s delay) **only** while the failure is `transient`; a permanent failure or the final attempt writes `FAILED` immediately. `channel="sms"` calls the stub once and writes `SIMULATED`. **Never raises** — every exception (including a non-`NotificationDeliveryError` bug in a provider) is caught, logged, and reflected as a real `FAILED` status, so a notification failure can never break the booking/cancel/reschedule action that already succeeded before this was called. `dispatch_queued_notifications(db, *, business_id=None)` — queries every currently-`QUEUED` Notification and dispatches each; not wired to a cron/worker (no new infrastructure, matching the ticket's explicit "a full task queue is likely overkill" steer), but callable by a future one with zero changes — this is the "picks up queued Notification rows" half of the ticket's ask, proven directly in Verification §6.
- **Wiring — synchronous, best-effort inline calls, not a background task queue.** Chosen because the ticket explicitly named this as an acceptable option ("synchronous-but-non-blocking... your call"), and because `Notification` queuing already happens deep inside `booking_service.py` (called from the plain HTTP route, the conversational tool, *and* every group-booking cluster) — threading FastAPI `BackgroundTasks` through all of those call stacks would be a materially larger diff for a demo-scale app where the success path adds no sleep at all (only a real retry ever sleeps, capped at ~2s worst case for `_MAX_SEND_ATTEMPTS=3` at 1s each).
  - `create_appointment` (Phase 10, the **only** function that writes an Appointment row) now also queues the booking's `Notification` (`event_type="booking_confirmed"`) in the same flush as the appointment insert, and — when `_commit=True` (every caller except the all-or-nothing group write pass) — dispatches it inline immediately after commit. This is the single place that fixes the "booking never queued a notification" gap noted above, and it's why the route, the tool, and `_create_group_partial`'s per-cluster bookings all get real confirmation emails with zero duplicated wiring.
  - `_create_group_all_or_nothing`'s write pass uses `create_appointment(..., _commit=False)` (unchanged from Phase 12) — the Notification is queued in the same deferred transaction but **not** dispatched until the group's own outer `db.commit()` succeeds, then dispatched precisely for the appointments just created (`Notification.appointment_id.in_([...])`, not "every queued notification for the business") so a concurrent unrelated booking's notification is never touched by this loop.
  - `cancel_appointment`/`reschedule_appointment` (Phase 11) already queued a Notification; both now also stamp `event_type` (`"appointment_cancelled"` / `"appointment_rescheduled"`) and dispatch it inline right after their existing commit.

**Real bugs/gaps found and fixed during this phase's own testing (not hidden):**
1. **Three Phase 11 regression tests broke** (`test_cancel_appointment_frees_the_slot_for_a_new_booking`, `test_reschedule_appointment_moves_same_id_to_new_time`, `test_cancellation_tool_cancels_real_appointment_and_response_reflects_it`) — root cause was two real, correct behavior changes at once: (a) booking now also queues its own `Notification`, so an appointment that was booked-then-cancelled has **two** Notification rows, not one, breaking a `len(...) == 1` assumption; (b) a queued Notification is no longer left sitting in `QUEUED` forever — it's dispatched for real inline, and since these tests' customers have no email on file, the honest real outcome is `FAILED` (permanent "no recipient," zero retries wasted), not `QUEUED`. Fixed by filtering each assertion to the specific `event_type` under test and asserting the real dispatched-to outcome (`FAILED`) instead of the old `QUEUED` placeholder assumption. Full diff is in the three test files; not a change to any production code path.

**Verification output (real DB + real HTTP throughout; provider network calls are explicitly labeled STUBBED where they are — the real, unstubbed Gmail send is a separate, later step pending your `.env` confirmation, see "Pending" below):**

1. **Migration — applied, reversed, and re-applied for real, including the enum rebuild:**
```
$ docker compose exec backend alembic upgrade head
INFO  Running upgrade e165f433cce9 -> f00944fc83c2, notification dispatch fields
$ docker compose exec backend alembic check
No new upgrade operations detected.

$ docker compose exec backend alembic downgrade -1
INFO  Running downgrade f00944fc83c2 -> e165f433cce9, notification dispatch fields
$ docker compose exec postgres psql -U nightguard -d nightguard -c "SELECT enumlabel FROM pg_enum WHERE enumtypid = 'notification_status'::regtype ORDER BY enumsortorder;"
 enumlabel
-----------
 QUEUED
 SENT
 DELIVERED
 FAILED
(4 rows)   -- SIMULATED correctly gone after downgrade

$ docker compose exec backend alembic upgrade head
INFO  Running upgrade e165f433cce9 -> f00944fc83c2, notification dispatch fields
$ docker compose exec backend alembic check
No new upgrade operations detected.

$ docker compose exec postgres psql -U nightguard -d nightguard -c "SELECT enumlabel FROM pg_enum WHERE enumtypid = 'notification_status'::regtype ORDER BY enumsortorder;"
 enumlabel
-----------
 QUEUED
 SENT
 DELIVERED
 FAILED
 SIMULATED   -- back after re-upgrade
(5 rows)
```

2. **REAL booking through `POST /appointments` (real HTTP, real DB, no LLM in this path), STUBBED provider network call — real DB row transitions QUEUED → SENT** (`tests/integration/test_notifications.py::test_booking_queues_and_sends_a_real_email_notification`, real customer email `jordan@example.com` on file, provider stubbed to a scripted success so no real network call is made in the automated suite):
```
Real Notification row after the real booking + real inline dispatch call:
  channel=email  event_type=booking_confirmed  status=SENT
  provider.calls == 1, provider.recipients == ["jordan@example.com"]
```

3. **Bounded retry — STUBBED transient failures, REAL retry loop, REAL DB status transitions** (`test_dispatch_retries_transient_failure_then_succeeds`): scripted provider fails transiently twice, succeeds on the 3rd call — real assertion `provider.calls == 3` and real DB row ends `SENT`. (`test_dispatch_exhausts_bounded_retries_and_marks_failed`): scripted provider always fails transiently — real assertion `provider.calls == dispatch_service._MAX_SEND_ATTEMPTS` (3, no more, no less) and real DB row ends `FAILED`.

4. **Permanent failure is never retried — STUBBED failure, REAL call-count proof** (`test_dispatch_permanent_failure_is_never_retried`): scripted provider raises a permanent (`transient=False`) error once — real assertion `provider.calls == 1` (not retried) and real DB row ends `FAILED`.

5. **Dispatch never breaks the booking flow, even on a provider bug** (`test_dispatch_never_raises_even_on_a_provider_bug`): provider's `send()` raises a bare `RuntimeError` (not even a `NotificationDeliveryError`) — the real `POST /appointments` call still returns real `201 Created` (asserted inside the `_book` helper), and the real DB row is left `FAILED`, not stuck or corrupted.

6. **Pickup path for a previously-undispatched Notification — real DB, real requeue, real re-dispatch** (`test_dispatch_queued_notifications_picks_up_a_notification_that_was_never_dispatched_inline`): a real booking's notification is driven to `FAILED` (stubbed permanent failure), manually reset to `QUEUED` (simulating "the process crashed before inline dispatch ran"), then `dispatch_queued_notifications(db, business_id=...)` — real function, real query — picks it up (`picked_up == 1`) and a real DB re-fetch shows `SENT`.

7. **SMS is marked SIMULATED, never SENT/DELIVERED — real DB, real Notification row, real stub provider** (`test_sms_channel_is_marked_simulated_never_sent_or_delivered`): a real `channel="sms"` Notification, dispatched for real through `dispatch_notification` → real DB status `SIMULATED`.

8. **The real `EmailNotificationProvider` class itself rejects a missing recipient / missing credentials *before any network call*** (`test_email_provider_rejects_missing_recipient_without_any_network_call`, `test_email_provider_rejects_missing_credentials_without_any_network_call`) — these call the real, un-mocked provider class directly; `pytest.raises(NotificationDeliveryError)` with `transient is False` in both cases. No `smtplib.SMTP(...)` object is ever constructed in either test (verified by code inspection: the guard clause returns before the `with smtplib.SMTP(...)` line is reached).

9. **Secrets/log-scrubbing check** (after this phase's real HTTP traffic and stubbed-provider test runs):
```
$ grep -rn "gmail_app_password\|gmail_address" app/    -> only config.py's declaration + email_provider.py's 3 real uses (settings.gmail_address x2, settings.gmail_app_password x1 in smtp.login) — no logger.* call references either
$ docker compose logs backend --tail=2000 | grep -iE "ogjvtcdaqghbopsj|samratghimire01"   -> no match (exit 1 both times) — the real local .env credentials never appeared in a container log across this phase's testing
$ git grep -nE 'GMAIL_(ADDRESS|APP_PASSWORD)\s*=\s*[A-Za-z0-9]' -- . ':!backend/.env.example'   -> no match, only placeholders in .env.example
$ git ls-files | grep -E '\.env$'   -> none tracked
$ git check-ignore -v backend/.env   -> .gitignore:21:.env backend/.env (still ignored)
```

10. Lint: `docker compose exec backend ruff check .` → `All checks passed!`

11. Full regression suite (9 new `test_notifications.py` tests + 3 pre-existing Phase 11 tests updated for the real behavior change described above, all real DB/HTTP, provider stubbed where noted):
```
$ docker compose exec backend python -m pytest tests/ -v
...
================== 101 passed, 1 skipped, 1 warning in 84.38s ===================
```

**REAL LIVE GMAIL SMTP VERIFICATION (run 2026-09-04, after you confirmed self-send to the real `GMAIL_ADDRESS` on file):**

All four of the following are real HTTP requests against the live running server (`localhost:8010`), a real conversation turn through the real (unstubbed) Azure LLM for the booking, real Postgres rows, and a real Gmail SMTP transaction for every send — nothing stubbed in this section. Business "Willow Creek Family Dentistry," service "Cleaning" $95/30min, customer "Jordan Lee" with `email` set to the real `GMAIL_ADDRESS` itself (your confirmed self-send choice) — every email below was sent to and from the same real Gmail account so you can check one inbox.

1. **Real conversation → real LLM → real booking → real email**, actual live server response:
```
POST /conversations/{id}/messages {"content": "Hi, I'd like to book a cleaning next Monday at 2pm please."}
HTTP/1.1 201 Created
{"intent":"booking","response":"You're all set, Jordan Lee! I've booked Cleaning for Monday, September 7 at 2:00 PM (30 min). Your booking ID is 9c259bf3-61ec-4df8-87df-7d2c5999457b."}
```
Real backend log line (the actual provider call's real success response, not an assumption):
```
notification_id=d72edeec-c7fd-483a-a6f5-e022f7fb282d sent on attempt 1/3: 250 message accepted for delivery
```
Real DB row, before (implicit, at `created_at`) / after:
```
 id=d72edeec-...  appointment_id=9c259bf3-...  channel=email  event_type=booking_confirmed
 status=SENT   created_at=03:16:15.237627   updated_at=03:16:21.896513   (~6.6s real SMTP round trip: STARTTLS + login + send)
```

2. **Real cancellation → real email**, same appointment:
```
PATCH /appointments/9c259bf3-.../cancel  -> HTTP/1.1 200 OK  {"status":"cancelled",...}
```
Real log: `notification_id=20b51eb0-... sent on attempt 1/3: 250 message accepted for delivery`
Real DB row: `event_type=appointment_cancelled  status=SENT  created_at=03:16:43.301699  updated_at=03:16:43.308655`

3. **Real booking + real reschedule → real email**, direct API (no LLM needed to exercise this path — same `booking_service.reschedule_appointment` either way):
```
POST /appointments {"scheduled_at":"2026-09-08T15:00:00Z", ...}          -> 201, notification_id=4ae39c5b-... SENT
PATCH /appointments/{id}/reschedule {"scheduled_at":"2026-09-08T16:00:00Z"} -> 200
```
Real log: `notification_id=010dce23-... sent on attempt 1/3: 250 message accepted for delivery`
Real DB row: `event_type=appointment_rescheduled  status=SENT  created_at=03:17:05.303132  updated_at=03:17:05.312845`

4. **Real induced-failure tests — real Gmail server, real network, not simulated:**
   - **Permanent (wrong credentials)**: a one-off process (`docker compose exec -e GMAIL_APP_PASSWORD=wrongpassword1234 backend python3 -c "..."`) — deliberately run as a *separate short-lived process with an overridden env var*, never touching your actual `backend/.env` file or restarting the long-running server — re-dispatched a real, already-sent Notification with a real wrong password against the real Gmail server:
     ```
     notification_id=a35ece20-... failed: failed after 1 attempt(s): SMTPAuthenticationError: permanent SMTP failure
     final status: NotificationStatus.FAILED
     ```
     Confirms: a real `SMTPAuthenticationError` from the real Gmail server, correctly classified permanent, **zero retries wasted** (1 attempt, not 3). (This also caught and fixed a real, minor logging bug: the failure message unconditionally said "exhausted 3 attempt(s)" even when only 1 real attempt had been made for a non-retried permanent failure — fixed in `dispatch_service.py` to report the true `attempts_made`; re-verified above with the corrected message text.)
   - **Transient (real unreachable host)**: same isolated-process technique, this time monkeypatching only `email_provider._SMTP_PORT` to a wrong port in that one throwaway process (confirmed separately via a raw `socket.create_connection` test that this sandbox's network stack really returns `OSError: [Errno 101] Network is unreachable` for it — a genuine network-level condition, not an app-level fake):
     ```
     notification_id=a35ece20-... send attempt 1/3 failed transiently, retrying: OSError: could not reach SMTP host
     notification_id=a35ece20-... send attempt 2/3 failed transiently, retrying: OSError: could not reach SMTP host
     notification_id=a35ece20-... failed: failed after 3 attempt(s): OSError: could not reach SMTP host
     elapsed 47.2s   final status: NotificationStatus.FAILED
     ```
     Confirms: **retries happen up to the bounded 3 attempts** against a real (if artificially induced) network failure, each attempt a real ~15s socket timeout with the real 1s backoff between (elapsed time matches exactly), then a real, honest `FAILED` — never silently swallowed, never left `QUEUED`.
   - **Neither induced failure broke anything else**: full regression suite re-run clean after both (`101 passed, 1 skipped`), and neither the wrong password nor the wrong port ever appeared in any container log (`docker compose logs backend --tail=50 | grep -i wrongpassword1234` → no match).

5. **Secrets re-check after all real SMTP traffic in this phase:**
```
$ docker compose logs backend --tail=2000 | grep -iE "ogjvtcdaqghbopsj|wrongpassword1234"   -> no match
$ git grep -nE 'GMAIL_(ADDRESS|APP_PASSWORD)\s*=\s*[A-Za-z0-9]' -- . ':!backend/.env.example'  -> no match
```

6. Full regression suite after the dispatch-message fix: `docker compose exec backend python -m pytest tests/ -q` → `101 passed, 1 skipped, 1 warning in 85.63s`. Lint: `ruff check .` → `All checks passed!`

7. DB left clean after all real/manual testing: `businesses=0 appointments=0 notifications=0 conversations=0 customers=0`.

**Not independently confirmed:** I have no IMAP/inbox access, so I cannot personally confirm the four real emails landed in the real Gmail inbox — the real SMTP `250` acceptance response and the real DB `SENT` transitions above are the proof available to me (per the acceptance criteria's own fallback for exactly this situation). **Please check `samratghimire01@gmail.com` and confirm the four messages (booking confirmation, cancellation, a second booking confirmation, reschedule) actually arrived with correct content** — flag me if anything is missing or malformed and I'll investigate.

**Result / Acceptance criteria:**
| Criterion | Status |
|---|---|
| `NotificationProvider` interface + real `EmailNotificationProvider` (Gmail SMTP) + stub `SMSNotificationProvider` | ✓ Pass |
| Dispatch service moves status through real states with bounded retries, on transient failure only | ✓ Pass — stubbed §3/§4 (call-count proofs) + real §4 above (real auth failure: 1 attempt; real unreachable host: exactly 3) |
| Notification failure never breaks the booking/cancel/reschedule flow | ✓ Pass — stubbed §5 above + real induced failures above, neither broke the appointment or the API response |
| Wired into real booking/cancel/reschedule flows, with a REAL Gmail send | ✓ Pass — real §1/§2/§3 above, real `250` responses, real DB `SENT` rows |
| Deterministic Python-composed email content (business, service, date/time, booking ID) | ✓ Pass — `content.py`, no LLM involvement; **pending your confirmation the real inbox received correct content** |
| Never logs the Gmail app password / SMTP auth details | ✓ Pass — grep clean across app code, 2000+ lines of real container logs including the two real induced-failure runs |
| Migration reversible (including the enum value, which needed a hand-written rebuild) | ✓ Pass — full down/up cycle, `SIMULATED` correctly present/absent each way |
| Lint clean | ✓ Pass |

**Known issues / punted items:**
- **No true worker/cron picks up `dispatch_queued_notifications` on a schedule** — it exists and is proven (Verification §6) but nothing currently calls it except a test; the inline dispatch on every booking/cancel/reschedule call site is what actually fires in practice. Flagging as a real, deliberate scope boundary (the ticket said a full task queue is likely overkill) rather than a hidden gap — a future phase could wire this to a simple periodic job with zero changes to `dispatch_service.py` itself.
- **No `DELIVERED` state is ever reached** — Gmail SMTP's `250` response only confirms the message was accepted by Google's server for delivery, not that it reached the recipient's inbox (that would need bounce-handling/webhook infrastructure this phase doesn't build). `SENT` is the real ceiling for the email channel; `DELIVERED` remains modeled in the schema (Phase 2) but is currently unreachable by any code path — an honest gap, not a claim of confirmed delivery.
- **A customer with no email on file simply gets a permanently-failed email Notification** — there's no automatic fallback to the (stub) SMS channel today; booking/cancel/reschedule always queue `channel="email"` regardless of what contact info the customer actually has, matching the existing Phase 10/11 precedent of hardcoding `channel="email"`. A future phase choosing SMS when no email exists (once SMS is real) would be a small, contained change in the three queuing call sites.
- **Retry backoff is a fixed 1-second sleep, not exponential** — simple and sufficient for `_MAX_SEND_ATTEMPTS=3`; flagged as a deliberate simplicity choice, not an oversight, in case a much larger retry budget is ever wanted.
- Carried over from Phase 10/11/12, still real and still open: no staff-capacity model, fixed 15-minute slot grid, exact-match-only service-name resolution, in-memory rate limiter, no refresh tokens.
- No commit has been made yet — awaiting your confirmation of this verification output per working rule #6, and separately, please check `samratghimire01@gmail.com` for the four real test emails and confirm they arrived with correct content.