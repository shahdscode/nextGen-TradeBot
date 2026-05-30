#!/usr/bin/env bash
# Start only the FastAPI backend (does not kill Metro :8081 or the web UI).
set -e
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
VENV="$ROOT/.venv/bin"
PORT=8002
LOG_DIR="$ROOT/.logs"
mkdir -p "$LOG_DIR"

die() { echo "Error: $1" >&2; exit 1; }

[[ -x "$VENV/python" ]] || die "Missing .venv — run: python3.11 -m venv .venv && pip install -r requirements.txt"

if curl -sf "http://127.0.0.1:$PORT/health" >/dev/null 2>&1; then
  echo "Backend already running on :$PORT"
  exit 0
fi

if lsof -ti ":$PORT" >/dev/null 2>&1; then
  lsof -ti ":$PORT" | xargs kill -9 2>/dev/null || true
  sleep 1
fi

cd "$ROOT/backend"
nohup "$VENV/uvicorn" app.main:app --host 0.0.0.0 --port "$PORT" \
  >"$LOG_DIR/backend.log" 2>&1 &
echo $! >"$LOG_DIR/backend.pid"
sleep 2
curl -sf "http://127.0.0.1:$PORT/health" >/dev/null \
  || die "Backend failed — see $LOG_DIR/backend.log"
echo "Backend started on http://127.0.0.1:$PORT"
