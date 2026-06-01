#!/usr/bin/env python3
"""
Step 3 — LSTM Out-of-Fold Prediction Collection.

Mirrors step2_xgb_oof.py but with a 2-layer LSTM classifier. Uses the SAME
fold_definitions.json so XGBoost and LSTM OOF predictions align exactly for
the meta-learner. Per-fold StandardScaler is fit on TRAIN ONLY (no leakage).

Inputs  (from Step 1):
    data/oof/features_us.csv
    data/oof/features_egx.csv
    data/models/fold_definitions.json
Output:
    data/oof/lstm_oof_predictions.csv   (date, ticker, lstm_signal, fold_id)

Usage:
    cd /Users/shaahdmaansour/Downloads/nextGen-TradeBot
    source .venv/bin/activate
    python scripts/step3_lstm_oof.py
"""

import sys, os, logging
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "backend"))
os.chdir(ROOT / "backend")

import numpy as np
import pandas as pd

logging.basicConfig(level=logging.INFO,
                    format="%(asctime)s  %(levelname)-8s  %(message)s",
                    datefmt="%H:%M:%S")
logger = logging.getLogger("step3")

from app.services.feature_service import prepare_xy, FEATURE_COLUMNS, load_fold_definitions, TARGET_HORIZON

FEATURES_US  = ROOT / "data" / "oof" / "features_us.csv"
FEATURES_EGX = ROOT / "data" / "oof" / "features_egx.csv"
FOLD_PATH    = ROOT / "data" / "models" / "fold_definitions.json"
OUTPUT_PATH  = ROOT / "data" / "oof" / "lstm_oof_predictions.csv"

SEQ_LEN = 20
EPOCHS  = 20
BATCH   = 64
LR      = 1e-3


def _slice_fold(df, fold, date_col="date"):
    df = df.copy()
    df[date_col] = pd.to_datetime(df[date_col])
    train_end  = pd.to_datetime(fold["train_end"])
    test_start = pd.to_datetime(fold["test_start"])
    test_end   = pd.to_datetime(fold["test_end"])
    train_df = df[df[date_col] <= train_end].copy()
    test_df  = df[(df[date_col] >= test_start) & (df[date_col] <= test_end)].copy()
    if len(train_df) > TARGET_HORIZON:
        embargo = train_df[date_col].sort_values().unique()[-TARGET_HORIZON:]
        train_df = train_df[~train_df[date_col].isin(embargo)]
    return train_df, test_df


def _make_sequences(X, y, seq_len):
    Xo, yo = [], []
    for i in range(seq_len - 1, len(X)):
        Xo.append(X[i - seq_len + 1:i + 1]); yo.append(y[i])
    return np.array(Xo, dtype=np.float32), np.array(yo, dtype=np.float32)


def _build_model(n_features, torch, nn):
    class LSTMClf(nn.Module):
        def __init__(self):
            super().__init__()
            self.lstm = nn.LSTM(n_features, 64, num_layers=2, batch_first=True, dropout=0.2)
            self.fc = nn.Linear(64, 1); self.sig = nn.Sigmoid()
        def forward(self, x):
            _, (h, _) = self.lstm(x)
            return self.sig(self.fc(h[-1]))
    return LSTMClf()


def collect_for_market(df, folds, market):
    import torch, torch.nn as nn
    from sklearn.preprocessing import StandardScaler
    tickers = sorted(df["tic"].unique())
    logger.info("[%s] %d tickers, %d folds", market.upper(), len(tickers), len(folds))
    rows = []
    for tic in tickers:
        tdf = df[df["tic"] == tic].sort_values("date").reset_index(drop=True)
        tic_rows = 0
        for fi, fold in enumerate(folds):
            tr, te = _slice_fold(tdf, fold)
            Xtr, ytr = prepare_xy(tr); Xte, yte = prepare_xy(te)
            if len(Xtr) < SEQ_LEN + 10 or len(Xte) == 0:
                continue
            scaler = StandardScaler()
            Xtr_s = scaler.fit_transform(Xtr); Xte_s = scaler.transform(Xte)
            Xtr_seq, ytr_seq = _make_sequences(Xtr_s, ytr, SEQ_LEN)
            if len(Xtr_seq) < 10:
                continue
            model = _build_model(Xtr.shape[1], torch, nn)
            opt = torch.optim.Adam(model.parameters(), lr=LR); crit = nn.BCELoss()
            Xt = torch.tensor(Xtr_seq); yt = torch.tensor(ytr_seq).unsqueeze(1)
            model.train()
            for _ in range(EPOCHS):
                for i in range(0, len(Xt), BATCH):
                    opt.zero_grad()
                    loss = crit(model(Xt[i:i+BATCH]), yt[i:i+BATCH])
                    loss.backward(); opt.step()

            # Prepend the last SEQ_LEN-1 TRAIN rows as lookback context so EVERY
            # test row gets a full sequence (otherwise the first 19 rows of each
            # ~21-day fold window are lost → ~2 preds/fold). Context is past
            # train data → no leakage; only test-row labels are predicted.
            ctx     = Xtr_s[-(SEQ_LEN - 1):]
            Xte_ctx = np.vstack([ctx, Xte_s])
            yte_ctx = np.concatenate([ytr[-(SEQ_LEN - 1):], yte])
            Xte_seq, _ = _make_sequences(Xte_ctx, yte_ctx, SEQ_LEN)
            if len(Xte_seq) == 0:
                continue
            model.eval()
            with torch.no_grad():
                probs = model(torch.tensor(Xte_seq)).squeeze(1).numpy()
            # len(Xte_seq) == len(Xte_s): one prediction per test row
            test_dates = pd.to_datetime(te["date"]).dt.strftime("%Y-%m-%d").tolist()
            for d, p in zip(test_dates, probs):
                rows.append({"date": d, "ticker": tic, "lstm_signal": round(float(p), 4), "fold_id": fi})
                tic_rows += 1
        logger.info("  %-12s  %d OOF predictions", tic, tic_rows)
    return rows


def main():
    logger.info("=" * 60)
    logger.info("Step 3 — LSTM OOF Collection (horizon=%d)", TARGET_HORIZON)
    logger.info("=" * 60)
    for p in (FEATURES_US, FEATURES_EGX, FOLD_PATH):
        if not p.exists():
            logger.error("Missing input: %s — run step1 then step2 first", p); sys.exit(1)

    folds = load_fold_definitions(str(FOLD_PATH))["folds"]
    us = pd.read_csv(FEATURES_US); egx = pd.read_csv(FEATURES_EGX)
    logger.info("US %d rows | EGX %d rows | %d folds", len(us), len(egx), len(folds))

    try:
        import torch  # noqa
        logger.info("PyTorch available")
    except ImportError:
        logger.error("PyTorch required for LSTM OOF"); sys.exit(1)

    rows = []
    logger.info("\n── US ──"); rows += collect_for_market(us, folds, "us")
    logger.info("\n── EGX ──"); rows += collect_for_market(egx, folds, "egx")

    if not rows:
        logger.error("No LSTM OOF predictions collected"); sys.exit(1)

    out = pd.DataFrame(rows).sort_values(["date", "ticker"]).reset_index(drop=True)
    OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    out.to_csv(OUTPUT_PATH, index=False)
    logger.info("\nLSTM OOF saved → %s  (%d rows, %d tickers)",
                OUTPUT_PATH, len(out), out["ticker"].nunique())
    logger.info("Next: python scripts/register_oof_runs.py  then Step 5")


if __name__ == "__main__":
    main()
