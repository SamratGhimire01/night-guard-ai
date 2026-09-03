# Architecture

Night Guard AI is a multi-tenant AI receptionist platform. As of Phase 1, only the
FastAPI + PostgreSQL foundation exists; the layers below describe the intended
end-to-end request flow as the system grows in later phases.

## Layered request flow

```
Channel (phone / SMS / web chat)
        |
        v
FastAPI (API layer, /api/v1)
        |
        v
Conversation / Orchestration layer
        |
        v
LLM (generation, tool use)
        |
        v
Python validation layer
        |
        v
Business logic (services)
        |
        v
PostgreSQL (persistence)
```

- **Channel** — the entry point a customer or patient actually uses (a phone call
  transcribed to text, an SMS webhook, a web chat widget). Out of scope until a
  channel integration phase.
- **FastAPI** — the stateless HTTP boundary. Validates requests, authenticates
  tenants, and dispatches to the orchestration layer. Routes are versioned under
  `/api/v1/`.
- **Conversation / Orchestration layer** — owns the state of an in-progress
  conversation and decides what happens next (call the LLM, call a business
  service, ask a clarifying question). Not implemented yet.
- **LLM** — generates natural-language responses and/or proposes actions (e.g.
  "book this appointment"). The LLM never writes directly to business data — see
  the rule below.
- **Python validation layer** — every action or data change proposed by the LLM is
  validated in plain Python (schema checks, business rules) before it is allowed
  to reach business logic. This is the safety boundary between untrusted model
  output and trusted state changes.
- **Business logic (services)** — deterministic, testable Python code that
  performs the actual operation (e.g. creating an appointment) and enforces
  tenant isolation.
- **PostgreSQL** — the system of record. Multi-tenant data lives here; no schema
  is defined yet (Phase 2 introduces the first business tables).

## Guiding rule

The LLM is never given direct write access to business-critical data. It can
propose actions; only validated, deterministic Python code is allowed to mutate
the database. This keeps hallucinations and prompt-injection from translating
into real-world side effects (e.g. an incorrect appointment booking or a leaked
record from another tenant).

## Authentication and tenant-scoping convention (added Phase 3)

Every business-data endpoint follows this rule, without exception:

**`business_id` is never read from client-supplied request data (body, query
params, path params) for the purpose of scoping a query. It comes only from
the validated JWT, via the `get_current_user` dependency.**

Concretely:

- `POST /api/v1/auth/register` creates a `Business` + its first `BusinessUser`
  (`role=owner`) in one transaction. Passwords are hashed with bcrypt
  (`app/core/security.py`) — never stored in plaintext.
- `POST /api/v1/auth/login` verifies credentials and returns a JWT whose
  payload carries `sub` (user id), `business_id`, and `role`. This token is the
  *only* source of truth for those three values on every later request.
- `app/api/dependencies.py::get_current_user` is a FastAPI dependency that
  validates the JWT (signature + expiry) and loads the corresponding
  `BusinessUser` row from the database. Every route handler that touches
  tenant data must declare `current_user: BusinessUser = Depends(get_current_user)`
  and filter its query by `current_user.business_id` — see
  `app/api/routes/customers.py` for the reference pattern (`create_customer`,
  `get_customer`). A resource belonging to another tenant is filtered out by
  the `WHERE business_id = ...` clause and returns 404, indistinguishable from
  a resource that never existed — this is what makes cross-tenant ID
  enumeration (IDOR) fail closed instead of leaking existence.
- `app/api/dependencies.py::require_role(["owner", "admin"])` is a dependency
  factory for role-gated endpoints (`owner`/`admin`/`staff`); see
  `DELETE /api/v1/customers/{id}` for the reference pattern.
- This convention is mandatory for every future business-data endpoint, not
  just the two above — they exist specifically to prove the mechanism works
  before the rest of the CRUD surface is built out in later phases.

## Current state (end of Phase 3)

Implemented: FastAPI app skeleton, structured logging, a custom exception
hierarchy with a consistent JSON error format, SQLAlchemy engine/session
wiring, `/api/v1/health`, the full Phase 2 schema with DB-level cross-tenant
foreign keys, and now: registration, login (bcrypt + JWT), `get_current_user`,
`require_role`, an in-memory login rate limiter, and two proof-of-mechanism
endpoints (`/api/v1/customers`) that are tenant-scoped end to end.

Not implemented: refresh tokens (punted — see PHASE_STATUS.md), a
Redis-backed (multi-process-safe) rate limiter, business-user management
(inviting additional staff/admin accounts), conversation orchestration, LLM
integration, RAG, and background workers.
