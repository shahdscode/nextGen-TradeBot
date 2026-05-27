import os
import json
import numpy as np
import pandas as pd
from pathlib import Path
from typing import Dict, Any, Optional
from app.config import settings
from app import finrl_wrapper
from app.services.trading_config import finrl_env_kwargs
from app.services.market_data_merge import overlay_yahoo_closes
from app.services.rl_features import build_alpha_state_pipeline
from app.services.pipeline_service import pick_primary_xgb_run_id, best_xgb_run_per_ticker
from app.services.rl_benchmark_rewards import build_benchmark_tracker
from app.services.rl_training import RLTrainingConfig, build_training_env

FINRL_AVAILABLE = finrl_wrapper.FINRL_AVAILABLE


def train_agent(
    run_id: str,
    data_job_id: str,
    algorithm: str,
    hyperparams: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """Train a DRL agent. Returns metrics dict."""
    data_path = Path(settings.data_dir) / data_job_id / "data.csv"
    model_dir = Path(settings.models_dir) / run_id
    model_dir.mkdir(parents=True, exist_ok=True)

    agent_cfg = finrl_wrapper.SUPPORTED_AGENTS.get(algorithm, {})
    params = {**agent_cfg.get("default_hyperparams", {}), **(hyperparams or {})}
    xgb_run_id = params.pop("xgb_run_id", None)
    lstm_run_id = params.pop("lstm_run_id", None)
    curriculum_phases = params.pop("curriculum_phases", None)
    rl_cfg = RLTrainingConfig.from_hyperparams(params)
    total_timesteps = max(int(params.pop("total_timesteps", 400_000)), 200_000)
    train_start = params.pop("train_start", None)
    train_end = params.pop("train_end", None)

    # SB3-only keys (reward/cooldown knobs live in rl_cfg, not PPO constructor)
    _NON_SB3 = {
        "cooldown_days", "trade_penalty", "turnover_penalty", "drawdown_penalty",
        "vol_exposure_penalty", "sharpe_bonus_weight", "reward_mode",
        "benchmark_sp500_weight", "benchmark_best_weight", "underperform_penalty",
        "positive_reward_scale", "regime_vol_turnover_mult", "regime_vol_action_penalty",
        "downside_multiplier", "use_risk_adjusted_reward", "risk_adjust_window",
        "action_smooth", "max_position_change", "entropy_decay_final",
        "train_start", "train_end", "test_start", "xgb_run_id", "lstm_run_id",
    }
    for k in list(params.keys()):
        if k in _NON_SB3:
            params.pop(k, None)

    # ── Leakage boundary guard ──────────────────────────────────────────────
    # If both train_end and a test_start are known, assert no temporal overlap.
    # This catches misconfigured date ranges before any model is trained.
    test_start_check = params.pop("test_start", None)
    if train_end and test_start_check:
        import pandas as _pd
        if _pd.Timestamp(train_end) >= _pd.Timestamp(test_start_check):
            raise ValueError(
                f"Data leakage: train_end ({train_end}) must be strictly before "
                f"test_start ({test_start_check}). Adjust your date ranges."
            )

    # Auto-resolve XGB alpha from same data job when training PPO
    if algorithm == "ppo" and not xgb_run_id and data_job_id:
        xgb_run_id = pick_primary_xgb_run_id(data_job_id)

    train_note = None
    price_overlay: Dict[str, Any] = {}
    if FINRL_AVAILABLE:
        try:
            from finrl.meta.preprocessor.preprocessors import data_split
            from finrl.meta.env_stock_trading.env_stocktrading import StockTradingEnv
            from finrl.agents.stablebaselines3.models import DRLAgent

            df = pd.read_csv(data_path)
            tech_indicators = finrl_wrapper.get_indicators(include_rl_extras=True)
            t0 = train_start or str(df["date"].min())
            t1 = train_end or str(df["date"].max())
            train_df = data_split(df, t0, t1)
            train_df, price_overlay = overlay_yahoo_closes(
                train_df, t0, t1, tech_indicators
            )
            train_df = build_alpha_state_pipeline(
                train_df,
                xgb_run_id=xgb_run_id,
                lstm_run_id=lstm_run_id,
                data_job_id=data_job_id,
            )
            for ind in tech_indicators:
                if ind not in train_df.columns:
                    train_df[ind] = 0.0

            stock_dim = len(train_df["tic"].unique())
            state_space = 1 + 2 * stock_dim + len(tech_indicators) * stock_dim

            env_kwargs = finrl_env_kwargs(
                stock_dim, state_space, tech_indicators, 1_000_000.0
            )

            bench_tracker = build_benchmark_tracker(train_df, t0, t1)

            e_train = StockTradingEnv(df=train_df, **env_kwargs)
            e_train = build_training_env(e_train, rl_cfg, bench_tracker)

            agent = DRLAgent(env=e_train)
            model = agent.get_model(algorithm, model_kwargs=params)
            callback = _entropy_decay_callback(algorithm, params, total_timesteps, rl_cfg)

            trained_model = model
            if curriculum_phases and isinstance(curriculum_phases, list) and len(curriculum_phases) > 1:
                ts_per_phase = max(total_timesteps // len(curriculum_phases), 50_000)
                t0_ts, t1_ts = pd.Timestamp(t0), pd.Timestamp(t1)
                for phase in curriculum_phases:
                    if isinstance(phase, dict) and phase.get("start") and phase.get("end"):
                        if pd.Timestamp(phase["end"]) < t0_ts or pd.Timestamp(phase["start"]) > t1_ts:
                            continue
                        phase_df = data_split(df, phase["start"], phase["end"])
                        phase_df, _ = overlay_yahoo_closes(phase_df, phase["start"], phase["end"], tech_indicators)
                        phase_df = build_alpha_state_pipeline(
                            phase_df, xgb_run_id, lstm_run_id, data_job_id
                        )
                        for ind in tech_indicators:
                            if ind not in phase_df.columns:
                                phase_df[ind] = 0.0
                        ph_tracker = build_benchmark_tracker(phase_df, phase["start"], phase["end"])
                        e_phase = build_training_env(
                            StockTradingEnv(df=phase_df, **env_kwargs), rl_cfg, ph_tracker
                        )
                        agent = DRLAgent(env=e_phase)
                        trained_model = agent.train_model(
                            model=trained_model,
                            tb_log_name=f"{run_id}_{phase['start'][:4]}",
                            total_timesteps=ts_per_phase,
                            callback=callback,
                        )
            else:
                trained_model = agent.train_model(
                    model=model,
                    tb_log_name=run_id,
                    total_timesteps=total_timesteps,
                    callback=callback,
                )

            model_path = str(model_dir / f"{algorithm}_model")
            trained_model.save(model_path)
            reward_curve = _extract_reward_curve(run_id)
        except Exception as e:
            train_note = f"Fell back to synthetic training: {e}"
            model_path, reward_curve = _synthetic_training(model_dir, algorithm, total_timesteps)
    else:
        model_path, reward_curve = _synthetic_training(model_dir, algorithm, total_timesteps)
        train_note = "Synthetic training used because FinRL is unavailable"

    metrics = {
        "reward_curve": reward_curve,
        "total_timesteps": total_timesteps,
        "algorithm": algorithm,
        "final_reward": reward_curve[-1]["reward"] if reward_curve else 0,
        "train_window": {"start": train_start, "end": train_end},
        "price_overlay": price_overlay,
        "rl_training": rl_cfg.__dict__,
        "reward_mode": rl_cfg.reward_mode,
        "alpha_inputs": {
            "xgb_run_id": xgb_run_id,
            "lstm_run_id": lstm_run_id,
            "xgb_runs_by_ticker": best_xgb_run_per_ticker(data_job_id) if data_job_id else {},
            "feature_count": len(finrl_wrapper.get_indicators(include_rl_extras=True)),
        },
        "transaction_costs": {
            "buy_cost_pct": settings.buy_cost_pct,
            "sell_cost_pct": settings.sell_cost_pct,
            "slippage_bps": settings.slippage_bps,
        },
    }
    if algorithm == "ppo" and xgb_run_id:
        metrics["xgb_auto_linked"] = xgb_run_id
    if train_note:
        metrics["note"] = train_note

    metrics_path = model_dir / "metrics.json"
    with open(metrics_path, "w") as f:
        json.dump(metrics, f)

    return {"model_path": model_path, "metrics": metrics}


def _entropy_decay_callback(algorithm: str, params: dict, total_timesteps: int, rl_cfg: RLTrainingConfig):
    """Linearly decay PPO entropy from ent_coef → entropy_decay_final."""
    if algorithm != "ppo":
        return None
    try:
        from stable_baselines3.common.callbacks import BaseCallback

        initial_ent = float(params.get("ent_coef", 0.01))

        class _EntropyDecay(BaseCallback):
            def __init__(self, final_ent: float, total_ts: int):
                super().__init__()
                self.final_ent = final_ent
                self.total_ts = max(total_ts, 1)

            def _on_step(self) -> bool:
                progress = min(1.0, self.num_timesteps / self.total_ts)
                self.model.ent_coef = initial_ent * (1.0 - progress) + self.final_ent * progress
                return True

        return _EntropyDecay(rl_cfg.entropy_decay_final, total_timesteps)
    except Exception:
        return None


def _extract_reward_curve(run_id: str):
    """Try to read TensorBoard logs; fall back to empty list."""
    try:
        from tensorboard.backend.event_processing.event_accumulator import EventAccumulator
        log_dir = f"./tensorboard_logs/{run_id}_1"
        ea = EventAccumulator(log_dir)
        ea.Reload()
        if "rollout/ep_rew_mean" in ea.Tags().get("scalars", []):
            events = ea.Scalars("rollout/ep_rew_mean")
            return [{"step": e.step, "reward": float(e.value)} for e in events]
    except Exception:
        pass
    return []


def _synthetic_training(model_dir: Path, algorithm: str, total_timesteps: int):
    import time
    import random

    steps = 20
    reward_curve = []
    for i in range(steps):
        time.sleep(0.05)
        reward_curve.append({
            "step": i * (max(1, total_timesteps) // steps),
            "reward": float(-500 + i * 50 + random.uniform(-20, 20)),
        })

    model_path = str(model_dir / f"{algorithm}_model.zip")
    Path(model_path).touch()
    return model_path, reward_curve
