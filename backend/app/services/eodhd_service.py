"""
EODHD market-data adapter — licensed data for the Egyptian Exchange (EGX).

Alpaca has no EGX coverage, so the Egyptian side of the platform needs a licensed
provider. EODHD covers EGX from ~2000 with an EOD API. When EODHD_API_KEY is
unset the callers fall back to yfinance, so this is drop-in and optional.

Symbology: the app uses Yahoo's '.CA' suffix (COMI.CA); EODHD uses the exchange
code '.EGX' (COMI.EGX). We translate on the way out and keep the original '.CA'
ticker on the returned frame so downstream code (features, sizing) is unchanged.

Prices are split+dividend adjusted (via EODHD's adjusted_close) to match Yahoo's
auto_adjust, so retraining/backtests stay consistent.
"""
from __future__ import annotations

import logging
from typing import List, Optional

import requests

from app.config import settings

logger = logging.getLogger(__name__)

_BASE = "https://eodhd.com/api"
_TIMEOUT = (6, 20)   # (connect, read) seconds


def configured() -> bool:
    return bool(settings.eodhd_api_key)


def _to_eodhd_symbol(tic: str) -> str:
    """COMI.CA (Yahoo) -> COMI.EGX (EODHD)."""
    base = tic.rsplit(".", 1)[0] if "." in tic else tic
    return f"{base}.EGX"


def get_daily_bars(tickers: List[str], start: str, end: str):
    """
    Daily split/dividend-adjusted OHLCV for EGX tickers via EODHD.

    Returns a long DataFrame [date, tic, open, high, low, close, volume] with the
    ORIGINAL '.CA' ticker preserved. Raises if not configured or nothing returned
    (caller falls back to yfinance). start/end are 'YYYY-MM-DD'.
    """
    import pandas as pd
    if not configured():
        raise RuntimeError("EODHD not configured — cannot fetch EGX bars")

    frames = []
    for tic in tickers:
        sym = _to_eodhd_symbol(tic)
        try:
            r = requests.get(
                f"{_BASE}/eod/{sym}",
                params={"api_token": settings.eodhd_api_key, "from": start,
                        "to": end, "period": "d", "fmt": "json"},
                timeout=_TIMEOUT,
            )
            if r.status_code >= 400:
                logger.warning("EODHD %s -> HTTP %s", sym, r.status_code)
                continue
            rows = r.json()
            if not isinstance(rows, list) or not rows:
                continue
            df = pd.DataFrame(rows)
            # Apply the split/dividend adjustment factor to all OHLC so the whole
            # bar is adjusted like Yahoo's auto_adjust (EODHD only adjusts close).
            if "adjusted_close" in df.columns:
                factor = (df["adjusted_close"] / df["close"]).where(df["close"] > 0, 1.0)
                for c in ("open", "high", "low"):
                    if c in df.columns:
                        df[c] = df[c] * factor
                df["close"] = df["adjusted_close"]
            df["tic"] = tic
            df["date"] = pd.to_datetime(df["date"])
            for c in ("open", "high", "low", "close", "volume"):
                if c not in df.columns:
                    df[c] = 0.0
            frames.append(df[["date", "tic", "open", "high", "low", "close", "volume"]])
        except Exception as exc:
            logger.warning("EODHD bars failed for %s: %s", sym, exc)

    if not frames:
        raise RuntimeError("EODHD returned no EGX bars")
    out = pd.concat(frames, ignore_index=True)
    return out.sort_values(["tic", "date"]).reset_index(drop=True)


def get_latest_price(tic: str) -> Optional[float]:
    """Latest close for an EGX ticker via EODHD real-time endpoint. None on failure."""
    if not configured():
        return None
    try:
        r = requests.get(
            f"{_BASE}/real-time/{_to_eodhd_symbol(tic)}",
            params={"api_token": settings.eodhd_api_key, "fmt": "json"},
            timeout=(4, 8),
        )
        if r.status_code >= 400:
            return None
        px = r.json().get("close")
        return float(px) if px not in (None, "NA") else None
    except Exception:
        return None
