"""
Feature engineering for ML models (XGBoost, LSTM).
Produces a 21-feature matrix from raw OHLCV + existing indicators.
Walk-forward fold generator ensures no data leakage.
"""
import numpy as np
import pandas as pd
from typing import Any, Dict, List, Tuple


FEATURE_COLUMNS = [
    "macd", "rsi_30", "rsi_14", "boll_ub", "boll_lb", "bb_width",
    "close_30_sma", "close_60_sma", "cci_30", "dx_30", "atr",
    "volume_zscore", "price_mom_5", "price_mom_20", "frac_diff_close",
    "turbulence", "high_low_range", "gap", "obv_zscore", "ema_cross",
    "vol_price_corr",
]


def build_features(df: pd.DataFrame, ticker: str) -> pd.DataFrame:
    """Build the 21-feature matrix for a single ticker. Returns df with features + target."""
    g = df[df["tic"] == ticker].copy().sort_values("date").reset_index(drop=True)
    if g.empty:
        return g

    close = g["close"].astype(float)
    high = g["high"].astype(float)
    low = g["low"].astype(float)
    volume = g["volume"].astype(float).replace(0, np.nan).fillna(1)

    # ── Existing indicators (pass-through if already computed) ──────────────
    for col in ["macd", "rsi_30", "boll_ub", "boll_lb", "close_30_sma", "close_60_sma",
                "cci_30", "dx_30", "turbulence"]:
        if col not in g.columns:
            g[col] = 0.0

    # ── Additional features ─────────────────────────────────────────────────
    # RSI-14
    delta = close.diff()
    gain = delta.clip(lower=0).rolling(14).mean()
    loss = (-delta.clip(upper=0)).rolling(14).mean().replace(0, 1e-9)
    g["rsi_14"] = 100 - (100 / (1 + gain / loss))

    # Bollinger Band width
    g["bb_width"] = (g["boll_ub"] - g["boll_lb"]) / close.replace(0, 1e-9)

    # ATR (14-period)
    tr = pd.concat([
        high - low,
        (high - close.shift()).abs(),
        (low - close.shift()).abs(),
    ], axis=1).max(axis=1)
    g["atr"] = tr.rolling(14).mean()

    # Volume z-score (20-period)
    vol_mean = volume.rolling(20).mean()
    vol_std = volume.rolling(20).std().replace(0, 1e-9)
    g["volume_zscore"] = (volume - vol_mean) / vol_std

    # Price momentum
    g["price_mom_5"] = close.pct_change(5)
    g["price_mom_20"] = close.pct_change(20)

    # Fractional differentiation (d=0.4 approximation via cumsum of weighted diffs)
    g["frac_diff_close"] = _frac_diff(close, d=0.4)

    # High-low range
    g["high_low_range"] = (high - low) / close.replace(0, 1e-9)

    # Gap (open vs previous close)
    g["gap"] = (g["open"].astype(float) - close.shift()) / close.shift().replace(0, 1e-9)

    # OBV z-score
    direction = np.sign(close.diff().fillna(0))
    obv = (direction * volume).cumsum()
    obv_mean = obv.rolling(20).mean()
    obv_std = obv.rolling(20).std().replace(0, 1e-9)
    g["obv_zscore"] = (obv - obv_mean) / obv_std

    # EMA crossover normalized
    ema12 = close.ewm(span=12, adjust=False).mean()
    ema26 = close.ewm(span=26, adjust=False).mean()
    g["ema_cross"] = (ema12 - ema26) / ema26.replace(0, 1e-9)

    # Volume-price correlation (10-period)
    g["vol_price_corr"] = close.rolling(10).corr(volume).fillna(0)

    # ── Target: next-day direction (1 = up, 0 = down) ───────────────────────
    # NaN > float evaluates to False in pandas, so the last row silently gets
    # target=0 instead of NaN. Drop it so we never train on a fabricated label.
    g["target"] = (close.shift(-1) > close).astype(int)
    g = g.iloc[:-1]  # remove last row — no next-day price available yet

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


def generate_walk_forward_folds(
    df: pd.DataFrame,
    train_months: int = 12,
    test_months: int = 1,
) -> List[Tuple[pd.DataFrame, pd.DataFrame]]:
    """
    Generate walk-forward train/test folds.
    Each fold trains on `train_months` months and tests on next `test_months` month(s).
    No data leakage: test data is always strictly after training data.
    """
    df = df.copy()
    df["date"] = pd.to_datetime(df["date"])
    df = df.sort_values("date")

    min_date = df["date"].min()
    max_date = df["date"].max()

    folds = []
    cursor = min_date + pd.DateOffset(months=train_months)

    while cursor + pd.DateOffset(months=test_months) <= max_date + pd.DateOffset(days=1):
        train_end = cursor
        test_end = cursor + pd.DateOffset(months=test_months)

        train_df = df[df["date"] < train_end].copy()
        test_df = df[(df["date"] >= train_end) & (df["date"] < test_end)].copy()

        if len(train_df) >= 60 and len(test_df) >= 5:
            folds.append((train_df, test_df))

        cursor += pd.DateOffset(months=test_months)

    return folds


def prepare_xy(df: pd.DataFrame) -> Tuple[np.ndarray, np.ndarray]:
    """Extract feature matrix X and target y from featured DataFrame."""
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
    2.  Column-name scan: no _future / _next / _fwd suffixes
    3.  Target not in FEATURE_COLUMNS
    4.  Row count sanity
    5.  Causal feature registry / pipeline DAG (no autocorrelation heuristics)
    6.  Normalisation scope warning (cannot be auto-detected — flagged for review)

    Known limitations (cannot be detected from DataFrames alone)
    -------------------------------------------------------------
    • A rolling mean computed on df (train+test concatenated) before split is
      backward-looking at every point and therefore produces the SAME values as
      computing on train only — so it is NOT a leakage issue.
    • Global normalisation (StandardScaler.fit on all data) IS a leakage source
      but is invisible in column values. Our LSTM fix (scaler fitted on last-fold
      train) addresses this; XGBoost is unscaled (no issue).
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

    # ── 5. Causal feature registry / pipeline DAG (no autocorrelation heuristics) ─
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

    # Timestamp availability: features must not use columns dated after row date
    if "date" in train_df.columns:
        checks.append(
            "Feature availability: pipeline assumes each row's features depend only on "
            "information at or before that row's date (enforced by backward-only construction)"
        )

    # ── 6. Normalisation scope warning (manual verification required) ────────
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


