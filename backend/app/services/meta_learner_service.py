"""
Meta-Learner — Stacking Ensemble.

Takes 7 base model signals + regime + sentiment + VIX as input features.
Learns from real Yahoo Finance 5-day returns which combination actually
predicts the market correctly.

The logistic regression coefficients represent learned optimal weights.
This replaces hand-coded fixed fusion weights with data-driven ones.

Academic references
-------------------
Wolpert (1992) — Stacked Generalization
Breiman (1996) — Stacked Regressions
"""
import json
import logging
import os
import pickle
from typing import Any, Dict, List, Optional

import numpy as np
import pandas as pd

logger = logging.getLogger(__name__)

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


def train_meta_learner(
    oof_dataset_path: str,
    model_save_path: str,
) -> Dict[str, Any]:
    """
    Train logistic regression on OOF predictions.

    Steps
    -----
    1. Load OOF dataset (from oof_collector_service)
    2. Features: META_LEARNER_FEATURES
    3. Target: target_5d (1 if 5-day return > 0)
    4. Time-ordered split: first 70% train, last 30% val
       NEVER random-split — this is time-series data
    5. StandardScaler fitted on train portion only
    6. LogisticRegression(C=1.0, max_iter=1000, random_state=42)
    7. Evaluate on validation: AUC, accuracy, Brier score
    8. Save model + scaler + feature_list + coefficients as JSON

    Returns
    -------
    {
      "model_path": str,
      "coefficients": {feature: coef},
      "auc": float,
      "accuracy": float,
      "brier_score": float,
      "n_train": int,
      "n_val": int,
      "top_features": [{"feature": str, "importance": float}]
    }
    """
    from sklearn.linear_model import LogisticRegression
    from sklearn.preprocessing import StandardScaler
    from sklearn.metrics import roc_auc_score, accuracy_score, brier_score_loss

    from app.services.oof_collector_service import load_oof_dataset

    df = load_oof_dataset(oof_dataset_path)
    df = df.sort_values("date").reset_index(drop=True)

    # Only keep rows where all required features exist
    avail_feats = [f for f in META_LEARNER_FEATURES if f in df.columns]
    if len(avail_feats) < 3:
        raise ValueError(f"Not enough feature columns in OOF dataset: {avail_feats}")

    df = df.dropna(subset=avail_feats + ["target_5d"])
    if len(df) < 100:
        raise ValueError(f"OOF dataset too small after dropping NaN: {len(df)} rows")

    X = df[avail_feats].values.astype(np.float32)
    y = df["target_5d"].values.astype(int)

    # Time-ordered 70/30 split
    split = int(len(df) * 0.70)
    X_tr, X_val = X[:split], X[split:]
    y_tr, y_val = y[:split], y[split:]

    # Scaler on train only
    scaler = StandardScaler()
    X_tr_s = scaler.fit_transform(X_tr)
    X_val_s = scaler.transform(X_val)

    model = LogisticRegression(C=1.0, max_iter=1000, random_state=42, solver="lbfgs")
    model.fit(X_tr_s, y_tr)

    # Validation metrics
    val_probs = model.predict_proba(X_val_s)[:, 1]
    val_preds = model.predict(X_val_s)

    auc = float(roc_auc_score(y_val, val_probs))
    acc = float(accuracy_score(y_val, val_preds))
    brier = float(brier_score_loss(y_val, val_probs))

    # Coefficients (feature importance proxy)
    coefs = dict(zip(avail_feats, model.coef_[0].tolist()))
    top_features = sorted(
        [{"feature": f, "importance": round(abs(v), 4)} for f, v in coefs.items()],
        key=lambda x: x["importance"], reverse=True,
    )

    # Save artifacts
    os.makedirs(os.path.dirname(model_save_path) or ".", exist_ok=True)
    artifacts = {
        "model": model,
        "scaler": scaler,
        "feature_list": avail_feats,
        "coefficients": coefs,
        "metrics": {"auc": auc, "accuracy": acc, "brier_score": brier},
    }
    with open(model_save_path, "wb") as f:
        pickle.dump(artifacts, f)

    # Also write a human-readable JSON sidecar
    json_path = model_save_path.replace(".pkl", "_meta.json")
    with open(json_path, "w") as f:
        json.dump({
            "feature_list": avail_feats,
            "coefficients": {k: round(v, 6) for k, v in coefs.items()},
            "top_features": top_features,
            "metrics": {"auc": round(auc, 4), "accuracy": round(acc, 4), "brier_score": round(brier, 4)},
            "n_train": int(split),
            "n_val": int(len(df) - split),
        }, f, indent=2)

    result = {
        "model_path":   model_save_path,
        "coefficients": {k: round(v, 6) for k, v in coefs.items()},
        "auc":          round(auc, 4),
        "accuracy":     round(acc, 4),
        "brier_score":  round(brier, 4),
        "n_train":      int(split),
        "n_val":        int(len(df) - split),
        "top_features": top_features,
    }
    logger.info("Meta-learner trained: AUC=%.4f, acc=%.4f, brier=%.4f (n_val=%d)",
                auc, acc, brier, len(df) - split)
    return result


def predict_meta_learner(
    model_path: str,
    feature_dict: Dict[str, float],
) -> Dict[str, Any]:
    """
    Inference for a single observation.

    Parameters
    ----------
    model_path   : path to the .pkl saved by train_meta_learner()
    feature_dict : dict with keys matching META_LEARNER_FEATURES
                   (missing keys filled with 0.0)

    Returns
    -------
    {
      "probability": float,               # calibrated 0-1
      "signal": float,                    # same as probability
      "method": "meta_learner",
      "feature_contributions": {feature: contribution}
    }
    """
    if not os.path.exists(model_path):
        return {"probability": 0.5, "signal": 0.5, "method": "fallback_no_model"}

    try:
        with open(model_path, "rb") as f:
            artifacts = pickle.load(f)

        model       = artifacts["model"]
        scaler      = artifacts["scaler"]
        feat_list   = artifacts["feature_list"]

        x = np.array([[feature_dict.get(f, 0.0) for f in feat_list]], dtype=np.float32)
        x_s = scaler.transform(x)

        prob = float(model.predict_proba(x_s)[0, 1])

        # Per-feature contribution (coef × scaled_value)
        coef = model.coef_[0]
        contributions = {
            feat_list[i]: round(float(coef[i] * x_s[0, i]), 5)
            for i in range(len(feat_list))
        }

        return {
            "probability":           round(prob, 4),
            "signal":                round(prob, 4),
            "method":                "meta_learner",
            "feature_contributions": contributions,
        }

    except Exception as exc:
        logger.warning("meta_learner predict failed: %s — returning 0.5", exc)
        return {"probability": 0.5, "signal": 0.5, "method": "fallback_error"}


def get_learned_weights(model_path: str) -> Dict[str, float]:
    """
    Return model coefficients as normalised weights that sum to 1.

    Only includes the 7 base model signals (not regime/sentiment/vix).
    Used for display in the admin UI to show which models are trusted most.
    """
    _MODEL_SIGNAL_KEYS = [
        "xgb_signal", "lstm_signal", "ppo_signal",
        "a2c_signal", "ddpg_signal", "td3_signal", "sac_signal",
    ]

    if not os.path.exists(model_path):
        equal = 1.0 / len(_MODEL_SIGNAL_KEYS)
        return {k: equal for k in _MODEL_SIGNAL_KEYS}

    try:
        with open(model_path, "rb") as f:
            artifacts = pickle.load(f)

        coefs     = artifacts.get("coefficients", {})
        feat_list = artifacts.get("feature_list", [])

        # Use absolute coefficient values as importance proxy
        raw = {k: abs(coefs.get(k, 0.0)) for k in _MODEL_SIGNAL_KEYS if k in feat_list}
        total = sum(raw.values()) or 1.0
        weights = {k: round(v / total, 4) for k, v in raw.items()}

        # Fill in any missing model keys with 0
        for k in _MODEL_SIGNAL_KEYS:
            if k not in weights:
                weights[k] = 0.0

        return weights

    except Exception as exc:
        logger.warning("get_learned_weights failed: %s", exc)
        equal = 1.0 / len(_MODEL_SIGNAL_KEYS)
        return {k: equal for k in _MODEL_SIGNAL_KEYS}


def compare_with_fixed_weights(
    oof_dataset_path: str,
    fixed_weights: Optional[Dict[str, float]] = None,
) -> Dict[str, Any]:
    """
    Compare meta-learner vs current fixed fusion on the validation portion of OOF.

    Parameters
    ----------
    oof_dataset_path : path to merged_oof_dataset.csv
    fixed_weights    : {"xgb": 0.45, "lstm": 0.35, "ppo": 0.20} etc.
                       Defaults to BULL-regime fixed weights from fusion_service.

    Returns
    -------
    {
      "meta_learner":  {sharpe, auc, win_rate, brier_score},
      "fixed_weights": {sharpe, auc, win_rate},
      "improvement":   {sharpe_delta, auc_delta, win_rate_delta}
    }
    """
    from sklearn.metrics import roc_auc_score, brier_score_loss
    from app.services.oof_collector_service import load_oof_dataset

    if fixed_weights is None:
        fixed_weights = {"xgb_signal": 0.45, "lstm_signal": 0.35, "ppo_signal": 0.20}

    df = load_oof_dataset(oof_dataset_path)
    df = df.sort_values("date").reset_index(drop=True)
    df = df.dropna(subset=["target_5d", "actual_5d_return"])

    split = int(len(df) * 0.70)
    val   = df.iloc[split:].copy()

    if len(val) < 20:
        raise ValueError("Validation set too small for comparison")

    # Meta-learner: load and run on val
    from app.config import settings
    meta_path = os.path.join(settings.models_dir, "meta_learner.pkl")
    ml_probs = []
    if os.path.exists(meta_path):
        for _, row in val.iterrows():
            fdict = {f: float(row.get(f, 0.0)) for f in META_LEARNER_FEATURES}
            pred  = predict_meta_learner(meta_path, fdict)
            ml_probs.append(pred["probability"])
    else:
        ml_probs = [0.5] * len(val)

    # Fixed weights: weighted sum of available signal columns.
    # Map model names → signal column names (xgboost→xgb_signal, etc.).
    _alias = {"xgboost": "xgb_signal", "xgb": "xgb_signal", "lstm": "lstm_signal",
              "ppo": "ppo_signal", "a2c": "a2c_signal", "ddpg": "ddpg_signal",
              "td3": "td3_signal", "sac": "sac_signal"}
    fixed_signal = pd.Series(0.0, index=val.index)
    used_w = 0.0
    for k, w in fixed_weights.items():
        col = _alias.get(k, k if k.endswith("_signal") else f"{k}_signal")
        if col in val.columns:
            fixed_signal = fixed_signal + val[col].fillna(0.5) * w
            used_w += w
    fw_total = used_w or 1.0
    fixed_probs = (fixed_signal / fw_total).clip(0, 1).values

    def _metrics(probs, actual_returns, targets):
        auc    = float(roc_auc_score(targets, probs)) if len(np.unique(targets)) > 1 else 0.5
        brier  = float(brier_score_loss(targets, probs))
        preds  = (np.array(probs) >= 0.5).astype(int)
        wr     = float(np.mean(preds == targets))
        # Simple Sharpe: daily PnL = signal * return
        pnl    = np.where(preds == 1, actual_returns, -actual_returns)
        sharpe = float(np.mean(pnl) / (np.std(pnl) + 1e-9) * np.sqrt(252))
        return {"sharpe": round(sharpe, 4), "auc": round(auc, 4),
                "win_rate": round(wr, 4), "brier_score": round(brier, 4)}

    ml_m  = _metrics(ml_probs, val["actual_5d_return"].values, val["target_5d"].values)
    fw_m  = _metrics(fixed_probs, val["actual_5d_return"].values, val["target_5d"].values)

    result = {
        "meta_learner":  ml_m,
        "fixed_weights": fw_m,
        "improvement": {
            "sharpe_delta":   round(ml_m["sharpe"]   - fw_m["sharpe"],   4),
            "auc_delta":      round(ml_m["auc"]       - fw_m["auc"],     4),
            "win_rate_delta": round(ml_m["win_rate"]  - fw_m["win_rate"], 4),
        },
    }
    logger.info("Comparison: meta AUC=%.4f vs fixed AUC=%.4f (Δ=%.4f)",
                ml_m["auc"], fw_m["auc"], result["improvement"]["auc_delta"])
    return result
