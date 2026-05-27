# NextGen TradeBot — Mobile App

React Native app (Expo SDK 54 managed workflow) for the user-facing trading signals experience.

**Stack:** Expo 54 · React Native 0.81 · React 19

## Screens

| Screen | Description |
|--------|-------------|
| **Login** | JWT authentication |
| **Home** | Regime banner + top 3 signals + market movers |
| **Signals** | Full signal grid with market + action filters |
| **Market** | Live prices, 3-month chart, news sentiment |
| **Leaderboard** | Ranked tickers by signal confidence |
| **Simulator** | Backtest runner with equity curve |

## Prerequisites

- Node.js ≥ 20.19 (required for Expo SDK 54)
- Expo Go app on your phone (SDK 54 compatible build)
- Or iOS Simulator / Android Emulator

## Setup

```bash
cd mobile
npm install
```

## Configure the API URL

The app picks your Mac's LAN IP automatically from Expo (same IP as the QR code).

If login shows "Cannot reach API", sync `.env` then restart Expo:

```bash
npm run sync-api-ip
npm run start
```

Copy `mobile/.env.example` → `mobile/.env` and set `EXPO_PUBLIC_API_URL=http://YOUR_MAC_IP:8002`.

> **Note:** `localhost` only works on simulators, not on a physical device. Backend must run on port **8002**.

## Run

```bash
npm run sync-api-ip
npm run start          # LAN — all phones on same Wi‑Fi as Mac
```

**Multiple phones (same room):** use `npm run start`, same Wi‑Fi, scan QR **inside Expo Go** on each phone (`exp://YOUR_MAC_IP:8081`).

**Any phone / any Wi‑Fi (different network, guest Wi‑Fi, mobile data):**
```bash
# 1. Backend running on the Mac
cd .. && ./scripts/start-all.sh

# 2. Free ngrok token → mobile/.env (one-time)
#    https://dashboard.ngrok.com/get-started/your-authtoken
npm run sync:ngrok

# 3. Remote mode (API tunnel + Expo tunnel)
npm run start:remote
```
Each phone: open **Expo Go → Scan QR** (not the iPhone Camera app).  
Login screen should show **🌐 Remote** and an `https://…ngrok…` or `loca.lt` API URL.

Same Wi‑Fi again? `Ctrl+C` then `npm run sync-api-ip && npm run start`.

```bash
# Custom dev build (not Expo Go)
npm run start:dev-client

# Scan the QR code with Expo Go (iOS/Android)
# Or press 'i' for iOS Simulator / 'a' for Android Emulator
```

## Build for production

```bash
# Install EAS CLI
npm install -g eas-cli
eas login

# Configure
eas build:configure

# Build for iOS
eas build --platform ios

# Build for Android
eas build --platform android
```

## Default login

- Username: `admin`
- Password: `admin123`

## Push Notifications

The app registers for Expo push notifications on startup (physical device only).
The backend can send notifications via the Expo Push API to tokens stored after registration.
