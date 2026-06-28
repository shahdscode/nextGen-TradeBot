# API Overview

Interactive docs: **`/docs`** (Swagger) and **`/redoc`** when the backend is running.

Base URL: `http://localhost:8000/api` (Docker) or `http://localhost:8002/api` (local dev).

Auth: `Authorization: Bearer <JWT>` unless noted **public**.

---

## Auth

| Method | Path | Description |
|--------|------|-------------|
| POST | `/auth/register` | Create account (`role: user`) |
| POST | `/auth/login` | Returns JWT |
| GET | `/auth/me` | Current user + Alpaca configured flag |
| PUT | `/auth/alpaca-config` | Save user's Alpaca paper keys |
| DELETE | `/auth/alpaca-config` | Remove keys |

---

## User app (authenticated)

| Method | Path | Description |
|--------|------|-------------|
| GET | `/paper-trading/command-center` | Daily dashboard aggregate |
| GET | `/paper-trading/analytics` | Portfolio intelligence metrics |
| GET | `/paper-trading/trade-log` | Trade journal (user-scoped) |
| GET | `/paper-trading/trade-log/{id}` | **Decision Explorer** full trace |
| GET | `/paper-trading/status` | Sim session status |
| POST | `/paper-trading/start` | Start sim session (`run_id=meta_learner`) |
| POST | `/paper-trading/rebalance` | Sim meta rebalance |
| GET | `/paper-trading/alpaca/portfolio` | Alpaca positions |
| POST | `/paper-trading/alpaca/rebalance` | Alpaca meta rebalance |

---

## Signals (**public**)

| Method | Path | Description |
|--------|------|-------------|
| GET | `/signals/top` | Latest signals (`market`, `limit`) |
| GET | `/signals/ticker/{ticker}` | Signal for one ticker |
| GET | `/signals/leaderboard` | Confidence leaderboard |

---

## ML / system

| Method | Path | Description |
|--------|------|-------------|
| GET | `/ml/meta/status` | Meta-learner loaded, EWMA init |
| GET | `/ml/weights/current` | EWMA fusion weights |
| GET | `/market/regime` | Current regime (US/EGX) |

---

## Admin only

| Area | Paths |
|------|-------|
| Data | `/data/download`, `/data/jobs` |
| Training | `/train/*` |
| Backtest | `/backtest` |
| ML pipeline | `/ml/train/*`, `/ml/oof/collect` |

---

## Mobile

| Method | Path | Description |
|--------|------|-------------|
| GET | `/mobile/dashboard` | Aggregated home payload |
| GET | `/mobile/health` | Connectivity check |

---

## Decision Explorer response shape

`GET /paper-trading/trade-log/{id}` returns:

```json
{
  "ticker": "JPM",
  "action": "BUY",
  "meta_probability_pct": 91.0,
  "model_votes": [{"model": "XGBoost", "vote": "BUY", "signal": 0.72}],
  "regime": {"market": "BULL", "volatility": "NORMAL"},
  "technicals": [{"label": "RSI", "value": "58"}],
  "fundamentals": {"pe_ratio": 18.4, "roe_pct": 21.0},
  "risk": {"position_size_pct": 4.2, "stop_loss_pct": 8.0},
  "final_explanation": "..."
}
```

---

## Error codes

| Code | Meaning |
|------|---------|
| 401 | Missing or invalid JWT |
| 403 | Admin required or registration disabled |
| 404 | Resource not found or not owned by user |
