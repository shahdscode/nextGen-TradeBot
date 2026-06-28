# NextGen TradeBot — Architecture

> **NextGen TradeBot** is an AI-powered quantitative research and paper-trading platform that provides **complete decision provenance** for every trading decision.

---

## Layered architecture

```text
Users
        │
        ▼
Web / Mobile Clients
(React, React Native)
        │
        ▼
Application Layer
Home (Command Center) · Paper Trading · Signals
Decision Explorer · Settings · Admin (Train / Backtest)
        │
        ▼
AI Decision Layer
Meta-Learner · ML (XGBoost, LSTM) · RL (5 agents)
EWMA Adaptive Weights · Regime Detection · Risk Engine
        │
        ▼
Research Layer
Walk-Forward Validation · Backtests · Stress Tests
SHAP · Performance Attribution · Regime Analysis
        │
        ▼
Execution Layer
Paper Simulator (per-user) · Alpaca Paper (per-user keys)
        │
        ▼
Persistence
SQLite / PostgreSQL · Models · Trade Logs · Signals
```

---

## Component map

| Layer | Key modules | Responsibility |
|-------|-------------|--------------|
| **Clients** | `frontend/`, `mobile/` | UX, auth tokens, dashboards |
| **API** | `backend/app/routers/` | REST endpoints, auth, tenancy |
| **AI** | `fusion_service`, `meta_learner_service`, `ewma_tracker_service` | Signal fusion, calibration |
| **ML/RL** | `xgboost_service`, `lstm_service`, `train_service` | Base model training & inference |
| **Research** | `backtest_service`, `feature_service` | Offline validation |
| **Execution** | `live_trading_service`, `alpaca_service`, `paper_trading.py` | Allocations & orders |
| **Provenance** | `trade_log_service`, `decision_explorer_service` | Auditable trade decisions |
| **Jobs** | Celery + Redis | Long-running train/backtest/OOF tasks |

---

## Data flow — live signal

1. **Features** built from Yahoo Finance OHLCV (+ VIX for US).
2. **Base models** produce probabilities (deployable pooled models or per-run artifacts).
3. **Meta-learner** or EWMA/fixed weights fuse into one confidence score.
4. **Risk guardrails** apply (turbulence, drawdown, suppress thresholds).
5. **Signal** persisted to shared `signals` table → all users see the same feed.
6. On **rebalance**, allocation + sizing run; each BUY/SELL logged to `trade_logs` with model votes, regime, indicators, stops.

---

## Multi-tenancy model

| Resource | Scope |
|----------|--------|
| Signals, Runs, EWMA scores | **Shared** (system) |
| PaperSession, Backtest, Job, TradeLog | **Per-user** (`user_id`) |
| Alpaca credentials | **Per-user** (on `users` table) |

---

## Decision provenance

Every executed trade stores:

- Meta probability
- Per-model signals (7 models)
- Market + volatility regime
- Technical indicator snapshot
- Position weight, stop, target, risk dollars
- Human-readable reason + generated final explanation (Decision Explorer)

This enables reproducibility: *why* a trade happened, not only *what* happened.

---

## Tech stack

| Layer | Technology |
|-------|------------|
| Backend | FastAPI, SQLAlchemy, Celery, Redis |
| Frontend | React, Vite, Tailwind, Recharts |
| Mobile | React Native, Expo |
| ML | XGBoost, PyTorch LSTM, SHAP |
| RL | FinRL / Stable-Baselines3 |
| Deploy | Docker Compose |

---

## Out of scope (v1.0)

- Live (real-money) brokerage execution
- Per-user signal universes
- Stripe / subscriptions (planned v1.1)
