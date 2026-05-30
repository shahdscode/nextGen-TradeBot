"""
LSTM service with wavelet denoising applied BEFORE feature computation.

Step-1 compatibility:
- 25 features (vix_level/vix_zscore, price_range_position, rank_20d_mom)
- 5-day forward-return target (handled by build_features)
- Wavelet denoising on raw OHLCV close BEFORE indicators are computed
  (previously denoised AFTER features — indicators were computed from noisy close)
- VIX downloaded for US tickers, passed to build_features
- Scaler fitted on last-fold training split only (leakage-free)
- Dynamic holdout: last 20% of data
"""
import json
import logging
import numpy as np
import pandas as pd
from pathlib import Path
from typing import Dict, Any, List, Optional, Tuple

from app.config import settings
from app.services.feature_service import (
    build_features,
    generate_walk_forward_folds,
    prepare_xy,
    FEATURE_COLUMNS,
    add_mahalanobis_turbulence,
    add_cross_sectional_rank,
    download_vix,
)

logger = logging.getLogger(__name__)

try:
    import torch
    import torch.nn as nn
    from torch.utils.data import DataLoader, TensorDataset
    TORCH_AVAILABLE = True
except ImportError:
    TORCH_AVAILABLE = False

try:
    import pywt
    PYWT_AVAILABLE = True
except ImportError:
    PYWT_AVAILABLE = False

try:
    from sklearn.preprocessing import StandardScaler
    from sklearn.metrics import roc_auc_score
    SKLEARN_AVAILABLE = True
except ImportError:
    SKLEARN_AVAILABLE = False

SEQUENCE_LEN = 20


class LSTMClassifier(nn.Module if TORCH_AVAILABLE else object):
    def __init__(self, input_size: int, hidden_size: int = 64,
                 num_layers: int = 2, dropout: float = 0.3):
        if TORCH_AVAILABLE:
            super().__init__()
            self.lstm = nn.LSTM(input_size, hidden_size, num_layers=num_layers,
                                dropout=dropout, batch_first=True)
            self.fc = nn.Linear(hidden_size, 1)
            self.sigmoid = nn.Sigmoid()

    def forward(self, x):
        out, _ = self.lstm(x)
        return self.sigmoid(self.fc(out[:, -1, :]))


def train_lstm(
    run_id: str,
    data_job_id: str,
    ticker: str,
    epochs: int = 30,
    market: str = "us",
) -> Dict[str, Any]:
    """
    Train LSTM with walk-forward evaluation and wavelet denoising.

    Parameters
    ----------
    run_id       : unique run identifier
    data_job_id  : ID of the completed data download job
    ticker       : ticker symbol to train on
    epochs       : training epochs per fold
    market       : "us" or "egx" — controls VIX download
    """
    data_path = Path(settings.data_dir) / data_job_id / "data.csv"
    model_dir = Path(settings.models_dir) / run_id
    model_dir.mkdir(parents=True, exist_ok=True)

    df_raw = pd.read_csv(data_path)
    if "tic" not in df_raw.columns:
        df_raw["tic"] = ticker
    tickers_available = df_raw["tic"].unique().tolist()
    if ticker not in tickers_available:
        ticker = tickers_available[0]

    # ── Cross-sectional preprocessing (multi-ticker path) ────────────────────
    if len(tickers_available) > 1:
        logger.info("Multi-ticker CSV (%d tickers) — Mahalanobis turbulence + rank",
                    len(tickers_available))
        df_raw = add_mahalanobis_turbulence(df_raw)
        df_raw = add_cross_sectional_rank(df_raw)

    # ── Wavelet denoising on RAW close BEFORE feature computation ────────────
    # IMPORTANT: denoising must happen here, on the OHLCV price, so that all
    # technical indicators (ATR, RSI, Bollinger, momentum, etc.) are computed
    # from the denoised price series — not from the raw noisy close.
    # Previous code applied denoising after build_features, making it a no-op.
    if PYWT_AVAILABLE:
        df_raw = _wavelet_denoise_df(df_raw, ticker)

    # ── VIX for US tickers ────────────────────────────────────────────────────
    vix_df = None
    is_egx = ticker.upper().endswith(".CA") or market.lower() == "egx"
    if not is_egx:
        try:
            dates = pd.to_datetime(df_raw["date"])
            vix_df = download_vix(str(dates.min().date()), str(dates.max().date()))
        except Exception as exc:
            logger.warning("VIX download failed: %s — vix features will be 0", exc)

    featured = build_features(df_raw, ticker, vix_df=vix_df)
    if len(featured) < SEQUENCE_LEN + 20:
        return _synthetic_lstm_result(model_dir, ticker)

    folds = generate_walk_forward_folds(featured, train_months=12, test_months=1)
    if not folds:
        return _synthetic_lstm_result(model_dir, ticker)

    fold_metrics = []

    if TORCH_AVAILABLE and SKLEARN_AVAILABLE:
        for train_df, test_df in folds:
            X_tr, y_tr = prepare_xy(train_df)
            X_te, y_te = prepare_xy(test_df)

            # Scaler fitted on training fold ONLY (no leakage)
            scaler = StandardScaler()
            X_tr = scaler.fit_transform(X_tr)
            X_te = scaler.transform(X_te)

            if len(X_tr) <= SEQUENCE_LEN or len(X_te) <= SEQUENCE_LEN:
                continue

            X_tr_seq, y_tr_seq = _make_sequences(X_tr, y_tr)
            X_te_seq, y_te_seq = _make_sequences(X_te, y_te)
            if len(X_tr_seq) < 10 or len(X_te_seq) < 1:
                continue

            model = LSTMClassifier(input_size=X_tr.shape[1])
            optimizer = torch.optim.Adam(model.parameters(), lr=1e-3)
            criterion = nn.BCELoss()

            dataset = TensorDataset(
                torch.FloatTensor(X_tr_seq),
                torch.FloatTensor(y_tr_seq).unsqueeze(1),
            )
            loader = DataLoader(dataset, batch_size=32, shuffle=True)

            best_loss = float("inf")
            patience_count = 0
            model.train()
            for epoch in range(epochs):
                epoch_loss = 0.0
                for xb, yb in loader:
                    optimizer.zero_grad()
                    pred = model(xb)
                    loss = criterion(pred, yb)
                    loss.backward()
                    optimizer.step()
                    epoch_loss += loss.item()
                if epoch_loss < best_loss:
                    best_loss = epoch_loss
                    patience_count = 0
                else:
                    patience_count += 1
                if patience_count >= 5:
                    break

            model.eval()
            with torch.no_grad():
                probs = model(torch.FloatTensor(X_te_seq)).numpy().flatten()
            preds = (probs >= 0.5).astype(int)
            acc = float(np.mean(preds == y_te_seq))
            auc = float(roc_auc_score(y_te_seq, probs)) if len(np.unique(y_te_seq)) > 1 else 0.5
            fold_metrics.append({"accuracy": round(acc, 4), "auc": round(auc, 4)})

        if fold_metrics:
            # ── Deployment model ─────────────────────────────────────────────
            # Scaler fitted on last-fold training split only (no leakage).
            last_train_df, _ = folds[-1]
            X_last_tr, _ = prepare_xy(last_train_df)
            deployment_scaler = StandardScaler().fit(X_last_tr)

            X_all, y_all = prepare_xy(featured.dropna())
            X_all_s = deployment_scaler.transform(X_all)

            # Dynamic holdout: last 20%
            mean_auc = float(np.mean([f["auc"] for f in fold_metrics]))
            mean_acc = float(np.mean([f["accuracy"] for f in fold_metrics]))
            val_auc, val_acc = mean_auc, mean_acc
            n = len(X_all_s)
            split = int(n * 0.80)
            if n - split >= SEQUENCE_LEN + 5 and split >= SEQUENCE_LEN + 10:
                X_vt_seq, y_vt_seq = _make_sequences(X_all_s[:split], y_all[:split])
                X_vv_seq, y_vv_seq = _make_sequences(X_all_s[split:], y_all[split:])
                if len(X_vv_seq) >= 5 and len(np.unique(y_vv_seq)) > 1:
                    val_m = LSTMClassifier(input_size=X_all_s.shape[1])
                    opt2  = torch.optim.Adam(val_m.parameters(), lr=1e-3)
                    ds2   = TensorDataset(torch.FloatTensor(X_vt_seq),
                                          torch.FloatTensor(y_vt_seq).unsqueeze(1))
                    ld2   = DataLoader(ds2, batch_size=32, shuffle=True)
                    val_m.train()
                    for _ in range(20):
                        for xb, yb in ld2:
                            opt2.zero_grad()
                            criterion(val_m(xb), yb).backward()
                            opt2.step()
                    val_m.eval()
                    with torch.no_grad():
                        vprobs = val_m(torch.FloatTensor(X_vv_seq)).numpy().flatten()
                    val_acc = float(np.mean((vprobs >= 0.5).astype(int) == y_vv_seq))
                    val_auc = float(roc_auc_score(y_vv_seq, vprobs))

            X_seq, y_seq = _make_sequences(X_all_s, y_all)
            final_model = LSTMClassifier(input_size=X_all_s.shape[1])
            opt_final = torch.optim.Adam(final_model.parameters(), lr=1e-3)
            ds_final  = TensorDataset(torch.FloatTensor(X_seq),
                                       torch.FloatTensor(y_seq).unsqueeze(1))
            ld_final  = DataLoader(ds_final, batch_size=32, shuffle=True)
            final_model.train()
            for _ in range(20):
                for xb, yb in ld_final:
                    opt_final.zero_grad()
                    criterion(final_model(xb), yb).backward()
                    opt_final.step()

            model_path = str(model_dir / f"lstm_{ticker}.pt")
            torch.save({
                "model_state":  final_model.state_dict(),
                "scaler_mean":  deployment_scaler.mean_.tolist(),
                "scaler_scale": deployment_scaler.scale_.tolist(),
                "input_size":   X_all_s.shape[1],
                "sequence_len": SEQUENCE_LEN,
                "wavelet_used": PYWT_AVAILABLE,
            }, model_path)

            metrics = {
                "ticker":             ticker,
                "market":             market,
                "algorithm":          "lstm",
                "model_type":         "lstm",
                "n_features":         X_all_s.shape[1],
                "mean_accuracy":      round(mean_acc, 4),
                "mean_auc":           round(mean_auc, 4),
                "holdout_auc":        round(val_auc, 4),
                "holdout_accuracy":   round(val_acc, 4),
                "holdout_split":      "last 20%",
                "n_folds":            len(fold_metrics),
                "fold_metrics":       fold_metrics,
                "final_reward":       round(mean_auc, 4),
                "wavelet_denoising":  PYWT_AVAILABLE,
                "vix_features_used":  vix_df is not None and not vix_df.empty,
                "mahalanobis_turbulence": len(tickers_available) > 1,
            }
            with open(model_dir / "metrics.json", "w") as f:
                json.dump(metrics, f, indent=2)
            return {"model_path": model_path, "metrics": metrics}

    return _synthetic_lstm_result(model_dir, ticker)


def predict_lstm(
    features: np.ndarray,
    model_path: str,
    sequence_len: int = SEQUENCE_LEN,
) -> Dict[str, Any]:
    """Run LSTM inference. features shape: (seq_len, n_features)."""
    try:
        if TORCH_AVAILABLE and Path(model_path).exists():
            checkpoint = torch.load(model_path, map_location="cpu", weights_only=False)
            scaler_mean  = np.array(checkpoint["scaler_mean"])
            scaler_scale = np.array(checkpoint["scaler_scale"])
            input_size   = checkpoint["input_size"]
            seq_len      = checkpoint.get("sequence_len", sequence_len)

            model = LSTMClassifier(input_size=input_size)
            model.load_state_dict(checkpoint["model_state"])
            model.eval()

            feat = features[-seq_len:] if len(features) >= seq_len else features
            feat = (feat - scaler_mean) / (scaler_scale + 1e-9)
            x = torch.FloatTensor(feat).unsqueeze(0)
            with torch.no_grad():
                prob = float(model(x).item())
            return {"probability": round(prob, 4)}
    except Exception as exc:
        logger.warning("predict_lstm failed: %s — returning neutral 0.5", exc)
    return {"probability": 0.5}


# ── Internal helpers ─────────────────────────────────────────────────────────

def _wavelet_denoise_df(df: pd.DataFrame, ticker: str) -> pd.DataFrame:
    """
    Apply Daubechies-4 wavelet soft-threshold denoising to the close price
    of *ticker* in the DataFrame, IN PLACE on a copy.

    This modifies df["close"] for rows belonging to *ticker* so that
    build_features() computes all indicators (ATR, RSI, Bollinger, etc.)
    from the denoised series.
    """
    df = df.copy()
    mask = df["tic"] == ticker
    try:
        close = df.loc[mask, "close"].values.astype(float)
        coeffs = pywt.wavedec(close, "db4", level=4)
        sigma = np.median(np.abs(coeffs[-1])) / 0.6745
        threshold = sigma * np.sqrt(2 * np.log(max(len(close), 2)))
        coeffs[1:] = [pywt.threshold(c, threshold, mode="soft") for c in coeffs[1:]]
        denoised = pywt.waverec(coeffs, "db4")[:len(close)]
        df.loc[mask, "close"] = denoised
    except Exception as exc:
        logger.warning("Wavelet denoising failed for %s: %s — using raw close", ticker, exc)
    return df


def _make_sequences(X: np.ndarray, y: np.ndarray) -> Tuple[np.ndarray, np.ndarray]:
    X_seq, y_seq = [], []
    for i in range(SEQUENCE_LEN, len(X)):
        X_seq.append(X[i - SEQUENCE_LEN:i])
        y_seq.append(y[i])
    return np.array(X_seq, dtype=np.float32), np.array(y_seq, dtype=np.float32)


def _synthetic_lstm_result(model_dir: Path, ticker: str) -> Dict[str, Any]:
    model_path = str(model_dir / f"lstm_{ticker}_synthetic.pkl")
    Path(model_path).touch()
    metrics = {
        "ticker":     ticker,
        "algorithm":  "lstm",
        "model_type": "lstm",
        "mean_auc":   0.0,
        "n_folds":    0,
        "note":       "Synthetic result — PyTorch unavailable or insufficient data",
        "final_reward": 0.5,
    }
    with open(model_dir / "metrics.json", "w") as f:
        json.dump(metrics, f, indent=2)
    return {"model_path": model_path, "metrics": metrics}
