#!/usr/bin/env python3
"""
OPTION 2 (robustness) — Walk-forward EGX RL backtest across expanding windows.

The single-split backtest (backtest_egx_rl.py) showed TD3/DDPG beating buy&hold
on ONE bull window — which could be regime luck. This retrains each algo on
several expanding windows and backtests each on the next unseen year, so we can
see whether an algo's edge is consistent or window-specific.

Reduced timesteps (this is a robustness sweep, not the final-magnitude run).
Reuses step4_train_rl.py env/configs and backtest_egx_rl.py's portfolio sim.

Usage:
    .venv/bin/python scripts/backtest_egx_rl_walkforward.py
Env overrides: TS_PPO, TS_OFF, ALGOS (csv)
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

import step4_train_rl as s4
from backtest_egx_rl import portfolio_backtest, INITIAL

logging.basicConfig(level=logging.INFO, format="%(asctime)s  %(levelname)-8s  %(message)s",
                    datefmt="%H:%M:%S")
log = logging.getLogger("egx_rl_wf")

EGX_FEATURES = ROOT / "data" / "oof" / "features_egx.csv"
OUT_DIR      = Path(os.environ.get("OUT_DIR", ROOT / "data" / "models" / "egx_rl_wf"))
RESULTS      = Path(os.environ.get("RESULTS", ROOT / "data" / "results" / "egx_rl_walkforward.json"))
OUT_DIR.mkdir(parents=True, exist_ok=True)

# Expanding-window walk-forward: train on everything up to train_end, test next slice
WINDOWS = [
    {"w": 1, "train": ["2019-01-01", "2021-12-31"], "test": ["2022-01-01", "2022-12-31"]},
    {"w": 2, "train": ["2019-01-01", "2022-12-31"], "test": ["2023-01-01", "2023-12-31"]},
    {"w": 3, "train": ["2019-01-01", "2023-12-31"], "test": ["2024-01-01", "2024-12-31"]},
    {"w": 4, "train": ["2019-01-01", "2024-12-31"], "test": ["2025-01-01", "2026-05-05"]},
]

TS_PPO = int(os.environ.get("TS_PPO", "50000"))
TS_OFF = int(os.environ.get("TS_OFF", "40000"))
ALGOS  = os.environ.get("ALGOS", "ppo,a2c,ddpg,td3,sac").split(",")


def bh_metrics(test_df):
    bh = test_df.groupby("date")["close"].mean().pct_change().dropna()
    total = float(np.prod(1 + bh.values) - 1)
    vol = float(np.std(bh.values) * np.sqrt(252))
    sharpe = float(((1 + total) ** (252 / max(len(bh), 1)) - 1) / (vol + 1e-9))
    return {"total_return": round(total, 4), "sharpe_ratio": round(sharpe, 4), "n_days": int(len(bh))}


def main():
    from app.finrl_wrapper import _mock_finrl_optional_deps
    _mock_finrl_optional_deps()
    from finrl.agents.stablebaselines3.models import DRLAgent
    from stable_baselines3.common.callbacks import BaseCallback

    df = pd.read_csv(EGX_FEATURES)
    df["date"] = pd.to_datetime(df["date"])

    results = {"universe_tickers": int(df["tic"].nunique()),
               "timesteps": {"ppo": TS_PPO, "off_policy": TS_OFF},
               "windows": [], "summary": {}}
    # algo -> list of (edge, beat_bool, sharpe) across windows
    track = {a: {"edges": [], "beats": 0, "sharpes": [], "returns": []} for a in ALGOS}

    for win in WINDOWS:
        tr0, tr1 = win["train"]; te0, te1 = win["test"]
        train_df = df[(df["date"] >= tr0) & (df["date"] <= tr1)].copy()
        test_df  = df[(df["date"] >= te0) & (df["date"] <= te1)].copy()
        if test_df.empty or train_df.empty:
            log.warning("Window %d empty (train=%d test=%d) — skipping", win["w"], len(train_df), len(test_df))
            continue
        bh = bh_metrics(test_df)
        log.info("══ Window %d | train %s→%s (%d rows) | test %s→%s (%d rows) | B&H ret=%.1f%% sharpe=%.2f",
                 win["w"], tr0, tr1, len(train_df), te0, te1, len(test_df),
                 bh["total_return"] * 100, bh["sharpe_ratio"])

        wres = {"window": win["w"], "train": win["train"], "test": win["test"],
                "benchmark": bh, "models": []}

        for algo in ALGOS:
            cfg = s4.ALGO_CONFIGS[algo]; sb3_kw = cfg["sb3_kwargs"].copy()
            total_ts = TS_PPO if algo == "ppo" else TS_OFF
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
            trained = model.learn(total_timesteps=total_ts, tb_log_name=f"egxwf_{algo}_w{win['w']}", callback=cb)
            trained.save(str(OUT_DIR / f"egx_{algo}_w{win['w']}_model"))
            perf = portfolio_backtest(trained, test_df)
            perf["algorithm"] = algo
            perf["edge_vs_buyhold"] = round(perf["total_return"] - bh["total_return"], 4)
            perf["beat_buyhold"] = bool(perf["total_return"] > bh["total_return"])
            perf["train_minutes"] = round((time.time() - t0) / 60, 2)
            wres["models"].append(perf)
            t = track[algo]
            t["edges"].append(perf["edge_vs_buyhold"]); t["sharpes"].append(perf["sharpe_ratio"])
            t["returns"].append(perf["total_return"]); t["beats"] += int(perf["beat_buyhold"])
            log.info("   %-4s W%d: ret=%.1f%% sharpe=%.2f edge=%.1f%% %s",
                     algo.upper(), win["w"], perf["total_return"] * 100, perf["sharpe_ratio"],
                     perf["edge_vs_buyhold"] * 100, "BEAT" if perf["beat_buyhold"] else "miss")
        results["windows"].append(wres)
        RESULTS.write_text(json.dumps(results, indent=2))  # checkpoint after each window

    n_win = len(results["windows"])
    for a in ALGOS:
        t = track[a]
        if not t["edges"]:
            continue
        results["summary"][a] = {
            "windows": n_win,
            "beat_buyhold_count": t["beats"],
            "beat_rate": round(t["beats"] / n_win, 2) if n_win else 0,
            "mean_edge": round(float(np.mean(t["edges"])), 4),
            "median_edge": round(float(np.median(t["edges"])), 4),
            "mean_sharpe": round(float(np.mean(t["sharpes"])), 4),
            "mean_return": round(float(np.mean(t["returns"])), 4),
            "edge_std": round(float(np.std(t["edges"])), 4),
        }
    RESULTS.write_text(json.dumps(results, indent=2))
    log.info("Saved -> %s", RESULTS)

    print("\n=== EGX RL WALK-FORWARD SUMMARY (%d windows) ===" % n_win)
    rows = [{"algo": a, **results["summary"][a]} for a in ALGOS if a in results["summary"]]
    cols = ["algo", "beat_buyhold_count", "beat_rate", "mean_edge", "median_edge",
            "mean_sharpe", "mean_return", "edge_std"]
    print(pd.DataFrame(rows)[cols].sort_values("mean_edge", ascending=False).to_string(index=False))


if __name__ == "__main__":
    main()
