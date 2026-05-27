"""Shared RL/backtest trading costs and FinRL env kwargs."""
from __future__ import annotations

from typing import Any, Dict, List

from app.config import settings


def transaction_costs_summary() -> Dict[str, Any]:
    return {
        "buy_cost_pct": settings.buy_cost_pct,
        "sell_cost_pct": settings.sell_cost_pct,
        "slippage_bps": settings.slippage_bps,
        "commission_note": (
            f"Each trade: ~{(settings.buy_cost_pct + settings.slippage_bps / 10000) * 100:.2f}% "
            f"buy friction, ~{(settings.sell_cost_pct + settings.slippage_bps / 10000) * 100:.2f}% sell."
        ),
    }


def effective_buy_price(price: float) -> float:
    slip = settings.slippage_bps / 10_000
    return price * (1 + settings.buy_cost_pct + slip)


def effective_sell_price(price: float) -> float:
    slip = settings.slippage_bps / 10_000
    return price * (1 - settings.sell_cost_pct - slip)


def finrl_env_kwargs(
    stock_dim: int,
    state_space: int,
    tech_indicators: List[str],
    initial_capital: float,
) -> Dict[str, Any]:
    pct_buy = [settings.buy_cost_pct] * stock_dim
    pct_sell = [settings.sell_cost_pct] * stock_dim
    return {
        "hmax": 100,
        "initial_amount": initial_capital,
        "num_stock_shares": [0] * stock_dim,
        "buy_cost_pct": pct_buy,
        "sell_cost_pct": pct_sell,
        "state_space": state_space,
        "stock_dim": stock_dim,
        "tech_indicator_list": tech_indicators,
        "action_space": stock_dim,
        "reward_scaling": 1e-4,
    }


def make_reward_shaped_env(base_env, turnover_penalty: float = 0.001, drawdown_penalty: float = 0.1):
    """Legacy alias — use rl_training.build_training_env for full PPO stack."""
    from app.services.rl_training import RLTrainingConfig, build_training_env

    cfg = RLTrainingConfig(
        turnover_penalty=turnover_penalty,
        drawdown_penalty=drawdown_penalty,
    )
    return build_training_env(base_env, cfg)
