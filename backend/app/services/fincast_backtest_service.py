"""
FinCast contextual-bandit backtest.

A faithful port of the FinCast research notebook's backtest
(FinCast_RL_Final_version.ipynb): FinCast produces a per-window price forecast
(point + q10/q90 at the horizon end); a contextual bandit discretises that into a
state (expected-return / volatility / confidence / trend bins) and learns
BUY/HOLD/SELL with delayed reward over the horizon. Train on the first
TRAIN_RATIO of windows, evaluate out-of-sample on the rest.

Constants and logic are kept identical to the notebook so results match.
"""
from __future__ import annotations

import random
from collections import defaultdict
from typing import Any, Dict, List

import numpy as np

from app.services.fincast_service import forecast_windows, CONTEXT_LEN, HORIZON_LEN

# ── Notebook constants ───────────────────────────────────────────────────────
ALPHA            = 0.3
EPSILON          = 0.1
EPSILON_DECAY    = 0.995
MIN_EPSILON      = 0.01
TRANSACTION_COST = 0.0015
TEST_WINDOWS     = 2000
TRAIN_RATIO      = 0.7


def compute_trend(prices, window: int = 10) -> float:
    if len(prices) < window:
        return 0.0
    x = np.arange(window)
    y = prices[-window:]
    slope = np.polyfit(x, y, 1)[0]
    return slope / prices[-1]


def discretize_state(point, q10, q90, current_price, price_history) -> str:
    expected_return = (point - current_price) / current_price
    spread = (q90 - q10) / current_price

    if expected_return < -0.04:   ret_bin = "VeryDown"
    elif expected_return < -0.015: ret_bin = "Down"
    elif expected_return < -0.005: ret_bin = "SlightDown"
    elif expected_return < 0.005:  ret_bin = "Flat"
    elif expected_return < 0.015:  ret_bin = "SlightUp"
    elif expected_return < 0.04:   ret_bin = "Up"
    else:                          ret_bin = "VeryUp"

    if spread < 0.01:   vol_bin = "LowVol"
    elif spread < 0.03: vol_bin = "MidVol"
    else:               vol_bin = "HighVol"

    conf_bin = "HighConf" if spread < 0.01 else "LowConf"

    trend = compute_trend(price_history, window=10)
    if trend > 0.001:    trend_bin = "TrendUp"
    elif trend < -0.001: trend_bin = "TrendDown"
    else:                trend_bin = "TrendFlat"

    return f"{ret_bin}_{vol_bin}_{conf_bin}_{trend_bin}"


class BanditAgent:
    def __init__(self, alpha=ALPHA, epsilon=EPSILON, epsilon_decay=EPSILON_DECAY, min_epsilon=MIN_EPSILON):
        self.q_table = defaultdict(lambda: {"BUY": 0.0, "HOLD": 0.0, "SELL": 0.0})
        self.alpha = alpha; self.epsilon = epsilon
        self.epsilon_decay = epsilon_decay; self.min_epsilon = min_epsilon
        self.actions = ["BUY", "HOLD", "SELL"]

    def act(self, state, greedy=False):
        if not greedy and random.random() < self.epsilon:
            return random.choice(self.actions)
        return max(self.q_table[state], key=self.q_table[state].get)

    def learn(self, state, action, reward):
        self.q_table[state][action] += self.alpha * (reward - self.q_table[state][action])
        self.epsilon = max(self.min_epsilon, self.epsilon * self.epsilon_decay)


def _metrics(returns: np.ndarray) -> Dict[str, float]:
    ret = np.asarray(returns)
    if len(ret) == 0:
        return {}
    mean_ret = float(np.mean(ret))
    std_ret = float(np.std(ret)) if len(ret) > 1 else 0.0
    ann = 252
    sharpe = mean_ret / std_ret * np.sqrt(ann) if std_ret > 0 else 0.0
    curve = np.cumprod(1 + ret)
    running_max = np.maximum.accumulate(curve)
    drawdown = curve / running_max - 1
    max_dd = float(np.min(drawdown)) if len(drawdown) else 0.0
    win_rate = float(np.mean(ret > 0)) if len(ret) else 0.0
    dn = ret[ret < 0]
    sortino = (mean_ret / float(np.std(dn)) * np.sqrt(ann)) if len(dn) and np.std(dn) > 0 else 0.0
    return {"sharpe_ratio": round(sharpe, 4), "max_drawdown": round(max_dd, 4),
            "win_rate": round(win_rate, 4), "sortino_ratio": round(sortino, 4),
            "mean_return": round(mean_ret, 6), "std_return": round(std_ret, 6)}


def run_fincast_backtest(closes: List[float], test_windows: int = TEST_WINDOWS,
                         seed: int = 42) -> Dict[str, Any]:
    """Run the FinCast+bandit backtest on a 5-minute close series."""
    random.seed(seed); np.random.seed(seed)
    close = [float(c) for c in closes if c is not None and np.isfinite(c)]
    total_len = CONTEXT_LEN + HORIZON_LEN
    if len(close) < total_len + 10:
        return {"ok": False, "message": f"Need >= {total_len + 10} bars, got {len(close)}"}

    # Bound compute: forecasting is per-window and CPU-heavy, so only keep enough
    # bars to produce ~test_windows windows (chronological, from the start). The
    # full series would otherwise infer thousands of windows.
    needed = min(len(close), test_windows + total_len + 5)
    close = close[:needed]
    n = len(close)

    # FinCast forecasts for the (bounded) windows (batched)
    fc = forecast_windows(close)
    if not fc.get("ok"):
        return {"ok": False, "message": fc.get("message", "forecast failed")}
    point, q10, q90 = fc["point"], fc["q10"], fc["q90"]

    max_windows = min(test_windows, n - total_len, len(point))
    train_split = int(max_windows * TRAIN_RATIO)

    agent = BanditAgent()
    history: Dict[int, dict] = {}
    all_actions: List[str] = []
    test_rewards: List[float] = []
    test_actions: List[str] = []

    for i in range(max_windows):
        context = close[i:i + CONTEXT_LEN]
        current_price = close[i + CONTEXT_LEN - 1]
        state = discretize_state(point[i], q10[i], q90[i], current_price, context)
        is_train = (i < train_split)
        action = agent.act(state, greedy=(not is_train))
        history[i] = {"state": state, "action": action, "price": current_price}
        all_actions.append(action)

        if i >= HORIZON_LEN:
            past = history[i - HORIZON_LEN]
            pp, pa, ps = past["price"], past["action"], past["state"]
            fut = current_price
            if pa == "BUY":
                reward = (fut - pp) / pp - TRANSACTION_COST * 2
            elif pa == "SELL":
                reward = (pp - fut) / pp - TRANSACTION_COST * 2
            else:
                reward = 0.0
            if (i - HORIZON_LEN) < train_split:
                agent.learn(ps, pa, reward)
            else:
                test_rewards.append(reward)
                test_actions.append(pa)

    if not test_rewards:
        return {"ok": False, "message": "No test trades completed — increase data/test_windows"}

    tr = np.array(test_rewards)
    compounded = float(np.prod(1 + tr) - 1)
    m = _metrics(tr)

    # Buy & hold over the exact test period (notebook formula)
    first_test_idx = train_split + CONTEXT_LEN - 1
    last_test_idx = min(n - 1, max_windows + CONTEXT_LEN - 2)
    bh_return = (close[last_test_idx] - close[first_test_idx]) / close[first_test_idx]

    action_counts = {a: all_actions.count(a) for a in ("BUY", "HOLD", "SELL")}
    return {
        "ok": True,
        "model": "fincast_v1+5min_adapter+bandit",
        "n_windows": int(max_windows), "train_windows": int(train_split),
        "test_trades": int(len(tr)),
        "oos_return": round(compounded, 4),
        "buyhold_return": round(float(bh_return), 4),
        "edge_vs_buyhold": round(compounded - float(bh_return), 4),
        "sharpe_ratio": m["sharpe_ratio"], "max_drawdown": m["max_drawdown"],
        "win_rate": m["win_rate"], "sortino_ratio": m["sortino_ratio"],
        "action_counts": action_counts,
        "equity_curve": [round(float(x), 5) for x in np.cumsum(tr)],
        "transaction_cost": TRANSACTION_COST, "train_ratio": TRAIN_RATIO,
        "context_len": CONTEXT_LEN, "horizon_len": HORIZON_LEN,
    }
