#!/usr/bin/env python3
"""
Step 6 — Adaptive EWMA Performance Tracker.

Simulates the daily self-correcting weight mechanism (Freund & Schapire 1997
Hedge algorithm) across the full OOF period. For each trading date it:
  1. Reads each model's mean signal across tickers
  2. Compares to the realized cross-ticker return direction
  3. Updates each model's EWMA score (λ=0.94) and re-derives fusion weights

Populates the model_performance_scores table → drives the Model Weights page.

Input:  data/oof/merged_oof_dataset.csv  (from Step 5)
Output: model_performance_scores rows in data/finrl.db

Usage:
    cd /Users/shaahdmaansour/Downloads/nextGen-TradeBot
    source .venv/bin/activate
    python scripts/step6_ewma_tracker.py
"""

import sys, os
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "backend"))
os.chdir(ROOT / "backend")

import pandas as pd

from app.database import SessionLocal, create_tables, ModelPerformanceScore
from app.services.ewma_tracker_service import (
    initialize_tracker, update_scores_for_date, get_current_weights,
    get_weight_history, MODEL_KEYS,
)

MERGED = ROOT / "data" / "oof" / "merged_oof_dataset.csv"

# model_key → signal column in merged dataset
SIGNAL_COL = {
    "xgboost": "xgb_signal", "lstm": "lstm_signal", "ppo": "ppo_signal",
    "a2c": "a2c_signal", "ddpg": "ddpg_signal", "td3": "td3_signal", "sac": "sac_signal",
}


def main():
    print("=" * 60)
    print("Step 6 — Adaptive EWMA Performance Tracker")
    print("=" * 60)

    create_tables()
    df = pd.read_csv(MERGED)
    df["date"] = pd.to_datetime(df["date"]).dt.strftime("%Y-%m-%d")
    dates = sorted(df["date"].unique())
    print(f"Loaded {len(df):,} rows | {len(dates)} trading dates "
          f"({dates[0]} → {dates[-1]})")

    db = SessionLocal()

    # Fresh start — clear any prior scores. We do NOT call initialize_tracker():
    # it stamps seed rows with today's date, which would sort AFTER the historical
    # simulation dates and make get_current_weights read the equal-weight seed
    # instead of the final simulated scores. The first update defaults each model
    # to INITIAL_SCORE (0.5) when no prior row exists, so seeding is unnecessary.
    db.query(ModelPerformanceScore).delete()
    db.commit()
    print(f"Cleared prior scores; starting all {len(MODEL_KEYS)} models at 0.5\n")

    print("Simulating daily score updates (cross-sectional hit rate) …")
    for i, date in enumerate(dates):
        day = df[df["date"] == date]
        up = (day["actual_5d_return"] > 0).values   # per-ticker actual direction
        model_predictions, correct_overrides = {}, {}
        for mk, col in SIGNAL_COL.items():
            if col not in day.columns:
                continue
            sig = day[col].values
            model_predictions[mk] = float(sig.mean())
            # Cross-sectional hit rate: fraction of tickers where signal
            # direction matched the realized return direction that day.
            pred_up = sig > 0.5
            correct_overrides[mk] = float((pred_up == up).mean())
        actual_returns = dict(zip(day["ticker"], day["actual_5d_return"]))
        update_scores_for_date(date, model_predictions, actual_returns, db,
                               correct_overrides=correct_overrides)
        if (i + 1) % 200 == 0:
            print(f"  …{i + 1}/{len(dates)} dates processed")

    db.commit()

    # ── Final weights ─────────────────────────────────────────────────────────
    weights = get_current_weights(db)
    print("\n=== Final adaptive EWMA weights ===")
    for k in MODEL_KEYS:
        w = weights.get(k, 0)
        print(f"  {k:<10} {w*100:5.1f}%  {'█' * int(w * 60)}")
    top = max(MODEL_KEYS, key=lambda k: weights.get(k, 0))
    print(f"  Top model: {top.upper()}")

    hist = get_weight_history(days=9999, db_session=db)
    print(f"\nWeight history rows available: {len(hist)} dates")
    db.close()

    print("\n" + "=" * 60)
    print("Step 6 complete — Model Weights page now has live data.")
    print("=" * 60)


if __name__ == "__main__":
    main()
