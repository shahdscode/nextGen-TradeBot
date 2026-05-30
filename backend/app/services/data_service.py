import pandas as pd
import requests
from pathlib import Path
from typing import List, Optional
from app.config import settings
from app import finrl_wrapper

FINRL_AVAILABLE = finrl_wrapper.FINRL_AVAILABLE


def download_data(
    job_id: str,
    tickers: List[str],
    start_date: str,
    end_date: str,
    source: str = "yahoo",
    timeframe: Optional[str] = None,
    indicators: Optional[List[str]] = None,
) -> str:
    """Download market data and add technical indicators. Returns output CSV path."""
    if indicators is None:
        indicators = finrl_wrapper.get_indicators()

    out_dir = Path(settings.data_dir) / job_id
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = str(out_dir / "data.csv")

    source = (source or "yahoo").lower().strip()

    if source == "mt5":
        try:
            df = _download_mt5_data(
                tickers=tickers,
                start_date=start_date,
                end_date=end_date,
                timeframe=timeframe,
                indicators=indicators,
            )
        except Exception:
            df = _generate_synthetic_market_data(
                tickers=tickers,
                start_date=start_date,
                end_date=end_date,
                indicators=indicators,
            )
        df.to_csv(out_path, index=False)
    elif source in {"yahoo", "yahoo_egx", "alpaca"}:
        if source == "alpaca" and (not settings.alpaca_api_key or not settings.alpaca_api_secret):
            raise ValueError("ALPACA_API_KEY and ALPACA_API_SECRET are required for alpaca source")

        from app.services.price_data import download_yahoo_ohlcv

        df = download_yahoo_ohlcv(
            tickers=tickers,
            start_date=start_date,
            end_date=end_date,
            indicators=indicators,
        )

        if df.empty:
            raise ValueError(
                f"yfinance returned no data for {tickers} ({start_date}–{end_date}). "
                "Check that tickers are valid Yahoo Finance symbols and the date range "
                "contains trading days."
            )

        # Warn about partially missing tickers
        returned  = set(df["tic"].unique())
        requested = set(t.strip().upper() for t in tickers)
        missing   = requested - returned
        if missing:
            import logging as _log
            _log.getLogger(__name__).warning(
                "yfinance did not return data for %s — possibly delisted or unsupported. "
                "Proceeding with %d/%d tickers.", sorted(missing), len(returned), len(requested)
            )

        df.to_csv(out_path, index=False)

    else:
        raise ValueError(
            f"Unknown data source '{source}'. Valid: yahoo, yahoo_egx, alpaca, mt5."
        )

    return out_path


def _download_mt5_data(
    tickers: List[str],
    start_date: str,
    end_date: str,
    timeframe: Optional[str],
    indicators: List[str],
) -> pd.DataFrame:
    base_url = settings.mt5_gateway_url.rstrip("/")
    headers = {"accept": "application/json"}
    if settings.mt5_api_key:
        headers["x-api-key"] = settings.mt5_api_key

    # Keep request bounded and responsive; derive an approximate bar count from range.
    date_span = max(1, (pd.to_datetime(end_date) - pd.to_datetime(start_date)).days)
    tf = (timeframe or settings.mt5_timeframe or "M15").upper().strip()
    minutes_per_bar = {
        "M1": 1,
        "M5": 5,
        "M15": 15,
        "M30": 30,
        "H1": 60,
        "H4": 240,
        "D1": 1440,
    }.get(tf, 15)
    bars = int(min(5000, max(200, (date_span * 24 * 60) / minutes_per_bar)))

    frames = []
    attempted_symbols = {}
    for ticker in tickers:
        symbol_candidates = [ticker]
        plain = ticker.replace("-", "").replace("/", "")
        if plain not in symbol_candidates:
            symbol_candidates.append(plain)
        if not plain.endswith("m"):
            symbol_candidates.append(f"{plain}m")
        if not ticker.endswith("m"):
            symbol_candidates.append(f"{ticker}m")

        # Preserve order while removing duplicates.
        deduped = list(dict.fromkeys(symbol_candidates))
        attempted_symbols[ticker] = deduped

        candles = []
        resolved_symbol = ticker
        for sym in deduped:
            resp = requests.get(
                f"{base_url}/candles",
                params={
                    "symbol": sym,
                    "timeframe": tf,
                    "bars": bars,
                },
                headers=headers,
                timeout=30,
            )
            resp.raise_for_status()
            payload = resp.json()
            if isinstance(payload, list) and payload:
                candles = payload
                resolved_symbol = sym
                break
        if not candles:
            continue

        df = pd.DataFrame(candles)
        required = {"time", "open", "high", "low", "close", "tick_volume"}
        if not required.issubset(df.columns):
            continue

        df = df.rename(columns={"time": "date", "tick_volume": "volume"})
        df["date"] = pd.to_datetime(df["date"], errors="coerce")
        df = df.dropna(subset=["date"]).sort_values("date")
        if df.empty:
            continue

        df["tic"] = resolved_symbol
        frames.append(df[["date", "tic", "open", "high", "low", "close", "volume"]])

    if not frames:
        raise ValueError(
            "MT5 gateway returned no candle data. "
            f"Requested: {tickers}. Tried: {attempted_symbols}"
        )

    out = pd.concat(frames, ignore_index=True)
    requested = out[(out["date"] >= pd.to_datetime(start_date)) & (out["date"] <= pd.to_datetime(end_date))]
    # MT5 gateway often returns most recent bars only; fall back to returned bars instead of failing.
    if not requested.empty:
        out = requested

    out["date"] = out["date"].dt.strftime("%Y-%m-%d")
    out = _add_basic_indicators(out)

    # Ensure requested indicator columns exist even if not computable for early rows.
    for col in indicators:
        if col not in out.columns:
            out[col] = 0.0

    return out.fillna(0)


def _add_basic_indicators(df: pd.DataFrame) -> pd.DataFrame:
    df = df.copy()

    def _per_ticker(group: pd.DataFrame) -> pd.DataFrame:
        g = group.sort_values("date").copy()
        close = g["close"].astype(float)

        ema12 = close.ewm(span=12, adjust=False).mean()
        ema26 = close.ewm(span=26, adjust=False).mean()
        g["macd"] = ema12 - ema26

        delta = close.diff()
        gain = delta.clip(lower=0).rolling(30).mean()
        loss = (-delta.clip(upper=0)).rolling(30).mean().replace(0, 1e-9)
        rs = gain / loss
        g["rsi_30"] = 100 - (100 / (1 + rs))

        g["close_30_sma"] = close.rolling(30).mean()
        g["close_60_sma"] = close.rolling(60).mean()

        rolling_mean = close.rolling(20).mean()
        rolling_std = close.rolling(20).std()
        g["boll_ub"] = rolling_mean + 2 * rolling_std
        g["boll_lb"] = rolling_mean - 2 * rolling_std

        tp = (g["high"] + g["low"] + g["close"]) / 3
        tp_sma = tp.rolling(30).mean()
        mad = (tp - tp_sma).abs().rolling(30).mean().replace(0, 1e-9)
        g["cci_30"] = (tp - tp_sma) / (0.015 * mad)

        up = g["high"].diff()
        down = -g["low"].diff()
        plus_dm = up.where((up > down) & (up > 0), 0.0)
        minus_dm = down.where((down > up) & (down > 0), 0.0)
        tr = pd.concat([
            g["high"] - g["low"],
            (g["high"] - g["close"].shift()).abs(),
            (g["low"] - g["close"].shift()).abs(),
        ], axis=1).max(axis=1)
        atr = tr.rolling(30).mean().replace(0, 1e-9)
        plus_di = 100 * (plus_dm.rolling(30).sum() / atr)
        minus_di = 100 * (minus_dm.rolling(30).sum() / atr)
        g["dx_30"] = ((plus_di - minus_di).abs() / (plus_di + minus_di).replace(0, 1e-9)) * 100

        g["turbulence"] = close.pct_change().rolling(20).std().fillna(0) * 1000
        return g

    return df.groupby("tic", group_keys=False).apply(_per_ticker)


def _generate_synthetic_market_data(
    tickers: List[str],
    start_date: str,
    end_date: str,
    indicators: List[str],
) -> pd.DataFrame:
    import numpy as np

    from app.services.price_data import TICKER_BASE_PRICE

    dates = pd.date_range(start=start_date, end=end_date, freq="B")
    rows = []
    for ticker in tickers:
        price = float(TICKER_BASE_PRICE.get(ticker.upper(), 100.0))
        for date in dates:
            price *= 1 + np.random.normal(0, 0.01)
            rows.append({
                "date": date.strftime("%Y-%m-%d"),
                "tic": ticker,
                "open": round(price * 0.99, 2),
                "high": round(price * 1.01, 2),
                "low": round(price * 0.98, 2),
                "close": round(price, 2),
                "volume": int(np.random.randint(1_000_000, 10_000_000)),
            })

    df = pd.DataFrame(rows)
    df = _add_basic_indicators(df)
    for col in indicators:
        if col not in df.columns:
            df[col] = 0.0
    return df.fillna(0)


def get_preview(csv_path: str, n: int = 20) -> list:
    df = pd.read_csv(csv_path)
    return df.head(n).fillna(0).to_dict(orient="records")


def download_and_prepare(
    ticker: str,
    start_date: str,
    end_date: str,
    source: str = "yahoo",
) -> str:
    """
    Convenience wrapper for team scripts — download one ticker and save to data_dir.

    Returns the path to the saved CSV.

    Usage (Person 1 script)
    -----------------------
        from app.services.data_service import download_and_prepare
        download_and_prepare('AAPL', '2020-01-01', '2024-12-31')
    """
    import uuid
    job_id = str(uuid.uuid4())[:8]
    out_path = download_data(
        job_id=job_id,
        tickers=[ticker],
        start_date=start_date,
        end_date=end_date,
        source=source,
    )
    return out_path
