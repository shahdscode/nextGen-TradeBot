"""
Live model-driven allocation for paper trading.

Applies a trained model to LIVE DOW30 daily data and returns the target
portfolio the model would hold right now. Used by the paper-trading router to
drive real model decisions (instead of equal-weight buy-and-hold).

Only equity models are supported (RL portfolio policies + meta-learner), since
they were trained on the 29 DOW30 stocks. The live feed is Yahoo daily bars
(MT5 retail gateways rarely carry US equities).

Flow:
  download ~420d daily OHLCV for 29 DOW30 stocks
    → 25-feature matrix (+ VIX, cross-sectional rank, Mahalanobis turbulence)
    → StockTradingEnv (state space identical to training)
    → run policy through history; read final holdings as the live target
    → scale to the paper account's capital → {ticker: target_qty}
"""
from __future__ import annotations

import logging
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Dict, List, Optional

import numpy as np
import pandas as pd

from app.config import settings
from app import finrl_wrapper
from app.database import SessionLocal, Run
from app.services.feature_service import (
    FEATURE_COLUMNS,
    build_features,
    add_cross_sectional_rank,
    add_mahalanobis_turbulence,
    download_vix,
)
from app.ticker_catalog import DOW_30_TICKER

logger = logging.getLogger(__name__)

# Training universe: DOW30 minus WBA (delisted on Yahoo). Must match step4.
LIVE_TICKERS = sorted([t for t in DOW_30_TICKER if t != "WBA"])
RL_ALGOS = {"ppo", "a2c", "ddpg", "td3", "sac"}
_LOOKBACK_DAYS = 420   # calendar days; ~280 trading days (252 warmup + buffer)


def _download_live(tickers: List[str], start: str, end: str) -> pd.DataFrame:
    import yfinance as yf
    frames = []
    for tic in tickers:
        try:
            raw = yf.download(tic, start=start, end=end, progress=False, auto_adjust=True)
            if raw.empty:
                continue
            if isinstance(raw.columns, pd.MultiIndex):
                raw.columns = raw.columns.get_level_values(0)
            raw = raw.rename(columns=str.lower).reset_index()
            raw = raw.rename(columns={"index": "date", "Date": "date", "Datetime": "date"})
            raw["tic"] = tic
            for c in ("open", "high", "low", "close", "volume"):
                if c not in raw.columns:
                    raw[c] = 0.0
            frames.append(raw[["date", "tic", "open", "high", "low", "close", "volume"]])
        except Exception as exc:
            logger.warning("live download failed for %s: %s", tic, exc)
    if not frames:
        raise RuntimeError("No live data downloaded for any ticker")
    df = pd.concat(frames, ignore_index=True)
    df["date"] = pd.to_datetime(df["date"]).dt.normalize()
    df = df.sort_values(["tic", "date"])
    df["close"] = df.groupby("tic")["close"].transform(
        lambda s: s.replace(0, np.nan).ffill().bfill()
    )
    return df


def _build_featured(df: pd.DataFrame, vix_df: pd.DataFrame) -> pd.DataFrame:
    df = add_cross_sectional_rank(df)
    df = add_mahalanobis_turbulence(df, lookback=252)
    feat_frames = []
    for tic in sorted(df["tic"].unique()):
        f = build_features(df, ticker=tic, vix_df=vix_df)
        if not f.empty:
            feat_frames.append(f)
    return pd.concat(feat_frames, ignore_index=True)


def _make_env(featured: pd.DataFrame, initial_cash: float):
    finrl_wrapper._mock_finrl_optional_deps()
    from finrl.meta.env_stock_trading.env_stocktrading import StockTradingEnv

    df = featured.copy()
    df["date"] = pd.to_datetime(df["date"])
    # Complete date×ticker grid + shared integer day index (FinRL requirement)
    all_dates = sorted(df["date"].unique())
    all_tics = sorted(df["tic"].unique())
    idx = pd.MultiIndex.from_product([all_dates, all_tics], names=["date", "tic"])
    df = (df.set_index(["date", "tic"]).reindex(idx)
            .groupby(level="tic", group_keys=False).ffill().reset_index())
    for c in ("open", "high", "low", "close", "volume"):
        if c in df.columns:
            df[c] = df.groupby("tic")[c].transform(lambda s: s.bfill())
    df = df.fillna(0).sort_values(["date", "tic"]).reset_index(drop=True)
    d2d = {d: i for i, d in enumerate(sorted(df["date"].unique()))}
    df.index = df["date"].map(d2d)
    df["day"] = df.index

    tics = sorted(df["tic"].unique())
    stock_dim = len(tics)
    tech = [c for c in FEATURE_COLUMNS if c in df.columns]
    state_space = 1 + 2 * stock_dim + len(tech) * stock_dim

    env = StockTradingEnv(
        df=df, stock_dim=stock_dim, hmax=100, initial_amount=initial_cash,
        num_stock_shares=[0] * stock_dim,
        buy_cost_pct=[0.001] * stock_dim, sell_cost_pct=[0.001] * stock_dim,
        reward_scaling=1e-4, state_space=state_space, action_space=stock_dim,
        tech_indicator_list=tech, turbulence_threshold=None,
        risk_indicator_col="turbulence", make_plots=False, print_verbosity=1,
    )
    return env, tics, stock_dim


def generate_live_allocation(run_id: str, initial_cash: float = 100_000.0) -> Dict[str, Any]:
    """
    Run the trained RL model on live DOW30 data and return the target portfolio.

    Returns
    -------
    {
        "ok": bool,
        "as_of": "YYYY-MM-DD",            # latest bar date used
        "tickers": [...],
        "target": {ticker: target_qty},   # shares to hold
        "prices": {ticker: latest_close},
        "signals": {ticker: "BUY"/"HOLD"/"SELL"},  # derived from holdings vs neutral
        "algorithm": str,
        "message": str,
    }
    """
    db = SessionLocal()
    run = db.query(Run).filter(Run.id == run_id).first()
    db.close()
    if not run:
        return {"ok": False, "message": f"Run {run_id} not found"}

    algo = (run.algorithm or "").lower()
    if algo not in RL_ALGOS:
        return {"ok": False, "message": (
            f"Live trading currently supports RL portfolio models {sorted(RL_ALGOS)}; "
            f"run '{run_id}' is '{algo}'. Pick a PPO/SAC/TD3/A2C/DDPG run.")}

    model_path = run.model_path
    if not (model_path and Path(str(model_path) + ".zip").exists()):
        return {"ok": False, "message": f"Model file missing for run {run_id}"}

    if not finrl_wrapper.FINRL_AVAILABLE:
        return {"ok": False, "message": "FinRL not available in this environment"}

    # ── Live data window ──────────────────────────────────────────────────────
    end = datetime.utcnow().date()
    start = end - timedelta(days=_LOOKBACK_DAYS)
    logger.info("Live allocation: %s on %d tickers (%s → %s)",
                algo.upper(), len(LIVE_TICKERS), start, end)

    try:
        raw = _download_live(LIVE_TICKERS, str(start), str(end))
        vix = download_vix(str(start), str(end))
        featured = _build_featured(raw, vix)
        if featured.empty:
            return {"ok": False, "message": "Feature matrix empty — no live data"}

        env, tics, stock_dim = _make_env(featured, initial_cash)

        # ── Run policy through the live window ────────────────────────────────
        from stable_baselines3 import PPO, A2C, DDPG, TD3, SAC
        cls = {"ppo": PPO, "a2c": A2C, "ddpg": DDPG, "td3": TD3, "sac": SAC}[algo]
        model = cls.load(model_path)

        reset_out = env.reset()
        obs = reset_out[0] if isinstance(reset_out, tuple) else reset_out
        done = False
        while not done:
            action, _ = model.predict(obs, deterministic=True)
            step_out = env.step(action)
            if len(step_out) == 5:
                obs, _, term, trunc, _ = step_out
                done = term or trunc
            else:
                obs, _, done, _ = step_out

        # ── Read final holdings from env state ───────────────────────────────
        # State layout: [cash] + prices[stock_dim] + holdings[stock_dim] + tech...
        state = np.asarray(env.state, dtype=float)
        prices_vec   = state[1 : 1 + stock_dim]
        holdings_vec = state[1 + stock_dim : 1 + 2 * stock_dim]

        # Latest real close per ticker (from featured frame)
        latest_date = pd.to_datetime(featured["date"]).max()
        latest_rows = featured[pd.to_datetime(featured["date"]) == latest_date]
        latest_close = dict(zip(latest_rows["tic"], latest_rows["close"].astype(float)))

        # The env's holdings reflect a portfolio that grew from initial_cash over
        # the lookback window, so their market value ≠ initial_cash. Scale the
        # share counts to the paper budget → preserves the model's RELATIVE
        # allocation while fitting the account's capital.
        raw_val = 0.0
        for i, tic in enumerate(tics):
            q = float(holdings_vec[i]) if i < len(holdings_vec) else 0.0
            px = latest_close.get(tic, float(prices_vec[i]) if i < len(prices_vec) else 0.0)
            if q > 0 and px > 0:
                raw_val += q * px
        scale = (initial_cash / raw_val) if raw_val > 0 else 0.0

        target, prices, signals = {}, {}, {}
        for i, tic in enumerate(tics):
            qty = (float(holdings_vec[i]) if i < len(holdings_vec) else 0.0) * scale
            px  = latest_close.get(tic, float(prices_vec[i]) if i < len(prices_vec) else 0.0)
            target[tic] = round(max(qty, 0.0), 4)
            prices[tic] = round(px, 4)
            signals[tic] = "BUY" if qty > 0 else "HOLD"

        held = sum(1 for q in target.values() if q > 0)
        return {
            "ok": True,
            "as_of": str(latest_date.date()),
            "tickers": tics,
            "target": target,
            "prices": prices,
            "signals": signals,
            "algorithm": algo,
            "message": f"{algo.upper()} holds {held}/{stock_dim} stocks as of {latest_date.date()}",
        }
    except Exception as exc:
        logger.exception("generate_live_allocation failed")
        return {"ok": False, "message": f"Live allocation error: {exc}"}
