# NextGen TradeBot — Mobile App

Expo SDK 54 · React Native · works on **any phone / any network** with one command.

## Quick start (recommended)

```bash
cd mobile
npm run setup    # once: ngrok token + optional cloudflared
npm start        # auto: backend + API tunnel + Expo QR
```

1. Wait until the terminal shows **Tunnel ready** and the connection box with **Expo URL**.
2. On your phone: open **Expo Go** (App Store / Play — must support SDK 54).
3. Scan the QR **inside Expo Go** (not an old screenshot).
4. Keep the Mac terminal **open** while testing.
5. Login: `admin` / `admin123`

From repo root:

```bash
./scripts/mobile-dev.sh
```

## What `npm start` does

- Starts the backend on `:8002` if it is not already running
- Opens a **Cloudflare** API tunnel (`cloudflared`) when installed — much more reliable than LAN
- Opens an **Expo ngrok** tunnel for Metro (works through macOS firewall)
- Writes `mobile/.env` automatically — no manual IP sync

## Troubleshooting

```bash
npm run doctor
```

| Issue | Fix |
|--------|-----|
| First time / no ngrok token | `npm run setup` |
| Expo tunnel failed | New token at [ngrok dashboard](https://dashboard.ngrok.com/get-started/your-authtoken) → `npm run setup` |
| API unreachable on phone | Tap status on login screen; ensure Mac terminal is still running |
| Same Wi‑Fi only, firewall off | `npm run start:lan` |

## Scripts

| Command | Purpose |
|---------|---------|
| `npm start` | Auto remote dev (default) |
| `npm run setup` | One-time ngrok + deps |
| `npm run start:lan` | LAN only (same Wi‑Fi, no firewall) |
| `npm run doctor` | Diagnose connection issues |
| `npm run stop` | Stop Metro |

## Screens

Login · Home · Signals · Market · Leaderboard · Simulator
