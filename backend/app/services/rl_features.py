"""
Alpha-oriented state features for RL: momentum, vol, regime, cross-section, drawdown, ML confidence.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

RL_ALPHA_FEATURES = [
    # Momentum
    "ret_1", "ret_5", "ret_20", "ret_60",
    # Volatility
    "vol_20", "vol_60", "atr_pct",
    # Trend / structure
    "sma_20_dist", "sma_60_dist", "trend_200", "rel_strength_20",
    # Market context
    "market_vol_20", "mkt_trend_200", "market_beta_60",
    # Regime (one-hot style)
    "regime_bull", "regime_bear", "regime_sideways", "regime_high_vol",
    # Liquidity & drawdown state
    "volume_z_20", "liquidity_spike",
    "ticker_drawdown_peak",
    # Calendar
    "dow_sin", "dow_cos",
    # Rule alpha
    "alpha_mom_rank", "alpha_vol_adj_mom",
    # Hybrid ML + confidence
    "ml_xgb_prob", "ml_lstm_prob", "ml_confidence", "ml_agreement",
]

RL_EXTRA_INDICATORS = RL_ALPHA_FEATURES


def enrich_rl_features(df: pd.DataFrame) -> pd.DataFrame:
    """Compute alpha features per (date, ticker). All backward-looking only."""
    if df.empty or "tic" not in df.columns:
        return df

    out = df.copy()
    out["date"] = pd.to_datetime(out["date"])
    out = out.sort_values(["date", "tic"])

    if "volume" not in out.columns:
        out["volume"] = 1.0
    if "high" not in out.columns:
        out["high"] = out["close"]
    if "low" not in out.columns:
        out["low"] = out["close"]

    mkt = out.groupby("date").agg(mkt_close=("close", "mean")).reset_index()
    mkt["mkt_ret"] = mkt["mkt_close"].pct_change()
    mkt["mkt_ret_20"] = mkt["mkt_close"].pct_change(20)
    mkt["market_vol_20"] = mkt["mkt_ret"].rolling(20, min_periods=5).std().fillna(0.01)
    mkt["mkt_sma_200"] = mkt["mkt_close"].rolling(200, min_periods=20).mean()
    mkt["mkt_trend_200"] = (
        mkt["mkt_close"] / mkt["mkt_sma_200"].replace(0, np.nan) - 1
    ).fillna(0)

    vol_med = float(mkt["market_vol_20"].median()) or 0.01
    mkt["regime_bull"] = (mkt["mkt_close"] > mkt["mkt_sma_200"]).astype(float)
    mkt["regime_bear"] = (mkt["mkt_close"] < mkt["mkt_sma_200"]).astype(float)
    mkt["regime_sideways"] = (mkt["mkt_ret_20"].abs() < 0.03).astype(float)
    mkt["regime_high_vol"] = (mkt["market_vol_20"] > vol_med * 1.5).astype(float)

    mkt_cols = [
        "date", "market_vol_20", "mkt_ret_20", "mkt_trend_200", "mkt_ret",
        "regime_bull", "regime_bear", "regime_sideways", "regime_high_vol",
    ]
    out = out.merge(mkt[mkt_cols], on="date", how="left")

    pieces: list[pd.DataFrame] = []
    for ticker, g in out.groupby("tic", sort=False):
        g = g.sort_values("date").copy()
        c = g["close"].astype(float)
        h = g["high"].astype(float)
        l = g["low"].astype(float)
        v = g["volume"].astype(float).replace(0, np.nan).fillna(1)

        g["ret_1"] = c.pct_change(1)
        g["ret_5"] = c.pct_change(5)
        g["ret_20"] = c.pct_change(20)
        g["ret_60"] = c.pct_change(60)
        g["vol_20"] = c.pct_change().rolling(20, min_periods=5).std().fillna(0)
        g["vol_60"] = c.pct_change().rolling(60, min_periods=10).std().fillna(0)

        tr = pd.concat([(h - l), (h - c.shift()).abs(), (l - c.shift()).abs()], axis=1).max(axis=1)
        g["atr_pct"] = (tr.rolling(14, min_periods=3).mean() / c.replace(0, np.nan)).fillna(0)

        sma20 = c.rolling(20, min_periods=5).mean()
        sma60 = c.rolling(60, min_periods=10).mean()
        g["sma_20_dist"] = (c / sma20.replace(0, np.nan) - 1).fillna(0)
        g["sma_60_dist"] = (c / sma60.replace(0, np.nan) - 1).fillna(0)
        g["sma_200"] = c.rolling(200, min_periods=20).mean()
        g["trend_200"] = (c / g["sma_200"].replace(0, np.nan) - 1).fillna(0)
        g["rel_strength_20"] = (g["ret_20"] - g["mkt_ret_20"]).fillna(0)

        # Rolling beta vs market basket
        mkt_ret_s = g["mkt_ret"].fillna(0)
        stk_ret = c.pct_change().fillna(0)
        cov = stk_ret.rolling(60, min_periods=20).cov(mkt_ret_s)
        var = mkt_ret_s.rolling(60, min_periods=20).var().replace(0, 1e-9)
        g["market_beta_60"] = (cov / var).fillna(1.0).clip(-3, 3)

        vol_mean = v.rolling(20, min_periods=5).mean()
        vol_std = v.rolling(20, min_periods=5).std().replace(0, 1)
        g["volume_z_20"] = ((v - vol_mean) / vol_std).fillna(0)
        g["liquidity_spike"] = (g["volume_z_20"].abs() > 2.0).astype(float)

        peak = c.cummax()
        g["ticker_drawdown_peak"] = ((c - peak) / peak.replace(0, np.nan)).fillna(0).clip(-1, 0)

        dow = g["date"].dt.dayofweek
        g["dow_sin"] = np.sin(2 * np.pi * dow / 7)
        g["dow_cos"] = np.cos(2 * np.pi * dow / 7)
        g["alpha_vol_adj_mom"] = (g["ret_20"] / (g["vol_20"] + 1e-6)).clip(-5, 5)
        pieces.append(g)

    result = pd.concat(pieces, ignore_index=True)
    result["alpha_mom_rank"] = result.groupby("date")["ret_20"].rank(pct=True).fillna(0.5)

    for col in RL_ALPHA_FEATURES:
        if col not in result.columns:
            result[col] = 0.5 if col.startswith("ml_") else 0.0
        result[col] = result[col].replace([np.inf, -np.inf], 0).fillna(
            0.5 if col.startswith("ml_") else 0.0
        )

    return result


def build_alpha_state_pipeline(
    df: pd.DataFrame,
    xgb_run_id: Optional[str] = None,
    lstm_run_id: Optional[str] = None,
    data_job_id: Optional[str] = None,
) -> pd.DataFrame:
    from app.services.rl_hybrid_alpha import attach_ml_alpha_features

    df = enrich_rl_features(df)
    df = attach_ml_alpha_features(df, xgb_run_id, lstm_run_id, data_job_id)
    if "ml_xgb_prob" in df.columns:
        df["ml_confidence"] = (df["ml_xgb_prob"].astype(float) - 0.5).abs() * 2.0
    else:
        df["ml_confidence"] = 0.0
    if "ml_xgb_prob" in df.columns and "ml_lstm_prob" in df.columns:
        df["ml_agreement"] = 1.0 - (df["ml_xgb_prob"] - df["ml_lstm_prob"]).abs()
    else:
        df["ml_agreement"] = 0.5
    return df
