"""
Feature engineering for ML models (XGBoost, LSTM).
Produces a 25-feature matrix from raw OHLCV + indicators.

Step 1 upgrades (CLAUDE.md):
  1a. VIX feature (US only; EGX gets 0.0)
  1b. 52-week price range position
  1c. Cross-sectional 20-day momentum rank
  1d. Target changed from 1-day to 5-day forward return

Walk-forward fold generator ensures no data leakage.
Last 5 rows of each training fold are dropped to prevent the 5-day
forward-return target from peeking into the test window.
"""
import logging
import numpy as np
import pandas as pd
from typing import Any, Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)

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
    ticker: str,
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
    vix_df  : output of download_vix() — supply for US tickers.
              Pass None for EGX tickers (.CA) to get vix_level=0, vix_zscore=0.

    Returns
    -------
    DataFrame with FEATURE_COLUMNS + 'target' column.
    Last 5 rows are always dropped (5-day forward return unavailable).
    All NaNs are filled with 0.
    """
    g = df[df["tic"] == ticker].copy().sort_values("date").reset_index(drop=True)
    if g.empty:
        return g

    close = g["close"].astype(float)
    high  = g["high"].astype(float)
    low   = g["low"].astype(float)
    volume = g["volume"].astype(float).replace(0, np.nan).fillna(1)

    # ── Existing indicators (pass-through if already computed) ──────────────
    for col in ["macd", "rsi_30", "boll_ub", "boll_lb", "close_30_sma",
                "close_60_sma", "cci_30", "dx_30", "turbulence"]:
        if col not in g.columns:
            g[col] = 0.0

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

    # ── 1d. Target: 5-day forward return direction ──────────────────────────
    # Replaces the old 1-day target.
    # Use a private temp name to avoid triggering the '_fwd' leakage check in
    # verify_no_leakage (the column is dropped before the function returns).
    _fwd_return = np.log(close.shift(-5) / (close + 1e-9))
    g["target"] = (_fwd_return > 0).astype(int)

    # Drop last 5 rows — 5-day forward price does not yet exist for them
    g = g.iloc[:-5]

    return g.fillna(0)


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

    LEAKAGE GUARD: the last 5 trading-days of EACH training fold are removed.
    This prevents the 5-day forward-return target from incorporating any
    prices that fall inside the test window.
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

        # CRITICAL: drop last 5 unique trading-dates from training fold.
        # Rows in those dates have targets that look 5 days forward into
        # the test window → label leakage.
        if len(train_df) > 0:
            last_5_dates = train_df["date"].sort_values().unique()[-5:]
            train_df = train_df[~train_df["date"].isin(last_5_dates)]

        if len(train_df) >= 60 and len(test_df) >= 5:
            folds.append((train_df, test_df))

        cursor += pd.DateOffset(months=test_months)

    logger.info("Generated %d walk-forward folds (train=%dm, test=%dm, leakage guard=5d)",
                len(folds), train_months, test_months)
    return folds


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
