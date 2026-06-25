# NextGen TradeBot — Complete Claude Code Context

## What this project is
NextGen TradeBot is an AI-powered trading decision-support platform for 
retail investors. It generates explainable BUY/HOLD/SELL signals for US 
(DOW 30) and Egyptian (EGX) stocks using a 7-model ensemble, serves them 
through a React web app and React Native mobile app, and explains every 
signal in plain language using SHAP feature attribution.

This is a university graduation project (GP2) at Nile University, Egypt.
The system is decision-support only — it never executes real trades.

---

## Tech stack
| Layer | Technology |
|-------|-----------|
| Backend API | FastAPI + Uvicorn |
| Background jobs | Celery + Redis |
| Database | SQLite (7 tables) |
| Web frontend | React + Vite + Tailwind CSS (13 pages) |
| Mobile app | React Native + Expo SDK 54 (6 screens) |
| ML models | XGBoost, LSTM (PyTorch), FinRL PPO/A2C/DDPG/TD3/SAC |
| Explainability | SHAP TreeExplainer |
| Sentiment | FinBERT (English) + AraBERT (Arabic/EGX) |
| Regime detection | hmmlearn GaussianHMM (3-state) |
| Scheduling | APScheduler (daily batch 07:00 UTC) |
| Execution model | Almgren-Chriss square-root market impact |

---

## Project structure
```
project-root/
├── backend/
│   ├── app/
│   │   ├── main.py                    # FastAPI app, router registration, scheduler
│   │   ├── config.py                  # Settings (pydantic-settings, .env)
│   │   ├── database.py                # SQLAlchemy models, 7 tables
│   │   ├── celery_app.py              # Celery + Redis config
│   │   ├── finrl_wrapper.py           # FinRL import bridge, ticker lists
│   │   ├── routers/
│   │   │   ├── auth.py
│   │   │   ├── data.py
│   │   │   ├── training.py
│   │   │   ├── ml.py
│   │   │   ├── backtest.py
│   │   │   ├── paper_trading.py
│   │   │   ├── market.py
│   │   │   ├── signals.py
│   │   │   ├── research.py
│   │   │   └── mobile.py
│   │   ├── services/
│   │   │   ├── feature_service.py     # 21 features, walk-forward folds
│   │   │   ├── xgboost_service.py     # XGBoost + SHAP + Optuna
│   │   │   ├── lstm_service.py        # LSTM + wavelet denoising
│   │   │   ├── train_service.py       # FinRL RL agents
│   │   │   ├── fusion_service.py      # Signal fusion + risk guardrails
│   │   │   ├── regime_service.py      # HMM regime detection
│   │   │   ├── sentiment_service.py   # FinBERT + AraBERT
│   │   │   ├── backtest_service.py    # Backtest engine
│   │   │   └── data_service.py        # Data download
│   │   └── tasks/
│   │       ├── ml_tasks.py
│   │       ├── train_tasks.py
│   │       ├── data_tasks.py
│   │       └── backtest_tasks.py
│   ├── requirements.txt
│   └── Dockerfile
├── frontend/src/pages/                # 13 React pages
├── mobile/src/screens/                # 6 React Native screens
└── docker-compose.yml
```

---

## Database schema (SQLite, 7 tables)
All in backend/app/database.py using SQLAlchemy.
Key tables: User, Job, Run, Backtest, Signal, SentimentScore, PaperSession

Signal table key fields:
- action: "BUY" / "HOLD" / "SELL" / "SUPPRESSED"
- confidence: float 0-1
- xgb_signal, lstm_signal, rl_signal: individual model outputs
- shap_json: [{feature, shap_value, weight}]
- regime: "BULL" / "BEAR" / "SIDEWAYS"
- risk_level: "LOW" / "MEDIUM" / "HIGH"
- stop_loss_pct, sentiment_score, sentiment_label, top_headline

Run table key fields:
- algorithm: "xgboost" / "lstm" / "ppo" / "a2c" / "ddpg" / "td3" / "sac"
- published: Boolean
- market: "US" or "EGX"
- metrics_json: dict of performance metrics

---

## Current AI pipeline (fully working)

Raw OHLCV → 21 features → XGBoost + LSTM + PPO → HMM regime →
fixed-weight fusion → risk guardrails → signal card → Signal table

Feature engineering (feature_service.py): 21 features including
MACD, RSI-14/30, BB, SMA-30/60, CCI-30, DX-30, ATR-14,
Volume Z-score, Price Momentum 5d/20d, Fractional Diff (d=0.4),
Turbulence, High-Low Range, Gap, OBV Z-score, EMA Crossover,
Volume-Price Correlation

Walk-forward folds: 6-month train, 1-month step, 6 leakage checks

Current fusion weights (fusion_service.py):
- BULL:     XGBoost 45%, LSTM 35%, PPO 20%
- BEAR:     XGBoost 35%, LSTM 30%, PPO 35%
- SIDEWAYS: XGBoost 40%, LSTM 35%, PPO 25%

Confidence thresholds:
- BUY > 0.60, HOLD 0.40-0.60, SELL < 0.40, SUPPRESSED < 0.55

Risk guardrails:
1. Confidence < 0.55 → SUPPRESSED
2. Turbulence > threshold → HIGH_VOLATILITY flag
3. Portfolio drawdown > 15% → MAX_DRAWDOWN flag

---

## What needs to be built — AI improvement

### WHY we are building this
Current system uses fixed fusion weights chosen by theory.
New system learns optimal weights from real Yahoo Finance returns.
All 5 RL models included (not just PPO).
System self-corrects every day without retraining.

### Architecture of new system
7 base models → OOF predictions → Meta-learner (trained on Yahoo returns)
                                → Adaptive EWMA weights (daily updates)
                                → Calibrated confidence (Platt scaling)
                                → Turbulence hard filter
                                → Risk guardrails → Signal card

---

## NEW COMPONENT 1: Feature upgrades
File: backend/app/services/feature_service.py

### 1a. Add VIX feature (US tickers only)
```python
# Download ^VIX from yfinance and add two columns:
# vix_level: raw daily VIX close value
# vix_zscore: (vix - vix.rolling(20).mean()) / vix.rolling(20).std()
# For EGX tickers: set vix_level=0.0, vix_zscore=0.0
```

### 1b. Add 52-week position feature
```python
# high_252 = close.rolling(252).max()
# low_252 = close.rolling(252).min()
# price_range_position = (close - low_252) / (high_252 - low_252 + 1e-9)
# Range: 0 (at 52-week low) to 1 (at 52-week high)
```

### 1c. Add cross-sectional momentum rank
```python
# For each date, rank each ticker's 20-day momentum
# within all tickers being processed.
# rank_20d_mom: percentile rank 0-1 among all tickers that day
# Must be computed before walk-forward split (no leakage risk
# because it only uses past returns)
```

### 1d. Change target from 1-day to 5-day forward return
```python
# CURRENT (replace this):
df["target"] = (df["log_return_1d"].shift(-1) > 0).astype(float)

# NEW (use this):
df["log_return_5d_fwd"] = np.log(close.shift(-5) / (close + 1e-9))
df["target"] = (df["log_return_5d_fwd"] > 0).astype(float)

# CRITICAL: drop last 5 rows of each training fold to avoid leakage
# In walk_forward_folds(): train = train.iloc[:-5]
```

Total features after upgrade: 26 (was 21)

---

## NEW COMPONENT 2: OOF Prediction Collector
File to create: backend/app/services/oof_collector_service.py

```python
"""
Out-of-Fold (OOF) Prediction Collector.

Runs all base models through walk-forward folds and stores
their predictions on held-out data only.

These OOF predictions become the training data for the meta-learner.

CRITICAL RULE: A prediction in the OOF dataset was made by a model
that did NOT train on that row. This prevents leakage in the meta-learner.

Example:
  Fold 1: train months 1-6, test month 7
    → XGBoost trained on months 1-6
    → XGBoost predicts on month 7
    → Those month-7 predictions go into OOF dataset
  Fold 2: train months 1-7, test month 8
    → XGBoost trained on months 1-7
    → XGBoost predicts on month 8
    → Those month-8 predictions go into OOF dataset
  ... and so on for all folds

Result: OOF dataset covers the entire test period
with no data leakage anywhere.
"""

def collect_xgb_oof(df: pd.DataFrame, 
                     fold_definitions_path: str) -> pd.DataFrame:
    """
    Returns dataframe columns:
    date, ticker, xgb_signal (0-1), xgb_shap_top3 (JSON)
    """

def collect_lstm_oof(df: pd.DataFrame,
                      fold_definitions_path: str) -> pd.DataFrame:
    """
    Uses IDENTICAL fold definitions as XGBoost.
    Returns: date, ticker, lstm_signal (0-1)
    """

def collect_rl_signals(trained_model_paths: dict,
                        test_df: pd.DataFrame) -> pd.DataFrame:
    """
    RL models are backtested on test period.
    Map action signals to 0-1 range.
    Returns: date, ticker, ppo_signal, a2c_signal,
             ddpg_signal, td3_signal, sac_signal
    """

def merge_oof_predictions(xgb_oof, lstm_oof, rl_signals,
                           regime_history, sentiment_history,
                           price_df) -> pd.DataFrame:
    """
    Merge all OOF predictions by (date, ticker).
    Add regime and sentiment for each date.
    Add actual 5-day forward return from price_df as ground truth.
    
    Output columns:
    date, ticker,
    xgb_signal, lstm_signal,
    ppo_signal, a2c_signal, ddpg_signal, td3_signal, sac_signal,
    regime_bull (0/1), regime_bear (0/1),
    sentiment_score (-1 to 1),
    vix_zscore,
    actual_5d_return (float),
    target_5d (1 if return > 0 else 0)  <- GROUND TRUTH
    """

def save_oof_dataset(df: pd.DataFrame, output_path: str):
    """Save as CSV."""

def load_oof_dataset(path: str) -> pd.DataFrame:
    """Load and validate. Raise if missing required columns."""
```

---

## NEW COMPONENT 3: Meta-Learner Service
File to create: backend/app/services/meta_learner_service.py

```python
"""
Meta-Learner — Stacking Ensemble.

The team's original AI model.
Takes 7 base model signals + regime + sentiment as input.
Learns from real Yahoo Finance 5-day returns which combination
actually predicts the market correctly.

The logistic regression coefficients = learned optimal weights.
This replaces hand-coded fixed fusion weights with data-driven weights.

Academic references:
- Wolpert (1992) Stacked Generalization
- Breiman (1996) Stacked Regressions
"""

META_LEARNER_FEATURES = [
    "xgb_signal",
    "lstm_signal", 
    "ppo_signal",
    "a2c_signal",
    "ddpg_signal",
    "td3_signal",
    "sac_signal",
    "regime_bull",
    "regime_bear",
    "sentiment_score",
    "vix_zscore",
]

def train_meta_learner(oof_dataset_path: str,
                        model_save_path: str) -> dict:
    """
    Train logistic regression on OOF predictions.
    
    Steps:
    1. Load OOF dataset (from oof_collector_service)
    2. Features: META_LEARNER_FEATURES
    3. Target: target_5d (1 if 5-day return > 0)
    4. Time-ordered split: first 70% train, last 30% val
       NEVER use random split — this is time series data
    5. StandardScaler fitted on train portion only
    6. LogisticRegression(C=1.0, max_iter=1000, random_state=42)
    7. Evaluate on validation: AUC, accuracy, Brier score
    8. Save model + scaler + feature_list + coefficients as JSON
    
    Returns: {
        "model_path": str,
        "coefficients": {feature_name: coefficient_value},
        "auc": float,
        "accuracy": float,
        "brier_score": float,
        "n_train": int,
        "n_val": int,
        "top_features": [{"feature": str, "importance": float}]
    }
    """

def predict_meta_learner(model_path: str,
                          feature_dict: dict) -> dict:
    """
    Inference for a single observation.
    
    feature_dict keys: META_LEARNER_FEATURES
    
    Returns: {
        "probability": float,   # calibrated 0-1
        "signal": float,        # same as probability
        "method": "meta_learner",
        "feature_contributions": {feature: contribution}
    }
    """

def get_learned_weights(model_path: str) -> dict:
    """
    Return coefficients as normalized weights (sum to 1).
    Used for display in admin UI.
    Shows which models the meta-learner trusts most.
    """

def compare_with_fixed_weights(oof_dataset_path: str,
                                 fixed_weights: dict) -> dict:
    """
    Compare meta-learner vs current fixed fusion on validation set.
    Returns: {
        "meta_learner": {sharpe, auc, win_rate, brier_score},
        "fixed_weights": {sharpe, auc, win_rate},
        "improvement": {sharpe_delta, auc_delta, win_rate_delta}
    }
    """
```

---

## NEW COMPONENT 4: Confidence Calibration Service
File to create: backend/app/services/calibration_service.py

```python
"""
Confidence Calibration using Platt Scaling.

Problem: ML models are often overconfident.
Fix: Fit logistic regression mapping raw scores to real probabilities.

After calibration: 75% confidence = correct ~75% of the time historically.

Academic reference:
Platt (1999) — Probabilistic Outputs for Support Vector Machines
"""

def fit_calibrator(raw_scores: np.ndarray,
                    actual_outcomes: np.ndarray,
                    save_path: str) -> dict:
    """
    Fit Platt scaling.
    
    raw_scores: array of model outputs (0-1)
    actual_outcomes: array of 1 (correct prediction) or 0 (wrong)
    
    Returns: {
        "brier_score_before": float,
        "brier_score_after": float,
        "reliability_data": [
            {"bin_center": float, "fraction_positive": float, "count": int}
        ]
    }
    """

def calibrate_score(raw_score: float,
                     calibrator_path: str) -> float:
    """Apply calibration to a single raw score."""

def plot_reliability_diagram(reliability_data: list,
                               save_path: str) -> str:
    """
    Save reliability diagram as PNG for thesis.
    X: mean predicted probability per bin
    Y: fraction of positives per bin
    Perfect calibration = diagonal line
    """
```

---

## NEW COMPONENT 5: Adaptive EWMA Tracker
File to create: backend/app/services/ewma_tracker_service.py

```python
"""
Adaptive EWMA Performance Tracker.

Every day after market close:
1. Check if each model's signal was correct
2. Update EWMA performance score for each model
3. Compute new fusion weights proportional to scores
4. Store in database for history and visualization

Decay factor λ=0.94 means recent performance matters more.
All 7 models tracked independently — the market decides
which RL algorithm is most accurate right now.

Academic reference:
Freund & Schapire (1997) — A Decision-Theoretic Generalization
of On-Line Learning (Hedge Algorithm)
"""

MODEL_KEYS = ["xgboost", "lstm", "ppo", "a2c", "ddpg", "td3", "sac"]
EWMA_DECAY = 0.94       # λ — 0.94 = ~16-day effective half-life
MIN_WEIGHT = 0.02       # floor so no model is completely ignored
INITIAL_SCORE = 0.5     # start equal for all models

def initialize_tracker(db_session) -> None:
    """
    Create initial equal scores for all 7 models.
    Only runs once — checks if already initialized.
    """

def update_scores_for_date(date: str,
                             model_predictions: dict,
                             actual_returns: dict,
                             db_session) -> dict:
    """
    Update EWMA scores based on outcomes for one date.
    
    model_predictions: {
        "xgboost": float,  # signal from yesterday (0-1)
        "lstm": float,
        "ppo": float,
        ... all 7 models
    }
    actual_returns: {ticker: actual_return_today (float)}
    
    For each model:
        predicted_up = signal > 0.5
        actual_up = actual_return > 0
        correct = 1.0 if predicted_up == actual_up else 0.0
        new_score = EWMA_DECAY * old_score + (1 - EWMA_DECAY) * correct
    
    Save to model_performance_scores table.
    Returns: new scores dict
    """

def get_current_weights(db_session) -> dict:
    """
    Return current fusion weights proportional to EWMA scores.
    Apply MIN_WEIGHT floor. Normalize to sum to 1.0.
    
    Returns: {
        "xgboost": float,
        "lstm": float,
        "ppo": float,
        "a2c": float,
        "ddpg": float,
        "td3": float,
        "sac": float,
        "method": "ewma_adaptive",
        "updated_at": str
    }
    """

def get_weight_history(days: int = 30, db_session = None) -> list:
    """
    Return last N days of weight evolution.
    Used for admin dashboard chart.
    
    Returns: [{
        "date": str,
        "xgboost": float,
        "lstm": float,
        ... all 7 models,
        "top_model": str
    }]
    """
```

---

## NEW COMPONENT 6: Updated fusion_service.py
File to modify: backend/app/services/fusion_service.py

### Change 1: Add turbulence hard filter
```python
TURBULENCE_SUPPRESS_PERCENTILE = 90

def apply_turbulence_filter(fusion_result: dict,
                              current_turbulence: float,
                              turbulence_history: list) -> dict:
    """
    Suppress BUY signals when turbulence is extreme.
    HOLD and SELL are not affected.
    
    Based on: Kritzman et al. (2010) — Skulls, Financial Turbulence,
    and Risk Management
    """
    if fusion_result.get("action") != "BUY":
        return fusion_result
    if not turbulence_history:
        return fusion_result
    threshold = np.percentile(turbulence_history, 
                               TURBULENCE_SUPPRESS_PERCENTILE)
    if current_turbulence > threshold:
        fusion_result["action"] = "HOLD"
        fusion_result["turbulence_suppressed"] = True
        return fusion_result
    return fusion_result
```

### Change 2: Update fuse_signals to use meta-learner OR adaptive weights
```python
def fuse_signals(
    xgb_signal,
    lstm_signal,
    ppo_signal,
    a2c_signal=None,       # NEW — all 5 RL models
    ddpg_signal=None,      # NEW
    td3_signal=None,       # NEW
    sac_signal=None,       # NEW
    regime="UNKNOWN",
    sentiment_score=None,
    use_meta_learner=False,      # NEW — set True when meta-learner trained
    meta_learner_path=None,      # NEW
    use_adaptive_weights=False,  # NEW — set True when EWMA initialized
    db_session=None,
):
    """
    Priority order:
    1. If use_meta_learner=True and model exists: use meta-learner
    2. Elif use_adaptive_weights=True: use EWMA weights from tracker
    3. Else: fall back to current fixed regime weights (backward compatible)
    """
```

### Change 3: Update generate_full_signal
```python
def generate_full_signal(
    ticker,
    xgb_result,
    lstm_result,
    ppo_result=None,
    a2c_result=None,     # NEW
    ddpg_result=None,    # NEW
    td3_result=None,     # NEW
    sac_result=None,     # NEW
    sentiment=None,
    regime="UNKNOWN",
    current_price=None,
    turbulence=None,
    turbulence_history=None,  # NEW
    date=None,
    meta_learner_path=None,
    calibrator_path=None,
    db_session=None,
):
```

---

## NEW COMPONENT 7: Database addition
File to modify: backend/app/database.py

```python
class ModelPerformanceScore(Base):
    """Daily EWMA scores for adaptive weight tracker."""
    __tablename__ = "model_performance_scores"
    id = Column(String, primary_key=True)
    date = Column(String, nullable=False)
    model_key = Column(String, nullable=False)  # "xgboost", "lstm", etc.
    ewma_score = Column(Float, nullable=False)
    daily_correct = Column(Float, nullable=True)  # 1/0/0.5
    weight = Column(Float, nullable=True)          # normalized weight
    created_at = Column(DateTime, default=datetime.utcnow)
```

Also add to create_tables():
```python
ModelPerformanceScore.__table__.create(bind=engine, checkfirst=True)
```

---

## NEW COMPONENT 8: New API endpoints
File to modify: backend/app/routers/ml.py

```python
# Add these endpoints:

POST /api/ml/oof/collect
# Trigger OOF collection for all trained models
# Dispatches Celery task, returns job_id

POST /api/ml/train/meta-learner  
# Train meta-learner on collected OOF predictions
# Returns: {run_id, learned_weights, metrics}

POST /api/ml/calibrate/{run_id}
# Apply Platt scaling to a trained model
# Returns: {brier_before, brier_after, reliability_diagram_path}

GET /api/ml/weights/current
# Return current EWMA adaptive weights for all 7 models
# Returns: {xgboost: float, lstm: float, ppo: float, ...}

GET /api/ml/weights/history?days=30
# Return weight evolution over last N days
# Returns: [{date, model_weights, top_model}]

GET /api/ml/performance/scores
# Return current EWMA scores for all 7 models
# Used for admin debugging
```

---

## Training sequence — MUST follow this order

```
Step 1 — PERSON 1: Data + features
  Download 4 years (2020-2024) all US + EGX tickers
  Add VIX column for US tickers
  Run feature engineering (outputs 26 features)
  Change target to 5-day forward return
  Generate fold_definitions.json (shared by ALL models)
  Run verify_no_leakage() — must pass before proceeding
  Output: feature CSVs + fold_definitions.json

Step 2 — PERSON 2: XGBoost OOF
  Train XGBoost on each fold using fold_definitions.json
  Optuna HPO on folds 1-3 only, apply best params to all
  Collect OOF predictions + SHAP values
  Output: xgb_oof_predictions.csv

Step 3 — PERSON 3: LSTM OOF
  Train LSTM on each fold (SAME fold_definitions.json)
  Wavelet denoising + per-fold scaler
  Collect OOF predictions
  Output: lstm_oof_predictions.csv

Step 4 — PERSON 4: All 5 RL models
  Train PPO, A2C, DDPG, TD3, SAC (identical environment)
  Backtest each on test period, record daily signals
  Record episode reward curves
  Output: rl_signals.csv

Step 5 — PERSON 2: Meta-learner
  Merge all OOF predictions
  Add actual Yahoo Finance 5-day returns as ground truth
  Train logistic regression meta-learner
  Apply Platt scaling calibration
  Output: meta_learner.pkl + calibrator.pkl

Step 6 — PERSON 2: EWMA tracker
  Initialize equal scores for all 7 models
  Simulate through test period, update scores daily
  Output: model_performance_scores in database

Step 7 — PERSON 5: Evaluation
  Run comparison table (all systems on held-out test period)
  Regime-split analysis (BULL/BEAR/SIDEWAYS)
  US vs EGX comparison
  Write docs/model_evaluation.md
  Update thesis Chapter 4
```

---

## Critical rules — never violate

1. Walk-forward only — no random 80/20 splits
2. OOF predictions only for meta-learner training
3. LSTM scaler: fit on training fold ONLY
4. 5-day target: drop last 5 rows of each training fold
5. Shared fold definitions: ALL models use identical boundaries
6. Transaction costs: 0.1% fee + Almgren-Chriss slippage in all backtests
7. verify_no_leakage() must pass on every fold
8. VIX features: US tickers only (EGX gets 0.0)

---

## What already works — do not break

- 45+ API endpoints across 11 routers
- JWT auth (POST /auth/register, /login, GET /me)
- SHAP explainability on XGBoost
- HMM regime detection + rule-based fallback
- FinBERT + AraBERT sentiment (lazily loaded)
- Signal card builder in fusion_service.py
- APScheduler daily batch 07:00 UTC
- Backtest engine with Almgren-Chriss execution model
- 5 baseline comparisons in backtest
- Stress tests
- Per-step JSONL debug log
- MT5 paper trading gateway
- Mobile aggregation endpoint (GET /api/mobile/dashboard)
- Docker Compose production setup

---

## Code patterns to follow

### New service file
Follow xgboost_service.py pattern:
- Lazy imports (try/except for optional deps)
- Separate train() and predict() functions
- Return standardized dict
- logger.info() for progress
- Save artifacts to settings.models_dir
- Return {"model_path": str, "metrics": dict}

### New Celery task
Follow ml_tasks.py pattern:
- @celery_app.task(bind=True, name="tasks.task_name")
- Update Run status "running" at start
- Update Run status "done" or "failed" at end
- try/except/finally with db.close()

### New API endpoint
Follow ml.py router pattern:
- Pydantic request model
- Dispatch Celery for long-running work
- Return {run_id, status: "pending"} immediately
- SessionLocal() in try/finally

### Database ops
- str(uuid.uuid4()) for all IDs
- Dates as "YYYY-MM-DD" strings
- JSON fields accept Python dicts directly
- Always db.close() in finally block

---

## Academic citations for each new component

Meta-learner:   Wolpert (1992) Stacked Generalization
                Breiman (1996) Stacked Regressions
Adaptive EWMA:  Freund & Schapire (1997) Hedge Algorithm
Turbulence:     Kritzman et al. (2010) Skulls, Financial Turbulence
Calibration:    Platt (1999) Probabilistic Outputs for SVMs
Walk-forward:   Arnott et al. (2019) Backtesting Protocol in ML Era
Frac diff:      Lopez de Prado (2018) Advances in Financial ML

---

## Expected new files after full implementation

backend/app/services/oof_collector_service.py
backend/app/services/meta_learner_service.py
backend/app/services/calibration_service.py
backend/app/services/ewma_tracker_service.py
backend/app/services/feature_service.py     (modified)
backend/app/services/fusion_service.py      (modified)
backend/app/database.py                     (modified - new table)
backend/app/routers/ml.py                   (modified - new endpoints)
docs/model_evaluation.md                    (thesis comparison table)
data/oof/xgb_oof_predictions.csv
data/oof/lstm_oof_predictions.csv
data/oof/rl_signals.csv
data/oof/merged_oof_dataset.csv
data/models/meta_learner.pkl
data/models/calibrator.pkl
data/models/fold_definitions.json
