"""Unit tests for correlation-aware portfolio optimization."""
import numpy as np
import pandas as pd

from app.services.portfolio_service import optimize_weights, returns_matrix, METHODS


def _price_history(seed=0):
    """3 correlated names + 1 uncorrelated low-vol diversifier."""
    rng = np.random.default_rng(seed)
    dates = pd.bdate_range("2024-01-01", periods=120)
    common = rng.normal(0, 0.01, len(dates))
    series = {}
    for t, beta, vol in [("A", 1.0, 0.012), ("B", 0.95, 0.013),
                         ("C", 1.05, 0.02), ("D", 0.0, 0.006)]:
        rets = beta * common + rng.normal(0, vol, len(dates))
        series[t] = 100 * np.cumprod(1 + rets)
    return pd.concat([pd.DataFrame({"date": dates, "tic": t, "close": s})
                      for t, s in series.items()])


def test_all_methods_return_normalized_weights():
    ph = _price_history()
    conv = {"A": 0.9, "B": 0.8, "C": 0.85, "D": 0.7}
    for m in METHODS:
        r = optimize_weights(list("ABCD"), ph, method=m, conviction=conv)
        s = sum(r["weights"].values())
        assert abs(s - 1.0) < 1e-6, f"{m} weights sum to {s}"
        assert all(w >= -1e-9 for w in r["weights"].values()), f"{m} has negative weight"


def test_risk_parity_favors_uncorrelated_lowvol_name():
    ph = _price_history()
    r = optimize_weights(list("ABCD"), ph, method="risk_parity")
    # D is uncorrelated + lowest vol -> should get the largest weight
    assert r["weights"]["D"] == max(r["weights"].values())


def test_insufficient_history_falls_back_to_conviction():
    dates = pd.bdate_range("2024-01-01", periods=5)   # < min history
    ph = pd.concat([pd.DataFrame({"date": dates, "tic": t, "close": [100, 101, 102, 103, 104]})
                    for t in ["A", "B"]])
    conv = {"A": 0.9, "B": 0.6}
    r = optimize_weights(["A", "B"], ph, method="risk_parity", conviction=conv)
    assert "fallback" in r["method"]
    assert r["weights"]["A"] > r["weights"]["B"]   # higher conviction -> higher weight


def test_avg_correlation_reported():
    ph = _price_history()
    r = optimize_weights(list("ABCD"), ph, method="min_variance")
    assert r["avg_correlation"] is not None
    assert -1.0 <= r["avg_correlation"] <= 1.0


def test_empty_candidates_safe():
    r = optimize_weights([], _price_history(), method="risk_parity")
    assert r["weights"] == {}
    assert r["n"] == 0


def test_returns_matrix_aligns_dates():
    ph = _price_history()
    rm = returns_matrix(ph, list("ABCD"))
    assert list(rm.columns) == list("ABCD")
    assert not rm.isnull().any().any()
