# NextGen TradeBot — GP2 Feature Inventory (Deployed Edition)

**Purpose:** Single source of truth for what is **actually implemented** in code and how it maps to the **deployed stack** (Vercel + Supabase + AWS).  
Use this when writing thesis chapters so Ch. 4 (design), Ch. 5 (implementation), and Ch. 6 (evaluation) stay consistent.

**Audit date:** 2026-06-20 (updated)  
**Project:** Nile University GP2 — AI-powered trading **decision-support** (no automatic live brokerage execution)

---

## 0. Deployed architecture (production)

```
┌─────────────────────────────────────────────────────────────────────────┐
│  VERCEL (Frontend)                                                       │
│  React 18 + Vite SPA · Landing page + Dashboard                          │
│  Env: VITE_API_URL → points to AWS backend                               │
└───────────────────────────────┬─────────────────────────────────────────┘
                                │ HTTPS /api/*
                                ▼
┌─────────────────────────────────────────────────────────────────────────┐
│  AWS (Backend compute — typical deployment)                              │
│  FastAPI + Uvicorn · Celery worker · Redis broker                         │
│  ML model artifacts on disk (XGB/LSTM/RL/meta-learner)                    │
│  MT5 gateway service (EGX data/prices) at configured EC2 IP              │
└───────────────────────────────┬─────────────────────────────────────────┘
                                │ PostgreSQL (SQLAlchemy)
                                ▼
┌─────────────────────────────────────────────────────────────────────────┐
│  SUPABASE (Database)                                                     │
│  PostgreSQL — 8 application tables                                       │
│  Connection via DATABASE_URL (SSL required)                              │
└─────────────────────────────────────────────────────────────────────────┘

Mobile (Expo) ──HTTPS──► AWS Backend (same API as web)
Alpaca Paper API ◄──────► AWS Backend (optional per-user keys)
Yahoo Finance / NewsAPI ◄─► AWS Backend (market data + sentiment)
```

| Layer | Platform | What runs there | Config |
|-------|----------|-----------------|--------|
| **Web UI** | **Vercel** | Static React build (`frontend/dist`), SPA routing via `vercel.json` | `VITE_API_URL` in Vercel env |
| **Database** | **Supabase** | PostgreSQL (users, signals, runs, backtests, jobs, …) | `DATABASE_URL`, `DATABASE_SSL_MODE=require` in backend `.env` |
| **API + ML + jobs** | **AWS** | FastAPI, Celery, Redis, model files, scheduler thread | Backend `.env` on server; Docker Compose also supported locally |
| **EGX price/data gateway** | **AWS EC2** (inferred) | MT5 gateway HTTP service | `MT5_GATEWAY_URL=http://51.21.209.128:8000` |
| **Mobile** | Expo (client devices) | React Native app calling same backend API | `EXPO_PUBLIC_API_URL` |

**Honest deployment notes:**
- Repo contains **Vercel config** (`frontend/vercel.json`) and **Supabase driver** (`psycopg2`, `database.py` PostgreSQL support).
- Repo does **not** contain Terraform/ECS/Elastic Beanstalk manifests — AWS deployment is operational but configured on the server, not fully codified in this repo.
- **Local dev** still supports SQLite (`data/finrl.db`) when `DATABASE_URL` is not set to Supabase.
- Model CSVs, OOF files, and trained weights remain on **backend disk** (not in Supabase).

---

## 1. System overview

| Layer | Technology | Status |
|-------|-----------|--------|
| Backend API | FastAPI + Uvicorn | ✅ Implemented |
| Background jobs | Celery + Redis | ✅ Implemented |
| Database | **Supabase PostgreSQL** (prod) / SQLite (local dev) | ✅ Implemented |
| Web frontend | React 18 + Vite + Tailwind | ✅ Implemented + **Vercel-ready** |
| Landing page | Animated public homepage at `/` | ✅ Implemented |
| Mobile app | React Native + Expo SDK 54 | ✅ Implemented |
| Containerization | Docker Compose (4 services) | ✅ Implemented (local/self-host) |
| Scheduling | Custom daemon thread (~21:00 UTC) | ✅ Implemented |

**Decision-support only:** Generates explainable BUY/HOLD/SELL signals. Alpaca **paper** trading is optional per-user.

---

## 2. AI / ML pipeline — what runs in production today

### 2.1 Default production signal path (daily batch)

```
Yahoo OHLCV → 25 features → deployable XGBoost + LSTM
  → PPO run signal (if published run exists)
  → HMM regime detection
  → FinBERT / CamelBERT sentiment (live headlines)
  → FIXED regime-weight fusion (XGB/LSTM/PPO only)
  → turbulence filter + risk guardrails
  → Signal card → Supabase signals table
```

**Not enabled by default in daily batch:** meta-learner fusion, EWMA adaptive weights (both implemented; used via explicit API/UI paths).

### 2.2 Full advanced pipeline (implemented, partially integrated)

```
7 base models → OOF predictions → meta-learner (logistic stacking)
  → optional Platt calibration
  → EWMA adaptive weights (read APIs exist; daily update hook missing)
  → turbulence filter → risk guardrails → signal card
```

---

## 3. Feature engineering (`feature_service.py`)

### 3.1 Feature count: **25**

| Group | Features |
|-------|----------|
| Original (21) | MACD, RSI-14/30, Bollinger, SMA-30/60, CCI-30, DX-30, ATR-14, volume z-score, momentum 5d/20d, fractional diff, turbulence, high-low range, gap, OBV z-score, EMA cross, vol-price corr |
| Upgrades (4) | `vix_level`, `vix_zscore` (US only), `price_range_position`, `rank_20d_mom` |

### 3.2 Target label

| Aspect | Design doc | **Actual** |
|--------|-----------|-----------|
| Target | 5-day sign | **Triple-barrier** (López de Prado) |
| Horizon | 5 days | **20 trading days** |
| Barrier | — | ±2.0 × 20-day volatility |

**Mismatch:** Meta-learner OOF ground truth still uses **5-day return** (`target_5d`), not triple-barrier.

### 3.3 Walk-forward

- Shared `fold_definitions.json` across XGB, LSTM, OOF
- 6-month train / 1-month test (presets in research router)
- `verify_no_leakage()` — 6 automated checks
- LSTM scaler fit on training fold only

---

## 4. Base models

### 4.1 XGBoost — ✅
Walk-forward, Optuna HPO, SHAP TreeExplainer, deployable `xgb_deploy.pkl`, API `POST /api/ml/train/xgboost`

### 4.2 LSTM — ✅
PyTorch, wavelet denoise, per-fold scaler, deployable `lstm_deploy.pt`, API `POST /api/ml/train/lstm`

### 4.3 FinRL (5 agents) — ✅

| Agent | Train | Fixed fusion | Meta path | Live allocation |
|-------|-------|--------------|-----------|-----------------|
| PPO | ✅ | ✅ | ✅ | ✅ |
| A2C | ✅ | ❌ | ✅ | ✅ |
| DDPG | ✅ | ❌ | ✅ | ✅ |
| TD3 | ✅ | ❌ | ✅ | ✅ |
| SAC | ✅ | ❌ | ✅ | ✅ |

FinRL + Stable-Baselines3; synthetic fallback if FinRL missing; 3-checkpoint expanding-window validation.

### 4.4 Meta-learner — ✅ (partial integration)
Logistic stacking on OOF, 11 features, time-ordered split, coefficient export, API + admin UI. **Not default daily path.**

### 4.5 Platt calibration — ✅ (API only)
`calibration_service.py`, reliability diagram PNG, `POST /api/ml/calibrate/{run_id}`. **No admin UI page.**

### 4.6 EWMA tracker — ⚠️ partial
Service + `model_performance_scores` table + read APIs + Model Weights page. **`update_scores_for_date()` never called from scheduler.**

### 4.7 OOF collector — ✅
XGB/LSTM/RL OOF CSVs, merged dataset, API `POST /api/ml/oof/collect`. Regime/sentiment merge stubbed empty in Celery task.

---

## 5. Explainability & context

### 5.1 SHAP — ✅
`shap.TreeExplainer` on XGBoost; stored in `signals.shap_features`; shown on web/mobile signal cards.

### 5.2 Sentiment — ✅

| | Implementation |
|--|----------------|
| English | FinBERT (`ProsusAI/finbert`) |
| Arabic EGX | CamelBERT sentiment model |
| Headlines | NewsAPI + Google News RSS + keyword fallback |
| In signals | Live at generation time |
| In meta-learner OOF | ❌ Removed (no historical news archive) |

### 5.3 Regime (HMM) — ✅
3-state Gaussian HMM + rule fallback → BULL/BEAR/SIDEWAYS; per-market JSON cache; regime-dependent fusion weights.

---

## 6. Signal fusion & risk (`fusion_service.py`)

**Priority:** meta-learner → EWMA → **fixed regime weights (default)**

| Regime | XGB | LSTM | PPO |
|--------|-----|------|-----|
| BULL | 45% | 35% | 20% |
| BEAR | 35% | 30% | 35% |
| SIDEWAYS | 40% | 35% | 25% |

**Actions:** BUY >0.60, HOLD 0.40–0.60, SELL <0.40, SUPPRESSED <0.55  
**Guardrails:** turbulence filter, drawdown kill-switch (15%), stop-loss (8%), BEAR defensive cash

---

## 7. Backtest engine — ✅

FinRL replay, meta backtest, 5 baselines, walk-forward, 3 stress tests, regime splits, significance tests, Almgren-Chriss slippage, JSONL step log.

**Metrics:** Sharpe, Sortino, max drawdown, return, win rate, AUC, accuracy, Brier, Calmar, regime splits, trade log.

---

## 8. Paper trading & brokers

| Module | Status |
|--------|--------|
| Internal simulated session | ✅ DB-backed `paper_sessions` |
| Alpaca paper (per-user keys) | ✅ Web + mobile portfolio/rebalance |
| MT5 gateway (AWS EC2) | ✅ Data + price quotes only; ❌ order execution |

---

## 9. FinCast (extra module) — ✅
MoE forecaster, Celery jobs, contextual-bandit backtest, web Market page. Not on mobile.

---

## 10. Database — Supabase PostgreSQL (8 tables)

| Table | Purpose |
|-------|---------|
| `users` | Auth, roles, per-user Alpaca keys |
| `jobs` | Async job tracking (download, train, backtest, …) |
| `runs` | ML/RL training runs + metrics + publish flag |
| `backtests` | Backtest results JSON |
| `signals` | Signal cards (action, confidence, SHAP, regime, probs) |
| `sentiment_scores` | Cached sentiment rows |
| `paper_sessions` | Simulated trading state |
| `model_performance_scores` | EWMA tracker scores/weights |

**Migration:** `backend/scripts/migrate_sqlite_to_supabase.py` copies SQLite → Supabase.

---

## 11. API inventory (~68 endpoints)

| Router | Prefix | Count | Highlights |
|--------|--------|-------|------------|
| Root | `/`, `/health`, `/api/info` | 3 | Health, FinRL status |
| auth | `/api/auth` | 6 | register, login, me, Alpaca config |
| data | `/api/data` | 6 | download, jobs, preview |
| training | `/api/train` | 7 | RL train, publish runs |
| ml | `/api/ml` | 12 | XGB/LSTM/regime, signals, OOF, meta, calibrate, EWMA |
| backtest | `/api/backtest` | 4 | run, results, step-log |
| signals | `/api/signals` | 4 | top, history, leaderboard |
| market | `/api/market` | 6 | overview, candles, news, regime |
| paper_trading | `/api/paper-trading` | 10 | session + Alpaca |
| research | `/api/research` | 6 | alpha pipeline, walk-forward presets |
| mobile | `/api/mobile` | 4 | dashboard aggregation |
| fincast | `/api/fincast` | 5 | forecast + backtest jobs |

Full interactive docs: `{BACKEND_URL}/docs`

---

## 12. Celery background tasks

| Task | Trigger |
|------|---------|
| `data_tasks.download` | Data page |
| `train_tasks.train` | RL training page |
| `backtest_tasks.run` | Backtest page |
| `ml_tasks.train_xgboost` / `train_lstm` | ML training page |
| `ml_tasks.generate_signals` | Publish page + daily scheduler |
| `meta_tasks.collect_oof` | Meta-learner page |
| `meta_tasks.train_meta_learner` | Meta-learner page |
| `meta_tasks.calibrate_model` | API only |
| `fincast_tasks.*` | Market page |

Requires **Redis** on AWS (or local).

---

## 13. Scheduler

| Job | Schedule | Action |
|-----|----------|--------|
| Daily signals | ~21:00 UTC | Generate US + EGX signals |
| Weekly rebalance | Monday ~21:00 UTC | Paper/Alpaca rebalance |

Daemon thread (not APScheduler). Runs inside backend process on AWS.

---

## 14. Web frontend (Vercel)

### Public routes

| Route | Page |
|-------|------|
| `/` | **Landing page** (animated hero, features, pipeline, CTA) |
| `/login` | Sign in |

### Authenticated app routes (`/app/*`)

| Route | Page | Role |
|-------|------|------|
| `/app` | Dashboard | Admin |
| `/app/data` | Data download | Admin |
| `/app/train` | RL training | Admin |
| `/app/ml-train` | XGB/LSTM training | Admin |
| `/app/meta-learner` | OOF + meta-learner | Admin |
| `/app/model-weights` | EWMA weights chart | Admin |
| `/app/performance` | Model performance | Admin |
| `/app/backtest` | Backtest engine | Admin |
| `/app/compare` | Equity curve compare | Admin |
| `/app/publish` | Publish runs + batch signals | Admin |
| `/app/paper-trading` | Paper + Alpaca | Admin |
| `/app/signals` | Signal cards + SHAP | All users |
| `/app/market` | Market + FinCast | All users |
| `/app/leaderboard` | Ranked signals | All users |
| `/app/simulator` | Simplified backtest | All users |

**Vercel config:** `frontend/vercel.json` — SPA rewrites, `VITE_API_URL` for backend.

---

## 15. Mobile app (Expo SDK 54)

| Screen | Features |
|--------|----------|
| Home | Regime, top signals, movers |
| Signals | Filtered signal list |
| Market | Candles, quote, news |
| Leaderboard | Ranked by confidence |
| Portfolio | Alpaca paper + rebalance |
| Profile | Auth, Alpaca keys |
| Auth | Splash, welcome, sign-in, **sign-up** |

**Not on mobile:** Admin training, backtest, FinCast, simulated EGX session.

---

## 16. Offline training pipeline (`scripts/`)

| Step | Script | Output |
|------|--------|--------|
| 1 | `step1_data_features.py` | Feature CSVs + `fold_definitions.json` |
| 2 | `step2_xgb_oof.py` | `xgb_oof_predictions.csv` |
| 3 | `step3_lstm_oof.py` | `lstm_oof_predictions.csv` |
| 4 | `step4_train_rl.py` | 5 RL models + signal CSVs |
| 5 | `step5_meta_learner.py` | `meta_learner.pkl` + calibrator |
| 6 | `step6_ewma_tracker.py` | EWMA simulation |
| — | `train_deployable_models.py` | Production deploy models |
| — | `fincast_eval.py` | FinCast evaluation |

Artifacts stored under `data/models/`, `data/oof/`, `data/results/` on AWS backend volume.

---

## 17. Evaluation (thesis Ch. 6 source)

**Document:** `docs/model_evaluation.md`

| Finding | Result |
|---------|--------|
| OOS directional AUC | **~0.51–0.52** (market-efficiency ceiling) |
| RL in-sample Sharpe | 1.2–2.8 |
| RL 2026 OOS | **Negative returns** (does not generalize) |
| System value | **Ensemble weighting + risk control**, not raw alpha |
| Protocol | Walk-forward, 20-day embargo, OOF meta-learner, leakage checks |

---

## 18. Planned vs implemented — gap matrix

| Feature | Claimed in design | **Actual** |
|---------|-------------------|-----------|
| 26 features | Planned | **25 implemented** |
| 5-day target | Planned | **Triple-barrier 20-day** |
| Meta-learner in daily signals | Planned | **Code exists; not default** |
| EWMA daily self-correction | Planned | **No scheduler hook** |
| All 5 RL in fixed fusion | Planned | **PPO only in fixed fusion** |
| APScheduler 07:00 UTC | Planned | **Daemon thread ~21:00 UTC** |
| Calibration UI | Planned | **API only** |
| MT5 live orders | Implied | **Data/prices only** |
| AraBERT | Named | **CamelBERT used** |
| Automated test suite | Expected | **None** (mobile smoke script only) |
| AWS IaC in repo | — | **Not codified** (operational deployment) |
| FinCast | Extra | **✅ Implemented** |
| Landing page | — | **✅ Implemented (Vercel)** |
| Supabase | — | **✅ PostgreSQL support + migration script** |

---

## 19. Security

- JWT (HS256), bcrypt passwords
- Admin vs user role gating
- Per-user Alpaca credentials in Supabase `users` table
- CORS `allow_origins=["*"]` on backend (required for Vercel cross-origin)
- Secrets in `.env` (never commit)

---

## 20. Thesis chapter mapping

| Chapter | Use sections |
|---------|-------------|
| Ch. 3 Requirements | §0 deployment, §1 overview, §14–15 UI |
| Ch. 4 Design | §3 features, §4 models, §6 fusion, §7 backtest, §10 DB |
| Ch. 5 Implementation | §0–2 pipeline, §11–13 APIs/tasks, §16 scripts |
| Ch. 6 Evaluation | §17 metrics + honest gaps from §18 |
| Ch. 7 Conclusion | §18 future work, §17 headline finding |

---

## 21. Ticker universes

- **US:** DOW 30 (~29 tickers) + VIX (`^VIX`)
- **EGX:** EGX 30 (~21 tickers, `.CA` suffix)

---

*Re-audit after major merges or deployment changes.*
