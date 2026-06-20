#!/usr/bin/env python3
"""
Backtest the EXISTING deployable base models (pooled XGBoost + LSTM) on EGX.

The RL ensemble (PPO/A2C/DDPG/TD3/SAC) is dimension-locked to the US DOW-30
universe it trained on, so it cannot be applied to the 21-ticker EGX universe.
The pooled deployable XGBoost/LSTM are ticker-agnostic per-row classifiers, so
they CAN score EGX rows. This script evaluates them on the existing labelled
EGX feature matrix (data/oof/features_egx.csv).

Two evaluations per model:
  1. Predictive quality vs ground-truth 5-day target (AUC, accuracy, Brier).
  2. A simple long-on-BUY equity sim (buy ticker for the 5d horizon when the
     model's prob > threshold) vs equal-weight buy & hold over the same window.
"""
import sys, os, json, pickle
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "backend"))
os.chdir(ROOT / "backend")

import numpy as np
import pandas as pd
from sklearn.metrics import roc_auc_score, accuracy_score, brier_score_loss

DEPLOY = ROOT / "data" / "models" / "deploy"
EGX_CSV = ROOT / "data" / "oof" / "features_egx.csv"
SEQ_LEN = 20
THRESH = 0.55          # BUY threshold on calibrated-ish prob
HORIZON = 5            # 5-day forward holding (matches target definition)

df = pd.read_csv(EGX_CSV)
df["date"] = pd.to_datetime(df["date"])
df = df.sort_values(["tic", "date"]).reset_index(drop=True)
# Forward 5d return per ticker for the trading sim
df["fwd_ret_5d"] = df.groupby("tic")["close"].transform(lambda c: c.shift(-HORIZON) / c - 1.0)
print(f"EGX rows: {len(df)}  tickers: {df['tic'].nunique()}  "
      f"dates: {df['date'].min().date()} -> {df['date'].max().date()}\n")


def predictive_metrics(name, probs, y):
    m = ~np.isnan(probs) & ~np.isnan(y)
    probs, y = probs[m], y[m].astype(int)
    return {
        "model": name, "n": int(len(y)),
        "auc": round(roc_auc_score(y, probs), 4),
        "accuracy": round(accuracy_score(y, (probs > 0.5).astype(int)), 4),
        "brier": round(brier_score_loss(y, probs), 4),
        "base_rate_up": round(float(y.mean()), 4),
    }


def trading_sim(name, work):
    """work: df rows with columns prob, fwd_ret_5d. Long when prob>THRESH."""
    w = work.dropna(subset=["prob", "fwd_ret_5d"]).copy()
    buys = w[w["prob"] > THRESH]
    if len(buys) == 0:
        return {"model": name, "n_trades": 0, "note": "no signals above threshold"}
    # non-overlapping-ish: average 5d return per BUY (each treated as one trade)
    avg = buys["fwd_ret_5d"].mean()
    win = (buys["fwd_ret_5d"] > 0).mean()
    bh = w["fwd_ret_5d"].mean()   # equal-weight buy&hold over all rows (5d horizon)
    return {
        "model": name, "n_trades": int(len(buys)),
        "avg_5d_ret_per_buy": round(float(avg), 4),
        "win_rate": round(float(win), 4),
        "buyhold_avg_5d_ret": round(float(bh), 4),
        "edge_vs_buyhold": round(float(avg - bh), 4),
    }


results = {"predictive": [], "trading": []}

# ── XGBoost (pooled deployable) ──────────────────────────────────────────────
with open(DEPLOY / "xgb_deploy.pkl", "rb") as f:
    xgb_bundle = pickle.load(f)
xgb_model, xgb_feats = xgb_bundle["model"], xgb_bundle["features"]
X = df[xgb_feats].values.astype(np.float32)
xgb_prob = xgb_model.predict_proba(X)[:, 1]
results["predictive"].append(predictive_metrics("xgboost_deploy", xgb_prob, df["target"].values))
xw = df[["fwd_ret_5d"]].copy(); xw["prob"] = xgb_prob
results["trading"].append(trading_sim("xgboost_deploy", xw))
print("XGBoost scored.")

# ── LSTM (pooled deployable, last-20 sequence per ticker) ────────────────────
import torch, torch.nn as nn
ck = torch.load(DEPLOY / "lstm_deploy.pt", weights_only=False)
seq_len = ck["seq_len"]; lf = ck["features"]
with open(DEPLOY / "lstm_scaler.pkl", "rb") as f:
    lstm_scaler = pickle.load(f)

class LSTMClf(nn.Module):
    def __init__(self, n):
        super().__init__()
        self.lstm = nn.LSTM(n, 64, num_layers=2, batch_first=True, dropout=0.3)
        self.fc = nn.Linear(64, 1); self.sig = nn.Sigmoid()
    def forward(self, x):
        o, _ = self.lstm(x); return self.sig(self.fc(o[:, -1, :]))

lstm_model = LSTMClf(ck["n_features"]); lstm_model.load_state_dict(ck["state_dict"]); lstm_model.eval()

lstm_probs = np.full(len(df), np.nan)
for tic, g in df.groupby("tic"):
    g = g.sort_values("date")
    arr = lstm_scaler.transform(g[lf].values.astype(np.float32))
    idx = g.index.to_numpy()
    for i in range(seq_len - 1, len(g)):
        seq = arr[i - seq_len + 1: i + 1]
        with torch.no_grad():
            lstm_probs[idx[i]] = float(lstm_model(torch.tensor(seq).unsqueeze(0)).item())
results["predictive"].append(predictive_metrics("lstm_deploy", lstm_probs, df["target"].values))
lw = df[["fwd_ret_5d"]].copy(); lw["prob"] = lstm_probs
results["trading"].append(trading_sim("lstm_deploy", lw))
print("LSTM scored.\n")

print("=== PREDICTIVE QUALITY (vs 5-day forward target) ===")
print(pd.DataFrame(results["predictive"]).to_string(index=False))
print("\n=== SIMPLE LONG-ON-BUY SIM (prob > %.2f, %dd horizon) ===" % (THRESH, HORIZON))
print(pd.DataFrame(results["trading"]).to_string(index=False))

out = ROOT / "data" / "results" / "egx_deploy_backtest.json"
out.parent.mkdir(parents=True, exist_ok=True)
with open(out, "w") as f:
    json.dump(results, f, indent=2)
print(f"\nSaved -> {out}")
