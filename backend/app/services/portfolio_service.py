"""
Portfolio optimization — correlation/covariance-aware allocation.

The allocator ranks stocks and the risk engine (risk_sizing_service) caps and
sizes them. But ranking + per-name sizing still ignores ONE thing a portfolio
manager never does: how the names move *together*. Buying the five highest-
conviction tech names looks diversified by count but is one concentrated bet.

This module estimates the covariance of recent daily returns and turns it into
allocation weights via several classic objectives:

  * inverse_vol   — weight ∝ 1/volatility (simple risk balancing)
  * risk_parity   — equal risk contribution per name (iterative ERC)
  * min_variance  — minimum-variance long-only portfolio (Σ⁻¹ closed form)
  * max_sharpe    — mean-variance tangency using conviction as expected return
  * conviction    — weight ∝ model edge (no covariance; the prior behavior)

All methods are long-only (negative weights clipped) and normalized to sum to 1.
A small ridge term is added to the covariance for numerical stability.

References:
  Markowitz (1952) Portfolio Selection
  Maillard, Roncalli, Teiletche (2010) Equal Risk Contribution
"""
from __future__ import annotations

import logging
from typing import Dict, List, Optional, Tuple

import numpy as np
import pandas as pd

logger = logging.getLogger(__name__)

METHODS = ("conviction", "inverse_vol", "risk_parity", "min_variance", "max_sharpe")

_RIDGE = 1e-5          # covariance regularization for invertibility
_MIN_HISTORY = 30      # need at least this many return observations


def returns_matrix(price_history: pd.DataFrame, tickers: List[str]) -> pd.DataFrame:
    """
    Build an aligned daily-returns DataFrame (columns = tickers) from a long
    price frame with columns [date, tic, close]. Inner-joins on date so all
    series share the same dates; drops any rows with missing values.
    """
    df = price_history[price_history["tic"].isin(tickers)][["date", "tic", "close"]].copy()
    df["date"] = pd.to_datetime(df["date"])
    wide = df.pivot_table(index="date", columns="tic", values="close").sort_index()
    wide = wide.reindex(columns=[t for t in tickers if t in wide.columns])
    rets = wide.pct_change().dropna(how="any")
    return rets


def _cov(rets: pd.DataFrame) -> Tuple[np.ndarray, List[str]]:
    cols = list(rets.columns)
    cov = rets.cov().values.astype(float)
    cov += np.eye(cov.shape[0]) * _RIDGE
    return cov, cols


def _normalize_long_only(w: np.ndarray) -> np.ndarray:
    w = np.clip(w, 0.0, None)
    s = w.sum()
    if s <= 0:
        return np.ones_like(w) / len(w)
    return w / s


def _inverse_vol(cov: np.ndarray) -> np.ndarray:
    vol = np.sqrt(np.diag(cov))
    vol[vol <= 0] = np.nan
    w = 1.0 / vol
    w[np.isnan(w)] = 0.0
    return _normalize_long_only(w)


def _risk_parity(cov: np.ndarray, iters: int = 500, tol: float = 1e-8) -> np.ndarray:
    """Equal-risk-contribution weights via a simple fixed-point iteration."""
    n = cov.shape[0]
    w = np.ones(n) / n
    for _ in range(iters):
        mrc = cov @ w                       # marginal risk contribution
        rc = w * mrc                        # risk contribution
        target = (w @ cov @ w) / n          # equal target per name
        # multiplicative update toward equal risk contribution
        step = target / (mrc + 1e-12)
        w_new = _normalize_long_only(w * np.sqrt(np.clip(step, 1e-6, 1e6)))
        if np.abs(w_new - w).max() < tol:
            w = w_new
            break
        w = w_new
    return w


def _min_variance(cov: np.ndarray) -> np.ndarray:
    n = cov.shape[0]
    try:
        inv = np.linalg.pinv(cov)
        ones = np.ones(n)
        w = inv @ ones / (ones @ inv @ ones)
        return _normalize_long_only(w)
    except Exception:
        return np.ones(n) / n


def _max_sharpe(cov: np.ndarray, mu: np.ndarray) -> np.ndarray:
    """Mean-variance tangency: w ∝ Σ⁻¹ μ (long-only clipped)."""
    try:
        inv = np.linalg.pinv(cov)
        w = inv @ mu
        return _normalize_long_only(w)
    except Exception:
        return _normalize_long_only(np.clip(mu, 0, None))


def optimize_weights(
    tickers: List[str],
    price_history: pd.DataFrame,
    method: str = "risk_parity",
    conviction: Optional[Dict[str, float]] = None,
) -> Dict[str, object]:
    """
    Compute correlation-aware target weights for `tickers`.

    Parameters
    ----------
    tickers       : names to allocate across (the BUY set)
    price_history : long frame [date, tic, close] covering the lookback window
    method        : one of METHODS
    conviction    : {ticker: prob 0..1} — required for 'max_sharpe' (expected
                    return proxy = prob − 0.5) and used to tilt 'conviction'

    Returns
    -------
    {
      "weights": {ticker: weight},      # sums to 1 over usable names
      "method": str,                    # method actually applied
      "avg_correlation": float|None,    # mean pairwise corr (diversification gauge)
      "n": int,
      "notes": [str, ...],
    }
    """
    method = (method or "risk_parity").lower()
    conviction = conviction or {}
    notes: List[str] = []
    tickers = [t for t in tickers]
    if not tickers:
        return {"weights": {}, "method": method, "avg_correlation": None, "n": 0, "notes": ["no candidates"]}

    # Pure-conviction path needs no price history.
    if method == "conviction":
        w = np.array([max(0.0, conviction.get(t, 0.5) - 0.5) for t in tickers])
        w = _normalize_long_only(w) if w.sum() > 0 else np.ones(len(tickers)) / len(tickers)
        return {"weights": {t: round(float(w[i]), 6) for i, t in enumerate(tickers)},
                "method": "conviction", "avg_correlation": None, "n": len(tickers), "notes": notes}

    rets = returns_matrix(price_history, tickers)
    if rets.shape[0] < _MIN_HISTORY or rets.shape[1] < 2:
        # Not enough overlapping history (or single name) → fall back to conviction.
        notes.append(f"insufficient return history ({rets.shape[0]}×{rets.shape[1]}) — fell back to conviction")
        w = np.array([max(0.0, conviction.get(t, 0.5) - 0.5) for t in tickers]) if conviction else np.ones(len(tickers))
        w = _normalize_long_only(w)
        return {"weights": {t: round(float(w[i]), 6) for i, t in enumerate(tickers)},
                "method": "conviction(fallback)", "avg_correlation": None, "n": len(tickers), "notes": notes}

    cov, cols = _cov(rets)

    if method == "inverse_vol":
        w = _inverse_vol(cov)
    elif method == "min_variance":
        w = _min_variance(cov)
    elif method == "max_sharpe":
        mu = np.array([max(0.0, conviction.get(t, 0.5) - 0.5) for t in cols])
        if mu.sum() <= 0:
            mu = np.ones(len(cols))
            notes.append("no conviction edge — max_sharpe defaulted to equal expected return")
        w = _max_sharpe(cov, mu)
    else:  # risk_parity (default)
        method = "risk_parity"
        w = _risk_parity(cov)

    # Diversification gauge: average off-diagonal correlation of the selected set.
    corr = rets.corr().values
    n = corr.shape[0]
    avg_corr = float((corr.sum() - n) / (n * (n - 1))) if n > 1 else None

    weights = {t: round(float(w[i]), 6) for i, t in enumerate(cols)}
    # Tickers dropped for lack of history get zero weight (left out of cols).
    for t in tickers:
        weights.setdefault(t, 0.0)
    return {"weights": weights, "method": method,
            "avg_correlation": round(avg_corr, 4) if avg_corr is not None else None,
            "n": len(cols), "notes": notes}
