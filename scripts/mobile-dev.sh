#!/usr/bin/env bash
# One command: backend + mobile tunnels + Expo QR
set -e
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT/mobile"
[[ -d node_modules ]] || npm install
exec npm start
