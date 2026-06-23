#!/usr/bin/env python3
"""
Robust RL training to reduce overfitting, applying three techniques:

  1. Validation-based early stopping — train on 2019-2023, hold out 2024 as a
     validation window; keep the checkpoint with the best validation reward
     (SB3 EvalCallback) and stop when it stops improving.
  2. Multi-seed ensemble — train N seeds per algorithm and AVERAGE their actions
     at inference; cuts the seed-variance that drives RL overfitting.
  3. More regimes / markets — MARKETS env var: "egx", "us", or "us,egx" (combined
     universe → more diverse experience). Training window spans multiple regimes
     (2019 COVID crash, 2022 drawdown, bull phases).

Reports the in-sample (train) vs out-of-sample (test) gap for: a single seed
(final), a single seed (best-validation), and the multi-seed ensemble — so the
overfitting reduction is visible.

Usage:
  ALGOS=sac SEEDS=3 TIMESTEPS=40000 MARKETS=egx .venv/bin/python scripts/rl_robust_train.py
"""
import sys, os, json, time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "backend"))
sys.path.insert(0, str(ROOT / "scripts"))
os.chdir(ROOT / "backend")

import numpy as np
import pandas as pd
import logging

import step4_train_rl as s4   # prepare_env, ALGO_CONFIGS

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s", datefmt="%H:%M:%S")
log = logging.getLogger("rl_robust")

OOF = ROOT / "data" / "oof"
OUT = ROOT / "data" / "results" / "rl_robust.json"
MODELS = ROOT / "data" / "models" / "rl_robust"
MODELS.mkdir(parents=True, exist_ok=True)

# Splits: train (multi-regime) | validation (early stopping) | test (OOS)
TRAIN = ("2019-01-01", "2023-12-31")
VAL   = ("2024-01-01", "2024-12-31")
TEST  = ("2025-01-01", "2026-05-05")

ALGOS     = os.environ.get("ALGOS", "sac").split(",")
SEEDS     = int(os.environ.get("SEEDS", "3"))
TIMESTEPS = int(os.environ.get("TIMESTEPS", "40000"))
MARKETS   = os.environ.get("MARKETS", "egx").split(",")
INITIAL   = 1_000_000.0


def load_universe(markets):
    frames = []
    for m in markets:
        f = OOF / (f"features_{m}.csv")
        if f.exists():
            d = pd.read_csv(f); d["date"] = pd.to_datetime(d["date"]); frames.append(d)
    df = pd.concat(frames, ignore_index=True)
    return df


def slice_df(df, span):
    return df[(df["date"] >= span[0]) & (df["date"] <= span[1])].copy()


def equity_metrics(values):
    v = np.asarray(values, float); r = np.diff(v) / (v[:-1] + 1e-9); n = len(r)
    tot = float((v[-1] - v[0]) / (v[0] + 1e-9))
    sharpe = float(np.mean(r) / (np.std(r) + 1e-9) * np.sqrt(252)) if n > 1 else 0.0
    peak = np.maximum.accumulate(v); maxdd = float(((v - peak) / (peak + 1e-9)).min())
    return {"return": round(tot, 4), "sharpe": round(sharpe, 2), "maxdd": round(maxdd, 4)}


def run_episode(models, env):
    """Step env once, averaging the action across an ensemble of models."""
    rr = env.reset(); obs = rr[0] if isinstance(rr, tuple) else rr
    vals = [env.initial_amount]; done = False
    while not done:
        acts = [m.predict(obs, deterministic=True)[0] for m in models]
        action = np.mean(acts, axis=0)
        sr = env.step(action)
        if len(sr) == 5: obs, _, term, trunc, _ = sr; done = term or trunc
        else: obs, _, done, _ = sr
        if getattr(env, "asset_memory", None): vals.append(env.asset_memory[-1])
    return equity_metrics(vals)


def bh_return(df):
    bh = df.groupby("date")["close"].mean().pct_change().dropna()
    return float(np.prod(1 + bh.values) - 1)


def main():
    from app.finrl_wrapper import _mock_finrl_optional_deps
    _mock_finrl_optional_deps()
    from finrl.agents.stablebaselines3.models import DRLAgent
    from stable_baselines3.common.callbacks import EvalCallback, StopTrainingOnNoModelImprovement
    from stable_baselines3.common.monitor import Monitor
    from stable_baselines3.common.vec_env import DummyVecEnv

    df = load_universe(MARKETS)
    train_df, val_df, test_df = slice_df(df, TRAIN), slice_df(df, VAL), slice_df(df, TEST)
    log.info("markets=%s tickers=%d | train %d | val %d | test %d rows",
             MARKETS, df["tic"].nunique(), len(train_df), len(val_df), len(test_df))
    bh = {"val": bh_return(val_df), "test": bh_return(test_df)}
    log.info("Buy&Hold: val %.1f%% | test %.1f%%", bh["val"]*100, bh["test"]*100)

    results = {"markets": MARKETS, "seeds": SEEDS, "timesteps": TIMESTEPS,
               "splits": {"train": TRAIN, "val": VAL, "test": TEST},
               "benchmark": bh, "models": {}}

    for algo in ALGOS:
        cfg = s4.ALGO_CONFIGS[algo]; sb3_kw = cfg["sb3_kwargs"].copy()
        seed_models, final_models = [], []
        for seed in range(SEEDS):
            t0 = time.time()
            train_env = s4.prepare_env(train_df, INITIAL)
            val_env = Monitor(s4.prepare_env(val_df, INITIAL))
            best_dir = MODELS / f"{algo}_s{seed}"
            best_dir.mkdir(parents=True, exist_ok=True)
            # (1) validation early stopping: keep best-on-val, stop if no improvement
            stop_cb = StopTrainingOnNoModelImprovement(max_no_improvement_evals=3, min_evals=3, verbose=0)
            eval_cb = EvalCallback(DummyVecEnv([lambda e=val_env: e]),
                                   best_model_save_path=str(best_dir),
                                   eval_freq=max(TIMESTEPS // 8, 2000),
                                   n_eval_episodes=1, deterministic=True,
                                   callback_after_eval=stop_cb, verbose=0)
            model = DRLAgent(env=train_env).get_model(algo, model_kwargs=dict(sb3_kw), seed=seed)
            model.learn(total_timesteps=TIMESTEPS, callback=eval_cb,
                        tb_log_name=f"robust_{algo}_s{seed}")
            final_models.append(model)
            # load best-on-validation checkpoint
            cls = type(model)
            best_path = best_dir / "best_model.zip"
            best = cls.load(str(best_path)) if best_path.exists() else model
            seed_models.append(best)
            log.info("  %s seed %d trained (%.1f min)", algo.upper(), seed, (time.time()-t0)/60)

        # ── Evaluate the three variants on train (in-sample) and test (OOS) ──
        def gap(models):
            ins = run_episode(models, s4.prepare_env(train_df, INITIAL))
            oos = run_episode(models, s4.prepare_env(test_df, INITIAL))
            return {"in_sample": ins, "out_of_sample": oos,
                    "gap_return": round(ins["return"] - oos["return"], 4),
                    "oos_vs_bh": round(oos["return"] - bh["test"], 4)}

        res = {
            "single_final":       gap([final_models[0]]),               # no early stop, 1 seed
            "single_best_val":    gap([seed_models[0]]),                # +early stopping
            "ensemble_best_val":  gap(seed_models),                     # +early stopping +ensemble
        }
        results["models"][algo] = res
        OUT.write_text(json.dumps(results, indent=2))
        log.info("== %s ==", algo.upper())
        for k, v in res.items():
            log.info("  %-18s IS %+.1f%% | OOS %+.1f%% | gap %.1f%% | OOS vs B&H %+.1f%%",
                     k, v["in_sample"]["return"]*100, v["out_of_sample"]["return"]*100,
                     v["gap_return"]*100, v["oos_vs_bh"]*100)

    OUT.write_text(json.dumps(results, indent=2))
    log.info("Saved -> %s", OUT)


if __name__ == "__main__":
    main()
