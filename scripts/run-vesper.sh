#!/usr/bin/env bash
# Starts everything: backend + database (Docker), the backend's public ngrok
# tunnel (fixed domain -- this is what WhatsApp/Messenger/Instagram webhooks
# and payment links point at), the frontend dev server, and its own ngrok
# tunnel (so the dashboard is reachable remotely too).
set -euo pipefail

PROJECT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
LOG_DIR="$PROJECT_DIR/.run-vesper-logs"
BACKEND_NGROK_URL="unfiltrated-sharla-futile.ngrok-free.dev"
mkdir -p "$LOG_DIR"

# Each ngrok agent runs its own local inspector API (4040, then 4041, 4042... if
# taken) -- this finds the public URL for whichever agent is tunnelling `port`,
# regardless of whether that agent was started by this script or already running.
ngrok_url_for_port() {
    local port="$1"
    for p in 4040 4041 4042 4043; do
        curl -s "http://127.0.0.1:$p/api/tunnels" 2>/dev/null \
            | grep -oE "\"public_url\":\"[^\"]*\"[^}]*\"addr\":\"[^\"]*:$port\"" \
            | grep -oE "\"public_url\":\"[^\"]*\"" | head -1 | cut -d'"' -f4 \
            && return 0
    done
    return 1
}

echo "==> Backend + database (Docker)..."
(cd "$PROJECT_DIR" && docker compose up -d)

if ! pgrep -f "ngrok http --url=$BACKEND_NGROK_URL" > /dev/null; then
    echo "==> Backend ngrok tunnel ($BACKEND_NGROK_URL -> :8010)..."
    nohup ngrok http --url="$BACKEND_NGROK_URL" 8010 > "$LOG_DIR/ngrok-backend.log" 2>&1 &
    echo $! > "$LOG_DIR/ngrok-backend.pid"
else
    echo "==> Backend ngrok tunnel already running."
fi

if ! pgrep -f "npm run dev" > /dev/null && ! pgrep -f "node.*vite" > /dev/null; then
    echo "==> Frontend dev server..."
    nohup npm --prefix "$PROJECT_DIR/frontend" run dev > "$LOG_DIR/frontend.log" 2>&1 &
    echo $! > "$LOG_DIR/frontend.pid"
    sleep 3
else
    echo "==> Frontend dev server already running."
fi
FRONTEND_PORT=$(grep -oE "localhost:[0-9]+" "$LOG_DIR/frontend.log" 2>/dev/null | head -1 | cut -d: -f2 || true)
FRONTEND_PORT=${FRONTEND_PORT:-5173}

if ! pgrep -f "ngrok http $FRONTEND_PORT" > /dev/null; then
    echo "==> Frontend ngrok tunnel (-> :$FRONTEND_PORT)..."
    nohup ngrok http "$FRONTEND_PORT" --log=stdout > "$LOG_DIR/ngrok-frontend.log" 2>&1 &
    echo $! > "$LOG_DIR/ngrok-frontend.pid"
else
    echo "==> Frontend ngrok tunnel already running."
fi

sleep 3
FRONTEND_NGROK_URL=$(ngrok_url_for_port "$FRONTEND_PORT" || true)

echo ""
echo "=================================================="
echo " Backend:   https://$BACKEND_NGROK_URL  ->  localhost:8010"
echo " Frontend:  ${FRONTEND_NGROK_URL:-<still starting, check $LOG_DIR/ngrok-frontend.log>}  ->  localhost:$FRONTEND_PORT"
echo " Local dashboard: http://localhost:$FRONTEND_PORT"
echo ""
echo " WhatsApp / Messenger / Instagram all route through the backend tunnel"
echo " above -- as long as it's up and matches what's registered in Meta's"
echo " App Dashboard, all three work automatically. No separate step per channel."
echo ""
echo " Logs: $LOG_DIR/"
echo " To stop everything: $PROJECT_DIR/scripts/stop-vesper.sh"
echo "=================================================="
