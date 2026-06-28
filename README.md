# NextGen TradeBot

**AI-powered quantitative research and paper-trading platform with complete decision provenance for every trading decision.**

Graduation project (GP2) · Nile University — decision-support only, not real-money execution.

---

## What it does

| For users | For admins / researchers |
|-----------|--------------------------|
| Daily Command Center | Walk-forward backtests |
| AI signals (US + EGX) | Meta-learner & OOF pipeline |
| Per-user paper trading | Train ML + 5 RL agents |
| Alpaca paper integration | Stress tests, SHAP, regimes |
| Decision Explorer (provenance) | Strategy comparison |

---

## Architecture

```text
Web / Mobile → FastAPI → Celery + Redis
                ↓
         Meta-Learner + Risk Engine
                ↓
    Paper Sim / Alpaca (per-user)
                ↓
         SQLite or PostgreSQL
```

See **[docs/ARCHITECTURE.md](docs/ARCHITECTURE.md)** for the full layered diagram.

---

## Quick start

```bash
cp .env.example .env
# Set JWT_SECRET_KEY in .env

docker compose up --build
```

| Service | URL |
|---------|-----|
| Web UI | http://localhost:80 |
| API | http://localhost:8000 |
| API docs | http://localhost:8000/docs |

**Dev login:** register at `/signup` or admin `admin` / `admin123` (development only).

**User landing:** `/app/home` (Command Center)

---

## Documentation

| Doc | Purpose |
|-----|---------|
| [CHANGELOG.md](CHANGELOG.md) | Version history |
| [docs/RELEASE_v1.0.md](docs/RELEASE_v1.0.md) | v1.0 release notes |
| [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) | System design |
| [docs/DEPLOYMENT.md](docs/DEPLOYMENT.md) | Local & production deploy |
| [docs/API.md](docs/API.md) | API overview |
| [docs/DEMO_SCRIPT.md](docs/DEMO_SCRIPT.md) | 15-min defense demo |

---

## Stack

| Layer | Technology |
|-------|------------|
| Backend | FastAPI, Celery, Redis, SQLAlchemy |
| Frontend | React, Vite, Tailwind, Recharts |
| Mobile | React Native (Expo) |
| ML | XGBoost, LSTM, SHAP, meta-learner |
| RL | FinRL (PPO, A2C, DDPG, TD3, SAC) |
| Deploy | Docker Compose |

---

## Project structure

```
nextGen-TradeBot/
├── backend/app/          # API, services, tasks
├── frontend/src/         # React web app
├── mobile/               # React Native app
├── data/                 # Models, DB, OOF (runtime)
├── docs/                 # Architecture & release docs
├── docker-compose.yml
└── .env.example
```

---

## Version

**Current release:** [v1.0.0](docs/RELEASE_v1.0.md) (2026-06-28)

**Next:** v1.1 — landing page, Stripe, email auth, production HTTPS (see CHANGELOG Unreleased).

---

## Disclaimer

This software is for **education and research**. It does not provide financial advice. Past backtest performance does not guarantee future results. Users are responsible for their own trading decisions.
