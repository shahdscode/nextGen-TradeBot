# FinRL Dashboard

A full-stack web dashboard for training, backtesting, and paper trading reinforcement learning agents using [FinRL](https://github.com/AI4Finance-Foundation/FinRL).

## Architecture

```
React (port 5173) → FastAPI (port 8000) → Celery Worker → FinRL core
                                        ↘ Redis (broker)
                                        ↘ SQLite (jobs, runs, backtests)
```

## Stack

| Layer      | Technology                        |
|------------|-----------------------------------|
| Frontend   | React + Vite + Tailwind + Recharts |
| Backend    | FastAPI + Uvicorn                  |
| Task queue | Celery + Redis                     |
| Database   | SQLite via SQLAlchemy              |
| ML         | FinRL + Stable-Baselines3          |

## Quick start

### 1. Clone and configure

```bash
git clone <your-repo>
cd finrl-dashboard
cp .env.example .env
```

### 2. Start all services

```bash
docker compose up --build
```

This starts:
- `backend` on http://localhost:8000
- `frontend` on http://localhost:5173
- `worker` (Celery background task runner)
- `redis` (message broker)

### 3. Seed demo data (optional)

Pre-populates the database with two trained agents and backtest results so the
dashboard is immediately usable:

```bash
docker compose exec backend python scripts/demo_seed.py
```

### 4. Open the dashboard

http://localhost:5173

## Usage

1. **Data page** — select tickers, date range, and source → download market data
2. **Train page** — pick an algorithm (PPO, A2C, DDPG, TD3, SAC), paste the Data Job ID → train
3. **Backtest page** — select a completed run → run backtest → view equity curve + metrics
4. **Compare page** — select up to 4 backtests → compare equity curves and metrics side by side
5. **Paper Trading** — configure MT5 gateway settings in `.env` to enable paper trading

## Paper trading setup

Add your MT5 gateway settings to `.env`:

```env
MT5_GATEWAY_URL=http://51.21.209.128:8000
MT5_API_KEY=your_key
MT5_TIMEFRAME=M15
```

Then restart: `docker compose restart backend worker`

## API docs

FastAPI auto-generates interactive docs at:
- Swagger UI: http://localhost:8000/docs
- ReDoc: http://localhost:8000/redoc

## Supported algorithms

| Algorithm | Description |
|-----------|-------------|
| PPO       | Proximal Policy Optimization — stable general-purpose baseline |
| A2C       | Advantage Actor-Critic — faster training |
| DDPG      | Deep Deterministic Policy Gradient — continuous action spaces |
| TD3       | Twin Delayed DDPG — reduced overestimation |
| SAC       | Soft Actor-Critic — entropy-regularized exploration |

## Project structure

```
finrl-dashboard/
├── ai-engine/
├── backend/
│   ├── app/
│   │   ├── main.py             # FastAPI entry point
│   │   ├── config.py           # Settings from env
│   │   ├── database.py         # SQLAlchemy models
│   │   ├── celery_app.py       # Celery config
│   │   ├── finrl_wrapper.py    # FinRL import bridge
│   │   ├── routers/            # API routes
│   │   ├── services/           # Business logic
│   │   ├── tasks/              # Celery tasks
│   │   └── models/             # Pydantic schemas
│   └── scripts/
│       └── demo_seed.py        # Pre-populate demo data
├── frontend/
│   └── src/
│       ├── App.jsx
│       ├── api/client.js       # Axios instance
│       ├── components/         # Reusable UI components
│       ├── pages/              # Route-level pages
│       └── hooks/              # Custom React hooks
├── docs/
├── infrastructure/
├── tests/
├── data/                       # Runtime datasets, models, results (gitignored)
├── requirements.txt            # Root install shortcut -> backend/requirements.txt
├── docker-compose.yml
└── .env.example
```

Note: `.env`, `.venv`, and `data/` are kept for local runtime and are intentionally not part of the tracked project skeleton.
