"""
Out-of-Fold (OOF) Prediction Collector.

Runs all base models through walk-forward folds and stores their predictions
on held-out data only.  These OOF predictions become the training data for
the meta-learner.

CRITICAL RULE: A prediction in the OOF dataset was made by a model that did
NOT train on that row.  This prevents leakage in the meta-learner.

Example
-------
  Fold 1: train months 1-6, test month 7
    → XGBoost trained on months 1-6
    → XGBoost predicts on month 7
    → Those month-7 predictions go into OOF dataset
  Fold 2: train months 1-7, test month 8
    → XGBoost trained on months 1-7
    → XGBoost predicts on month 8
    → Those month-8 predictions go into OOF dataset
  ... and so on

Result: OOF dataset covers the entire test period with no data leakage.
"""
import json
import logging
import os
from typing import Dict, Optional

import numpy as np
import pandas as pd

from app.config import settings
from app.services.feature_service import (
    FEATURE_COLUMNS,
    add_cross_sectional_rank,
    build_features,
    generate_walk_forward_folds,
    load_fold_definitions,
    prepare_xy,
)

logger = logging.getLogger(__name__)

# Required columns in the final merged OOF dataset
_OOF_REQUIRED_COLS = {
    "date", "ticker",
    "xgb_signal", "lstm_signal",
    "ppo_signal", "a2c_signal", "ddpg_signal", "td3_signal", "sac_signal",
    "regime_bull", "regime_bear",
    "sentiment_score",
    "vix_zscore",
    "actual_5d_return",
    "target_5d",
}


# ── XGBoost OOF ───────────────────────────────────────────────────────────────

def collect_xgb_oof(
    df: pd.DataFrame,
    fold_definitions_path: str,
    vix_df: Optional[pd.DataFrame] = None,
) -> pd.DataFrame:
    """
    Train XGBoost walk-forward and collect out-of-fold predictions.

    Parameters
    ----------
    df                   : full multi-ticker featured DataFrame
    fold_definitions_path: path to fold_definitions.json
    vix_df               : VIX data from download_vix() — pass for US tickers

    Returns
    -------
    DataFrame with columns: date, ticker, xgb_signal (0-1), xgb_shap_top3 (JSON str)
    """
    try:
        import xgboost as xgb
    except ImportError:
        raise ImportError("xgboost is required: pip install xgboost")

    fold_defs = load_fold_definitions(fold_definitions_path)
    tickers = sorted(df["tic"].unique())
    records = []

    for ticker in tickers:
        try:
            featured = build_features(df, ticker, vix_df=vix_df)
            if featured.empty or len(featured) < 100:
                logger.warning("OOF XGB: skipping %s (too few rows: %d)", ticker, len(featured))
                continue

            for fold in fold_defs["folds"]:
                fold_id = fold["fold_id"]
                feat_dates = pd.to_datetime(featured["date"])

                train_mask = (feat_dates >= fold["train_start"]) & (feat_dates <= fold["train_end"])
                test_mask  = (feat_dates >= fold["test_start"])  & (feat_dates <= fold["test_end"])

                train_fold = featured[train_mask]
                test_fold  = featured[test_mask]

                if len(train_fold) < 30 or len(test_fold) < 1:
                    continue

                X_tr, y_tr = prepare_xy(train_fold)
                X_te, _    = prepare_xy(test_fold)

                model = xgb.XGBClassifier(
                    n_estimators=200, max_depth=4, learning_rate=0.05,
                    subsample=0.8, colsample_bytree=0.8,
                    use_label_encoder=False, eval_metric="logloss",
                    random_state=42, verbosity=0,
                )
                model.fit(X_tr, y_tr)
                probs = model.predict_proba(X_te)[:, 1]

                # SHAP top-3 for each test row
                try:
                    import shap
                    explainer = shap.TreeExplainer(model)
                    shap_vals = explainer.shap_values(X_te)
                    if isinstance(shap_vals, list):
                        shap_vals = shap_vals[1]
                    available_feats = [c for c in FEATURE_COLUMNS if c in test_fold.columns]
                    shap_rows = []
                    for sv in shap_vals:
                        top3 = sorted(
                            zip(available_feats, sv.tolist()),
                            key=lambda x: abs(x[1]), reverse=True
                        )[:3]
                        shap_rows.append(json.dumps([{"f": f, "v": round(v, 4)} for f, v in top3]))
                except Exception:
                    shap_rows = ["[]"] * len(probs)

                for i, (idx, row) in enumerate(test_fold.iterrows()):
                    records.append({
                        "date":         str(pd.to_datetime(row["date"]).date()),
                        "ticker":       ticker,
                        "xgb_signal":   float(probs[i]),
                        "xgb_shap_top3": shap_rows[i] if i < len(shap_rows) else "[]",
                        "fold_id":      fold_id,
                    })

        except Exception as exc:
            logger.error("OOF XGB: %s failed — %s", ticker, exc)

    result = pd.DataFrame(records)
    logger.info("XGBoost OOF: %d predictions across %d tickers", len(result), result["ticker"].nunique() if len(result) else 0)
    return result


# ── LSTM OOF ──────────────────────────────────────────────────────────────────

def collect_lstm_oof(
    df: pd.DataFrame,
    fold_definitions_path: str,
    vix_df: Optional[pd.DataFrame] = None,
    seq_len: int = 30,
) -> pd.DataFrame:
    """
    Train LSTM walk-forward (SAME fold definitions as XGBoost) and collect OOF.

    Returns
    -------
    DataFrame with columns: date, ticker, lstm_signal (0-1), fold_id
    """
    try:
        import torch
        import torch.nn as nn
        from sklearn.preprocessing import StandardScaler
    except ImportError:
        raise ImportError("torch and scikit-learn are required")

    fold_defs = load_fold_definitions(fold_definitions_path)
    tickers = sorted(df["tic"].unique())
    records = []

    class _LSTMClassifier(nn.Module):
        def __init__(self, n_features, hidden=64, layers=2):
            super().__init__()
            self.lstm = nn.LSTM(n_features, hidden, layers,
                                batch_first=True, dropout=0.2)
            self.fc = nn.Linear(hidden, 1)

        def forward(self, x):
            out, _ = self.lstm(x)
            return torch.sigmoid(self.fc(out[:, -1, :]))

    for ticker in tickers:
        try:
            featured = build_features(df, ticker, vix_df=vix_df)
            if featured.empty or len(featured) < seq_len + 20:
                continue

            for fold in fold_defs["folds"]:
                feat_dates = pd.to_datetime(featured["date"])
                train_mask = (feat_dates >= fold["train_start"]) & (feat_dates <= fold["train_end"])
                test_mask  = (feat_dates >= fold["test_start"])  & (feat_dates <= fold["test_end"])

                train_fold = featured[train_mask]
                test_fold  = featured[test_mask]

                if len(train_fold) < seq_len + 10 or len(test_fold) < 1:
                    continue

                X_tr, y_tr = prepare_xy(train_fold)
                X_te, _    = prepare_xy(test_fold)

                # Scaler fitted on training fold ONLY (no leakage)
                scaler = StandardScaler()
                X_tr = scaler.fit_transform(X_tr)
                X_te = scaler.transform(X_te)

                n_features = X_tr.shape[1]

                # Build sequences
                def _make_seqs(X, y=None):
                    xs, ys = [], []
                    for i in range(seq_len, len(X)):
                        xs.append(X[i - seq_len:i])
                        if y is not None:
                            ys.append(y[i])
                    return np.array(xs, dtype=np.float32), np.array(ys, dtype=np.float32) if y is not None else None

                X_tr_seq, y_tr_seq = _make_seqs(X_tr, y_tr)
                X_te_seq, _        = _make_seqs(X_te)
                if len(X_tr_seq) < 10 or len(X_te_seq) == 0:
                    continue

                device = "cuda" if torch.cuda.is_available() else "cpu"
                model = _LSTMClassifier(n_features).to(device)
                optimizer = torch.optim.Adam(model.parameters(), lr=1e-3)
                criterion = nn.BCELoss()

                Xt = torch.tensor(X_tr_seq).to(device)
                yt = torch.tensor(y_tr_seq).unsqueeze(1).to(device)

                model.train()
                for _ in range(30):  # lightweight — full training happens in lstm_service
                    optimizer.zero_grad()
                    loss = criterion(model(Xt), yt)
                    loss.backward()
                    optimizer.step()

                model.eval()
                with torch.no_grad():
                    probs = model(torch.tensor(X_te_seq).to(device)).cpu().numpy().flatten()

                # test_fold rows [seq_len:] correspond to probs
                test_rows = test_fold.iloc[seq_len:] if len(test_fold) > seq_len else test_fold
                for i, (_, row) in enumerate(test_rows.iterrows()):
                    if i >= len(probs):
                        break
                    records.append({
                        "date":       str(pd.to_datetime(row["date"]).date()),
                        "ticker":     ticker,
                        "lstm_signal": float(probs[i]),
                        "fold_id":    fold["fold_id"],
                    })

        except Exception as exc:
            logger.error("OOF LSTM: %s failed — %s", ticker, exc)

    result = pd.DataFrame(records)
    logger.info("LSTM OOF: %d predictions", len(result))
    return result


# ── RL signals ────────────────────────────────────────────────────────────────

def collect_rl_signals(
    trained_model_paths: Dict[str, str],
    test_df: pd.DataFrame,
) -> pd.DataFrame:
    """
    Backtest all 5 RL models over the test period and map their actions to [0, 1].

    Parameters
    ----------
    trained_model_paths : {"ppo": "/path/to/model.zip", "a2c": ..., ...}
    test_df             : featured test DataFrame (same tickers as training)

    Returns
    -------
    DataFrame: date, ticker, ppo_signal, a2c_signal, ddpg_signal, td3_signal, sac_signal
    """
    rl_keys = ["ppo", "a2c", "ddpg", "td3", "sac"]

    try:
        from stable_baselines3 import PPO, A2C, DDPG, TD3, SAC
        _rl_classes = {"ppo": PPO, "a2c": A2C, "ddpg": DDPG, "td3": TD3, "sac": SAC}
    except ImportError:
        logger.warning("stable_baselines3 not available — RL signals will be 0.5")
        _rl_classes = {}

    records = []
    dates = sorted(test_df["date"].unique())
    tickers = sorted(test_df["tic"].unique())

    # Load models once
    loaded_models = {}
    for key in rl_keys:
        path = trained_model_paths.get(key)
        if path and os.path.exists(path) and key in _rl_classes:
            try:
                loaded_models[key] = _rl_classes[key].load(path)
                logger.info("Loaded %s from %s", key, path)
            except Exception as exc:
                logger.warning("Could not load %s: %s", key, exc)

    for date in dates:
        day_df = test_df[test_df["date"] == date]
        for ticker in tickers:
            row = day_df[day_df["tic"] == ticker]
            if row.empty:
                continue

            signals = {"date": str(date), "ticker": ticker}
            X, _ = prepare_xy(row)

            for key in rl_keys:
                if key in loaded_models:
                    try:
                        action, _ = loaded_models[key].predict(X[0], deterministic=True)
                        # Map RL action to 0-1: 0=sell, 1=hold, 2=buy (standard FinRL env)
                        action_int = int(action) if np.isscalar(action) else int(action[0])
                        signals[f"{key}_signal"] = float(action_int) / 2.0  # 0.0 / 0.5 / 1.0
                    except Exception:
                        signals[f"{key}_signal"] = 0.5
                else:
                    signals[f"{key}_signal"] = 0.5

            records.append(signals)

    result = pd.DataFrame(records)
    logger.info("RL signals: %d rows (%d dates × %d tickers approx.)",
                len(result), len(dates), len(tickers))
    return result


# ── Merge & finalise ──────────────────────────────────────────────────────────

def merge_oof_predictions(
    xgb_oof: pd.DataFrame,
    lstm_oof: pd.DataFrame,
    rl_signals: pd.DataFrame,
    regime_history: pd.DataFrame,
    sentiment_history: pd.DataFrame,
    price_df: pd.DataFrame,
) -> pd.DataFrame:
    """
    Merge all OOF predictions by (date, ticker) and add ground-truth returns.

    Parameters
    ----------
    xgb_oof          : output of collect_xgb_oof()
    lstm_oof         : output of collect_lstm_oof()
    rl_signals       : output of collect_rl_signals()
    regime_history   : DataFrame with columns (date, regime) — regime per date
    sentiment_history: DataFrame with columns (date, ticker, sentiment_score)
    price_df         : raw OHLCV DataFrame with (date, tic, close)

    Returns
    -------
    Merged DataFrame with all OOF features + actual_5d_return + target_5d.
    """
    # Normalise date columns
    for df_ref in [xgb_oof, lstm_oof, rl_signals, regime_history, sentiment_history, price_df]:
        if "date" in df_ref.columns:
            df_ref["date"] = df_ref["date"].astype(str).str[:10]

    # Start from XGBoost OOF as base (has all (date, ticker) pairs)
    merged = xgb_oof[["date", "ticker", "xgb_signal"]].copy()

    # LSTM
    if not lstm_oof.empty and "lstm_signal" in lstm_oof.columns:
        merged = merged.merge(
            lstm_oof[["date", "ticker", "lstm_signal"]],
            on=["date", "ticker"], how="left",
        )
    else:
        merged["lstm_signal"] = 0.5

    # RL signals
    rl_cols = ["ppo_signal", "a2c_signal", "ddpg_signal", "td3_signal", "sac_signal"]
    if not rl_signals.empty:
        avail_rl = [c for c in rl_cols if c in rl_signals.columns]
        if avail_rl:
            merged = merged.merge(
                rl_signals[["date", "ticker"] + avail_rl],
                on=["date", "ticker"], how="left",
            )
    for col in rl_cols:
        if col not in merged.columns:
            merged[col] = 0.5

    # Regime (binary encoded)
    if not regime_history.empty and "regime" in regime_history.columns:
        rh = regime_history[["date", "regime"]].copy()
        rh["regime_bull"] = (rh["regime"] == "BULL").astype(int)
        rh["regime_bear"] = (rh["regime"] == "BEAR").astype(int)
        merged = merged.merge(rh[["date", "regime_bull", "regime_bear"]], on="date", how="left")
    else:
        merged["regime_bull"] = 0
        merged["regime_bear"] = 0

    # Sentiment
    if not sentiment_history.empty and "sentiment_score" in sentiment_history.columns:
        sent_cols = ["date", "ticker", "sentiment_score"]
        available = [c for c in sent_cols if c in sentiment_history.columns]
        if set(available) == set(sent_cols):
            merged = merged.merge(sentiment_history[sent_cols], on=["date", "ticker"], how="left")
        else:
            merged["sentiment_score"] = 0.0
    else:
        merged["sentiment_score"] = 0.0

    # VIX z-score (from price_df if present, else 0.0)
    if "vix_zscore" in price_df.columns:
        vix_cols = price_df[["date", "vix_zscore"]].drop_duplicates("date")
        merged = merged.merge(vix_cols, on="date", how="left")
    else:
        merged["vix_zscore"] = 0.0

    # Actual 5-day forward return (ground truth)
    close_df = price_df[price_df["tic"].isin(merged["ticker"].unique())].copy()
    close_df["date"] = close_df["date"].astype(str).str[:10]
    close_df = close_df.rename(columns={"tic": "ticker"})
    close_df = close_df.sort_values(["ticker", "date"])
    close_df["close_fwd5"] = close_df.groupby("ticker")["close"].shift(-5)
    close_df["actual_5d_return"] = np.log(
        close_df["close_fwd5"] / (close_df["close"] + 1e-9)
    )
    close_df = close_df.dropna(subset=["actual_5d_return"])

    merged = merged.merge(
        close_df[["date", "ticker", "actual_5d_return"]],
        on=["date", "ticker"], how="inner",   # drop rows without a known outcome
    )
    merged["target_5d"] = (merged["actual_5d_return"] > 0).astype(int)

    # Fill remaining NaNs with neutral values
    fill_map = {
        "lstm_signal": 0.5, "ppo_signal": 0.5, "a2c_signal": 0.5,
        "ddpg_signal": 0.5, "td3_signal": 0.5, "sac_signal": 0.5,
        "regime_bull": 0, "regime_bear": 0,
        "sentiment_score": 0.0, "vix_zscore": 0.0,
    }
    for col, fill_val in fill_map.items():
        if col in merged.columns:
            merged[col] = merged[col].fillna(fill_val)

    merged = merged.sort_values(["date", "ticker"]).reset_index(drop=True)
    logger.info("Merged OOF dataset: %d rows, %d tickers", len(merged), merged["ticker"].nunique())
    return merged


# ── I/O ───────────────────────────────────────────────────────────────────────

def save_oof_dataset(df: pd.DataFrame, output_path: str) -> None:
    """Save OOF dataset as CSV, creating parent dirs as needed."""
    os.makedirs(os.path.dirname(output_path) or ".", exist_ok=True)
    df.to_csv(output_path, index=False)
    logger.info("OOF dataset saved → %s  (%d rows)", output_path, len(df))


def load_oof_dataset(path: str) -> pd.DataFrame:
    """
    Load OOF dataset from CSV and validate required columns.

    Raises
    ------
    FileNotFoundError if path does not exist.
    ValueError if required columns are missing.
    """
    df = pd.read_csv(path)
    missing = _OOF_REQUIRED_COLS - set(df.columns)
    if missing:
        raise ValueError(
            f"OOF dataset at {path!r} is missing required columns: {missing}"
        )
    logger.info("OOF dataset loaded from %s  (%d rows)", path, len(df))
    return df
