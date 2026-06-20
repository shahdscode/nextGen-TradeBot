"""
Market overview endpoints: current prices, regime, news sentiment.
Uses live Yahoo Finance by default. Demo/dataset fallbacks only if
MARKET_ALLOW_DEMO_FALLBACK=true in .env.
"""
from __future__ import annotations

import hashlib
import logging
import random
from datetime import datetime, timedelta
from pathlib import Path
from typing import List, Optional, Tuple, Any

from fastapi import APIRouter, HTTPException, Query

from app.config import settings

router = APIRouter(prefix="/market", tags=["market"])
logger = logging.getLogger(__name__)

# Rough reference prices for synthetic/demo data when live feeds fail
_REF_PRICES = {
    "AAPL": 190, "MSFT": 420, "GOOGL": 175, "AMZN": 185, "NVDA": 880,
    "META": 520, "TSLA": 240, "JPM": 200, "V": 280, "JNJ": 155,
}


@router.get("/data-status")
def market_data_status():
    """Report whether live market feeds are reachable."""
    probe = _yf_quote("AAPL")
    live_ok = probe is not None
    return {
        "live_market_ok": live_ok,
        "demo_fallback_enabled": settings.market_allow_demo_fallback,
        "newsapi_configured": bool(settings.newsapi_key),
        "message": (
            "Live Yahoo Finance data is available."
            if live_ok
            else (
                "Live data unavailable. Set MARKET_ALLOW_DEMO_FALLBACK=true only for dev demos."
                if not settings.market_allow_demo_fallback
                else "Live data unavailable; demo/dataset fallbacks are enabled."
            )
        ),
    }


@router.get("/overview")
def market_overview(market: str = Query("us"), tickers: Optional[str] = Query(None)):
    """Return current price + daily change for a list of tickers."""
    ticker_list = _get_default_tickers(market) if not tickers else tickers.split(",")
    ticker_list = [t.strip() for t in ticker_list[:20]]

    try:
        import yfinance as yf

        data = yf.download(ticker_list, period="5d", progress=False, auto_adjust=True)
        if data.empty:
            return _overview_fallback(ticker_list)

        result = []
        for ticker in ticker_list:
            try:
                if len(ticker_list) == 1:
                    closes = data["Close"]
                else:
                    closes = data["Close"][ticker]
                closes = closes.dropna()
                if len(closes) < 2:
                    continue
                current = float(closes.iloc[-1])
                prev = float(closes.iloc[-2])
                change_pct = round((current - prev) / prev * 100, 2) if prev else 0
                result.append({
                    "ticker": ticker,
                    "price": round(current, 2),
                    "change_pct": change_pct,
                    "direction": _direction(change_pct),
                })
            except Exception:
                continue

        if not result:
            return _overview_fallback(ticker_list)

        for row in result:
            row["source"] = "live"
        return sorted(result, key=lambda r: abs(r["change_pct"]), reverse=True)
    except Exception as exc:
        logger.warning("market overview yfinance failed: %s", exc)
        return _overview_fallback(ticker_list)


@router.get("/quote/{ticker}")
def get_quote(ticker: str, market: str = Query("us")):
    ticker = ticker.strip().upper()
    live = _yf_quote(ticker)
    if live:
        live["source"] = "live"
        return _json_safe(live)

    fallback = _quote_fallback(ticker)
    if fallback:
        return _json_safe(fallback)

    raise HTTPException(
        status_code=503,
        detail=f"Live quote unavailable for {ticker}. Check Yahoo Finance connectivity.",
    )


@router.get("/candles/{ticker}")
def get_candles(ticker: str, period: str = Query("3mo"), interval: str = Query("1d")):
    ticker = ticker.strip().upper()
    try:
        live = _yf_candles(ticker, period, interval)
        if live:
            return _json_safe(_tag_source(live, "live"))
    except Exception as exc:
        logger.warning("candles live path failed for %s: %s", ticker, exc)

    fallback = _candles_fallback(ticker, period, interval)
    if fallback:
        return _json_safe(fallback)

    raise HTTPException(
        status_code=503,
        detail=f"Live candle data unavailable for {ticker}. Check Yahoo Finance connectivity.",
    )


@router.get("/news/{ticker}")
def get_news_sentiment(ticker: str):
    from app.services.sentiment_service import fetch_and_score
    return fetch_and_score(ticker)


@router.get("/regime")
def get_regime(market: str = Query("us")):
    from app.services.regime_service import get_regime_info
    return get_regime_info(market)


def _json_safe(obj):
    """Recursively replace NaN/Inf floats with None so the response is valid
    JSON. yfinance `.info` (pe_ratio, marketCap, 52w_*) and gap rows in OHLC
    data can contain NaN, which crashes the default JSON encoder."""
    import math
    if isinstance(obj, float):
        return obj if math.isfinite(obj) else None
    if isinstance(obj, dict):
        return {k: _json_safe(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [_json_safe(v) for v in obj]
    return obj


def _direction(change_pct: float) -> str:
    if change_pct > 0:
        return "up"
    if change_pct < 0:
        return "down"
    return "flat"


def _tag_source(payload, source: str):
    if isinstance(payload, list):
        return [{**row, "source": source} for row in payload]
    return {**payload, "source": source}


def _overview_fallback(ticker_list: List[str]) -> List[dict]:
    if not settings.market_allow_demo_fallback:
        raise HTTPException(
            status_code=503,
            detail="Live market overview unavailable. Upgrade yfinance or check network.",
        )
    return _tag_source(_synthetic_overview(ticker_list), "synthetic")


def _quote_fallback(ticker: str) -> Optional[dict]:
    if not settings.market_allow_demo_fallback:
        return None
    csv_quote = _csv_quote(ticker)
    if csv_quote:
        csv_quote["source"] = "dataset"
        return csv_quote
    return _tag_source(_synthetic_quote(ticker), "synthetic")


def _candles_fallback(ticker: str, period: str, interval: str) -> Optional[List[dict]]:
    if not settings.market_allow_demo_fallback:
        return None
    csv_candles = _csv_candles(ticker, period)
    if csv_candles:
        return _tag_source(csv_candles, "dataset")
    return _tag_source(_synthetic_candles(ticker, period, interval), "synthetic")


def _flatten_yf_df(df):
    """yfinance >= 0.2.54 may return MultiIndex OHLC columns."""
    import pandas as pd

    if isinstance(df.columns, pd.MultiIndex):
        df = df.copy()
        df.columns = [str(col[0]) for col in df.columns]
    return df


def _scalar(val) -> float:
    if hasattr(val, "iloc"):
        return float(val.iloc[-1])
    return float(val)


def _seeded_rng(key: str) -> random.Random:
    digest = hashlib.md5(key.encode()).hexdigest()
    return random.Random(int(digest[:8], 16))


def _yf_quote(ticker: str) -> Optional[dict]:
    try:
        import yfinance as yf

        t = yf.Ticker(ticker)
        hist = _flatten_yf_df(t.history(period="5d"))
        if hist.empty:
            return None
        current = _scalar(hist["Close"])
        prev = _scalar(hist["Close"].iloc[-2]) if len(hist) > 1 else current
        change_pct = round((current - prev) / prev * 100, 2) if prev else 0
        info = t.info or {}
        return {
            "ticker": ticker,
            "price": round(current, 2),
            "change_pct": change_pct,
            "direction": _direction(change_pct),
            "company": info.get("longName", ticker),
            "sector": info.get("sector", ""),
            "market_cap": info.get("marketCap"),
            "pe_ratio": info.get("trailingPE"),
            "52w_high": info.get("fiftyTwoWeekHigh"),
            "52w_low": info.get("fiftyTwoWeekLow"),
        }
    except Exception as exc:
        logger.warning("yfinance quote failed for %s: %s", ticker, exc)
        return None


def _yf_candles(ticker: str, period: str, interval: str) -> Optional[List[dict]]:
    try:
        import yfinance as yf

        df = yf.download(ticker, period=period, interval=interval, progress=False, auto_adjust=True)
        if df.empty:
            return None
        return _df_to_candles(_flatten_yf_df(df))
    except Exception as exc:
        logger.warning("yfinance candles failed for %s: %s", ticker, exc)
        return None


def _df_to_candles(df) -> List[dict]:
    df = _flatten_yf_df(df).reset_index()
    date_col = "Date" if "Date" in df.columns else ("Datetime" if "Datetime" in df.columns else df.columns[0])
    result = []
    for _, row in df.iterrows():
        result.append({
            "date": str(row[date_col])[:10],
            "open": round(_scalar(row["Open"]), 2),
            "high": round(_scalar(row["High"]), 2),
            "low": round(_scalar(row["Low"]), 2),
            "close": round(_scalar(row["Close"]), 2),
            "volume": int(_scalar(row["Volume"])) if "Volume" in df.columns else 0,
        })
    return result


def _dataset_paths() -> List[Path]:
    roots = [
        Path(settings.data_dir),
        Path(settings.data_dir).resolve(),
        Path(__file__).resolve().parents[2] / "data" / "datasets",
        Path(__file__).resolve().parents[2].parent / "data" / "datasets",
    ]
    seen = set()
    paths = []
    for root in roots:
        if not root.exists():
            continue
        for csv_path in sorted(root.glob("*/data.csv"), key=lambda p: p.stat().st_mtime, reverse=True):
            key = str(csv_path.resolve())
            if key not in seen:
                seen.add(key)
                paths.append(csv_path)
    return paths


def _load_ticker_frame(ticker: str):
    try:
        import pandas as pd
    except ImportError:
        return None

    ticker = ticker.upper()
    for csv_path in _dataset_paths():
        try:
            df = pd.read_csv(csv_path, usecols=lambda c: c in {
                "date", "tic", "open", "high", "low", "close", "volume",
            })
            subset = df[df["tic"].astype(str).str.upper() == ticker]
            if not subset.empty:
                subset = subset.sort_values("date")
                return subset
        except Exception:
            continue
    return None


def _period_days(period: str) -> int:
    mapping = {
        "1d": 1, "5d": 5, "1mo": 30, "3mo": 90, "6mo": 180,
        "1y": 365, "2y": 730, "5y": 1825, "10y": 3650, "ytd": 180, "max": 1825,
    }
    return mapping.get(period, 90)


def _csv_candles(ticker: str, period: str) -> Optional[List[dict]]:
    frame = _load_ticker_frame(ticker)
    if frame is None or frame.empty:
        return None

    days = _period_days(period)
    if "date" in frame.columns:
        frame = frame.copy()
        frame["date"] = frame["date"].astype(str)
        cutoff = (datetime.utcnow() - timedelta(days=days)).strftime("%Y-%m-%d")
        frame = frame[frame["date"] >= cutoff]
    if frame.empty:
        frame = _load_ticker_frame(ticker)
        frame = frame.tail(min(days, len(frame)))

    result = []
    for _, row in frame.iterrows():
        result.append({
            "date": str(row["date"])[:10],
            "open": round(float(row["open"]), 2),
            "high": round(float(row["high"]), 2),
            "low": round(float(row["low"]), 2),
            "close": round(float(row["close"]), 2),
            "volume": int(row["volume"]) if "volume" in row and row["volume"] == row["volume"] else 0,
        })
    return result or None


def _csv_quote(ticker: str) -> Optional[dict]:
    candles = _csv_candles(ticker, "5d")
    if not candles or len(candles) < 1:
        return None
    current = candles[-1]["close"]
    prev = candles[-2]["close"] if len(candles) > 1 else current
    change_pct = round((current - prev) / prev * 100, 2) if prev else 0
    highs = [c["high"] for c in candles]
    lows = [c["low"] for c in candles]
    return {
        "ticker": ticker.upper(),
        "price": current,
        "change_pct": change_pct,
        "direction": _direction(change_pct),
        "company": ticker.upper(),
        "sector": "",
        "market_cap": None,
        "pe_ratio": None,
        "52w_high": max(highs),
        "52w_low": min(lows),
    }


def _synthetic_candles(ticker: str, period: str, interval: str) -> List[dict]:
    rng = _seeded_rng(f"{ticker}:{period}:{interval}")
    days = _period_days(period)
    if interval in ("1h", "60m", "30m", "15m", "5m"):
        bars = min(days * 8, 500)
    else:
        bars = days

    base = _REF_PRICES.get(ticker.upper(), 100 + (hash(ticker) % 400))
    price = base
    start = datetime.utcnow() - timedelta(days=bars)
    candles = []
    for i in range(bars):
        drift = rng.uniform(-0.02, 0.02)
        open_p = price
        close_p = max(1.0, open_p * (1 + drift))
        high_p = max(open_p, close_p) * (1 + rng.uniform(0, 0.01))
        low_p = min(open_p, close_p) * (1 - rng.uniform(0, 0.01))
        candles.append({
            "date": (start + timedelta(days=i)).strftime("%Y-%m-%d"),
            "open": round(open_p, 2),
            "high": round(high_p, 2),
            "low": round(low_p, 2),
            "close": round(close_p, 2),
            "volume": rng.randint(1_000_000, 50_000_000),
        })
        price = close_p
    return candles


def _synthetic_quote(ticker: str) -> dict:
    candles = _synthetic_candles(ticker, "5d", "1d")
    current = candles[-1]["close"]
    prev = candles[-2]["close"]
    change_pct = round((current - prev) / prev * 100, 2)
    highs = [c["high"] for c in candles]
    lows = [c["low"] for c in candles]
    return {
        "ticker": ticker.upper(),
        "price": current,
        "change_pct": change_pct,
        "direction": _direction(change_pct),
        "company": ticker.upper(),
        "sector": "Demo",
        "market_cap": None,
        "pe_ratio": None,
        "52w_high": max(highs),
        "52w_low": min(lows),
    }


def _get_default_tickers(market: str) -> List[str]:
    if market == "egx":
        return ["COMI.CA", "HRHO.CA", "ETEL.CA", "TMGH.CA", "EFIH.CA",
                "PHDC.CA", "OCDI.CA", "ABUK.CA", "ORAS.CA", "EKHO.CA"]
    return ["AAPL", "MSFT", "GOOGL", "AMZN", "NVDA", "META", "TSLA", "JPM", "V", "JNJ"]


def _synthetic_overview(tickers: List[str]) -> List[dict]:
    result = []
    for t in tickers:
        q = _synthetic_quote(t)
        result.append({
            "ticker": q["ticker"],
            "price": q["price"],
            "change_pct": q["change_pct"],
            "direction": q["direction"],
        })
    return result
