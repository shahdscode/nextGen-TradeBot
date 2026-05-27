"""
Hybrid ML → RL: attach directional alpha signals into the training dataframe.
"""
from __future__ import annotations

import logging
from pathlib import Path
from typing import Any, Dict, List, Optional

import numpy as np
import pandas as pd

from app.config import settings
from app.services.feature_service import FEATURE_COLUMNS, build_features

logger = logging.getLogger(__name__)

ML_ALPHA_COLUMNS = ["ml_xgb_prob", "ml_lstm_prob"]


def attach_ml_alpha_features(
    df: pd.DataFrame,
    xgb_run_id: Optional[str] = None,
    lstm_run_id: Optional[str] = None,
    data_job_id: Optional[str] = None,
) -> pd.DataFrame:
    """
    Add ml_xgb_prob / ml_lstm_prob per row (0.5 neutral if model missing).
    Uses per-ticker XGB runs from data_job_id when available.
    """
    out = df.copy()
    out["ml_xgb_prob"] = 0.5
    out["ml_lstm_prob"] = 0.5

    if data_job_id:
        from app.services.pipeline_service import best_xgb_run_per_ticker

        for ticker, rid in best_xgb_run_per_ticker(data_job_id).items():
            out = _merge_xgb_probs(out, rid, data_job_id, ticker_filter=ticker)
    elif xgb_run_id:
        out = _merge_xgb_probs(out, xgb_run_id, data_job_id)

    if lstm_run_id:
        out = _merge_lstm_probs(out, lstm_run_id, data_job_id)

    return out


def _merge_xgb_probs(
    df: pd.DataFrame,
    run_id: str,
    data_job_id: Optional[str],
    ticker_filter: Optional[str] = None,
) -> pd.DataFrame:
    from app.database import SessionLocal, Run
    from app.services.xgboost_service import predict_xgboost

    db = SessionLocal()
    try:
        run = db.query(Run).filter(Run.id == run_id).first()
    finally:
        db.close()

    if not run or not run.model_path:
        return df

    ticker = ticker_filter or (run.hyperparams or {}).get("ticker")
    model_path = str(run.model_path)
    if not Path(model_path).exists() and Path(f"{model_path}.json").exists():
        model_path = f"{model_path}.json"

    out = df.copy()
    tickers = [ticker] if ticker else out["tic"].unique().tolist()

    for tic in tickers:
        g = build_features(out, str(tic))
        if g.empty:
            continue
        feat_cols = [c for c in FEATURE_COLUMNS if c in g.columns]
        probs = []
        for _, row in g.iterrows():
            try:
                x = row[feat_cols].astype(float).values
                pred = predict_xgboost(x, model_path, feat_cols)
                probs.append(pred.get("probability", 0.5))
            except Exception:
                probs.append(0.5)
        g = g.copy()
        g["ml_xgb_prob"] = probs
        idx = out["tic"] == tic
        merged = out.loc[idx].merge(
            g[["date", "ml_xgb_prob"]],
            on="date",
            how="left",
            suffixes=("_drop", ""),
        )
        if "ml_xgb_prob" in merged.columns:
            out.loc[idx, "ml_xgb_prob"] = merged["ml_xgb_prob"].fillna(0.5).values

    return out


def _merge_lstm_probs(df: pd.DataFrame, run_id: str, data_job_id: Optional[str]) -> pd.DataFrame:
    from app.database import SessionLocal, Run
    from app.services.lstm_service import predict_lstm

    db = SessionLocal()
    try:
        run = db.query(Run).filter(Run.id == run_id).first()
    finally:
        db.close()

    if not run or not run.model_path:
        return df

    ticker = (run.hyperparams or {}).get("ticker")
    model_dir = Path(run.model_path).parent
    model_path = run.model_path

    out = df.copy()
    tickers = [ticker] if ticker else out["tic"].unique().tolist()

    for tic in tickers:
        g = build_features(out, str(tic))
        if g.empty or len(g) < 30:
            continue
        feat_cols = [c for c in FEATURE_COLUMNS if c in g.columns]
        try:
            seq_len = 20
            X = g[feat_cols].astype(float).values
            probs = [0.5] * len(g)
            for i in range(seq_len, len(g)):
                window = X[i - seq_len : i]
                pred = predict_lstm(window, str(model_path))
                probs[i] = pred.get("probability", 0.5)
            g = g.copy()
            g["ml_lstm_prob"] = probs
            idx = out["tic"] == tic
            merged = out.loc[idx].merge(g[["date", "ml_lstm_prob"]], on="date", how="left")
            if "ml_lstm_prob" in merged.columns:
                out.loc[idx, "ml_lstm_prob"] = merged["ml_lstm_prob"].fillna(0.5).values
        except Exception as e:
            logger.debug("LSTM alpha merge skipped for %s: %s", tic, e)

    return out
