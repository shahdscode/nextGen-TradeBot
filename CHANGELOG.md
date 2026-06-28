# Changelog

All notable changes to **NextGen TradeBot** are documented here.

Format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/).  
Versioning follows [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

---

## [1.0.0] — 2026-06-28

First product release: AI quantitative research + paper trading with **decision provenance**.

### Added — AI & Research

- 7-model ensemble (XGBoost, LSTM, PPO, A2C, DDPG, TD3, SAC)
- Meta-learner stacking on out-of-fold predictions
- EWMA adaptive fusion weights
- HMM / rule-based regime detection
- 26-feature engineering pipeline with walk-forward validation
- SHAP explainability on XGBoost signals
- Backtest engine with Almgren-Chriss execution, stress tests, regime splits, bootstrap CIs
- FinBERT + AraBERT sentiment (US / EGX)

### Added — Product (SaaS)

- User registration, JWT authentication, role-based access (user / admin)
- Multi-tenant paper trading with per-user sessions and Alpaca credentials
- Shared AI signal feed (US DOW 30 + EGX)
- Web app: Command Center, Signals, Paper Trading, Settings, admin research tools
- React Native mobile app (6 screens)
- Portfolio Intelligence (sector/symbol allocation, diversification, beta)
- Command Center (daily portfolio health, AI summary, alerts)
- Decision Explorer + trade journal with full decision provenance
- Docker Compose production-like stack (backend, worker, Redis, frontend)

### Security & Config

- `ENVIRONMENT`, `ALLOW_PUBLIC_REGISTER`, `CORS_ORIGINS`, production JWT guard
- Per-user resource scoping (`user_id` on PaperSession, Backtest, Job)

### Documentation

- Architecture, deployment, API overview, demo script, release notes

---

## [Unreleased] — Planned for v1.1

- Landing page and onboarding
- Stripe subscriptions
- Email verification and password reset
- Managed PostgreSQL + HTTPS production deploy
- Terms of Service, Privacy Policy, financial disclaimer
- CI/CD, monitoring, rate limiting

---

[1.0.0]: https://github.com/your-org/nextgen-tradebot/releases/tag/v1.0.0
