#!/usr/bin/env bash
# Stops everything run-vesper.sh started: both ngrok tunnels, the frontend
# dev server, and the backend + database containers.
set -euo pipefail

PROJECT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
LOG_DIR="$PROJECT_DIR/.run-vesper-logs"

for name in ngrok-backend ngrok-frontend frontend; do
    if [ -f "$LOG_DIR/$name.pid" ]; then
        pid="$(cat "$LOG_DIR/$name.pid")"
        kill "$pid" 2>/dev/null && echo "Stopped $name (pid $pid)" || echo "$name (pid $pid) was already stopped"
        rm -f "$LOG_DIR/$name.pid"
    fi
done

echo "==> Backend + database (Docker)..."
(cd "$PROJECT_DIR" && docker compose down)

echo "Stopped everything."
