# Release Notes — v1.0.0

**Release date:** 2026-06-28  
**Codename:** Decision Provenance  
**Status:** Feature-complete MVP for invite-only beta (paper trading + research)

---

## Positioning

> NextGen TradeBot is an AI-powered quantitative research and paper-trading platform that provides complete decision provenance for every trading decision.

**What it is:** Decision-support and research — not automated real-money investing.

**Who it's for:** Retail investors, students, and quants who want explainable AI signals and paper trading with their own Alpaca account.

---

## Highlights

### Intelligence
- 7-model ensemble with meta-learner trained on walk-forward OOF data
- Regime-aware fusion and EWMA adaptive weights
- Daily signal generation for US (DOW 30) and EGX

### Research (admin)
- Walk-forward backtests with transaction costs and Almgren-Chriss slippage
- Stress tests, regime splits, bootstrap confidence intervals, SHAP cards

### Product (all users)
- Register, login, per-user paper simulator + Alpaca paper keys
- **Command Center** — daily portfolio health, AI confidence, alerts
- **Portfolio Intelligence** — sector/symbol allocation, diversification, beta
- **Decision Explorer** — full provenance chain per trade

### Operations
- Docker Compose stack (API, Celery worker, Redis, Nginx frontend)
- Production config flags (`ENVIRONMENT`, CORS, JWT hardening)

---

## Upgrade notes

1. Copy `.env.example` → `.env` and set `JWT_SECRET_KEY`.
2. `docker compose up --build`
3. Register at `/signup` or use seeded admin (`SEED_ADMIN=true` in production).
4. Place trained artifacts in `data/models/` (`meta_learner.pkl`, `deploy/`).
5. Open `/app/home` after login.

---

## Known limitations

- SQLite default (use PostgreSQL for production — see `DEPLOYMENT.md`)
- Fundamentals in Decision Explorer are best-effort (Yahoo Finance)
- Backtest/train UI remains admin-only
- No email verification or Stripe (v1.1)

---

## What's next — v1.1

See [CHANGELOG.md](../CHANGELOG.md) Unreleased section.
