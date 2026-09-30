#!/bin/sh
# Brings the database schema up to date, then starts the API. A failed migration stops the container (and shows in
# `docker compose logs backend`) instead of serving requests against the wrong schema.
set -e
alembic upgrade head
exec "$@"
