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
