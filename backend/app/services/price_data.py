"""
Live OHLCV download via yfinance. Keeps raw close prices for training/backtest display.
"""
from __future__ import annotations

import logging
from typing import List, Optional

import pandas as pd

logger = logging.getLogger(__name__)

# Realistic anchors for synthetic fallback only (not used when yfinance works)
TICKER_BASE_PRICE = {
    "AAPL": 190.0,
    "MSFT": 420.0,
    "GOOGL": 175.0,
    "AMZN": 185.0,
    "NVDA": 880.0,
    "META": 520.0,
    "TSLA": 240.0,
    "JPM": 200.0,
    "V": 280.0,
    "JNJ": 155.0,
}

# Average daily notional volume (USD) — used for Almgren-Chriss participation-rate calc.
# Source: approximate trailing 6-month ADV (2024/2025 estimates).
# Illiquid assets get higher market impact; this controls the sqrt(Q/V) term.
TICKER_ADV_NOTIONAL: dict = {
    # ── US large-caps ────────────────────────────────────────────────────────
    "AAPL":  350_000_000,
    "MSFT":  280_000_000,
    "GOOGL": 150_000_000,
    "AMZN":  160_000_000,
    "NVDA":  400_000_000,
    "META":  180_000_000,
    "TSLA":  220_000_000,
    "JPM":   130_000_000,
    "V":      90_000_000,
    "JNJ":    60_000_000,
    # ── EGX 30 constituents (EGP→USD at ~50 EGP/USD, ~2024 estimates) ───────
    "COMI.CA": 8_000_000,   # CIB — most liquid EGX stock
    "HRHO.CA": 3_000_000,   # EFG Hermes
    "ETEL.CA": 2_500_000,   # Telecom Egypt
    "TMGH.CA": 2_000_000,   # TMG Holding
    "EFIH.CA": 1_500_000,   # EFG Hermes Intl Holdings
    "AMOC.CA": 1_200_000,   # Alexandria Mineral Oils
    "ABUK.CA": 1_000_000,   # Abu Kir Fertilizers
    "PHDC.CA": 1_000_000,   # Palm Hills Developments
    "SWDY.CA": 2_000_000,   # El Sewedy Electric
    "ORWE.CA":   800_000,   # Oriental Weavers
    "CLHO.CA":   700_000,   # Cleopatra Hospital Group
    "ESRS.CA": 1_500_000,   # Ezz Steel
    "MNHD.CA":   600_000,   # Medinet Nasr Housing
    "FWRY.CA": 1_800_000,   # Fawry (fintech)
    "EGTS.CA":   500_000,   # Egyptian Gas
    "EAST.CA":   900_000,   # Eastern Company (tobacco)
    "OCDI.CA":   600_000,   # Orascom Development Egypt
    "ACGC.CA":   400_000,   # Arab Cotton Ginning
    "ISPH.CA": 1_200_000,   # Integrated Diagnostics Holdings
    "GBCO.CA":   700_000,   # GB Auto
    "GTHE.CA":   500_000,   # Ghabbour Auto
    "MFPC.CA":   800_000,   # Misr Fertilizers Production Company
    "ABIS.CA":   400_000,   # Alexandria Spinning
    "BICO.CA":   300_000,   # Bisco Egypt
    "BTFH.CA":   300_000,   # Biotechnology
}
_DEFAULT_ADV: float     = 100_000_000   # $100 M fallback for unknown US tickers
_DEFAULT_ADV_EGX: float = 500_000       # ~$500 K fallback for unknown EGX tickers


def get_adv(ticker: str) -> float:
    """Return ADV notional for ticker, with market-aware fallback."""
    if ticker in TICKER_ADV_NOTIONAL:
        return TICKER_ADV_NOTIONAL[ticker]
    return _DEFAULT_ADV_EGX if ticker.endswith(".CA") else _DEFAULT_ADV


def _scalar(series_or_val):
    if hasattr(series_or_val, "iloc"):
        v = series_or_val.iloc[-1]
        return float(v.item() if hasattr(v, "item") else v)
    return float(series_or_val)


def download_yahoo_ohlcv(
    tickers: List[str],
    start_date: str,
    end_date: str,
    indicators: Optional[List[str]] = None,
) -> pd.DataFrame:
    """Download unscaled OHLCV; technical indicators computed on raw closes."""
    from app.services.data_service import _add_basic_indicators

    import yfinance as yf

    tickers = [t.strip().upper() for t in tickers if t.strip()]
    if not tickers:
        raise ValueError("no tickers provided")

    raw = yf.download(
        tickers,
        start=start_date,
        end=end_date,
        progress=False,
        auto_adjust=True,
        group_by="column",
    )
    if raw is None or raw.empty:
        raise ValueError("yfinance returned no rows")

    frames = []
    if len(tickers) == 1:
        ticker = tickers[0]
        sub = raw.copy()
        sub.columns = [c if isinstance(c, str) else c[0] for c in sub.columns]
        for dt, row in sub.iterrows():
            frames.append(_row_from_yf(dt, ticker, row))
    else:
        for ticker in tickers:
            try:
                sub = raw.xs(ticker, axis=1, level=1)
            except (KeyError, TypeError):
                try:
                    sub = raw[ticker]
                except KeyError:
                    continue
            for dt, row in sub.iterrows():
                frames.append(_row_from_yf(dt, ticker, row))

    if not frames:
        raise ValueError("could not parse yfinance response")

    df = pd.DataFrame(frames)
    df["date"] = pd.to_datetime(df["date"]).dt.strftime("%Y-%m-%d")
    df = df.sort_values(["date", "tic"]).reset_index(drop=True)
    df = _add_basic_indicators(df)

    if indicators:
        for col in indicators:
            if col not in df.columns:
                df[col] = 0.0

    return df.fillna(0)


def _row_from_yf(dt, ticker: str, row) -> dict:
    def g(name, default=0.0):
        try:
            v = row.get(name, default) if hasattr(row, "get") else row[name]
            return _scalar(v) if v is not None and pd.notna(v) else default
        except (KeyError, TypeError, IndexError):
            return default

    close = g("Close")
    return {
        "date": dt,
        "tic": ticker,
        "open": round(g("Open", close), 4),
        "high": round(g("High", close), 4),
        "low": round(g("Low", close), 4),
        "close": round(close, 4),
        "volume": int(g("Volume", 0)),
    }


def fetch_close_on_date(ticker: str, date: str, cache: dict) -> Optional[float]:
    """Return Yahoo close for ticker on date (YYYY-MM-DD), using cache dict."""
    ticker = ticker.strip().upper()
    key = (ticker, date)
    if key in cache:
        return cache[key]

    import yfinance as yf

    start = pd.Timestamp(date) - pd.Timedelta(days=7)
    end = pd.Timestamp(date) + pd.Timedelta(days=7)
    try:
        hist = yf.download(
            ticker,
            start=start.strftime("%Y-%m-%d"),
            end=end.strftime("%Y-%m-%d"),
            progress=False,
            auto_adjust=True,
        )
        if hist is None or hist.empty:
            cache[key] = None
            return None
        hist = hist.reset_index()
        hist["date"] = pd.to_datetime(hist["Date"]).dt.strftime("%Y-%m-%d")
        row = hist.loc[hist["date"] == date]
        if row.empty:
            row = hist.iloc[[-1]]
        close = _scalar(row["Close"])
        cache[key] = round(close, 2)
        return cache[key]
    except Exception as exc:
        logger.debug("yahoo close %s %s: %s", ticker, date, exc)
        cache[key] = None
        return None


def detect_dataset_quality(df: pd.DataFrame, tickers: List[str]) -> dict:
    """Flag synthetic/unrealistic closes vs Yahoo spot check."""
    import yfinance as yf

    issues = []
    sample = df[df["tic"].isin(tickers)].groupby("tic").tail(1)
    for _, row in sample.iterrows():
        tic = row["tic"]
        try:
            live = yf.Ticker(tic).history(period="5d", auto_adjust=True)
            if live.empty:
                continue
            live_close = _scalar(live["Close"])
            csv_close = float(row["close"])
            if live_close > 0 and abs(csv_close - live_close) / live_close > 0.35:
                issues.append(
                    f"{tic}: dataset close ${csv_close:.2f} vs recent Yahoo ${live_close:.2f}"
                )
        except Exception:
            pass

    return {
        "live_prices": len(issues) == 0,
        "issues": issues,
        "message": (
            "Training data uses live Yahoo OHLCV."
            if not issues
            else "Dataset prices may be synthetic or stale — re-download data from the Data page."
        ),
    }
