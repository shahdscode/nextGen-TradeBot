# Deployment Guide

## Local development (recommended for thesis demo)

### Prerequisites

- Docker & Docker Compose
- Node 18+ (optional, for frontend dev server)
- Python 3.10+ (optional, for backend without Docker)

### Docker Compose (production-like)

```bash
cp .env.example .env
# Edit JWT_SECRET_KEY — required for ENVIRONMENT=production

docker compose up --build
```

| Service | URL |
|---------|-----|
| Frontend | http://localhost:80 |
| API | http://localhost:8000 |
| API docs | http://localhost:8000/docs |

### Local dev (hot reload)

```bash
# Terminal 1 — Redis
docker run -p 6379:6379 redis:7-alpine

# Terminal 2 — Backend
cd backend && uvicorn app.main:app --reload --port 8002

# Terminal 3 — Celery worker
cd backend && celery -A app.celery_app worker --loglevel=info

# Terminal 4 — Frontend
cd frontend && npm install && npm run dev
```

Frontend: http://localhost:5173 (proxies API per `vite.config`)

---

## Environment variables

See [`.env.example`](../.env.example). Critical vars:

| Variable | Purpose |
|----------|---------|
| `JWT_SECRET_KEY` | Auth tokens — **must change in production** |
| `ENVIRONMENT` | `development` \| `production` |
| `DATABASE_URL` | SQLite (dev) or PostgreSQL (prod) |
| `REDIS_URL` | Celery broker |
| `ALLOW_PUBLIC_REGISTER` | Open signup |
| `CORS_ORIGINS` | Comma-separated frontend origins |

---

## Production checklist (v1.1 target)

- [ ] PostgreSQL (e.g. Supabase) with automated backups
- [ ] HTTPS reverse proxy (Caddy / Nginx / Cloudflare)
- [ ] Strong `JWT_SECRET_KEY` in secrets manager
- [ ] `ENVIRONMENT=production`, `SEED_ADMIN=false` unless needed
- [ ] Health monitoring (`/health`) + error tracking (Sentry)
- [ ] Rate limit on `/api/auth/register` and `/api/signals`
- [ ] CI/CD pipeline (test → build → deploy)

### PostgreSQL

```env
DATABASE_URL=postgresql://user:pass@host:5432/tradebot
DATABASE_SSL_MODE=require
```

Run migrations via app startup (`create_tables()` + legacy column migrations).

### Data persistence

Mount `data/` volume for models, SQLite/exports, and OOF artifacts:

```yaml
volumes:
  - ./data:/data
```

---

## Model artifacts

Place under `data/models/`:

| File | Purpose |
|------|---------|
| `meta_learner.pkl` | Live meta-learner fusion |
| `calibrator.pkl` | Platt scaling (optional) |
| `deploy/xgb_deploy.pkl` | Pooled XGBoost |
| `deploy/lstm_deploy.pt` | Pooled LSTM |

Without these, signals fall back to fixed regime weights.

---

## Health checks

```bash
curl http://localhost:8000/health
curl http://localhost:8000/api/ml/meta/status
```

---

## Troubleshooting

| Issue | Fix |
|-------|-----|
| Celery tasks stuck | Ensure Redis is running; check `REDIS_URL` |
| Empty signal feed | Run meta-learner pipeline or scheduled signal job |
| Alpaca 401 | User must set keys in Settings |
| JWT warning on start | Set `JWT_SECRET_KEY` in `.env` |
