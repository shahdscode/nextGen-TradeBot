"""Unit tests for backtest metrics: FIFO trade accounting + risk-adjusted stats."""
import numpy as np

from app.services.backtest_service import (
    _compute_trade_return_stats, _compute_metrics, _compute_daily_returns,
)


def test_fifo_simple_round_trip():
    trades = [
        {"date": "2024-01-01", "ticker": "X", "action": "buy",  "shares": 10, "price": 100.0},
        {"date": "2024-01-05", "ticker": "X", "action": "sell", "shares": 10, "price": 110.0},
    ]
    s = _compute_trade_return_stats(trades)
    assert s["n_closed_lots"] == 1
    assert abs(s["avg_trade_return"] - 0.10) < 1e-9   # +10%
    assert s["trade_win_rate"] == 1.0


def test_fifo_partial_matching_across_lots():
    # Two buys, one larger sell -> FIFO consumes oldest lot first.
    trades = [
        {"date": "2024-01-01", "ticker": "X", "action": "buy",  "shares": 10, "price": 100.0},
        {"date": "2024-01-02", "ticker": "X", "action": "buy",  "shares": 10, "price": 120.0},
        {"date": "2024-01-05", "ticker": "X", "action": "sell", "shares": 15, "price": 130.0},
    ]
    s = _compute_trade_return_stats(trades)
    # 10 sh matched vs 100 (+30%), 5 sh matched vs 120 (+8.33%) -> 2 closed lots
    assert s["n_closed_lots"] == 2
    assert s["trade_win_rate"] == 1.0


def test_fifo_does_not_treat_every_sell_as_full_roundtrip():
    # The bug we fixed: many small sells against one buy shouldn't fabricate losses.
    trades = [{"date": "2024-01-01", "ticker": "X", "action": "buy", "shares": 100, "price": 100.0}]
    trades += [{"date": f"2024-02-{d:02d}", "ticker": "X", "action": "sell",
                "shares": 1, "price": 101.0} for d in range(1, 11)]
    s = _compute_trade_return_stats(trades)
    assert s["n_closed_lots"] == 10
    assert s["avg_trade_return"] > 0        # all small wins, not spurious losses


def test_fifo_uses_effective_price_when_present():
    trades = [
        {"date": "2024-01-01", "ticker": "X", "action": "buy",  "shares": 10,
         "price": 100.0, "effective_price": 101.0},
        {"date": "2024-01-05", "ticker": "X", "action": "sell", "shares": 10,
         "price": 110.0, "effective_price": 109.0},
    ]
    s = _compute_trade_return_stats(trades)
    # (109 - 101)/101 ~= 0.0792, not (110-100)/100
    assert abs(s["avg_trade_return"] - (8.0 / 101.0)) < 1e-6


def test_no_trades_is_safe():
    s = _compute_trade_return_stats([])
    assert s["n_closed_lots"] == 0
    assert s["avg_trade_return"] is None


def test_sharpe_positive_for_noisy_uptrend():
    # Positive drift WITH volatility (constant returns have zero vol -> Sharpe 0).
    rng = np.random.default_rng(0)
    daily = 0.0008 + rng.normal(0, 0.008, 252)   # positive mean, real variance
    vals = [100000.0]
    for d in daily:
        vals.append(vals[-1] * (1 + d))
    rets = _compute_daily_returns(vals)
    m = _compute_metrics(vals, rets, 100000.0)
    assert m["sharpe"] > 0
    assert m["total_return"] > 0
    assert m["max_drawdown"] >= 0


def test_max_drawdown_computed():
    vals = [100.0, 120.0, 90.0, 110.0]   # peak 120 -> trough 90 = 25% dd
    rets = _compute_daily_returns(vals)
    m = _compute_metrics(vals, rets, 100.0)
    assert abs(m["max_drawdown"] - 0.25) < 1e-6


def test_profit_factor_gt_one_when_wins_exceed_losses():
    vals = [100.0, 105.0, 104.0, 110.0]
    rets = _compute_daily_returns(vals)
    m = _compute_metrics(vals, rets, 100.0)
    assert m["profit_factor"] > 1.0


def test_daily_returns_length():
    vals = [100.0, 101.0, 102.0]
    assert len(_compute_daily_returns(vals)) == 2
