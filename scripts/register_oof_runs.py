#!/usr/bin/env python3
"""
Register XGBoost + LSTM summary runs from their OOF predictions.

Step 2 (XGBoost) and Step 3 (LSTM) produce out-of-fold prediction CSVs but
no deployable single model and no DB run — that's correct for walk-forward OOF
methodology. This script computes summary metrics (AUC, accuracy, Brier) by
joining the OOF signals against the 5-day-forward ground-truth target, then
registers one summary run per model in the unified DB so they appear on the
Dashboard / Performance pages alongside the RL models.

Usage:
    cd /Users/shaahdmaansour/Downloads/nextGen-TradeBot
    source .venv/bin/activate
    python scripts/register_oof_runs.py
"""

import sys, os, json, uuid, sqlite3
from pathlib import Path
from datetime import datetime

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "backend"))

import numpy as np
import pandas as pd
from sklearn.metrics import roc_auc_score, brier_score_loss

OOF_DIR  = ROOT / "data" / "oof"
DB_PATH  = ROOT / "data" / "finrl.db"


def load_ground_truth() -> pd.DataFrame:
    """Concat US + EGX feature matrices, return date/tic/target."""
    frames = []
    for name in ("features_us.csv", "features_egx.csv"):
        p = OOF_DIR / name
        if p.exists():
            df = pd.read_csv(p, usecols=["date", "tic", "target"])
            frames.append(df)
    if not frames:
        raise FileNotFoundError("No features_us.csv / features_egx.csv found in data/oof/")
    gt = pd.concat(frames, ignore_index=True)
    gt["date"] = pd.to_datetime(gt["date"]).dt.strftime("%Y-%m-%d")
    return gt.rename(columns={"tic": "ticker"})


def summarize(oof_path: Path, signal_col: str, gt: pd.DataFrame) -> dict:
    df = pd.read_csv(oof_path)
    # Normalise ticker column name (step2 writes 'tic', step3 writes 'ticker')
    if "ticker" not in df.columns and "tic" in df.columns:
        df = df.rename(columns={"tic": "ticker"})
    df["date"] = pd.to_datetime(df["date"]).dt.strftime("%Y-%m-%d")
    merged = df.merge(gt, on=["date", "ticker"], how="inner").dropna(subset=[signal_col, "target"])

    y      = merged["target"].astype(int).values
    p      = merged[signal_col].astype(float).clip(0, 1).values
    preds  = (p >= 0.5).astype(int)

    auc      = float(roc_auc_score(y, p)) if len(np.unique(y)) > 1 else 0.5
    accuracy = float(np.mean(preds == y))
    brier    = float(brier_score_loss(y, p))

    n_folds = int(df["fold_id"].nunique()) if "fold_id" in df.columns else None
    return {
        "n_predictions":  int(len(df)),
        "n_evaluated":    int(len(merged)),
        "n_tickers":      int(df["ticker"].nunique()),
        "n_folds":        n_folds,
        "mean_auc":       round(auc, 4),
        "accuracy":       round(accuracy, 4),
        "brier_score":    round(brier, 4),
        "signal_mean":    round(float(df[signal_col].mean()), 4),
        "date_start":     str(df["date"].min()),
        "date_end":       str(df["date"].max()),
        "final_reward":   round(auc, 4),   # dashboard sort key
    }


def register_run(algorithm: str, metrics: dict, oof_path: Path):
    run_id = str(uuid.uuid4())
    now    = datetime.utcnow().isoformat()
    full_metrics = {
        "algorithm":   algorithm,
        "model_type":  algorithm,
        "method":      "walk_forward_oof",
        "oof_path":    str(oof_path),
        **metrics,
    }
    conn = sqlite3.connect(str(DB_PATH))
    cur  = conn.cursor()
    # Remove any prior summary run for this algorithm to avoid duplicates
    cur.execute("DELETE FROM runs WHERE algorithm=? AND data_job_id='step23_oof'", (algorithm,))
    cur.execute("""
        INSERT INTO runs
            (id, data_job_id, algorithm, status, created_at, updated_at,
             model_path, metrics_json, hyperparams, error)
        VALUES (?, ?, ?, 'done', ?, ?, ?, ?, ?, NULL)
    """, (run_id, "step23_oof", algorithm, now, now,
          str(oof_path), json.dumps(full_metrics), json.dumps({})))
    conn.commit()
    conn.close()
    return run_id, full_metrics


def main():
    print("=" * 60)
    print("Registering XGBoost + LSTM OOF summary runs")
    print("=" * 60)

    gt = load_ground_truth()
    print(f"Ground truth: {len(gt):,} (date,ticker,target) rows")

    jobs = [
        ("xgboost", OOF_DIR / "xgb_oof_predictions.csv",  "xgb_signal"),
        ("lstm",    OOF_DIR / "lstm_oof_predictions.csv", "lstm_signal"),
    ]

    for algo, path, col in jobs:
        if not path.exists():
            print(f"  ✗ {algo}: {path} not found — skipping")
            continue
        metrics = summarize(path, col, gt)
        run_id, _ = register_run(algo, metrics, path)
        print(f"\n  ✓ {algo.upper()} registered (run {run_id[:8]})")
        print(f"      predictions: {metrics['n_predictions']:,} | tickers: {metrics['n_tickers']} | folds: {metrics['n_folds']}")
        print(f"      AUC={metrics['mean_auc']}  accuracy={metrics['accuracy']}  brier={metrics['brier_score']}")
        print(f"      coverage: {metrics['date_start']} → {metrics['date_end']}")

    print("\n" + "=" * 60)
    print("Done — XGBoost & LSTM now appear on the Dashboard / Performance pages.")
    print("=" * 60)


if __name__ == "__main__":
    main()
