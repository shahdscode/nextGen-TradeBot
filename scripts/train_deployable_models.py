#!/usr/bin/env python3
"""
Train DEPLOYABLE XGBoost + LSTM models for live inference.

Steps 2/3 produce out-of-fold predictions only (no saved model). For live
trading the meta-learner needs callable base models. This trains ONE pooled
XGBoost and ONE pooled LSTM on ALL available feature rows (every ticker, full
history) and saves them. Training on all history is correct for a deployment
model — you use everything you know to predict the next move.

Outputs:
    data/models/deploy/xgb_deploy.pkl       (pooled XGBoost)
    data/models/deploy/lstm_deploy.pt       (pooled LSTM state_dict)
    data/models/deploy/lstm_scaler.pkl      (StandardScaler for LSTM)
    data/models/deploy/deploy_meta.json     (feature list, metrics)

Usage:
    cd /Users/shaahdmaansour/Downloads/nextGen-TradeBot
    source .venv/bin/activate
    python scripts/train_deployable_models.py
"""
import sys, os, json, pickle
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "backend"))
os.chdir(ROOT / "backend")

import numpy as np
import pandas as pd
from sklearn.preprocessing import StandardScaler
from sklearn.metrics import roc_auc_score

from app.services.feature_service import FEATURE_COLUMNS

OOF_DIR    = ROOT / "data" / "oof"
DEPLOY_DIR = ROOT / "data" / "models" / "deploy"
SEQ_LEN    = 20


def load_all_features() -> pd.DataFrame:
    frames = []
    for name in ("features_us.csv", "features_egx.csv"):
        p = OOF_DIR / name
        if p.exists():
            frames.append(pd.read_csv(p))
    df = pd.concat(frames, ignore_index=True)
    df["date"] = pd.to_datetime(df["date"])
    return df.sort_values(["tic", "date"]).reset_index(drop=True)


def train_xgb(df: pd.DataFrame) -> dict:
    try:
        import xgboost as xgb
        mk = lambda: xgb.XGBClassifier(
            n_estimators=200, max_depth=5, learning_rate=0.05,
            subsample=0.8, colsample_bytree=0.8, min_child_weight=3,
            eval_metric="logloss", random_state=42, verbosity=0)
    except ImportError:
        from sklearn.ensemble import GradientBoostingClassifier
        mk = lambda: GradientBoostingClassifier(n_estimators=200, max_depth=5, learning_rate=0.05)

    feats = [c for c in FEATURE_COLUMNS if c in df.columns]
    X = df[feats].values.astype(np.float32)
    y = df["target"].values.astype(int)

    # Time-ordered 80/20 for an honest in-sample AUC readout
    cut = int(len(df) * 0.8)
    m = mk(); m.fit(X[:cut], y[:cut])
    auc = float(roc_auc_score(y[cut:], m.predict_proba(X[cut:])[:, 1])) if len(np.unique(y[cut:])) > 1 else 0.5

    # Final model on ALL data for deployment
    final = mk(); final.fit(X, y)
    DEPLOY_DIR.mkdir(parents=True, exist_ok=True)
    with open(DEPLOY_DIR / "xgb_deploy.pkl", "wb") as f:
        pickle.dump({"model": final, "features": feats}, f)
    print(f"  XGBoost: holdout AUC={auc:.4f}  saved → xgb_deploy.pkl")
    return {"xgb_holdout_auc": round(auc, 4), "n_rows": len(df), "features": feats}


def train_lstm(df: pd.DataFrame) -> dict:
    import torch, torch.nn as nn
    from torch.utils.data import DataLoader, TensorDataset

    feats = [c for c in FEATURE_COLUMNS if c in df.columns]

    # Build sequences per ticker (no cross-ticker leakage across the boundary)
    scaler = StandardScaler().fit(df[feats].values.astype(np.float32))
    Xs_all, ys_all = [], []
    for tic, g in df.groupby("tic"):
        Xs = scaler.transform(g[feats].values.astype(np.float32))
        y  = g["target"].values.astype(np.float32)
        for i in range(SEQ_LEN - 1, len(Xs)):
            Xs_all.append(Xs[i - SEQ_LEN + 1:i + 1]); ys_all.append(y[i])
    X = np.array(Xs_all, dtype=np.float32); y = np.array(ys_all, dtype=np.float32)

    class LSTMClf(nn.Module):
        def __init__(self, n):
            super().__init__()
            self.lstm = nn.LSTM(n, 64, num_layers=2, batch_first=True, dropout=0.3)
            self.fc = nn.Linear(64, 1); self.sig = nn.Sigmoid()
        def forward(self, x):
            o, _ = self.lstm(x); return self.sig(self.fc(o[:, -1, :]))

    cut = int(len(X) * 0.8)
    model = LSTMClf(len(feats))
    opt = torch.optim.Adam(model.parameters(), lr=1e-3); crit = nn.BCELoss()
    dl = DataLoader(TensorDataset(torch.tensor(X[:cut]), torch.tensor(y[:cut]).unsqueeze(1)),
                    batch_size=128, shuffle=True)
    model.train()
    for _ in range(15):
        for xb, yb in dl:
            opt.zero_grad(); loss = crit(model(xb), yb); loss.backward(); opt.step()
    model.eval()
    with torch.no_grad():
        probs = model(torch.tensor(X[cut:])).squeeze(1).numpy()
    auc = float(roc_auc_score(y[cut:], probs)) if len(np.unique(y[cut:])) > 1 else 0.5

    # Retrain on ALL data for deployment
    model_full = LSTMClf(len(feats))
    opt = torch.optim.Adam(model_full.parameters(), lr=1e-3)
    dl_all = DataLoader(TensorDataset(torch.tensor(X), torch.tensor(y).unsqueeze(1)),
                        batch_size=128, shuffle=True)
    model_full.train()
    for _ in range(15):
        for xb, yb in dl_all:
            opt.zero_grad(); loss = crit(model_full(xb), yb); loss.backward(); opt.step()

    DEPLOY_DIR.mkdir(parents=True, exist_ok=True)
    torch.save({"state_dict": model_full.state_dict(), "n_features": len(feats),
                "features": feats, "seq_len": SEQ_LEN}, DEPLOY_DIR / "lstm_deploy.pt")
    with open(DEPLOY_DIR / "lstm_scaler.pkl", "wb") as f:
        pickle.dump(scaler, f)
    print(f"  LSTM: holdout AUC={auc:.4f}  saved → lstm_deploy.pt + lstm_scaler.pkl")
    return {"lstm_holdout_auc": round(auc, 4)}


def main():
    print("=" * 60)
    print("Training deployable XGBoost + LSTM (pooled, all history)")
    print("=" * 60)
    df = load_all_features()
    print(f"Loaded {len(df):,} rows, {df['tic'].nunique()} tickers\n")

    meta = {}
    meta.update(train_xgb(df))
    meta.update(train_lstm(df))

    with open(DEPLOY_DIR / "deploy_meta.json", "w") as f:
        json.dump(meta, f, indent=2)
    print(f"\nSaved deployable models → {DEPLOY_DIR}")
    print("Next: live meta-learner inference can now use these base models.")
    print("=" * 60)


if __name__ == "__main__":
    main()
