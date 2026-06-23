#!/usr/bin/env python3
"""
Unified, leakage-free trading backtest of XGBoost and LSTM on the SAME EGX window
as the RL agents (train 2019-01-01..2024-12-31, test 2025-01-01..2026-05-05, 21
.CA tickers). Produces Return / Sharpe / MaxDD / vs-B&H / Accuracy so the
classifiers sit in the same table as the RL agents.

Strategy (identical for both classifiers): daily, equal-weight LONG in every
ticker whose predicted up-probability > 0.5; hold one day; 0.1% per-side cost on
turnover. Accuracy = native 5-day directional task on the test rows.
"""
import sys, os, json
from pathlib import Path
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "backend"))
os.chdir(ROOT / "backend")

import numpy as np, pandas as pd
from app.services.feature_service import FEATURE_COLUMNS

EGX = ROOT / "data" / "oof" / "features_egx.csv"
TRAIN_END, TEST_START, TEST_END = "2024-12-31", "2025-01-01", "2026-05-05"
COST = 0.001
SEQ = 20

df = pd.read_csv(EGX)
df["date"] = pd.to_datetime(df["date"])
df = df.sort_values(["tic", "date"]).reset_index(drop=True)
df["ret_fwd_1d"] = df.groupby("tic")["close"].transform(lambda c: c.shift(-1)/c - 1.0)
feats = [f for f in FEATURE_COLUMNS if f in df.columns]

tr = df[df["date"] <= TRAIN_END]
te = df[(df["date"] >= TEST_START) & (df["date"] <= TEST_END)]
print(f"train rows {len(tr)} | test rows {len(te)} | tickers {df['tic'].nunique()}")


def equity_metrics(test_df, prob_col):
    """Daily equal-weight long-on-BUY (prob>0.5). Returns dict of metrics."""
    d = test_df.dropna(subset=[prob_col, "ret_fwd_1d"]).copy()
    d["hold"] = (d[prob_col] > 0.5).astype(int)
    daily, prev = [], set()
    for dt, g in d.groupby("date"):
        held = g[g["hold"] == 1]
        r = held["ret_fwd_1d"].mean() if len(held) else 0.0
        cur = set(held["tic"])
        turnover = len(cur.symmetric_difference(prev)) / max(len(cur | prev), 1)
        daily.append(r - COST * turnover)
        prev = cur
    r = np.array([x for x in daily if np.isfinite(x)])
    if len(r) == 0:
        return None
    eq = np.cumprod(1 + r)
    total = float(eq[-1] - 1)
    sharpe = float(np.mean(r) / (np.std(r) + 1e-9) * np.sqrt(252))
    peak = np.maximum.accumulate(eq)
    maxdd = float(((eq - peak) / peak).min())
    # Buy & hold = equal-weight all tickers
    bh = d.groupby("date")["ret_fwd_1d"].mean()
    bh_total = float(np.prod(1 + bh.values) - 1)
    acc = float(((d[prob_col] > 0.5).astype(int) == d["target"]).mean())
    return {"return": total, "sharpe": round(sharpe, 2), "maxdd": maxdd,
            "vs_bh": total - bh_total, "bh": bh_total, "accuracy": acc}


results = {}

# ── XGBoost (EGX-native) ─────────────────────────────────────────────────────
import xgboost as xgb
m = xgb.XGBClassifier(n_estimators=200, max_depth=5, learning_rate=0.05,
                      subsample=0.8, colsample_bytree=0.8, eval_metric="logloss",
                      random_state=42, verbosity=0)
m.fit(tr[feats].values, tr["target"].values)
te = te.copy()
te["xgb"] = m.predict_proba(te[feats].values)[:, 1]
results["XGBoost"] = equity_metrics(te, "xgb")
print("XGBoost done")

# ── LSTM (EGX-native) ────────────────────────────────────────────────────────
import torch, torch.nn as nn
from sklearn.preprocessing import StandardScaler
sc = StandardScaler().fit(tr[feats].values)

class LSTMClf(nn.Module):
    def __init__(self, n):
        super().__init__()
        self.lstm = nn.LSTM(n, 64, num_layers=2, batch_first=True, dropout=0.3)
        self.fc = nn.Linear(64, 1); self.sig = nn.Sigmoid()
    def forward(self, x):
        o, _ = self.lstm(x); return self.sig(self.fc(o[:, -1, :]))

def make_seqs(frame):
    X, y, idx = [], [], []
    for tic, g in frame.groupby("tic"):
        g = g.sort_values("date")
        arr = sc.transform(g[feats].values).astype(np.float32)
        tgt = g["target"].values; rows = g.index.values
        for i in range(SEQ - 1, len(g)):
            X.append(arr[i-SEQ+1:i+1]); y.append(tgt[i]); idx.append(rows[i])
    return np.array(X), np.array(y, np.float32), idx

Xtr, ytr, _ = make_seqs(tr)
net = LSTMClf(len(feats)); opt = torch.optim.Adam(net.parameters(), lr=1e-3); lossf = nn.BCELoss()
Xt = torch.tensor(Xtr); yt = torch.tensor(ytr).unsqueeze(1)
net.train()
for ep in range(15):
    perm = torch.randperm(len(Xt))
    for i in range(0, len(Xt), 256):
        b = perm[i:i+256]; opt.zero_grad()
        loss = lossf(net(Xt[b]), yt[b]); loss.backward(); opt.step()
# predict on test (need seq context, so build seqs over full per-ticker history up to each test row)
net.eval()
full = df[df["date"] <= TEST_END]
probs = {}
with torch.no_grad():
    for tic, g in full.groupby("tic"):
        g = g.sort_values("date")
        arr = sc.transform(g[feats].values).astype(np.float32); rows = g.index.values
        for i in range(SEQ - 1, len(g)):
            probs[rows[i]] = float(net(torch.tensor(arr[i-SEQ+1:i+1]).unsqueeze(0)).item())
te["lstm"] = te.index.map(probs)
results["LSTM"] = equity_metrics(te, "lstm")
print("LSTM done")

# benchmark
bh = te.dropna(subset=["ret_fwd_1d"]).groupby("date")["ret_fwd_1d"].mean()
bh_total = float(np.prod(1 + bh.values) - 1)
print(f"\nBenchmark B&H (test): {bh_total*100:.1f}%")
print("\n%-9s %9s %7s %9s %10s %9s" % ("Model","Return","Sharpe","MaxDD","vsB&H","Accuracy"))
for k, v in results.items():
    if v:
        print("%-9s %8.1f%% %7.2f %8.1f%% %9.1f%% %8.1f%%" %
              (k, v["return"]*100, v["sharpe"], v["maxdd"]*100, v["vs_bh"]*100, v["accuracy"]*100))

out = ROOT / "data" / "results" / "egx_unified_classifier_backtest.json"
out.write_text(json.dumps({"window":[TEST_START,TEST_END],"benchmark":bh_total,"results":results}, indent=2))
print("saved ->", out)
