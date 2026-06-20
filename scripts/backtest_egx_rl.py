#!/usr/bin/env python3
"""
OPTION 2 — Train EGX-native RL models and backtest them out-of-sample.

The US-trained RL policies are dimension-locked to the DOW-30 universe, so they
cannot be applied to EGX. This trains fresh PPO/A2C/DDPG/TD3/SAC on the EGX
universe (21 .CA tickers), then runs each through a held-out out-of-sample
backtest with a long-only portfolio sim and an equal-weight buy & hold
benchmark over the SAME window.

Reuses step4_train_rl.py's env builder / configs so the environment matches the
production pipeline. Timesteps are reduced (env TS_* overrides) so all five
models finish in a reasonable time — this is a proof-of-capability backtest,
not the full 400k-step production train.

Usage:
    .venv/bin/python scripts/backtest_egx_rl.py
Env overrides:
    TS_PPO, TS_OFF (default 50000 / 40000), ALGOS (csv), TRAIN_END, TEST_END
"""
import sys, os, json, time, uuid
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "backend"))
sys.path.insert(0, str(ROOT / "scripts"))
os.chdir(ROOT / "backend")

import numpy as np
import pandas as pd

import step4_train_rl as s4   # reuse prepare_env, align_dates, ALGO_CONFIGS

EGX_FEATURES = ROOT / "data" / "oof" / "features_egx.csv"
OUT_DIR      = ROOT / "data" / "models" / "egx_rl"
RESULTS      = ROOT / "data" / "results" / "egx_rl_backtest.json"
OUT_DIR.mkdir(parents=True, exist_ok=True)

TRAIN_START = "2019-01-01"
TRAIN_END   = os.environ.get("TRAIN_END", "2024-12-31")
TEST_START  = "2025-01-01"
TEST_END    = os.environ.get("TEST_END", "2026-05-05")
INITIAL     = 1_000_000.0

TS_PPO = int(os.environ.get("TS_PPO", "50000"))
TS_OFF = int(os.environ.get("TS_OFF", "40000"))
ALGOS  = os.environ.get("ALGOS", "ppo,a2c,ddpg,td3,sac").split(",")

import logging
logging.basicConfig(level=logging.INFO, format="%(asctime)s  %(levelname)-8s  %(message)s",
                    datefmt="%H:%M:%S")
log = logging.getLogger("egx_rl")


def portfolio_backtest(model, test_df):
    """Run trained policy through the test window. Returns equity-curve metrics."""
    env = s4.prepare_env(test_df, initial_amount=INITIAL)
    rr = env.reset(); obs = rr[0] if isinstance(rr, tuple) else rr
    values = [env.initial_amount]; trades = 0; done = False
    while not done:
        action, _ = model.predict(obs, deterministic=True)
        trades += int(np.sum(np.abs(action) > 0.1))
        sr = env.step(action)
        if len(sr) == 5:
            obs, _, term, trunc, _ = sr; done = term or trunc
        else:
            obs, _, done, _ = sr
        if getattr(env, "asset_memory", None):
            values.append(env.asset_memory[-1])
    v = np.array(values, float); r = np.diff(v) / (v[:-1] + 1e-9); n = len(r)
    tr = float((v[-1] - v[0]) / (v[0] + 1e-9))
    ann = float((1 + tr) ** (252 / max(n, 1)) - 1)
    vol = float(np.std(r) * np.sqrt(252)) if n > 1 else 1e-9
    sharpe = float(ann / (vol + 1e-9))
    peak = np.maximum.accumulate(v); max_dd = float(((v - peak) / (peak + 1e-9)).min())
    return {"total_return": round(tr, 4), "ann_return": round(ann, 4),
            "sharpe_ratio": round(sharpe, 4), "max_drawdown": round(max_dd, 4),
            "win_rate": round(float(np.mean(r > 0)) if n else 0.5, 4),
            "trades_per_day": round(trades / max(n, 1), 2),
            "final_value": round(float(v[-1]), 2), "n_days": int(n)}


def main():
    from app.finrl_wrapper import _mock_finrl_optional_deps
    _mock_finrl_optional_deps()
    from finrl.agents.stablebaselines3.models import DRLAgent
    from stable_baselines3.common.callbacks import BaseCallback

    df = pd.read_csv(EGX_FEATURES)
    df["date"] = pd.to_datetime(df["date"])
    train_df = df[(df["date"] >= TRAIN_START) & (df["date"] <= TRAIN_END)].copy()
    test_df  = df[(df["date"] >= TEST_START) & (df["date"] <= TEST_END)].copy()
    log.info("EGX universe: %d tickers | train rows %d (%s→%s) | test rows %d (%s→%s)",
             df["tic"].nunique(), len(train_df), TRAIN_START, TRAIN_END,
             len(test_df), TEST_START, TEST_END)

    # Equal-weight buy & hold benchmark over the test window
    bh = test_df.groupby("date")["close"].mean().pct_change().dropna()
    bh_total = float(np.prod(1 + bh.values) - 1)
    bh_vol = float(np.std(bh.values) * np.sqrt(252))
    bh_sharpe = float(((1 + bh_total) ** (252 / max(len(bh), 1)) - 1) / (bh_vol + 1e-9))
    benchmark = {"name": "equal_weight_buyhold", "total_return": round(bh_total, 4),
                 "sharpe_ratio": round(bh_sharpe, 4), "n_days": int(len(bh))}
    log.info("Benchmark (EW buy&hold): total_return=%.2f%% sharpe=%.2f",
             bh_total * 100, bh_sharpe)

    results = {"window": {"train": [TRAIN_START, TRAIN_END], "test": [TEST_START, TEST_END]},
               "universe_tickers": int(df["tic"].nunique()),
               "benchmark": benchmark, "models": []}

    for algo in ALGOS:
        cfg = s4.ALGO_CONFIGS[algo]
        sb3_kw = cfg["sb3_kwargs"].copy()
        total_ts = TS_PPO if algo == "ppo" else TS_OFF
        log.info("── %s | %d timesteps ──", algo.upper(), total_ts)
        t0 = time.time()
        env = s4.prepare_env(train_df, initial_amount=INITIAL)
        model = DRLAgent(env=env).get_model(algo, model_kwargs=sb3_kw)

        cb = None
        if algo == "ppo":
            init_ent = float(sb3_kw.get("ent_coef", 0.01))
            class Decay(BaseCallback):
                def _on_step(self):
                    p = min(1.0, self.num_timesteps / total_ts)
                    self.model.ent_coef = init_ent * (1 - p) + 0.0001 * p
                    return True
            cb = Decay()

        trained = model.learn(total_timesteps=total_ts,
                              tb_log_name=f"egx_{algo}", callback=cb)
        mp = str(OUT_DIR / f"egx_{algo}_model")
        trained.save(mp)
        perf = portfolio_backtest(trained, test_df)
        perf["edge_vs_buyhold"] = round(perf["total_return"] - bh_total, 4)
        perf["algorithm"] = algo
        perf["total_timesteps"] = total_ts
        perf["train_minutes"] = round((time.time() - t0) / 60, 2)
        perf["model_path"] = mp + ".zip"
        results["models"].append(perf)
        log.info("  %s OOS: ret=%.2f%% sharpe=%.2f maxDD=%.1f%% edge=%.2f%% (%.1f min)",
                 algo.upper(), perf["total_return"] * 100, perf["sharpe_ratio"],
                 perf["max_drawdown"] * 100, perf["edge_vs_buyhold"] * 100,
                 perf["train_minutes"])

    RESULTS.parent.mkdir(parents=True, exist_ok=True)
    RESULTS.write_text(json.dumps(results, indent=2))
    log.info("Saved -> %s", RESULTS)

    print("\n=== EGX RL OUT-OF-SAMPLE BACKTEST (%s → %s) ===" % (TEST_START, TEST_END))
    print("Benchmark EW buy&hold: total_return=%.2f%%  sharpe=%.2f\n"
          % (bh_total * 100, bh_sharpe))
    cols = ["algorithm", "total_return", "sharpe_ratio", "max_drawdown",
            "win_rate", "trades_per_day", "edge_vs_buyhold", "train_minutes"]
    print(pd.DataFrame(results["models"])[cols].to_string(index=False))


if __name__ == "__main__":
    main()
