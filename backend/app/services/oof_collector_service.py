"""
Out-of-Fold (OOF) Prediction Collector.

Public file-path API (used by team scripts)
-------------------------------------------
    collect_xgb_oof(data_dir=, fold_definitions_path=, output_path=)
    collect_lstm_oof(data_dir=, fold_definitions_path=, output_path=)
    collect_rl_signals(algorithm=, data_dir=, output_path=)
    merge_oof_predictions(xgb_path=, lstm_path=, rl_paths=, output_path=)
    save_oof_dataset(df, path)
    load_oof_dataset(path)

Internal DataFrame API (used by Celery tasks and tests)
-------------------------------------------------------
    _collect_xgb_oof_df(df, fold_definitions_path, vix_df)
    _collect_lstm_oof_df(df, fold_definitions_path, vix_df)
    _collect_rl_signals_df(trained_model_paths, test_df)
    _merge_oof_df(xgb_oof, lstm_oof, rl_signals, regime_history, sentiment_history, price_df)

CRITICAL RULE: A prediction in the OOF dataset was made by a model that did NOT
train on that row.  This prevents leakage in the meta-learner.

Example
-------
  Fold 1: train months 1-6, test month 7  →  XGBoost trained on 1-6, predicts 7
  Fold 2: train months 1-7, test month 8  →  XGBoost trained on 1-7, predicts 8
  ...
  Result: OOF dataset covers the full test period with no leakage anywhere.
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
    download_vix,
    load_fold_definitions,
    prepare_xy,
)

logger = logging.getLogger(__name__)

_DEFAULT_FOLD_PATH = os.path.join("data", "oof", "fold_definitions.json")

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


# ═══════════════════════════════════════════════════════════════════════════════
# PUBLIC FILE-PATH API  (one-liner per person)
# ═══════════════════════════════════════════════════════════════════════════════

def collect_xgb_oof(
    data_dir: str = "data/datasets",
    fold_definitions_path: str = _DEFAULT_FOLD_PATH,
    output_path: str = "data/oof/xgb_oof_predictions.csv",
    vix_df: Optional[pd.DataFrame] = None,
) -> pd.DataFrame:
    """
    Person 2 entry point — XGBoost OOF collection.

    Loads data from *data_dir*, trains XGBoost walk-forward, and writes
    out-of-fold predictions to *output_path*.
    """
    df = _load_df_from_dir(data_dir)
    df = add_cross_sectional_rank(df)
    if vix_df is None:
        dates = pd.to_datetime(df["date"])
        vix_df = download_vix(str(dates.min().date()), str(dates.max().date()))
    result = _collect_xgb_oof_df(df, fold_definitions_path, vix_df=vix_df)
    save_oof_dataset(result, output_path)
    return result


def collect_lstm_oof(
    data_dir: str = "data/datasets",
    fold_definitions_path: str = _DEFAULT_FOLD_PATH,
    output_path: str = "data/oof/lstm_oof_predictions.csv",
    vix_df: Optional[pd.DataFrame] = None,
) -> pd.DataFrame:
    """
    Person 3 entry point — LSTM OOF collection.

    Uses the SAME fold_definitions.json as XGBoost — critical for consistency.
    """
    df = _load_df_from_dir(data_dir)
    df = add_cross_sectional_rank(df)
    if vix_df is None:
        dates = pd.to_datetime(df["date"])
        vix_df = download_vix(str(dates.min().date()), str(dates.max().date()))
    result = _collect_lstm_oof_df(df, fold_definitions_path, vix_df=vix_df)
    save_oof_dataset(result, output_path)
    return result


def collect_rl_signals(
    algorithm: str,
    data_dir: str = "data/datasets",
    fold_definitions_path: str = _DEFAULT_FOLD_PATH,
    output_path: Optional[str] = None,
    trained_model_paths: Optional[Dict[str, str]] = None,
) -> pd.DataFrame:
    """
    Person 4 entry point — RL signal collection for one algorithm.

    Parameters
    ----------
    algorithm : "ppo" | "a2c" | "ddpg" | "td3" | "sac"
    """
    if output_path is None:
        output_path = os.path.join("data", "oof", f"rl_{algorithm}_signals.csv")

    df = _load_df_from_dir(data_dir)

    # Use test period from last fold
    fold_defs = load_fold_definitions(fold_definitions_path)
    last_fold = fold_defs["folds"][-1]
    test_df = df[
        (df["date"].astype(str) >= last_fold["test_start"]) &
        (df["date"].astype(str) <= last_fold["test_end"])
    ].copy()

    # Locate model from DB if not supplied
    if trained_model_paths is None:
        trained_model_paths = {}
        try:
            from app.database import SessionLocal, Run
            _db = SessionLocal()
            run = (
                _db.query(Run)
                .filter(Run.status == "done", Run.algorithm == algorithm)
                .order_by(Run.updated_at.desc())
                .first()
            )
            _db.close()
            if run and run.model_path:
                trained_model_paths[algorithm] = run.model_path
        except Exception:
            pass

    result = _collect_rl_signals_df(trained_model_paths, test_df)
    save_oof_dataset(result, output_path)
    return result


def merge_oof_predictions(
    xgb_path:  str = "data/oof/xgb_oof_predictions.csv",
    lstm_path: str = "data/oof/lstm_oof_predictions.csv",
    rl_paths:  Optional[Dict[str, str]] = None,
    output_path: str = "data/oof/merged_oof_dataset.csv",
    data_dir:    str = "data/datasets",
    regime_path:    Optional[str] = None,
    sentiment_path: Optional[str] = None,
) -> pd.DataFrame:
    """
    Person 2 entry point — merge all OOF predictions into one dataset.

    Reads per-model CSVs, joins them by (date, ticker), adds actual Yahoo
    Finance 5-day returns as ground truth, and writes merged_oof_dataset.csv.

    Parameters
    ----------
    rl_paths : {"ppo": "data/oof/rl_ppo_signals.csv", "a2c": ..., ...}
    """
    xgb_oof  = pd.read_csv(xgb_path)  if os.path.exists(xgb_path)  else pd.DataFrame()
    lstm_oof = pd.read_csv(lstm_path) if os.path.exists(lstm_path) else pd.DataFrame()

    rl_dfs = []
    if rl_paths:
        for _, path in rl_paths.items():
            if os.path.exists(path):
                rl_dfs.append(pd.read_csv(path))
    rl_signals = pd.concat(rl_dfs, ignore_index=True) if rl_dfs else pd.DataFrame()

    regime_history = (
        pd.read_csv(regime_path) if regime_path and os.path.exists(regime_path)
        else pd.DataFrame(columns=["date", "regime"])
    )
    sentiment_history = (
        pd.read_csv(sentiment_path) if sentiment_path and os.path.exists(sentiment_path)
        else pd.DataFrame(columns=["date", "ticker", "sentiment_score"])
    )

    price_df = _load_df_from_dir(data_dir)

    merged = _merge_oof_df(
        xgb_oof, lstm_oof, rl_signals,
        regime_history, sentiment_history, price_df,
    )
    save_oof_dataset(merged, output_path)
    return merged


# ═══════════════════════════════════════════════════════════════════════════════
# I/O HELPERS
# ═══════════════════════════════════════════════════════════════════════════════

def save_oof_dataset(df: pd.DataFrame, output_path: str) -> None:
    """Save OOF dataset as CSV, creating parent dirs as needed."""
    os.makedirs(os.path.dirname(os.path.abspath(output_path)), exist_ok=True)
    df.to_csv(output_path, index=False)
    logger.info("OOF dataset saved → %s  (%d rows)", output_path, len(df))


def load_oof_dataset(path: str) -> pd.DataFrame:
    """
    Load OOF dataset from CSV and validate required columns.

    Raises FileNotFoundError / ValueError on problems.
    """
    df = pd.read_csv(path)
    missing = _OOF_REQUIRED_COLS - set(df.columns)
    if missing:
        raise ValueError(
            f"OOF dataset at {path!r} is missing required columns: {missing}"
        )
    logger.info("OOF dataset loaded from %s  (%d rows)", path, len(df))
    return df


# ═══════════════════════════════════════════════════════════════════════════════
# INTERNAL DATAFRAME-LEVEL FUNCTIONS  (used by Celery tasks and unit tests)
# ═══════════════════════════════════════════════════════════════════════════════

def _collect_xgb_oof_df(
    df: pd.DataFrame,
    fold_definitions_path: str,
    vix_df: Optional[pd.DataFrame] = None,
) -> pd.DataFrame:
    """
    Train XGBoost on each walk-forward fold and collect out-of-fold predictions.

    Returns DataFrame: date, ticker, xgb_signal (0-1), xgb_shap_top3 (JSON), fold_id
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
                    eval_metric="logloss", random_state=42, verbosity=0,
                )
                model.fit(X_tr, y_tr)
                probs = model.predict_proba(X_te)[:, 1]

                # SHAP top-3 per row
                shap_rows = _compute_shap_top3(model, X_te, test_fold)

                for i, (_, row) in enumerate(test_fold.iterrows()):
                    records.append({
                        "date":         str(pd.to_datetime(row["date"]).date()),
                        "ticker":       ticker,
                        "xgb_signal":   float(probs[i]),
                        "xgb_shap_top3": shap_rows[i] if i < len(shap_rows) else "[]",
                        "fold_id":      fold["fold_id"],
                    })

        except Exception as exc:
            logger.error("OOF XGB: %s failed — %s", ticker, exc)

    result = pd.DataFrame(records)
    logger.info("XGBoost OOF: %d predictions across %d tickers",
                len(result), result["ticker"].nunique() if len(result) else 0)
    return result


def _compute_shap_top3(model, X_te: np.ndarray, test_fold: pd.DataFrame) -> list:
    """Return list of JSON strings with top-3 SHAP features per row."""
    try:
        import shap
        explainer = shap.TreeExplainer(model)
        shap_vals = explainer.shap_values(X_te)
        if isinstance(shap_vals, list):
            shap_vals = shap_vals[1]
        available_feats = [c for c in FEATURE_COLUMNS if c in test_fold.columns]
        rows = []
        for sv in shap_vals:
            top3 = sorted(zip(available_feats, sv.tolist()),
                          key=lambda x: abs(x[1]), reverse=True)[:3]
            rows.append(json.dumps([{"f": f, "v": round(v, 4)} for f, v in top3]))
        return rows
    except Exception:
        return ["[]"] * len(X_te)


def _collect_lstm_oof_df(
    df: pd.DataFrame,
    fold_definitions_path: str,
    vix_df: Optional[pd.DataFrame] = None,
    seq_len: int = 30,
) -> pd.DataFrame:
    """
    Train LSTM on each walk-forward fold (SAME definitions as XGBoost) and collect OOF.

    Returns DataFrame: date, ticker, lstm_signal (0-1), fold_id
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

    class _LSTMNet(nn.Module):
        def __init__(self, n_features, hidden=64, layers=2):
            super().__init__()
            self.lstm = nn.LSTM(n_features, hidden, layers,
                                batch_first=True, dropout=0.2)
            self.fc = nn.Linear(hidden, 1)

        def forward(self, x):
            out, _ = self.lstm(x)
            return torch.sigmoid(self.fc(out[:, -1, :]))

    device = "cuda" if torch.cuda.is_available() else "cpu"

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

                # Scaler on training fold ONLY
                scaler = StandardScaler()
                X_tr = scaler.fit_transform(X_tr)
                X_te = scaler.transform(X_te)
                n_features = X_tr.shape[1]

                def _seqs(X, y=None):
                    xs, ys = [], []
                    for i in range(seq_len, len(X)):
                        xs.append(X[i - seq_len:i])
                        if y is not None:
                            ys.append(y[i])
                    return (np.array(xs, dtype=np.float32),
                            np.array(ys, dtype=np.float32) if y is not None else None)

                X_tr_s, y_tr_s = _seqs(X_tr, y_tr)
                X_te_s, _      = _seqs(X_te)
                if len(X_tr_s) < 10 or len(X_te_s) == 0:
                    continue

                model = _LSTMNet(n_features).to(device)
                opt   = torch.optim.Adam(model.parameters(), lr=1e-3)
                crit  = nn.BCELoss()
                Xt = torch.tensor(X_tr_s).to(device)
                yt = torch.tensor(y_tr_s).unsqueeze(1).to(device)

                model.train()
                for _ in range(30):   # lightweight training per fold
                    opt.zero_grad()
                    crit(model(Xt), yt).backward()
                    opt.step()

                model.eval()
                with torch.no_grad():
                    probs = model(torch.tensor(X_te_s).to(device)).cpu().numpy().flatten()

                test_rows = test_fold.iloc[seq_len:] if len(test_fold) > seq_len else test_fold
                for i, (_, row) in enumerate(test_rows.iterrows()):
                    if i >= len(probs):
                        break
                    records.append({
                        "date":        str(pd.to_datetime(row["date"]).date()),
                        "ticker":      ticker,
                        "lstm_signal": float(probs[i]),
                        "fold_id":     fold["fold_id"],
                    })

        except Exception as exc:
            logger.error("OOF LSTM: %s failed — %s", ticker, exc)

    result = pd.DataFrame(records)
    logger.info("LSTM OOF: %d predictions", len(result))
    return result


def _collect_rl_signals_df(
    trained_model_paths: Dict[str, str],
    test_df: pd.DataFrame,
) -> pd.DataFrame:
    """
    Backtest all 5 RL models over the test period and map actions to [0, 1].

    Returns DataFrame: date, ticker, ppo_signal, a2c_signal, ddpg_signal, td3_signal, sac_signal
    """
    rl_keys = ["ppo", "a2c", "ddpg", "td3", "sac"]

    try:
        from stable_baselines3 import PPO, A2C, DDPG, TD3, SAC
        _rl_cls = {"ppo": PPO, "a2c": A2C, "ddpg": DDPG, "td3": TD3, "sac": SAC}
    except ImportError:
        logger.warning("stable_baselines3 not available — RL signals will be 0.5")
        _rl_cls = {}

    loaded = {}
    for key in rl_keys:
        path = trained_model_paths.get(key)
        if path and os.path.exists(path) and key in _rl_cls:
            try:
                loaded[key] = _rl_cls[key].load(path)
            except Exception as e:
                logger.warning("Could not load %s: %s", key, e)

    records = []
    for date in sorted(test_df["date"].unique()):
        day_df = test_df[test_df["date"] == date]
        for ticker in sorted(test_df["tic"].unique()):
            row = day_df[day_df["tic"] == ticker]
            if row.empty:
                continue
            signals = {"date": str(date), "ticker": ticker}
            X, _ = prepare_xy(row)
            for key in rl_keys:
                if key in loaded:
                    try:
                        action, _ = loaded[key].predict(X[0], deterministic=True)
                        action_int = int(action) if np.isscalar(action) else int(action[0])
                        signals[f"{key}_signal"] = float(action_int) / 2.0
                    except Exception:
                        signals[f"{key}_signal"] = 0.5
                else:
                    signals[f"{key}_signal"] = 0.5
            records.append(signals)

    result = pd.DataFrame(records)
    logger.info("RL signals: %d rows", len(result))
    return result


def _merge_oof_df(
    xgb_oof: pd.DataFrame,
    lstm_oof: pd.DataFrame,
    rl_signals: pd.DataFrame,
    regime_history: pd.DataFrame,
    sentiment_history: pd.DataFrame,
    price_df: pd.DataFrame,
) -> pd.DataFrame:
    """
    Merge all OOF predictions by (date, ticker) and add ground-truth returns.
    """
    # Normalise date strings
    for _df in [xgb_oof, lstm_oof, rl_signals, regime_history, sentiment_history, price_df]:
        if "date" in _df.columns:
            _df["date"] = _df["date"].astype(str).str[:10]

    merged = xgb_oof[["date", "ticker", "xgb_signal"]].copy()

    if not lstm_oof.empty and "lstm_signal" in lstm_oof.columns:
        merged = merged.merge(lstm_oof[["date", "ticker", "lstm_signal"]],
                              on=["date", "ticker"], how="left")
    else:
        merged["lstm_signal"] = 0.5

    rl_cols = ["ppo_signal", "a2c_signal", "ddpg_signal", "td3_signal", "sac_signal"]
    if not rl_signals.empty:
        avail = [c for c in rl_cols if c in rl_signals.columns]
        if avail:
            merged = merged.merge(rl_signals[["date", "ticker"] + avail],
                                  on=["date", "ticker"], how="left")
    for col in rl_cols:
        if col not in merged.columns:
            merged[col] = 0.5

    if not regime_history.empty and "regime" in regime_history.columns:
        rh = regime_history[["date", "regime"]].copy()
        rh["regime_bull"] = (rh["regime"] == "BULL").astype(int)
        rh["regime_bear"] = (rh["regime"] == "BEAR").astype(int)
        merged = merged.merge(rh[["date", "regime_bull", "regime_bear"]], on="date", how="left")
    else:
        merged["regime_bull"] = 0
        merged["regime_bear"] = 0

    if not sentiment_history.empty and "sentiment_score" in sentiment_history.columns:
        merged = merged.merge(
            sentiment_history[["date", "ticker", "sentiment_score"]],
            on=["date", "ticker"], how="left",
        )
    else:
        merged["sentiment_score"] = 0.0

    if "vix_zscore" in price_df.columns:
        vix = price_df[["date", "vix_zscore"]].drop_duplicates("date")
        merged = merged.merge(vix, on="date", how="left")
    else:
        merged["vix_zscore"] = 0.0

    # Ground-truth 5-day forward return
    close_df = price_df[price_df["tic"].isin(merged["ticker"].unique())].copy()
    close_df = close_df.rename(columns={"tic": "ticker"}).sort_values(["ticker", "date"])
    close_df["close_fwd5"] = close_df.groupby("ticker")["close"].shift(-5)
    close_df["actual_5d_return"] = np.log(
        close_df["close_fwd5"] / (close_df["close"] + 1e-9)
    )
    close_df = close_df.dropna(subset=["actual_5d_return"])

    merged = merged.merge(
        close_df[["date", "ticker", "actual_5d_return"]],
        on=["date", "ticker"], how="inner",
    )
    merged["target_5d"] = (merged["actual_5d_return"] > 0).astype(int)

    fill = {"lstm_signal": 0.5, "ppo_signal": 0.5, "a2c_signal": 0.5,
            "ddpg_signal": 0.5, "td3_signal": 0.5, "sac_signal": 0.5,
            "regime_bull": 0, "regime_bear": 0, "sentiment_score": 0.0, "vix_zscore": 0.0}
    for col, v in fill.items():
        if col in merged.columns:
            merged[col] = merged[col].fillna(v)

    merged = merged.sort_values(["date", "ticker"]).reset_index(drop=True)
    logger.info("Merged OOF: %d rows, %d tickers", len(merged), merged["ticker"].nunique())
    return merged


# ── Internal helper ─────────────────────────────────────────────────────────

def _load_df_from_dir(data_dir: str) -> pd.DataFrame:
    """Load the most-recent parquet or CSV from *data_dir* (recursive search)."""
    import glob
    for ext in ("*.parquet", "*.csv"):
        matches = sorted(glob.glob(os.path.join(data_dir, "**", ext), recursive=True))
        if matches:
            path = matches[-1]
            logger.info("Loading data from %s", path)
            return pd.read_parquet(path) if path.endswith(".parquet") else pd.read_csv(path)
    raise FileNotFoundError(f"No parquet or CSV found under {data_dir!r}")
