#!/usr/bin/env python3
"""
Experiment — Confidence-Threshold Sweep (precision/coverage tradeoff).

Reproduces the production meta-learner (logistic, time-ordered 70/30 split,
scaler fit on train only), then sweeps the BUY confidence threshold over the
validation window and reports trade count, coverage, win rate, and gross
5-day return per threshold.

Shows whether the meta-learner's confidence is *informative*: if win rate
rises monotonically with the threshold, confidence gating works.

Usage:
    cd /Users/shaahdmaansour/Downloads/nextGen-TradeBot
    source .venv/bin/activate
    python scripts/experiment_threshold_sweep.py
"""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "backend"))

import numpy as np
import pandas as pd
from sklearn.linear_model import LogisticRegression
from sklearn.preprocessing import StandardScaler

OOF = ROOT / "data" / "oof" / "merged_oof_dataset.csv"
FEATS = ["xgb_signal", "lstm_signal", "ppo_signal", "a2c_signal", "ddpg_signal",
         "td3_signal", "sac_signal", "regime_bull", "regime_bear",
         "sentiment_score", "vix_zscore"]
THRESHOLDS = [0.50, 0.55, 0.60, 0.65, 0.70, 0.75]


def main():
    df = pd.read_csv(OOF)
    df["date"] = pd.to_datetime(df["date"])
    df = df.sort_values("date").reset_index(drop=True)
    sub = df.dropna(subset=FEATS + ["target_5d", "actual_5d_return"]).reset_index(drop=True)

    X = sub[FEATS].values
    y = sub["target_5d"].values.astype(int)
    rets = sub["actual_5d_return"].values

    cut = int(len(sub) * 0.70)
    sc = StandardScaler().fit(X[:cut])
    m = LogisticRegression(C=1.0, max_iter=1000, random_state=42)
    m.fit(sc.transform(X[:cut]), y[:cut])
    p = m.predict_proba(sc.transform(X[cut:]))[:, 1]
    yv, rv = y[cut:], rets[cut:]

    print("=" * 66)
    print("Experiment — Confidence-Threshold Sweep")
    print("=" * 66)
    print(f"Validation rows: {len(yv):,}  "
          f"({sub['date'].iloc[cut].date()} → {sub['date'].iloc[-1].date()})")
    print(f"Base rate (up): {yv.mean():.3f}\n")
    print(f"{'Threshold':>9} {'BUY trades':>11} {'Coverage':>9} "
          f"{'Win rate':>9} {'Avg 5d ret':>11}")
    print("-" * 56)
    for t in THRESHOLDS:
        mask = p >= t
        n = int(mask.sum())
        if n == 0:
            print(f"{t:>9.2f} {0:>11} {'0.0%':>9} {'—':>9} {'—':>11}")
            continue
        print(f"{t:>9.2f} {n:>11,} {n/len(yv)*100:>8.1f}% "
              f"{yv[mask].mean()*100:>8.1f}% {rv[mask].mean()*100:>+10.3f}%")
    print("\nNote: returns are GROSS 5-day forward returns (no costs) and include")
    print("market beta. Rows with < ~30 trades are too small a sample to trust.")
    print("=" * 66)


if __name__ == "__main__":
    main()
