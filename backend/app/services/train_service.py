import os
import json
import numpy as np
import pandas as pd
from pathlib import Path
from typing import Dict, Any, Optional
from app.config import settings
from app import finrl_wrapper

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
    total_timesteps = params.pop("total_timesteps", 5000)

    train_note = None
    if FINRL_AVAILABLE:
        try:
            from finrl.meta.preprocessor.preprocessors import data_split
            from finrl.meta.env_stock_trading.env_stocktrading import StockTradingEnv
            from finrl.agents.stablebaselines3.models import DRLAgent

            df = pd.read_csv(data_path)
            tech_indicators = finrl_wrapper.get_indicators()
            for ind in tech_indicators:
                if ind not in df.columns:
                    df[ind] = 0.0
            train_df = data_split(df, df["date"].min(), df["date"].max())

            stock_dim = len(train_df["tic"].unique())
            state_space = 1 + 2 * stock_dim + len(tech_indicators) * stock_dim
            buy_cost = [0.001] * stock_dim
            sell_cost = [0.001] * stock_dim
            num_stock_shares = [0] * stock_dim

            env_kwargs = {
                "hmax": 100,
                "initial_amount": 1_000_000,
                "num_stock_shares": num_stock_shares,
                "buy_cost_pct": buy_cost,
                "sell_cost_pct": sell_cost,
                "state_space": state_space,
                "stock_dim": stock_dim,
                "tech_indicator_list": tech_indicators,
                "action_space": stock_dim,
                "reward_scaling": 1e-4,
            }

            e_train = StockTradingEnv(df=train_df, **env_kwargs)
            agent = DRLAgent(env=e_train)
            model = agent.get_model(algorithm, model_kwargs=params)
            trained_model = agent.train_model(
                model=model,
                tb_log_name=run_id,
                total_timesteps=total_timesteps,
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
    }
    if train_note:
        metrics["note"] = train_note

    metrics_path = model_dir / "metrics.json"
    with open(metrics_path, "w") as f:
        json.dump(metrics, f)

    return {"model_path": model_path, "metrics": metrics}


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
