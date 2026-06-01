#!/usr/bin/env python3
"""
Step 5 — Meta-Learner (stacking ensemble).

Assembles the merged OOF dataset from all 7 base-model signals + regime +
sentiment + VIX + ground truth, then trains the logistic-regression meta-learner
(Wolpert 1992 stacked generalization). The learned coefficients ARE the
data-driven fusion weights that replace hand-coded regime weights.

Inputs:
    data/oof/xgb_oof_predictions.csv      (date, tic, xgb_signal)
    data/oof/lstm_oof_predictions.csv     (date, ticker, lstm_signal)
    data/oof/rl_signals.csv               (date, tic, {ppo,a2c,ddpg,td3,sac}_signal)
    data/oof/features_us.csv + features_egx.csv  (target, vix_zscore, close, price_mom_20)
Outputs:
    data/oof/merged_oof_dataset.csv
    data/models/meta_learner.pkl  (+ scaler + coefficients JSON)
    DB run registered as algorithm='meta_learner'

Usage:
    cd /Users/shaahdmaansour/Downloads/nextGen-TradeBot
    source .venv/bin/activate
    python scripts/step5_meta_learner.py
"""

import sys, os, json, uuid, sqlite3
from pathlib import Path
from datetime import datetime

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "backend"))
os.chdir(ROOT / "backend")

import numpy as np
import pandas as pd

from app.services.feature_service import TARGET_HORIZON
from app.services.meta_learner_service import train_meta_learner, get_learned_weights, META_LEARNER_FEATURES

OOF_DIR    = ROOT / "data" / "oof"
MODELS_DIR = ROOT / "data" / "models"
DB_PATH    = ROOT / "data" / "finrl.db"
MERGED     = OOF_DIR / "merged_oof_dataset.csv"
MODEL_OUT  = MODELS_DIR / "meta_learner.pkl"

RL_ALGOS = ["ppo", "a2c", "ddpg", "td3", "sac"]


def _norm_ticker(df):
    if "ticker" not in df.columns and "tic" in df.columns:
        df = df.rename(columns={"tic": "ticker"})
    df["date"] = pd.to_datetime(df["date"]).dt.strftime("%Y-%m-%d")
    return df


def build_merged_dataset() -> pd.DataFrame:
    # ── Base signals ──────────────────────────────────────────────────────────
    xgb  = _norm_ticker(pd.read_csv(OOF_DIR / "xgb_oof_predictions.csv"))[["date", "ticker", "xgb_signal"]]
    lstm = _norm_ticker(pd.read_csv(OOF_DIR / "lstm_oof_predictions.csv"))[["date", "ticker", "lstm_signal"]]
    rl   = _norm_ticker(pd.read_csv(OOF_DIR / "rl_signals.csv"))
    rl_cols = ["date", "ticker"] + [f"{a}_signal" for a in RL_ALGOS if f"{a}_signal" in rl.columns]
    rl = rl[rl_cols]

    merged = xgb.merge(lstm, on=["date", "ticker"], how="outer")
    merged = merged.merge(rl, on=["date", "ticker"], how="outer")

    # ── Ground truth + VIX + regime from feature matrices ────────────────────
    feats = []
    for name in ("features_us.csv", "features_egx.csv"):
        p = OOF_DIR / name
        if p.exists():
            f = pd.read_csv(p, usecols=["date", "tic", "close", "target", "vix_zscore", "price_mom_20"])
            feats.append(f)
    gt = pd.concat(feats, ignore_index=True).rename(columns={"tic": "ticker"})
    gt["date"] = pd.to_datetime(gt["date"])
    gt = gt.sort_values(["ticker", "date"])
    # Actual forward return over the target horizon (for fixed-weight comparison)
    gt["actual_5d_return"] = gt.groupby("ticker")["close"].transform(
        lambda s: s.shift(-TARGET_HORIZON) / s - 1.0
    )
    gt["target_5d"] = gt["target"].astype(int)

    # ── Regime from cross-sectional 20-day momentum (backward-looking, no leak) ─
    daily_mkt = gt.groupby("date")["price_mom_20"].mean().rename("mkt_mom")
    thr = daily_mkt.std() * 0.5
    regime = pd.DataFrame({"date": daily_mkt.index})
    regime["regime_bull"] = (daily_mkt.values >  thr).astype(int)
    regime["regime_bear"] = (daily_mkt.values < -thr).astype(int)
    regime["date"] = pd.to_datetime(regime["date"]).dt.strftime("%Y-%m-%d")

    gt["date"] = gt["date"].dt.strftime("%Y-%m-%d")
    gt = gt[["date", "ticker", "vix_zscore", "actual_5d_return", "target_5d"]]

    merged = merged.merge(gt, on=["date", "ticker"], how="inner")
    merged = merged.merge(regime, on="date", how="left")

    # ── Fill neutral defaults ─────────────────────────────────────────────────
    for a in RL_ALGOS:
        c = f"{a}_signal"
        if c not in merged.columns:
            merged[c] = 0.5
        merged[c] = merged[c].fillna(0.5)
    merged["xgb_signal"]   = merged["xgb_signal"].fillna(0.5)
    merged["lstm_signal"]  = merged["lstm_signal"].fillna(0.5)
    merged["vix_zscore"]   = merged["vix_zscore"].fillna(0.0)
    merged["regime_bull"]  = merged["regime_bull"].fillna(0).astype(int)
    merged["regime_bear"]  = merged["regime_bear"].fillna(0).astype(int)
    merged["sentiment_score"] = 0.0   # no historical sentiment series available

    merged = merged.dropna(subset=["target_5d", "actual_5d_return"])
    merged = merged.sort_values(["date", "ticker"]).reset_index(drop=True)
    return merged


def register_run(metrics: dict, weights: dict):
    run_id = str(uuid.uuid4())
    now = datetime.utcnow().isoformat()
    full = {"algorithm": "meta_learner", "model_type": "meta_learner",
            "method": "stacked_logistic_regression", "coefficients": weights, **metrics,
            "final_reward": metrics.get("auc", 0)}
    conn = sqlite3.connect(str(DB_PATH)); cur = conn.cursor()
    cur.execute("DELETE FROM runs WHERE algorithm='meta_learner'")
    cur.execute("""INSERT INTO runs (id, data_job_id, algorithm, status, created_at, updated_at,
                   model_path, metrics_json, hyperparams, error)
                   VALUES (?, 'step5_meta', 'meta_learner', 'done', ?, ?, ?, ?, '{}', NULL)""",
                (run_id, now, now, str(MODEL_OUT), json.dumps(full)))
    conn.commit(); conn.close()
    return run_id


def main():
    print("=" * 60)
    print("Step 5 — Meta-Learner (stacking ensemble)")
    print("=" * 60)

    merged = build_merged_dataset()
    MERGED.parent.mkdir(parents=True, exist_ok=True)
    merged.to_csv(MERGED, index=False)
    print(f"Merged dataset: {len(merged):,} rows, {merged['ticker'].nunique()} tickers")
    print(f"  coverage: {merged['date'].min()} → {merged['date'].max()}")
    print(f"  target balance (up): {merged['target_5d'].mean():.3f}")
    print(f"  saved → {MERGED}")

    print("\nTraining meta-learner …")
    metrics = train_meta_learner(str(MERGED), str(MODEL_OUT))
    weights = get_learned_weights(str(MODEL_OUT))

    print("\n=== Validation metrics ===")
    print(f"  AUC={metrics.get('auc')}  accuracy={metrics.get('accuracy')}  "
          f"brier={metrics.get('brier_score')}")
    print(f"  n_train={metrics.get('n_train')}  n_val={metrics.get('n_val')}")

    print("\n=== Learned fusion weights (normalised |coef|) ===")
    for k, v in sorted(weights.items(), key=lambda x: -abs(x[1])):
        bar = "█" * int(abs(v) * 40)
        print(f"  {k:<16} {v:+.4f}  {bar}")

    run_id = register_run(metrics, weights)
    print(f"\nRegistered meta_learner run {run_id[:8]} in DB")
    print("Next: Step 6 (EWMA adaptive weights) or view the Meta-Learner page")
    print("=" * 60)


if __name__ == "__main__":
    main()
