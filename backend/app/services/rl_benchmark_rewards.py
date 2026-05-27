"""
Daily benchmark return lookup for benchmark-relative RL rewards during training.
"""
from __future__ import annotations

from typing import Dict, List, Optional

import numpy as np
import pandas as pd


class BenchmarkReturnTracker:
    """
    Maps each trading date → benchmark daily returns for alpha-relative reward.

    series[date] = {
        "sp500": float,
        "momentum": float,
        "sma_cross": float,
        "best_baseline": float,
        "high_vol": bool,
    }
    """

    def __init__(self, by_date: Dict[str, Dict[str, float]], ordered_dates: List[str]):
        self.by_date = by_date
        self.ordered_dates = ordered_dates
        self._date_to_idx = {d: i for i, d in enumerate(ordered_dates)}

    def get(self, date_key: str) -> Dict[str, float]:
        return self.by_date.get(date_key, _neutral_day())

    def get_by_index(self, day_idx: int) -> Dict[str, float]:
        if 0 <= day_idx < len(self.ordered_dates):
            return self.get(self.ordered_dates[day_idx])
        return _neutral_day()


def _neutral_day() -> Dict[str, float]:
    return {
        "sp500": 0.0,
        "momentum": 0.0,
        "sma_cross": 0.0,
        "best_baseline": 0.0,
        "high_vol": False,
    }


def build_benchmark_tracker(
    train_df: pd.DataFrame,
    train_start: str,
    train_end: str,
) -> BenchmarkReturnTracker:
    """
    Build per-date benchmark returns aligned to the training dataframe.
    Uses Yahoo ^GSPC when available; falls back to equal-weight basket in train_df.
    """
    df = train_df.copy()
    df["date"] = pd.to_datetime(df["date"])
    dates = sorted(df["date"].unique())

    # Market proxy from training data
    mkt = df.groupby("date")["close"].mean().sort_index()
    mkt_ret = mkt.pct_change().fillna(0)
    mkt_vol = mkt_ret.rolling(20, min_periods=5).std().fillna(0.01)
    vol_med = float(mkt_vol.median()) or 0.01
    mom_20 = mkt.pct_change(20).fillna(0)
    sma20 = mkt.rolling(20, min_periods=5).mean()
    sma50 = mkt.rolling(50, min_periods=10).mean()
    sma_signal = (sma20 > sma50).astype(float).diff().fillna(0)

    # Optional live SPY/^GSPC overlay
    sp_ret_map: Dict[pd.Timestamp, float] = {}
    try:
        import yfinance as yf

        raw = yf.download(
            "^GSPC",
            start=train_start,
            end=train_end,
            progress=False,
            auto_adjust=True,
        )
        if raw is not None and not raw.empty:
            sp_close = raw["Close"].squeeze()
            sp_ret = sp_close.pct_change().fillna(0)
            for dt, r in sp_ret.items():
                sp_ret_map[pd.Timestamp(dt).normalize()] = float(r)
    except Exception:
        pass

    by_date: Dict[str, Dict[str, float]] = {}
    ordered: List[str] = []

    for i, dt in enumerate(dates):
        dkey = str(pd.Timestamp(dt).date())
        ordered.append(dkey)
        sp = sp_ret_map.get(pd.Timestamp(dt).normalize(), float(mkt_ret.get(dt, 0)))
        mom = float(mom_20.get(dt, 0)) / 20.0  # spread 20d momentum into daily scale
        sma = float(sma_signal.get(dt, 0)) * float(mkt_ret.get(dt, 0))
        best = max(sp, mom, sma, 0.0) if max(sp, mom, sma) > 0 else min(sp, mom, sma)
        by_date[dkey] = {
            "sp500": sp,
            "momentum": mom,
            "sma_cross": sma,
            "best_baseline": best,
            "high_vol": bool(float(mkt_vol.get(dt, 0)) > vol_med * 1.5),
        }

    return BenchmarkReturnTracker(by_date, ordered)


def _env_current_date(env) -> Optional[str]:
    """Resolve FinRL env calendar date for benchmark lookup."""
    try:
        day = int(getattr(env, "day", 0))
        data = getattr(env, "data", None) or getattr(env, "df", None)
        if data is not None and day < len(data):
            row = data.iloc[day]
            if "date" in row.index:
                return str(pd.Timestamp(row["date"]).date())
        dates = getattr(env, "date_memory", None)
        if dates is not None and day < len(dates):
            return str(pd.Timestamp(dates[day]).date())
    except Exception:
        pass
    return None
