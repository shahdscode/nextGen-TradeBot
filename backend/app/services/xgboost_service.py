"""
XGBoost service with SHAP explainability and walk-forward evaluation.
Falls back to sklearn GradientBoostingClassifier when xgboost is not installed.

Step-1 compatibility:
- 25 features (includes vix_level/vix_zscore, price_range_position, rank_20d_mom)
- 5-day forward-return target (handled by build_features — no change needed here)
- Mahalanobis turbulence applied when CSV contains multiple tickers
- VIX downloaded once for US tickers, passed to build_features
- Holdout split is dynamic (last 20% of data) instead of hardcoded year
"""
import json
import logging
import uuid
import numpy as np
import pandas as pd
from pathlib import Path
from typing import Dict, Any, List, Optional, Tuple

from app.config import settings
from app.services.feature_service import (
    build_features,
    generate_walk_forward_folds,
    prepare_xy,
    FEATURE_COLUMNS,
    add_mahalanobis_turbulence,
    add_cross_sectional_rank,
    download_vix,
)

logger = logging.getLogger(__name__)

try:
    import xgboost as xgb
    XGB_AVAILABLE = True
except ImportError:
    XGB_AVAILABLE = False

try:
    import shap
    SHAP_AVAILABLE = True
except ImportError:
    SHAP_AVAILABLE = False

try:
    import optuna
    optuna.logging.set_verbosity(optuna.logging.WARNING)
    OPTUNA_AVAILABLE = True
except ImportError:
    OPTUNA_AVAILABLE = False

try:
    from sklearn.ensemble import GradientBoostingClassifier
    from sklearn.metrics import roc_auc_score
    SKLEARN_AVAILABLE = True
except ImportError:
    SKLEARN_AVAILABLE = False


def train_xgboost(
    run_id: str,
    data_job_id: str,
    ticker: str,
    n_trials: int = 30,
    market: str = "us",
) -> Dict[str, Any]:
    """
    Train XGBoost with Optuna HPO and walk-forward evaluation.

    Parameters
    ----------
    run_id       : unique run identifier
    data_job_id  : ID of the completed data download job
    ticker       : ticker symbol to train on
    n_trials     : Optuna HPO trials on the first fold
    market       : "us" or "egx" — controls VIX download
    """
    data_path = Path(settings.data_dir) / data_job_id / "data.csv"
    model_dir = Path(settings.models_dir) / run_id
    model_dir.mkdir(parents=True, exist_ok=True)

    df_raw = pd.read_csv(data_path)
    if "tic" not in df_raw.columns:
        df_raw["tic"] = ticker
    tickers_available = df_raw["tic"].unique().tolist()
    if ticker not in tickers_available:
        ticker = tickers_available[0]

    # ── Cross-sectional preprocessing (multi-ticker path) ────────────────────
    # Mahalanobis turbulence and cross-sectional rank require all tickers.
    # When the CSV has >1 ticker, compute them here. Single-ticker CSVs fall
    # back to the per-ticker proxy already stored in the CSV.
    if len(tickers_available) > 1:
        logger.info("Multi-ticker CSV (%d tickers) — computing Mahalanobis turbulence "
                    "and cross-sectional momentum rank", len(tickers_available))
        df_raw = add_mahalanobis_turbulence(df_raw)
        df_raw = add_cross_sectional_rank(df_raw)

    # ── VIX for US tickers ────────────────────────────────────────────────────
    vix_df = None
    is_egx = ticker.upper().endswith(".CA") or market.lower() == "egx"
    if not is_egx:
        try:
            dates = pd.to_datetime(df_raw["date"])
            vix_df = download_vix(str(dates.min().date()), str(dates.max().date()))
        except Exception as exc:
            logger.warning("VIX download failed: %s — vix features will be 0", exc)

    featured = build_features(df_raw, ticker, vix_df=vix_df)
    if len(featured) < 80:
        return _synthetic_xgb_result(model_dir, ticker)

    folds = generate_walk_forward_folds(featured, train_months=12, test_months=1)
    if not folds:
        return _synthetic_xgb_result(model_dir, ticker)

    # ── HPO on first 3 folds to get stable params ─────────────────────────────
    hpo_folds = folds[:3]
    X_hpo_tr = np.vstack([prepare_xy(tr)[0] for tr, _ in hpo_folds])
    y_hpo_tr = np.hstack([prepare_xy(tr)[1] for tr, _ in hpo_folds])
    X_hpo_te = np.vstack([prepare_xy(te)[0] for _, te in hpo_folds])
    y_hpo_te = np.hstack([prepare_xy(te)[1] for _, te in hpo_folds])
    best_params = _hpo(X_hpo_tr, y_hpo_tr, X_hpo_te, y_hpo_te, n_trials=n_trials)

    # ── Walk-forward evaluation ───────────────────────────────────────────────
    fold_metrics = []
    for train_df, test_df in folds:
        X_tr, y_tr = prepare_xy(train_df)
        X_te, y_te = prepare_xy(test_df)
        model = _build_model(best_params)
        model.fit(X_tr, y_tr)
        probs = model.predict_proba(X_te)[:, 1]
        preds = (probs >= 0.5).astype(int)
        acc = float(np.mean(preds == y_te)) if len(y_te) > 0 else 0.5
        auc = float(roc_auc_score(y_te, probs)) if len(np.unique(y_te)) > 1 else 0.5
        fold_metrics.append({"accuracy": round(acc, 4), "auc": round(auc, 4)})

    mean_acc = float(np.mean([f["accuracy"] for f in fold_metrics]))
    mean_auc = float(np.mean([f["auc"] for f in fold_metrics]))

    # ── Dynamic holdout: last 20% of data (not hardcoded year) ───────────────
    val_auc, val_acc = mean_auc, mean_acc
    n = len(featured)
    split_idx = int(n * 0.80)
    if n - split_idx >= 30 and split_idx >= 80:
        train_part = featured.iloc[:split_idx]
        val_part   = featured.iloc[split_idx:]
        if len(np.unique(prepare_xy(val_part)[1])) > 1:
            X_vt, y_vt = prepare_xy(train_part)
            X_vv, y_vv = prepare_xy(val_part)
            vm = _build_model(best_params)
            vm.fit(X_vt, y_vt)
            vprobs = vm.predict_proba(X_vv)[:, 1]
            val_acc = float(np.mean((vprobs >= 0.5).astype(int) == y_vv))
            val_auc = float(roc_auc_score(y_vv, vprobs))

    # ── Final model on all data ───────────────────────────────────────────────
    X_all, y_all = prepare_xy(featured.dropna())
    final_model = _build_model(best_params)
    final_model.fit(X_all, y_all)

    model_path = str(model_dir / f"xgb_{ticker}.pkl")
    _save_model(final_model, model_path)

    shap_importance = _compute_shap_importance(final_model, X_all)

    metrics = {
        "ticker":               ticker,
        "market":               market,
        "algorithm":            "xgboost",
        "model_type":           "xgboost",
        "n_features":           X_all.shape[1],
        "mean_accuracy":        round(mean_acc, 4),
        "mean_auc":             round(mean_auc, 4),
        "holdout_auc":          round(val_auc, 4),
        "holdout_accuracy":     round(val_acc, 4),
        "holdout_split":        "last 20%",
        "alpha_quality_ok":     val_auc >= 0.52,
        "n_folds":              len(fold_metrics),
        "fold_metrics":         fold_metrics,
        "best_params":          best_params,
        "shap_importance":      shap_importance,
        "vix_features_used":    vix_df is not None and not vix_df.empty,
        "mahalanobis_turbulence": len(tickers_available) > 1,
        "final_reward":         round(mean_auc, 4),
    }

    with open(model_dir / "metrics.json", "w") as f:
        json.dump(metrics, f, indent=2)

    return {"model_path": model_path, "metrics": metrics}


def predict_xgboost(
    features: np.ndarray,
    model_path: str,
    feature_names: Optional[List[str]] = None,
) -> Dict[str, Any]:
    """Run inference and return signal probability + SHAP explanation."""
    try:
        model = _load_model(model_path)
        prob = float(model.predict_proba(features.reshape(1, -1))[0][1])
        shap_features = _compute_shap_local(model, features, feature_names or FEATURE_COLUMNS)
        return {"probability": round(prob, 4), "shap_features": shap_features}
    except Exception as exc:
        logger.warning("predict_xgboost failed: %s — returning neutral 0.5", exc)
        return {
            "probability": 0.5,
            "shap_features": [],
        }


# ── Internal helpers ─────────────────────────────────────────────────────────

def _hpo(X_tr, y_tr, X_te, y_te, n_trials: int = 30) -> dict:
    if not OPTUNA_AVAILABLE or not SKLEARN_AVAILABLE:
        return {"n_estimators": 100, "max_depth": 5, "learning_rate": 0.05}

    def objective(trial):
        params = {
            "n_estimators":     trial.suggest_int("n_estimators", 50, 300),
            "max_depth":        trial.suggest_int("max_depth", 3, 8),
            "learning_rate":    trial.suggest_float("learning_rate", 0.01, 0.3, log=True),
            "subsample":        trial.suggest_float("subsample", 0.6, 1.0),
            "colsample":        trial.suggest_float("colsample", 0.6, 1.0),
            "min_child_weight": trial.suggest_int("min_child_weight", 1, 10),
        }
        m = _build_model(params)
        m.fit(X_tr, y_tr)
        probs = m.predict_proba(X_te)[:, 1]
        if len(np.unique(y_te)) < 2:
            return 0.5
        return float(roc_auc_score(y_te, probs))

    study = optuna.create_study(direction="maximize")
    study.optimize(objective, n_trials=n_trials, show_progress_bar=False)
    return study.best_params


def _build_model(params: dict):
    p = dict(params)
    if XGB_AVAILABLE:
        return xgb.XGBClassifier(
            n_estimators=p.get("n_estimators", 100),
            max_depth=p.get("max_depth", 5),
            learning_rate=p.get("learning_rate", 0.05),
            subsample=p.get("subsample", 0.8),
            colsample_bytree=p.get("colsample", 0.8),
            min_child_weight=p.get("min_child_weight", 3),
            eval_metric="logloss",
            random_state=42,
            verbosity=0,
        )
    elif SKLEARN_AVAILABLE:
        return GradientBoostingClassifier(
            n_estimators=p.get("n_estimators", 100),
            max_depth=p.get("max_depth", 5),
            learning_rate=p.get("learning_rate", 0.05),
            random_state=42,
        )
    raise ImportError("Neither xgboost nor sklearn is available")


def _save_model(model, path: str):
    import pickle
    with open(path, "wb") as f:
        pickle.dump(model, f)


def _load_model(path: str):
    import pickle
    with open(path, "rb") as f:
        return pickle.load(f)


def _compute_shap_importance(model, X: np.ndarray) -> List[Dict]:
    names = FEATURE_COLUMNS[:X.shape[1]]
    if SHAP_AVAILABLE:
        try:
            explainer = shap.TreeExplainer(model)
            shap_vals = explainer.shap_values(X)
            if isinstance(shap_vals, list):
                shap_vals = shap_vals[1]
            importance = np.abs(shap_vals).mean(axis=0)
            idx = np.argsort(importance)[::-1][:10]
            return [{"name": names[i], "importance": round(float(importance[i]), 4)} for i in idx]
        except Exception:
            pass
    try:
        fi = model.feature_importances_
        idx = np.argsort(fi)[::-1][:10]
        return [{"name": names[i] if i < len(names) else f"f{i}",
                 "importance": round(float(fi[i]), 4)} for i in idx]
    except Exception:
        return []


def _compute_shap_local(model, features: np.ndarray, names: List[str]) -> List[Dict]:
    if SHAP_AVAILABLE:
        try:
            explainer = shap.TreeExplainer(model)
            shap_vals = explainer.shap_values(features.reshape(1, -1))
            if isinstance(shap_vals, list):
                shap_vals = shap_vals[1]
            vals = shap_vals[0]
            idx = np.argsort(np.abs(vals))[::-1][:5]
            total = sum(abs(vals[i]) for i in idx) or 1
            return [
                {
                    "name":         names[i] if i < len(names) else f"f{i}",
                    "value":        round(float(features[i]), 4) if i < len(features) else 0,
                    "contribution": round(float(abs(vals[i]) / total * 100), 1),
                }
                for i in idx
            ]
        except Exception:
            pass
    return []


def _synthetic_xgb_result(model_dir: Path, ticker: str) -> Dict[str, Any]:
    model_path = str(model_dir / f"xgb_{ticker}_synthetic.pkl")
    Path(model_path).touch()
    metrics = {
        "ticker":      ticker,
        "algorithm":   "xgboost",
        "model_type":  "xgboost",
        "mean_auc":    0.0,
        "n_folds":     0,
        "note":        "Synthetic result — insufficient data or missing dependencies",
        "final_reward": 0.5,
    }
    with open(model_dir / "metrics.json", "w") as f:
        json.dump(metrics, f, indent=2)
    return {"model_path": model_path, "metrics": metrics}
