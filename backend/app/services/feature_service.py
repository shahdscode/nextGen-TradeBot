"""
Feature engineering for ML models (XGBoost, LSTM).
Produces a 25-feature matrix from raw OHLCV + indicators.

Step 1 upgrades (CLAUDE.md):
  1a. VIX feature (US only; EGX gets 0.0)
  1b. 52-week price range position
  1c. Cross-sectional 20-day momentum rank
  1d. Target: triple-barrier label (López de Prado) over TARGET_HORIZON days

Walk-forward fold generator ensures no data leakage.
The last TARGET_HORIZON rows of each training fold are dropped to prevent the
forward-looking triple-barrier target from peeking into the test window.
"""
import logging
import numpy as np
import pandas as pd
from typing import Any, Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)

# ── Target labeling configuration ─────────────────────────────────────────────
# The original 5-day sign target was near-random (OOF AUC ≈ 0.50) because short-
# horizon large-cap direction is dominated by noise around zero. We switch to a
# triple-barrier label (López de Prado, Advances in Financial ML, 2018):
#   For each day t, set an upper barrier at +k·σ and lower at −k·σ (σ = 20d vol).
#   Look forward up to TARGET_HORIZON days:
#     label = 1 if the upper (profit) barrier is touched first,
#     label = 0 if the lower barrier is touched first,
#     if neither is touched by the vertical (time) barrier → label by sign of
#     the return at expiry.
# This produces a cleaner, more learnable label and de-noises flat moves.
# Tuned by horizon/barrier sweep: H=20,k=2.0 gave the best OOF AUC (~0.53)
# vs ~0.50 for the old 5-day sign target and 0.515 for H=10,k=1.0.
TARGET_HORIZON = 20        # vertical (time) barrier, trading days
TARGET_BARRIER_K = 2.0     # barrier width in units of 20-day volatility

FEATURE_COLUMNS = [
    "macd", "rsi_30", "rsi_14", "boll_ub", "boll_lb", "bb_width",
    "close_30_sma", "close_60_sma", "cci_30", "dx_30", "atr",
    "volume_zscore", "price_mom_5", "price_mom_20", "frac_diff_close",
    "turbulence", "high_low_range", "gap", "obv_zscore", "ema_cross",
    "vol_price_corr",
    # ── Step 1 feature upgrades ───────────────────────────────────────────────
    "vix_level",             # 1a: VIX index daily close (US only; EGX → 0.0)
    "vix_zscore",            # 1a: VIX z-score rolling 20d
    "price_range_position",  # 1b: 52-week price position (0=at low, 1=at high)
    "rank_20d_mom",          # 1c: cross-sectional percentile rank of 20d momentum
]


# ── VIX helpers ────────────────────────────────────────────────────────────────

def download_vix(start_date: str, end_date: str) -> pd.DataFrame:
    """
    Download VIX index from Yahoo Finance for the given date range.

    Returns a DataFrame with columns: date (datetime64), vix_level, vix_zscore.
    Returns an empty DataFrame on any error so callers can safely fall back to 0.

    Call this ONCE before processing all US tickers and pass the result into
    build_features(vix_df=...).  EGX tickers (.CA) should receive vix_df=None.
    """
    try:
        import yfinance as yf
        raw = yf.download("^VIX", start=start_date, end=end_date,
                          progress=False, auto_adjust=True)
        if raw.empty:
            logger.warning("VIX download returned empty DataFrame for %s – %s", start_date, end_date)
            return pd.DataFrame(columns=["date", "vix_level", "vix_zscore"])

        # Handle MultiIndex columns produced by yfinance ≥ 0.2.x
        if isinstance(raw.columns, pd.MultiIndex):
            raw.columns = raw.columns.get_level_values(0)

        vix = raw[["Close"]].rename(columns={"Close": "vix_level"}).copy()
        vix["vix_zscore"] = (
            (vix["vix_level"] - vix["vix_level"].rolling(20).mean()) /
            vix["vix_level"].rolling(20).std().replace(0, 1e-9)
        )
        vix = vix.reset_index()
        # yfinance index column may be "Date" or "Datetime"
        date_col = [c for c in vix.columns if c.lower() in ("date", "datetime")][0]
        vix = vix.rename(columns={date_col: "date"})
        vix["date"] = pd.to_datetime(vix["date"]).dt.normalize()
        result = vix[["date", "vix_level", "vix_zscore"]].fillna(0.0)
        logger.info("VIX downloaded: %d rows (%s – %s)", len(result), start_date, end_date)
        return result
    except Exception as exc:
        logger.warning("VIX download failed (%s) — will use 0.0 for all US tickers", exc)
        return pd.DataFrame(columns=["date", "vix_level", "vix_zscore"])


# ── Mahalanobis turbulence ─────────────────────────────────────────────────────

def add_mahalanobis_turbulence(
    df: pd.DataFrame,
    lookback: int = 252,
    training_start: Optional[str] = None,
) -> pd.DataFrame:
    """
    Compute the Kritzman (2010) Mahalanobis turbulence index for every date.

    For each date t:
        turbulence_t = (r_t − μ)ᵀ · Σ⁻¹ · (r_t − μ)

    where r_t  = vector of all-ticker daily returns on day t,
          μ    = mean return vector over the trailing *lookback* window,
          Σ    = covariance matrix of returns over the same window.

    This is a cross-sectional measure: it captures whether all tickers are
    moving abnormally together (systemic stress), NOT just whether one ticker
    is volatile.  Correlation with per-ticker rolling-std proxy ≈ 0.32 —
    they are largely different signals.

    MUST be called on the full multi-ticker DataFrame BEFORE per-ticker
    build_features() calls or walk-forward splitting.

    WARMUP REQUIREMENT: the first `lookback` trading days produce turbulence=0
    because there is not enough history to estimate Σ.  For correct COVID-2020
    detection with lookback=252 (1 year), download data from 2019-01-01 even
    though the training window starts 2020-01-01.  Use training_start= to be
    warned if insufficient warmup is available.

    Parameters
    ----------
    df             : multi-ticker OHLCV DataFrame with 'date', 'tic', 'close'
    lookback       : rolling window for μ and Σ (default 252 = 1 year)
    training_start : "YYYY-MM-DD" — if supplied, warns when the gap between
                     the earliest data row and training_start < lookback days

    Returns
    -------
    df with an overwritten 'turbulence' column (Mahalanobis distance, each row
    shares the cross-sectional turbulence for its date).
    """
    df = df.copy()
    df["date"] = pd.to_datetime(df["date"])

    # Warmup check
    if training_start:
        ts = pd.to_datetime(training_start)
        earliest = df["date"].min()
        warmup_days = (ts - earliest).days
        if warmup_days < lookback:
            logger.warning(
                "add_mahalanobis_turbulence: only %d calendar days of warmup before "
                "training_start=%s (need ~%d for lookback=%d). "
                "Download from at least %s to get correct COVID-2020 detection.",
                warmup_days, training_start, int(lookback * 1.4),
                lookback,
                (ts - pd.Timedelta(days=int(lookback * 1.4))).date(),
            )

    # Build date × ticker return pivot
    pivot = (
        df.pivot_table(index="date", columns="tic", values="close", aggfunc="last")
        .sort_index()
        .pct_change()
    )

    # Compute rolling Mahalanobis turbulence
    turb_series: dict = {}
    dates = pivot.index.tolist()

    for i, date in enumerate(dates):
        if i < lookback:
            turb_series[date] = 0.0
            continue

        window = pivot.iloc[i - lookback:i].dropna(axis=1)   # drop tickers with NaN
        if window.shape[1] < 2:
            turb_series[date] = 0.0
            continue

        r_t_series = pivot.loc[date, window.columns]
        if r_t_series.isna().any():
            turb_series[date] = 0.0
            continue
        r_t = r_t_series.values

        mu  = window.mean().values
        cov = window.cov().values
        try:
            cov_inv = np.linalg.pinv(cov)
            diff = (r_t - mu)
            turb = float(diff @ cov_inv @ diff)
            # Clip to finite positive value — extreme values (>1e4) arise from
            # near-singular covariance matrices on holiday/zero-return days and
            # would cause downstream ML models to reject the data as "too large".
            turb_series[date] = float(np.clip(max(0.0, turb), 0.0, 1e4))
        except Exception:
            turb_series[date] = 0.0

    turb_df = pd.DataFrame.from_dict(turb_series, orient="index", columns=["turbulence"])
    turb_df.index.name = "date"
    turb_df = turb_df.reset_index()
    turb_df["date"] = pd.to_datetime(turb_df["date"])

    # Merge back — every ticker on a given date gets the same turbulence value
    df = df.merge(turb_df, on="date", how="left", suffixes=("_old", ""))
    if "turbulence_old" in df.columns:
        df = df.drop(columns=["turbulence_old"])
    df["turbulence"] = df["turbulence"].fillna(0.0)

    logger.info(
        "Mahalanobis turbulence computed: mean=%.2f, max=%.2f (lookback=%d days)",
        df["turbulence"].mean(), df["turbulence"].max(), lookback,
    )
    return df


# ── Cross-sectional feature ────────────────────────────────────────────────────

def add_cross_sectional_rank(df: pd.DataFrame) -> pd.DataFrame:
    """
    Add cross-sectional 20-day momentum rank (rank_20d_mom) for all tickers.

    For each calendar date, each ticker's 20-day price momentum is ranked as a
    percentile (0 = lowest momentum, 1 = highest) among all tickers with data
    on that date.  Because momentum only looks backward, there is no leakage.

    MUST be called on the full multi-ticker DataFrame BEFORE walk-forward
    splitting or per-ticker build_features() calls.
    """
    df = df.copy()
    df["date"] = pd.to_datetime(df["date"])
    df = df.sort_values(["tic", "date"]).reset_index(drop=True)

    # Per-ticker 20-day momentum (pure backward-looking)
    df["_mom_20"] = df.groupby("tic")["close"].pct_change(20)

    # Cross-sectional percentile rank per date (ties → average rank)
    df["rank_20d_mom"] = (
        df.groupby("date")["_mom_20"]
        .rank(pct=True)
        .fillna(0.5)
    )
    df = df.drop(columns=["_mom_20"])
    logger.info("Cross-sectional momentum rank added (%d tickers)", df["tic"].nunique())
    return df


# ── Core feature builder ───────────────────────────────────────────────────────

def build_features(
    df: pd.DataFrame,
    ticker: Optional[str] = None,
    vix_df: Optional[pd.DataFrame] = None,
) -> pd.DataFrame:
    """
    Build the 25-feature matrix for a single ticker.

    Parameters
    ----------
    df      : full multi-ticker (or single-ticker) OHLCV DataFrame.
              If add_cross_sectional_rank() was called beforehand, the
              'rank_20d_mom' column will already be present; otherwise a
              neutral fallback of 0.5 is used.
    ticker  : ticker symbol to extract (must appear in df['tic']).
              If None and df contains exactly one unique ticker, that ticker
              is used automatically.
    vix_df  : output of download_vix() — supply for US tickers.
              Pass None for EGX tickers (.CA) to get vix_level=0, vix_zscore=0.

    Returns
    -------
    DataFrame with FEATURE_COLUMNS + 'target' column.
    Last TARGET_HORIZON rows are always dropped (forward window unobservable).
    All NaNs are filled with 0.
    """
    # Auto-detect ticker for single-ticker DataFrames
    if ticker is None:
        unique = df["tic"].unique() if "tic" in df.columns else []
        if len(unique) == 1:
            ticker = unique[0]
        elif len(unique) == 0:
            raise ValueError("build_features: df has no 'tic' column")
        else:
            raise ValueError(
                f"build_features: ticker is required when df has multiple tickers: {list(unique)[:5]}…"
            )

    g = df[df["tic"] == ticker].copy().sort_values("date").reset_index(drop=True)
    if g.empty:
        return g

    # Drop rows where close == 0 (exchange holidays filled with 0 by yfinance).
    # These rows cause division-by-zero in gap/ema_cross and distort Mahalanobis
    # turbulence.  Forward-fill within the caller's DataFrame is the canonical fix;
    # this filter is a secondary safety net for any that slip through.
    zero_rows = (g["close"].astype(float) == 0)
    if zero_rows.any():
        logger.debug(
            "%s: dropping %d zero-close rows (exchange holidays) before feature computation",
            ticker, zero_rows.sum(),
        )
        g = g[~zero_rows].reset_index(drop=True)
    if g.empty:
        return g

    close = g["close"].astype(float)
    high  = g["high"].astype(float)
    low   = g["low"].astype(float)
    volume = g["volume"].astype(float).replace(0, np.nan).fillna(1)

    # ── Base indicators: pass-through if pre-computed, otherwise derive from OHLCV ──
    # Pre-computed by _add_basic_indicators() during download → fast path.
    # If the DataFrame comes from raw OHLCV (e.g. unit tests), compute here so
    # nothing silently becomes 0 and trains on zeros.

    if "macd" not in g.columns:
        _ema12 = close.ewm(span=12, adjust=False).mean()
        _ema26 = close.ewm(span=26, adjust=False).mean()
        g["macd"] = _ema12 - _ema26

    if "rsi_30" not in g.columns:
        _delta = close.diff()
        _gain  = _delta.clip(lower=0).rolling(30).mean()
        _loss  = (-_delta.clip(upper=0)).rolling(30).mean().replace(0, 1e-9)
        g["rsi_30"] = 100 - (100 / (1 + _gain / _loss))

    if "boll_ub" not in g.columns or "boll_lb" not in g.columns:
        _rm  = close.rolling(20).mean()
        _rs  = close.rolling(20).std()
        g["boll_ub"] = _rm + 2 * _rs
        g["boll_lb"] = _rm - 2 * _rs

    if "close_30_sma" not in g.columns:
        g["close_30_sma"] = close.rolling(30).mean()

    if "close_60_sma" not in g.columns:
        g["close_60_sma"] = close.rolling(60).mean()

    if "cci_30" not in g.columns:
        _tp     = (high + low + close) / 3
        _tp_sma = _tp.rolling(30).mean()
        _mad    = (_tp - _tp_sma).abs().rolling(30).mean().replace(0, 1e-9)
        g["cci_30"] = (_tp - _tp_sma) / (0.015 * _mad)

    if "dx_30" not in g.columns:
        _up  = high.diff()
        _dn  = -low.diff()
        _pdm = _up.where((_up > _dn) & (_up > 0), 0.0)
        _mdm = _dn.where((_dn > _up) & (_dn > 0), 0.0)
        _tr  = pd.concat([high - low,
                          (high - close.shift()).abs(),
                          (low  - close.shift()).abs()], axis=1).max(axis=1)
        _atr30 = _tr.rolling(30).mean().replace(0, 1e-9)
        _pdi   = 100 * (_pdm.rolling(30).sum() / _atr30)
        _mdi   = 100 * (_mdm.rolling(30).sum() / _atr30)
        g["dx_30"] = ((_pdi - _mdi).abs() / (_pdi + _mdi).replace(0, 1e-9)) * 100

    if "turbulence" not in g.columns:
        # Per-ticker volatility proxy — will be overwritten by add_mahalanobis_turbulence()
        # when the full multi-ticker DataFrame is processed before fold splitting.
        g["turbulence"] = close.pct_change().rolling(20).std().fillna(0) * 1000
        logger.debug(
            "turbulence for %s: using per-ticker volatility proxy. "
            "Call add_mahalanobis_turbulence(full_df) before build_features() "
            "for the academically correct cross-sectional Mahalanobis measure.", ticker
        )

    # ── Additional features ─────────────────────────────────────────────────

    # RSI-14
    delta = close.diff()
    gain  = delta.clip(lower=0).rolling(14).mean()
    loss  = (-delta.clip(upper=0)).rolling(14).mean().replace(0, 1e-9)
    g["rsi_14"] = 100 - (100 / (1 + gain / loss))

    # Bollinger Band width
    g["bb_width"] = (g["boll_ub"] - g["boll_lb"]) / close.replace(0, 1e-9)

    # ATR (14-period)
    tr = pd.concat([
        high - low,
        (high - close.shift()).abs(),
        (low  - close.shift()).abs(),
    ], axis=1).max(axis=1)
    g["atr"] = tr.rolling(14).mean()

    # Volume z-score (20-period)
    vol_mean = volume.rolling(20).mean()
    vol_std  = volume.rolling(20).std().replace(0, 1e-9)
    g["volume_zscore"] = (volume - vol_mean) / vol_std

    # Price momentum
    g["price_mom_5"]  = close.pct_change(5)
    g["price_mom_20"] = close.pct_change(20)

    # Fractional differentiation (d=0.4 approximation)
    g["frac_diff_close"] = _frac_diff(close, d=0.4)

    # High-low range
    g["high_low_range"] = (high - low) / close.replace(0, 1e-9)

    # Gap (open vs previous close)
    g["gap"] = (g["open"].astype(float) - close.shift()) / close.shift().replace(0, 1e-9)

    # OBV z-score
    direction = np.sign(close.diff().fillna(0))
    obv       = (direction * volume).cumsum()
    obv_mean  = obv.rolling(20).mean()
    obv_std   = obv.rolling(20).std().replace(0, 1e-9)
    g["obv_zscore"] = (obv - obv_mean) / obv_std

    # EMA crossover normalised
    ema12 = close.ewm(span=12, adjust=False).mean()
    ema26 = close.ewm(span=26, adjust=False).mean()
    g["ema_cross"] = (ema12 - ema26) / ema26.replace(0, 1e-9)

    # Volume-price correlation (10-period)
    g["vol_price_corr"] = close.rolling(10).corr(volume).fillna(0)

    # ── 1a. VIX feature (US tickers only) ───────────────────────────────────
    is_egx = ticker.upper().endswith(".CA")
    if not is_egx and vix_df is not None and not vix_df.empty:
        g_dates = pd.to_datetime(g["date"]).dt.normalize()
        vix_copy = vix_df.copy()
        vix_copy["date"] = pd.to_datetime(vix_copy["date"]).dt.normalize()
        # Left-merge so every row in g gets VIX (trading-day aligned)
        merged = g.assign(_date_norm=g_dates).merge(
            vix_copy[["date", "vix_level", "vix_zscore"]],
            left_on="_date_norm", right_on="date",
            how="left", suffixes=("", "_vix"),
        )
        # Forward-fill holiday/weekend gaps, then zero-fill any remaining NaN
        g["vix_level"]  = merged["vix_level"].ffill().fillna(0.0).values
        g["vix_zscore"] = merged["vix_zscore"].ffill().fillna(0.0).values
    else:
        g["vix_level"]  = 0.0
        g["vix_zscore"] = 0.0

    # ── 1b. 52-week price range position ────────────────────────────────────
    high_252 = close.rolling(252).max()
    low_252  = close.rolling(252).min()
    g["price_range_position"] = (close - low_252) / (high_252 - low_252 + 1e-9)

    # ── 1c. Cross-sectional momentum rank ───────────────────────────────────
    # Pre-computed by add_cross_sectional_rank() on the full multi-ticker df.
    # If not present (single-ticker call), fall back to neutral 0.5.
    if "rank_20d_mom" not in g.columns:
        g["rank_20d_mom"] = 0.5

    # ── 1d. Target: triple-barrier label over TARGET_HORIZON days ────────────
    # Volatility-scaled barriers de-noise the flat moves that made the old
    # 5-day sign target near-random. See TARGET_HORIZON / TARGET_BARRIER_K.
    g["target"] = _triple_barrier_label(
        close, horizon=TARGET_HORIZON, k=TARGET_BARRIER_K
    )

    # Drop last TARGET_HORIZON rows — forward window not yet observable
    g = g.iloc[:-TARGET_HORIZON]

    # Replace inf/-inf with 0 (can arise from division by near-zero prices)
    # and then fill remaining NaN.  This must happen before returning so no
    # model ever receives inf or NaN in its feature matrix.
    g = g.replace([np.inf, -np.inf], np.nan)
    return g.fillna(0)


def _triple_barrier_label(
    close: pd.Series,
    horizon: int = TARGET_HORIZON,
    k: float = TARGET_BARRIER_K,
    vol_window: int = 20,
) -> pd.Series:
    """
    Triple-barrier labeling (López de Prado 2018).

    For each row t:
      σ_t      = rolling std of daily returns (vol_window)
      upper    = close_t · (1 + k·σ_t)   (profit-taking barrier)
      lower    = close_t · (1 − k·σ_t)   (stop-loss barrier)
      Scan close_{t+1 … t+horizon}:
        → first touch of upper  ⇒ label 1
        → first touch of lower  ⇒ label 0
        → neither (time barrier) ⇒ label = 1 if close_{t+horizon} > close_t else 0

    Returns an int Series aligned to `close` (last `horizon` rows are 0-padded;
    build_features drops them).
    """
    n = len(close)
    c = close.values.astype(float)
    rets = pd.Series(c).pct_change()
    sigma = rets.rolling(vol_window).std().fillna(rets.std()).values
    labels = np.zeros(n, dtype=int)

    for t in range(n - horizon):
        ct = c[t]
        if ct <= 0:
            continue
        s = sigma[t] if sigma[t] > 1e-6 else 0.01
        upper = ct * (1.0 + k * s)
        lower = ct * (1.0 - k * s)
        window = c[t + 1 : t + 1 + horizon]
        hit = 0
        for px in window:
            if px >= upper:
                hit = 1
                break
            if px <= lower:
                hit = 0
                break
        else:
            # No barrier hit → sign at vertical (time) barrier
            hit = 1 if window[-1] > ct else 0
        labels[t] = hit

    return pd.Series(labels, index=close.index)


def _frac_diff(series: pd.Series, d: float = 0.4, thres: float = 1e-5) -> pd.Series:
    """Fixed-width fractional differentiation (simplified)."""
    w = [1.0]
    for k in range(1, 20):
        w_k = -w[-1] * (d - k + 1) / k
        if abs(w_k) < thres:
            break
        w.append(w_k)
    w = np.array(w)
    result = np.full(len(series), np.nan)
    for i in range(len(w), len(series) + 1):
        window = series.iloc[i - len(w):i].values[::-1]
        result[i - 1] = np.dot(w, window)
    return pd.Series(result, index=series.index)


# ── Walk-forward fold generator ────────────────────────────────────────────────

def generate_walk_forward_folds(
    df: pd.DataFrame,
    train_months: int = 12,
    test_months: int = 1,
) -> List[Tuple[pd.DataFrame, pd.DataFrame]]:
    """
    Generate walk-forward train/test folds.

    Each fold trains on ``train_months`` months and tests on the next
    ``test_months`` month(s).  Test data is always strictly after training data.

    LEAKAGE GUARD: the last TARGET_HORIZON trading-days of EACH training fold
    are removed. This prevents the forward-looking triple-barrier target from
    incorporating any prices that fall inside the test window.
    """
    df = df.copy()
    df["date"] = pd.to_datetime(df["date"])
    df = df.sort_values("date")

    min_date = df["date"].min()
    max_date = df["date"].max()

    folds: List[Tuple[pd.DataFrame, pd.DataFrame]] = []
    cursor = min_date + pd.DateOffset(months=train_months)

    while cursor + pd.DateOffset(months=test_months) <= max_date + pd.DateOffset(days=1):
        train_end = cursor
        test_end  = cursor + pd.DateOffset(months=test_months)

        train_df = df[df["date"] < train_end].copy()
        test_df  = df[(df["date"] >= train_end) & (df["date"] < test_end)].copy()

        # CRITICAL: drop last TARGET_HORIZON unique trading-dates from training
        # fold. Their triple-barrier targets look forward into the test window
        # → label leakage. Horizon-aware embargo (was hardcoded 5).
        if len(train_df) > 0:
            embargo_dates = train_df["date"].sort_values().unique()[-TARGET_HORIZON:]
            train_df = train_df[~train_df["date"].isin(embargo_dates)]

        if len(train_df) >= 60 and len(test_df) >= 5:
            folds.append((train_df, test_df))

        cursor += pd.DateOffset(months=test_months)

    logger.info("Generated %d walk-forward folds (train=%dm, test=%dm, leakage guard=%dd)",
                len(folds), train_months, test_months, TARGET_HORIZON)
    return folds


# Convenience alias used in team scripts
walk_forward_folds = generate_walk_forward_folds


def save_fold_definitions(
    folds: List[Tuple[pd.DataFrame, pd.DataFrame]],
    output_path: str,
    train_months: int = 12,
    test_months: int = 1,
) -> str:
    """
    Serialise fold date boundaries to JSON so every model (XGBoost, LSTM, RL)
    trains on IDENTICAL time windows.

    Parameters
    ----------
    folds       : output of generate_walk_forward_folds()
    output_path : where to write, e.g. "data/models/fold_definitions.json"
    train_months / test_months : metadata stored for documentation

    Returns path written.
    """
    import json, os
    from datetime import datetime as _dt

    fold_list = []
    for i, (tr, te) in enumerate(folds):
        tr_dates = pd.to_datetime(tr["date"])
        te_dates = pd.to_datetime(te["date"])
        fold_list.append({
            "fold_id":     i,
            "train_start": str(tr_dates.min().date()),
            "train_end":   str(tr_dates.max().date()),
            "test_start":  str(te_dates.min().date()),
            "test_end":    str(te_dates.max().date()),
            "n_train":     len(tr),
            "n_test":      len(te),
        })

    payload = {
        "generated_at": _dt.utcnow().isoformat(),
        "train_months": train_months,
        "test_months":  test_months,
        "n_folds":      len(folds),
        "folds":        fold_list,
    }

    os.makedirs(os.path.dirname(output_path) or ".", exist_ok=True)
    with open(output_path, "w") as f:
        json.dump(payload, f, indent=2)

    logger.info("Fold definitions saved → %s  (%d folds)", output_path, len(folds))
    return output_path


def load_fold_definitions(path: str) -> dict:
    """
    Load fold definitions from JSON.

    Returns the dict as-is with keys:
      generated_at, train_months, test_months, n_folds, folds (list of dicts)

    Raises FileNotFoundError if path does not exist.
    Raises ValueError if the JSON is missing required keys.
    """
    import json
    with open(path) as f:
        data = json.load(f)

    required = {"n_folds", "folds"}
    missing = required - set(data.keys())
    if missing:
        raise ValueError(f"fold_definitions.json missing keys: {missing}")

    logger.info("Fold definitions loaded from %s  (%d folds)", path, data["n_folds"])
    return data


def prepare_xy(df: pd.DataFrame) -> Tuple[np.ndarray, np.ndarray]:
    """Extract feature matrix X and target y from a featured DataFrame."""
    available = [c for c in FEATURE_COLUMNS if c in df.columns]
    X = df[available].values.astype(np.float32)
    y = df["target"].values.astype(int) if "target" in df.columns else np.zeros(len(X), dtype=int)
    return X, y


# ── Leakage guard ─────────────────────────────────────────────────────────────

def verify_no_leakage(train_df: pd.DataFrame, test_df: pd.DataFrame) -> Dict[str, Any]:
    """
    Explicit data-leakage audit for supervised and RL training pipelines.

    Checks performed
    ----------------
    1.  Temporal boundary: max(train_date) < min(test_date)
    2.  Column-name scan: no _future / _next / _fwd / _lead suffixes
    3.  Target not in FEATURE_COLUMNS
    4.  Row count sanity
    5.  Causal feature registry / pipeline DAG
    6.  Normalisation scope warning (cannot be auto-detected — flagged for review)

    Known limitations (cannot be detected from DataFrames alone)
    -------------------------------------------------------------
    • A rolling mean computed on df (train+test concatenated) before split is
      backward-looking at every point — NOT a leakage issue.
    • Global StandardScaler.fit on all data IS a leakage source but is invisible
      in column values.  Our LSTM fix (scaler fitted on last-fold train) addresses
      this; XGBoost is unscaled (no issue).
    • FinRL RL agent: no scaling applied — not at risk.
    """
    violations: List[str] = []
    checks:     List[str] = []
    warnings:   List[str] = []

    # ── 1. Temporal boundary ─────────────────────────────────────────────────
    if "date" in train_df.columns and "date" in test_df.columns:
        max_train = str(pd.to_datetime(train_df["date"]).max().date())
        min_test  = str(pd.to_datetime(test_df["date"]).min().date())
        if max_train >= min_test:
            violations.append(
                f"Temporal overlap: max(train_date)={max_train} >= min(test_date)={min_test}"
            )
        else:
            checks.append(f"Temporal boundary OK: train ends {max_train} < test starts {min_test}")

    # ── 2. Future-price column names ─────────────────────────────────────────
    future_cols = [
        c for c in test_df.columns
        if any(c.endswith(s) for s in ("_future", "_next", "_fwd", "_lead"))
    ]
    if future_cols:
        violations.append(f"Future-price columns detected: {future_cols}")
    else:
        checks.append("No future-price column names detected")

    # ── 3. Target not in features ────────────────────────────────────────────
    if "target" in FEATURE_COLUMNS:
        violations.append("'target' is in FEATURE_COLUMNS — label leakage")
    else:
        checks.append("'target' not in FEATURE_COLUMNS (correct)")

    # ── 4. Row counts ────────────────────────────────────────────────────────
    if len(train_df) == 0:
        violations.append("train_df is empty")
    if len(test_df) == 0:
        violations.append("test_df is empty")
    if len(train_df) > 0 and len(test_df) > 0:
        checks.append(f"Row counts: train={len(train_df)}, test={len(test_df)}")

    # ── 5. Causal feature registry / pipeline DAG ────────────────────────────
    from app.services.causal_features import (
        CAUSAL_FEATURE_REGISTRY,
        pipeline_dag_check,
    )

    feat_in_train = [c for c in FEATURE_COLUMNS if c in train_df.columns]
    dag_msgs = pipeline_dag_check(list(train_df.columns))
    if dag_msgs:
        violations.extend(dag_msgs)
    else:
        checks.append(
            f"All {len(feat_in_train)} feature columns registered in causal registry "
            f"({len(CAUSAL_FEATURE_REGISTRY)} definitions)"
        )

    if "date" in train_df.columns:
        checks.append(
            "Feature availability: pipeline assumes each row's features depend only on "
            "information at or before that row's date (enforced by backward-only construction)"
        )

    # ── 6. Normalisation scope warning ───────────────────────────────────────
    warnings.append(
        "Normalisation scope (StandardScaler etc.) cannot be verified from DataFrames. "
        "Ensure scalers are fit on TRAIN SPLIT ONLY and then .transform() on test. "
        "LSTM: fixed (scaler fitted on last fold train). XGBoost: no scaler (safe). "
        "RL agent: no scaler applied (safe)."
    )

    passed = len(violations) == 0
    return {
        "passed":     passed,
        "checks":     checks,
        "warnings":   warnings,
        "violations": violations,
        "summary":    "✓ No critical leakage detected" if passed else f"✗ {len(violations)} violation(s) found",
    }
