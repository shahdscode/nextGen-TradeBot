#!/usr/bin/env bash
# Start NextGen TradeBot locally (no Docker).
# Usage: ./scripts/start-all.sh
# Stop:  ./scripts/stop-all.sh

set -e
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
VENV="$ROOT/.venv/bin"
BACKEND_PORT=8002
FRONTEND_PORT=5174
LOG_DIR="$ROOT/.logs"
mkdir -p "$LOG_DIR"

die() { echo "Error: $1" >&2; exit 1; }

[[ -x "$VENV/python" ]] || die "Missing .venv — run: python3.11 -m venv .venv && pip install -r requirements.txt"

free_port() {
  local p="$1"
  if lsof -ti ":$p" >/dev/null 2>&1; then
    lsof -ti ":$p" | xargs kill -9 2>/dev/null || true
    echo "Freed port $p"
  fi
}

echo "=== Stopping old processes ==="
free_port "$BACKEND_PORT"
free_port "$FRONTEND_PORT"
free_port 8081
free_port 8082
pkill -f "celery -A app.celery_app" 2>/dev/null || true
sleep 1

echo "=== Redis ==="
if redis-cli ping >/dev/null 2>&1; then
  echo "Redis already running"
else
  if command -v redis-server >/dev/null 2>&1; then
    redis-server --daemonize yes 2>/dev/null || redis-server &
    sleep 1
    redis-cli ping >/dev/null 2>&1 || die "Could not start Redis. Install: brew install redis"
    echo "Redis started"
  else
    die "redis-server not found. Install: brew install redis"
  fi
fi

echo "=== Backend API (port $BACKEND_PORT) ==="
cd "$ROOT/backend"
nohup "$VENV/uvicorn" app.main:app --host 0.0.0.0 --port "$BACKEND_PORT" \
  >"$LOG_DIR/backend.log" 2>&1 &
echo $! >"$LOG_DIR/backend.pid"
sleep 2
curl -sf "http://127.0.0.1:$BACKEND_PORT/health" >/dev/null \
  || die "Backend failed — see $LOG_DIR/backend.log"

echo "=== Celery worker ==="
nohup "$VENV/celery" -A app.celery_app worker --loglevel=info --pool=solo \
  >"$LOG_DIR/celery.log" 2>&1 &
echo $! >"$LOG_DIR/celery.pid"
sleep 2

echo "=== Web frontend (port $FRONTEND_PORT) ==="
cd "$ROOT/frontend"
[[ -d node_modules ]] || npm install
nohup env VITE_API_URL="http://127.0.0.1:$BACKEND_PORT" npm run dev -- --host 0.0.0.0 --port "$FRONTEND_PORT" \
  >"$LOG_DIR/frontend.log" 2>&1 &
echo $! >"$LOG_DIR/frontend.pid"
sleep 3

LAN_IP="$(ipconfig getifaddr en0 2>/dev/null || ipconfig getifaddr en1 2>/dev/null || echo "127.0.0.1")"

echo ""
echo "════════════════════════════════════════════════════════════"
echo "  NextGen TradeBot — all services started"
echo "════════════════════════════════════════════════════════════"
echo "  API:      http://127.0.0.1:$BACKEND_PORT  (docs: /docs)"
echo "  Web UI:   http://127.0.0.1:$FRONTEND_PORT"
echo "  Login:    admin / admin123"
echo "  Logs:     $LOG_DIR/"
echo ""
echo "  Mobile (NEW terminal):"
echo "    cd $ROOT/mobile"
echo "    npm run sync-api-ip && npm run start"
echo "    Same Wi‑Fi: scan QR in Expo Go (not Camera)"
echo "    Other Wi‑Fi / mobile data? → npm run sync:ngrok && npm run start:remote"
echo "    URL: exp://$LAN_IP:8081  API: http://$LAN_IP:$BACKEND_PORT"
echo "════════════════════════════════════════════════════════════"
