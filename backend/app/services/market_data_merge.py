"""Overlay live Yahoo OHLCV closes onto dataset rows for RL/backtest."""
from __future__ import annotations

import logging

import pandas as pd

logger = logging.getLogger(__name__)


def overlay_yahoo_closes(
    df: pd.DataFrame,
    start: str,
    end: str,
    indicators: list | None = None,
) -> tuple[pd.DataFrame, dict]:
    """
    Replace close/open/high/low with Yahoo data for the date range.
    Keeps technical columns from the original frame where possible.
    """
    from app.services.price_data import download_yahoo_ohlcv, detect_dataset_quality

    tickers = sorted(df["tic"].unique().tolist())
    before = detect_dataset_quality(df, tickers)

    try:
        live = download_yahoo_ohlcv(tickers, start, end, indicators or [])
    except Exception as exc:
        logger.warning("Yahoo overlay failed: %s", exc)
        return df, {
            "overlay": "failed",
            "live_prices": False,
            "message": str(exc),
            "issues": before.get("issues", []),
        }

    live = live.copy()
    live["date"] = pd.to_datetime(live["date"]).dt.strftime("%Y-%m-%d")
    base = df.copy()
    base["date"] = pd.to_datetime(base["date"]).dt.strftime("%Y-%m-%d")

    ohlcv_cols = ["open", "high", "low", "close", "volume"]
    drop_cols = [c for c in ohlcv_cols if c in base.columns]
    merged = base.drop(columns=drop_cols, errors="ignore").merge(
        live[["date", "tic"] + ohlcv_cols],
        on=["date", "tic"],
        how="left",
    )
    for col in ohlcv_cols:
        if col in merged.columns:
            merged[col] = merged[col].fillna(0)

    after = detect_dataset_quality(merged, tickers)
    return merged.fillna(0), {
        "overlay": "yahoo",
        "live_prices": after.get("live_prices", False),
        "message": (
            "Backtest/training uses Yahoo OHLCV for this window."
            if after.get("live_prices")
            else after.get("message", "")
        ),
        "issues": after.get("issues", []),
    }
