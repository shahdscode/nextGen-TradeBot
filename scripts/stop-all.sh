#!/usr/bin/env bash
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
LOG_DIR="$ROOT/.logs"

for name in backend celery frontend; do
  pidfile="$LOG_DIR/${name}.pid"
  if [[ -f "$pidfile" ]]; then
    kill "$(cat "$pidfile")" 2>/dev/null || true
    rm -f "$pidfile"
  fi
done

for p in 8002 5174 8081 8082; do
  lsof -ti ":$p" 2>/dev/null | xargs kill -9 2>/dev/null || true
done
pkill -f "celery -A app.celery_app" 2>/dev/null || true
pkill -f "uvicorn app.main:app" 2>/dev/null || true

echo "Stopped API, Celery, frontend, and Metro ports."
