"""
PPO / DRL training stack: benchmark-relative rewards, regime penalties, action smoothing.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, List, Optional

import numpy as np

from app.services.rl_benchmark_rewards import BenchmarkReturnTracker, _env_current_date


@dataclass
class RLTrainingConfig:
    cooldown_days: int = 5
    turnover_penalty: float = 0.002
    trade_penalty: float = 0.001
    drawdown_penalty: float = 0.5
    vol_exposure_penalty: float = 0.01
    downside_multiplier: float = 2.0
    use_risk_adjusted_reward: bool = False
    risk_adjust_window: int = 20
    sharpe_bonus_weight: float = 0.15
    action_smooth: float = 0.9
    max_position_change: float = 0.10
    entropy_decay_final: float = 0.0001
    # Benchmark-relative alpha (Priority 1)
    reward_mode: str = "alpha_relative"
    benchmark_sp500_weight: float = 1.0
    benchmark_best_weight: float = 0.5
    underperform_penalty: float = 2.0
    positive_reward_scale: float = 10.0
    # Regime-aware churn (Priority 3)
    regime_vol_turnover_mult: float = 2.0
    regime_vol_action_penalty: float = 0.003

    @classmethod
    def from_hyperparams(cls, hp: Optional[Dict[str, Any]]) -> "RLTrainingConfig":
        hp = hp or {}
        fields = set(cls.__dataclass_fields__.keys())
        kwargs = {k: hp.pop(k) for k in list(hp.keys()) if k in fields}
        return cls(**kwargs)


def build_training_env(
    base_env,
    cfg: RLTrainingConfig,
    benchmark_tracker: Optional[BenchmarkReturnTracker] = None,
):
    env = base_env
    env = _ActionSmoothingWrapper(env, cfg.action_smooth, cfg.max_position_change)
    env = _CooldownWrapper(env, cfg.cooldown_days)
    env = _RewardShapedWrapper(env, cfg, benchmark_tracker)
    return env


def _gym_wrapper_classes():
    try:
        import gymnasium as gym
        return gym.Wrapper, True
    except ImportError:
        import gym as gym_old
        return gym_old.Wrapper, False


WrapperBase, _GYMNASIUM = _gym_wrapper_classes()


class _ActionSmoothingWrapper(WrapperBase):
    def __init__(self, env, smooth: float, max_delta: float):
        super().__init__(env)
        self._smooth = float(np.clip(smooth, 0.0, 0.99))
        self._max_delta = float(max_delta)
        self._prev: Optional[np.ndarray] = None

    def reset(self, **kwargs):
        if _GYMNASIUM:
            obs, info = self.env.reset(**kwargs)
        else:
            obs = self.env.reset()
            info = {}
        self._prev = None
        return (obs, info) if _GYMNASIUM else obs

    def _smooth_action(self, action):
        a = np.asarray(action, dtype=float).flatten()
        if self._prev is None or len(self._prev) != len(a):
            self._prev = a.copy()
            return a
        target = self._smooth * self._prev + (1.0 - self._smooth) * a
        delta = np.clip(target - self._prev, -self._max_delta, self._max_delta)
        out = self._prev + delta
        self._prev = out.copy()
        return out

    def step(self, action):
        smoothed = self._smooth_action(action)
        if _GYMNASIUM:
            return self.env.step(smoothed)
        return self.env.step(smoothed)


class _CooldownWrapper(WrapperBase):
    def __init__(self, env, cooldown_days: int):
        super().__init__(env)
        self._cooldown = max(int(cooldown_days), 0)
        self._last_trade_day: Dict[int, int] = {}
        self._day = 0

    def reset(self, **kwargs):
        self._last_trade_day = {}
        self._day = 0
        if _GYMNASIUM:
            obs, info = self.env.reset(**kwargs)
            return obs, info
        return self.env.reset()

    def _stock_dim(self) -> int:
        return int(getattr(self.env, "stock_dim", 1))

    def _apply_cooldown(self, action):
        a = np.asarray(action, dtype=float).flatten()
        if self._cooldown <= 0:
            return a
        out = a.copy()
        for i in range(min(len(out), self._stock_dim())):
            last = self._last_trade_day.get(i, -self._cooldown - 1)
            if abs(out[i]) > 1e-8 and (self._day - last) < self._cooldown:
                out[i] = 0.0
        return out

    def step(self, action):
        prev = np.array(getattr(self.env, "num_stock_shares", [0] * self._stock_dim()), dtype=float)
        gated = self._apply_cooldown(action)
        if _GYMNASIUM:
            obs, reward, terminated, truncated, info = self.env.step(gated)
        else:
            obs, reward, done, info = self.env.step(gated)
            terminated, truncated = done, False

        new_shares = np.array(getattr(self.env, "num_stock_shares", prev), dtype=float)
        if np.any(np.abs(new_shares - prev) > 1e-6):
            for i in range(min(len(gated), self._stock_dim())):
                if abs(gated[i]) > 1e-8:
                    self._last_trade_day[i] = self._day
        self._day += 1

        if _GYMNASIUM:
            return obs, reward, terminated, truncated, info
        return obs, reward, terminated or truncated, info


class _RewardShapedWrapper(WrapperBase):
    """
    Reward = (portfolio_return − benchmark_return) with adversarial best-baseline term,
    drawdown/turnover penalties, regime-scaled churn, sqrt positive scaling.
    """

    def __init__(
        self,
        env,
        cfg: RLTrainingConfig,
        benchmark_tracker: Optional[BenchmarkReturnTracker] = None,
    ):
        super().__init__(env)
        self._cfg = cfg
        self._bench = benchmark_tracker
        self._peak = 0.0
        self._prev_pv = 0.0
        self._prev_action: Optional[np.ndarray] = None
        self._return_buf: List[float] = []
        self._step_i = 0

    def reset(self, **kwargs):
        init = float(getattr(self.env, "initial_amount", 1_000_000.0))
        self._peak = init
        self._prev_pv = init
        self._prev_action = None
        self._return_buf = []
        self._step_i = 0
        if _GYMNASIUM:
            obs, info = self.env.reset(**kwargs)
            return obs, info
        return self.env.reset()

    def _benchmark_day(self) -> Dict[str, float]:
        if not self._bench:
            return {"sp500": 0.0, "best_baseline": 0.0, "high_vol": False}
        dkey = _env_current_date(self.env)
        if dkey:
            return self._bench.get(dkey)
        day = int(getattr(self.env, "day", self._step_i))
        return self._bench.get_by_index(day)

    def step(self, action):
        action_arr = np.asarray(action, dtype=float).flatten()
        bench = self._benchmark_day()

        if _GYMNASIUM:
            obs, reward, terminated, truncated, info = self.env.step(action)
        else:
            obs, reward, done, info = self.env.step(action)
            terminated, truncated = done, False

        pv = float(getattr(self.env, "portfolio_value", self._prev_pv))
        if pv > self._peak:
            self._peak = pv
        step_ret = (pv - self._prev_pv) / self._prev_pv if self._prev_pv > 0 else 0.0
        self._prev_pv = pv
        self._step_i += 1

        sp_ret = float(bench.get("sp500", 0.0))
        best_ret = float(bench.get("best_baseline", 0.0))
        high_vol = bool(bench.get("high_vol", False))

        if self._cfg.reward_mode == "alpha_relative":
            # Core: beat the market
            alpha = step_ret - self._cfg.benchmark_sp500_weight * sp_ret
            # Adversarial: penalize losing to strongest baseline that day
            if step_ret < best_ret:
                alpha -= self._cfg.underperform_penalty * (best_ret - step_ret)
            alpha += self._cfg.benchmark_best_weight * (step_ret - best_ret)
            shaped = alpha
        else:
            shaped = float(reward)

        # Non-linear positive rewards (compounding behavior)
        if shaped > 0:
            shaped = np.sign(shaped) * np.sqrt(abs(shaped)) * self._cfg.positive_reward_scale
        elif shaped < 0:
            shaped *= self._cfg.downside_multiplier

        self._return_buf.append(step_ret)
        if len(self._return_buf) > self._cfg.risk_adjust_window:
            self._return_buf = self._return_buf[-self._cfg.risk_adjust_window :]

        if self._cfg.use_risk_adjusted_reward and len(self._return_buf) >= 5:
            vol = float(np.std(self._return_buf)) + 1e-8
            shaped = shaped / vol

        # Turnover — doubled in high-vol regimes
        if self._prev_action is not None and len(self._prev_action) == len(action_arr):
            turnover = float(np.sum(np.abs(action_arr - self._prev_action)))
        else:
            turnover = float(np.sum(np.abs(action_arr)))
        self._prev_action = action_arr.copy()

        turn_mult = self._cfg.regime_vol_turnover_mult if high_vol else 1.0
        shaped -= self._cfg.turnover_penalty * turn_mult * turnover

        if float(np.sum(np.abs(action_arr))) > 1e-8:
            shaped -= self._cfg.trade_penalty
            if high_vol:
                shaped -= self._cfg.regime_vol_action_penalty * turnover

        dd = (self._peak - pv) / self._peak if self._peak > 0 else 0.0
        shaped -= self._cfg.drawdown_penalty * dd

        if len(self._return_buf) >= 5:
            port_vol = float(np.std(self._return_buf))
            shaped -= self._cfg.vol_exposure_penalty * port_vol
            if step_ret > sp_ret and port_vol > 1e-8:
                shaped += self._cfg.sharpe_bonus_weight * ((step_ret - sp_ret) / port_vol)

        if _GYMNASIUM:
            return obs, float(shaped), terminated, truncated, info
        return obs, float(shaped), terminated or truncated, info
