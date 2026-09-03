# Local development

## Prerequisites

- Docker and Docker Compose
- (Optional, for running outside Docker) Python 3.11+

## 1. Configure environment variables

Copy the example env file and adjust values if needed (the defaults work for
local development):

```bash
cp backend/.env.example backend/.env
```

`backend/.env` is git-ignored and must never be committed. It supplies both the
Postgres container's credentials and the backend's `DATABASE_URL` / `SECRET_KEY`.

## 2. Start the stack

From the repository root:

```bash
docker compose up --build
```

This starts two services:

- `postgres` — PostgreSQL 16, with data persisted in the named volume
  `postgres_data`.
- `backend` — the FastAPI app, served on `http://localhost:8000`.

## 3. Verify it's running

```bash
curl http://localhost:8000/api/v1/health
```

A healthy response looks like:

```json
{"status": "ok", "database": "connected"}
```

If the database is unreachable, this endpoint returns HTTP 503 with a JSON
error body instead of a false "ok".

## Stopping the stack

```bash
docker compose down
```

Add `-v` to also remove the Postgres data volume (this deletes all local data).
