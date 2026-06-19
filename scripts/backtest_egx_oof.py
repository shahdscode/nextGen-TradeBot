#!/usr/bin/env python3
"""
OPTION 1 — Walk-forward (out-of-fold) backtest of XGBoost + LSTM on EGX.

Unlike backtest_egx_deploy.py (in-sample), this uses the existing OOF
predictions produced by step2/step3, where every prediction was made by a
model that did NOT train on that row. This is the legitimate, leakage-free
generalization estimate for the EGX universe.

Inputs:
    data/oof/xgb_oof_predictions.csv   (date, tic, market, xgb_signal, ...)
    data/oof/lstm_oof_predictions.csv  (date, ticker, lstm_signal, fold_id)
    data/oof/features_egx.csv          (ground-truth target + close for ret sim)
"""
import sys, os, json
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
import numpy as np
import pandas as pd
from sklearn.metrics import roc_auc_score, accuracy_score, brier_score_loss

OOF = ROOT / "data" / "oof"
THRESH, HORIZON = 0.55, 5

# ── Ground truth from EGX features ───────────────────────────────────────────
feat = pd.read_csv(OOF / "features_egx.csv", usecols=["date", "tic", "close", "target"])
feat["date"] = pd.to_datetime(feat["date"])
feat = feat.sort_values(["tic", "date"]).reset_index(drop=True)
feat["fwd_ret_5d"] = feat.groupby("tic")["close"].transform(lambda c: c.shift(-HORIZON) / c - 1.0)

# ── XGBoost OOF (EGX slice) ──────────────────────────────────────────────────
xgb = pd.read_csv(OOF / "xgb_oof_predictions.csv")
xgb = xgb[xgb["market"] == "egx"].copy()
xgb["date"] = pd.to_datetime(xgb["date"])
xgb = xgb.merge(feat, on=["date", "tic"], how="inner")

# ── LSTM OOF (EGX slice — restrict to EGX tickers) ───────────────────────────
egx_tickers = set(feat["tic"].unique())
lstm = pd.read_csv(OOF / "lstm_oof_predictions.csv").rename(columns={"ticker": "tic"})
lstm = lstm[lstm["tic"].isin(egx_tickers)].copy()
lstm["date"] = pd.to_datetime(lstm["date"])
lstm = lstm.merge(feat, on=["date", "tic"], how="inner")


def metrics(name, sig, w):
    w = w.dropna(subset=[sig, "target"])
    y, p = w["target"].astype(int).values, w[sig].values
    pred = {"model": name, "n": int(len(w)),
            "auc": round(roc_auc_score(y, p), 4) if len(np.unique(y)) > 1 else None,
            "accuracy": round(accuracy_score(y, (p > 0.5).astype(int)), 4),
            "brier": round(brier_score_loss(y, p), 4),
            "base_rate_up": round(float(y.mean()), 4)}
    t = w.dropna(subset=["fwd_ret_5d"])
    buys = t[t[sig] > THRESH]
    bh = t["fwd_ret_5d"].mean()
    trade = {"model": name,
             "n_buy_signals": int(len(buys)),
             "avg_5d_ret_per_buy": round(float(buys["fwd_ret_5d"].mean()), 4) if len(buys) else None,
             "win_rate": round(float((buys["fwd_ret_5d"] > 0).mean()), 4) if len(buys) else None,
             "buyhold_avg_5d_ret": round(float(bh), 4),
             "edge_vs_buyhold": round(float(buys["fwd_ret_5d"].mean() - bh), 4) if len(buys) else None}
    return pred, trade


out = {"predictive": [], "trading": [], "note": "walk-forward OOF (leakage-free)"}
for name, sig, w in [("xgboost_oof", "xgb_signal", xgb), ("lstm_oof", "lstm_signal", lstm)]:
    p, t = metrics(name, sig, w)
    out["predictive"].append(p); out["trading"].append(t)

print(f"EGX OOF rows — xgb: {len(xgb)}  lstm: {len(lstm)}  "
      f"dates: {xgb['date'].min().date()} -> {xgb['date'].max().date()}\n")
print("=== PREDICTIVE QUALITY (walk-forward OOF vs 5d target) ===")
print(pd.DataFrame(out["predictive"]).to_string(index=False))
print("\n=== LONG-ON-BUY SIM (prob > %.2f, %dd horizon) ===" % (THRESH, HORIZON))
print(pd.DataFrame(out["trading"]).to_string(index=False))

res = ROOT / "data" / "results" / "egx_oof_backtest.json"
res.parent.mkdir(parents=True, exist_ok=True)
res.write_text(json.dumps(out, indent=2))
print(f"\nSaved -> {res}")
