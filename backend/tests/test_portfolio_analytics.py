"""Unit tests for portfolio analytics — effective-holdings (diversification)."""
from app.services.portfolio_analytics_service import (
    _diversification_score, _position_weights, compute_portfolio_analytics,
)


def _w(symbol, weight):
    return {"symbol": symbol, "weight": weight}


def test_single_holding_is_one():
    assert _diversification_score([_w("A", 1.0)]) == 1.0


def test_two_equal_holdings_is_two():
    assert _diversification_score([_w("A", 0.5), _w("B", 0.5)]) == 2.0


def test_ten_equal_holdings_is_ten():
    assert _diversification_score([_w(f"S{i}", 0.1) for i in range(10)]) == 10.0


def test_ten_equal_holdings_with_50pct_cash_still_ten():
    # The exact bug: raw weights sum to 0.5 -> unnormalized gave ~40. Must be 10.
    w = [_w(f"S{i}", 0.05) for i in range(10)] + [_w("CASH", 0.5)]
    assert _diversification_score(w) == 10.0


def test_concentrated_is_between_one_and_holdings():
    # One dominant name + a few tiny ones -> effective well below the count.
    w = [_w("BIG", 0.9)] + [_w(f"S{i}", 0.02) for i in range(5)]
    score = _diversification_score(w)
    assert 1.0 < score < 6.0
    assert score < 2.0   # heavily concentrated


def test_never_exceeds_invested_holdings():
    for n in (3, 7, 15):
        # random-ish uneven weights, plus cash
        invested = [_w(f"S{i}", (i + 1) / 100.0) for i in range(n)]
        score = _diversification_score(invested + [_w("CASH", 0.3)])
        assert 1.0 <= score <= n + 1e-9


def test_no_holdings_is_zero():
    assert _diversification_score([_w("CASH", 1.0)]) == 0.0
    assert _diversification_score([]) == 0.0


def test_metrics_from_same_snapshot_are_consistent():
    # holdings_count, largest_position, and diversification all derive from ONE
    # weights list -> they can't disagree about the portfolio.
    portfolio = {
        "portfolio_value": 100_000.0, "cash": 50_000.0,
        "positions": [{"symbol": f"S{i}", "market_value": 5_000.0} for i in range(10)],
    }
    a = compute_portfolio_analytics(portfolio, include_beta=False)
    assert a["holdings_count"] == 10
    assert a["diversification_score"] == 10.0        # 10 equal names, cash excluded
    assert a["diversification_score"] <= a["holdings_count"]
    assert a["cash_pct"] == 50.0
