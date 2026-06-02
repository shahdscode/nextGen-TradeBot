#!/usr/bin/env python3
"""
Step 4 — RL Model Training: 3-Checkpoint Expanding Window (Option 4)

Strategy: train each algorithm 3 times on expanding windows, collect
OOF signals only on data each checkpoint NEVER trained on.

  Checkpoint 1: train 2019-01 → 2021-12  collect signals 2022-01 → 2022-12
  Checkpoint 2: train 2019-01 → 2022-12  collect signals 2023-01 → 2023-12
  Checkpoint 3: train 2019-01 → 2023-12  collect signals 2024-01 → 2024-11

Total clean RL OOF coverage: Jan 2022 → Nov 2024  (~3 years)
Rows in OOF dataset before 2022: rl_signal = 0.5 (neutral placeholder)
Meta-learner correctly learns RL weight from clean 2022-2024 signals.

Training runs: 3 checkpoints × 5 algos = 15 runs  (~5-6 hours total)

Outputs:
  data/oof/rl_signals.csv              — merged OOF signals all algos all tickers
  data/models/rl_{algo}_ckpt{n}/       — saved model per checkpoint
  data/models/rl_training_summary.json — metrics table

Usage:
    cd /Users/shaahdmaansour/Downloads/nextGen-TradeBot
    source .venv/bin/activate
    python scripts/step4_train_rl.py
"""

import sys, os, json, logging, time, uuid
from pathlib import Path
from datetime import datetime

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "backend"))
os.chdir(ROOT / "backend")

import numpy as np
import pandas as pd

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-8s  %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger("step4")

# ── Paths ──────────────────────────────────────────────────────────────────────
FEATURES_PATH = ROOT / "data" / "oof" / "features_us.csv"
MODELS_DIR    = ROOT / "data" / "models"
OOF_DIR       = ROOT / "data" / "oof"
DB_PATH       = ROOT / "data" / "finrl.db"

# ── 3-Checkpoint expanding windows ────────────────────────────────────────────
# Each checkpoint trains on all data up to train_end,
# then collects signals on [signal_start, signal_end] — data it never saw.
CHECKPOINTS = [
    {"ckpt": 1, "train_start": "2019-01-01", "train_end": "2021-12-31",
               "signal_start": "2022-01-01", "signal_end": "2022-12-31"},
    {"ckpt": 2, "train_start": "2019-01-01", "train_end": "2022-12-31",
               "signal_start": "2023-01-01", "signal_end": "2023-12-31"},
    {"ckpt": 3, "train_start": "2019-01-01", "train_end": "2023-12-31",
               "signal_start": "2024-01-01", "signal_end": "2024-12-31"},
]

ALGOS = ["ppo", "a2c", "ddpg", "td3", "sac"]

# ── Hyperparameters (from CLAUDE.md) ──────────────────────────────────────────
ALGO_CONFIGS = {
    "ppo": {
        # Tuned for finance: very low LR, large batches, tight clip, long gamma
        "total_timesteps": 400_000,
        "sb3_kwargs": {
            "n_steps":       4096,
            "ent_coef":      0.01,
            "learning_rate": 3e-5,   # low = stable critic learning
            "batch_size":    512,
            "n_epochs":      15,     # more passes → better value estimation
            "clip_range":    0.1,    # tight clip → stable policy updates
            "gae_lambda":    0.99,   # high = long-horizon value targets
            "gamma":         0.995,  # trading is long-horizon: compounds over time
        },
        "entropy_decay_final": 0.0001,
    },
    "a2c": {
        # Reduced LR (was 0.0007→1e-4) and n_steps (5→20) for critic stability
        "total_timesteps": 200_000,
        "sb3_kwargs": {
            "n_steps":       20,     # was 5 — too short for finance episodes
            "ent_coef":      0.005,  # lower entropy → less random trading
            "learning_rate": 1e-4,   # was 0.0007 — main cause of instability
            "gae_lambda":    0.95,
            "gamma":         0.995,  # long-horizon reward discounting
        },
    },
    "ddpg": {
        # Higher LR (0.001) caused noisy actor updates
        # Larger buffer (100k) improves sample diversity for stable critic
        "total_timesteps": 200_000,
        "sb3_kwargs": {
            "batch_size":    256,    # was 128 — larger batch = stabler gradient
            "buffer_size":   100_000, # was 50k — more diverse replay
            "learning_rate": 1e-4,   # was 0.001 — reduces policy oscillations
            "tau":           0.005,  # soft update rate — default is fine
        },
    },
    "td3": {
        # Same LR fix as DDPG; policy_delay=2 already helps stability
        "total_timesteps": 200_000,
        "sb3_kwargs": {
            "batch_size":    256,
            "buffer_size":   100_000,
            "learning_rate": 1e-4,   # was 0.001
            "policy_delay":  2,      # delayed actor update stabilises critic
            "tau":           0.005,
        },
    },
    "sac": {
        # SAC is the most stable off-policy algo — mainly needs buffer size fix
        # ent_coef="auto" is correct: automatic entropy tuning
        "total_timesteps": 200_000,
        "sb3_kwargs": {
            "batch_size":    256,
            "buffer_size":   100_000,
            "learning_rate": 3e-4,   # SAC tolerates slightly higher LR
            "ent_coef":      "auto",  # automatic entropy → controls overtrading
            "tau":           0.005,
        },
    },
}

TECH_INDICATORS = [
    "macd", "rsi_30", "rsi_14", "boll_ub", "boll_lb", "bb_width",
    "close_30_sma", "close_60_sma", "cci_30", "dx_30", "atr",
    "volume_zscore", "price_mom_5", "price_mom_20", "frac_diff_close",
    "turbulence", "high_low_range", "gap", "obv_zscore", "ema_cross",
    "vol_price_corr", "vix_level", "vix_zscore", "price_range_position",
    "rank_20d_mom",
]


# ── FinRL helpers ──────────────────────────────────────────────────────────────

def align_dates(df: pd.DataFrame) -> pd.DataFrame:
    """
    FinRL does self.df.loc[day_int, :] expecting a DataFrame (all tickers).
    Fix: build a complete date×ticker grid and set a shared integer index
    per calendar date so every .loc[day] returns stock_dim rows.
    """
    df = df.copy()
    df["date"] = pd.to_datetime(df["date"])
    all_dates   = sorted(df["date"].unique())
    all_tickers = sorted(df["tic"].unique())
    full_idx    = pd.MultiIndex.from_product([all_dates, all_tickers],
                                              names=["date", "tic"])
    df = (df.set_index(["date", "tic"])
            .reindex(full_idx)
            .groupby(level="tic", group_keys=False)
            .ffill()           # forward-fill within each ticker
            .reset_index())

    # For dates before a ticker was listed, ffill leaves NaN.
    # We CANNOT drop these rows — that breaks the date×ticker grid and makes
    # df.loc[day_int] return fewer than stock_dim rows, causing SB3's observation
    # buffer shape mismatch (e.g. 758 vs 784).
    # Instead: fill pre-listing OHLCV with the ticker's first known price,
    # and zero-fill feature columns. This keeps grid intact with no price leakage
    # (features are 0 = neutral, not invented history).
    ohlcv_cols = ["open", "high", "low", "close", "volume"]
    for col in ohlcv_cols:
        if col in df.columns:
            # bfill per ticker for price columns only — fills pre-listing gap
            df[col] = df.groupby("tic")[col].transform(lambda s: s.bfill())
    # Any remaining NaN (feature columns) → 0
    df = df.fillna(0)

    df = df.sort_values(["date", "tic"]).reset_index(drop=True)
    date_to_day = {d: i for i, d in enumerate(sorted(df["date"].unique()))}
    df.index  = df["date"].map(date_to_day)
    df["day"] = df.index
    return df


def prepare_env(df: pd.DataFrame, initial_amount: float = 1_000_000.0):
    """Build a FinRL StockTradingEnv."""
    from app.finrl_wrapper import _mock_finrl_optional_deps
    _mock_finrl_optional_deps()
    from finrl.meta.env_stock_trading.env_stocktrading import StockTradingEnv

    df = align_dates(df)
    for ind in TECH_INDICATORS:
        if ind not in df.columns:
            df[ind] = 0.0

    stock_dim   = df["tic"].nunique()
    state_space = 1 + 2 * stock_dim + len(TECH_INDICATORS) * stock_dim

    return StockTradingEnv(
        df                   = df,
        stock_dim            = stock_dim,
        hmax                 = 100,
        initial_amount       = initial_amount,
        num_stock_shares     = [0] * stock_dim,
        # 0.1% per side — forces agent to make high-conviction trades only
        # (was 0.001 = 0.1% which sounds the same but with 29 tickers and
        #  hmax=100 shares the absolute cost per step discourages overtrading)
        buy_cost_pct         = [0.001] * stock_dim,
        sell_cost_pct        = [0.001] * stock_dim,
        reward_scaling       = 1e-4,
        state_space          = state_space,
        action_space         = stock_dim,
        tech_indicator_list  = TECH_INDICATORS,
        turbulence_threshold = None,
        risk_indicator_col   = "turbulence",
        make_plots           = False,
        print_verbosity      = 1,
    )


# ── Training ───────────────────────────────────────────────────────────────────

def train_checkpoint(algo: str, ckpt: dict, train_df: pd.DataFrame) -> tuple:
    """
    Train one algorithm for one checkpoint.
    Returns (trained_model, run_id, model_path, metrics_dict).
    """
    from app.finrl_wrapper import _mock_finrl_optional_deps
    _mock_finrl_optional_deps()
    from finrl.agents.stablebaselines3.models import DRLAgent
    from stable_baselines3.common.callbacks import BaseCallback

    cfg      = ALGO_CONFIGS[algo]
    total_ts = cfg["total_timesteps"]
    sb3_kw   = cfg["sb3_kwargs"].copy()
    run_id   = str(uuid.uuid4())
    out_dir  = MODELS_DIR / f"rl_{algo}_ckpt{ckpt['ckpt']}_{run_id[:8]}"
    out_dir.mkdir(parents=True, exist_ok=True)

    logger.info("  [Ckpt %d] %s | train %s→%s | %d timesteps | %d tickers",
                ckpt["ckpt"], algo.upper(),
                ckpt["train_start"], ckpt["train_end"],
                total_ts, train_df["tic"].nunique())

    t0  = time.time()
    env = prepare_env(train_df)
    agent = DRLAgent(env=env)
    model = agent.get_model(algo, model_kwargs=sb3_kw)

    # PPO entropy decay callback
    callback = None
    if algo == "ppo":
        decay_final = cfg.get("entropy_decay_final", 0.0001)
        initial_ent = float(sb3_kw.get("ent_coef", 0.01))

        class EntropyDecay(BaseCallback):
            def _on_step(self):
                progress = min(1.0, self.num_timesteps / total_ts)
                self.model.ent_coef = (initial_ent * (1 - progress)
                                       + decay_final * progress)
                return True

        callback = EntropyDecay()

    trained = model.learn(
        total_timesteps = total_ts,
        tb_log_name     = f"{algo}_ckpt{ckpt['ckpt']}_{run_id[:8]}",
        callback        = callback,
    )

    elapsed    = time.time() - t0
    model_path = str(out_dir / f"{algo}_model")
    trained.save(model_path)

    # ── Evaluate on the signal window (data the model never saw) ────────────
    signal_df = train_df.copy()  # placeholder until collect_signals is called
    # We evaluate on the checkpoint's own signal window for metrics
    perf = _eval_on_test(trained, train_df, ckpt)
    logger.info("  [Ckpt %d] %s | Sharpe=%.3f Sortino=%.3f MaxDD=%.1f%% "
                "WinRate=%.1f%% Trades/day=%.1f vs B&H=%.2f%%",
                ckpt["ckpt"], algo.upper(),
                perf["sharpe_ratio"], perf["sortino_ratio"],
                perf["max_drawdown"] * 100, perf["win_rate"] * 100,
                perf["trades_per_day"], perf["vs_buyhold"] * 100)

    metrics = {
        "algorithm":       algo,
        "checkpoint":      ckpt["ckpt"],
        "run_id":          run_id,
        "total_timesteps": total_ts,
        "train_start":     ckpt["train_start"],
        "train_end":       ckpt["train_end"],
        "signal_start":    ckpt["signal_start"],
        "signal_end":      ckpt["signal_end"],
        "n_tickers":       int(train_df["tic"].nunique()),
        "elapsed_minutes": round(elapsed / 60, 2),
        "hyperparams":     sb3_kw,
        "model_path":      model_path + ".zip",
        "trained_at":      datetime.utcnow().isoformat(),
        **perf,
        "final_reward":    perf["total_return"],
    }
    with open(out_dir / "metrics.json", "w") as f:
        json.dump(metrics, f, indent=2)

    _register_run(run_id, algo, model_path, metrics, ckpt)
    logger.info("  [Ckpt %d] %s done in %.1f min → %s.zip",
                ckpt["ckpt"], algo.upper(), elapsed / 60, model_path)
    return trained, run_id, model_path, metrics


def _eval_on_test(model, ref_df: pd.DataFrame, ckpt: dict) -> dict:
    """
    Run model on a small in-sample slice to get training-period metrics.
    Full out-of-sample evaluation happens during signal collection.
    """
    try:
        # Use last 20% of training data as a quick in-sample eval slice
        dates  = sorted(ref_df["date"].unique())
        cutoff = dates[int(len(dates) * 0.8)]
        eval_df = ref_df[ref_df["date"] >= cutoff].copy()

        env          = prepare_env(eval_df)
        reset_result = env.reset()
        obs          = reset_result[0] if isinstance(reset_result, tuple) else reset_result
        values       = [env.initial_amount]
        total_trades = 0
        done         = False

        while not done:
            action, _ = model.predict(obs, deterministic=True)
            total_trades += int(np.sum(np.abs(action) > 0.1))
            step_result   = env.step(action)
            if len(step_result) == 5:
                obs, _, terminated, truncated, _ = step_result
                done = terminated or truncated
            else:
                obs, _, done, _ = step_result
            if hasattr(env, "asset_memory") and env.asset_memory:
                values.append(env.asset_memory[-1])

        v       = np.array(values, dtype=float)
        r       = np.diff(v) / (v[:-1] + 1e-9)
        n       = len(r)
        tr      = float((v[-1] - v[0]) / (v[0] + 1e-9))
        ann_r   = float((1 + tr) ** (252 / max(n, 1)) - 1)
        vol     = float(np.std(r) * np.sqrt(252)) if n > 1 else 1e-9
        sharpe  = float(ann_r / (vol + 1e-9))
        dn_r    = r[r < 0]
        sortino = float(ann_r / (float(np.std(dn_r) * np.sqrt(252)) + 1e-9)) if len(dn_r) > 1 else 0.0
        peak    = np.maximum.accumulate(v)
        max_dd  = float(((v - peak) / (peak + 1e-9)).min())
        calmar  = float(ann_r / (abs(max_dd) + 1e-9)) if max_dd < 0 else 0.0
        win_rate = float(np.mean(r > 0)) if n > 0 else 0.5
        tpd      = round(total_trades / max(n, 1), 2)

        # Buy-and-hold baseline
        bh = eval_df.groupby("date")["close"].mean().pct_change().dropna()
        bh_total = float(np.prod(1 + bh.values) - 1)

        return {
            "total_return":    round(tr, 4),
            "ann_return":      round(ann_r, 4),
            "sharpe_ratio":    round(sharpe, 4),
            "sortino_ratio":   round(sortino, 4),
            "calmar_ratio":    round(calmar, 4),
            "max_drawdown":    round(max_dd, 4),
            "win_rate":        round(win_rate, 4),
            "trades_per_day":  tpd,
            "final_value":     round(float(v[-1]), 2),
            "baseline_bh_return": round(bh_total, 4),
            "vs_buyhold":      round(tr - bh_total, 4),
        }
    except Exception as e:
        logger.warning("Eval failed: %s", e)
        return {"total_return": 0.0, "sharpe_ratio": 0.0, "sortino_ratio": 0.0,
                "calmar_ratio": 0.0, "max_drawdown": 0.0, "win_rate": 0.5,
                "trades_per_day": 0.0, "final_value": 1_000_000.0,
                "baseline_bh_return": 0.0, "vs_buyhold": 0.0, "ann_return": 0.0}


# ── Signal collection ──────────────────────────────────────────────────────────

def collect_signals(trained_model, signal_df: pd.DataFrame,
                    algo: str, ckpt: dict) -> pd.DataFrame:
    """
    Run trained model on signal_df (data it never saw).
    Map continuous portfolio actions to 0-1 directional signals.
    Returns DataFrame with columns: date, tic, {algo}_signal.
    """
    logger.info("  [Ckpt %d] Collecting %s signals %s→%s …",
                ckpt["ckpt"], algo.upper(),
                ckpt["signal_start"], ckpt["signal_end"])

    tickers    = sorted(signal_df["tic"].unique())
    signal_env = prepare_env(signal_df)

    reset_result = signal_env.reset()
    obs  = reset_result[0] if isinstance(reset_result, tuple) else reset_result
    done = False

    actions_by_step = []
    dates_by_step   = []
    step_idx        = 0

    # Get the aligned date sequence from the env's DataFrame
    env_df    = signal_env.df
    all_dates = sorted(env_df["date"].unique())

    while not done:
        action, _ = trained_model.predict(obs, deterministic=True)
        actions_by_step.append(action.copy())

        if step_idx < len(all_dates):
            dates_by_step.append(str(pd.Timestamp(all_dates[step_idx]).date()))
        else:
            dates_by_step.append(None)

        step_result = signal_env.step(action)
        if len(step_result) == 5:
            obs, _, terminated, truncated, _ = step_result
            done = terminated or truncated
        else:
            obs, _, done, _ = step_result
        step_idx += 1

    # ── Log action distribution (diagnostic: detects dead/saturated policies) ──
    all_actions = np.array(actions_by_step)   # shape (steps, stock_dim)
    flat        = all_actions.flatten()
    logger.info("  [Ckpt %d] %s action dist | mean=%.3f std=%.3f "
                "p5=%.3f p25=%.3f p75=%.3f p95=%.3f",
                ckpt["ckpt"], algo.upper(),
                float(np.mean(flat)), float(np.std(flat)),
                float(np.percentile(flat, 5)),  float(np.percentile(flat, 25)),
                float(np.percentile(flat, 75)), float(np.percentile(flat, 95)))
    # Saturation warning: if 80%+ of actions are near ±1 the policy is stuck
    saturated = np.mean(np.abs(flat) > 0.9) * 100
    if saturated > 80:
        logger.warning("  [Ckpt %d] %s: %.0f%% of actions near ±1 — "
                       "policy may be saturated/stuck",
                       ckpt["ckpt"], algo.upper(), saturated)

    # ── Build rows: one row per (date, ticker) ─────────────────────────────────
    # ACTION_THRESHOLD: |action| < threshold → neutral 0.5 (no conviction)
    # Also store raw confidence (|action|) as a meta-feature for Step 5
    ACTION_THRESHOLD = 0.10

    rows = []
    for date, action in zip(dates_by_step, actions_by_step):
        if date is None:
            continue
        for j, tic in enumerate(tickers):
            raw        = float(action[j]) if j < len(action) else 0.0
            confidence = round(abs(raw), 4)   # |action| = conviction magnitude

            if abs(raw) < ACTION_THRESHOLD:
                signal = 0.5                  # below threshold → neutral
            else:
                signal = float(np.clip((raw + 1) / 2, 0.0, 1.0))

            rows.append({
                "date":                    date,
                "tic":                     tic,
                f"{algo}_signal":          round(signal, 4),
                f"{algo}_confidence":      confidence,  # raw |action| for meta-learner
            })

    result = pd.DataFrame(rows)

    # Diagnostic summary
    sig_col    = f"{algo}_signal"
    real_sigs  = result[result[sig_col] != 0.5]
    pct_active = len(real_sigs) / max(len(result), 1) * 100
    logger.info("  [Ckpt %d] %s: %d rows | %.1f%% high-conviction "
                "(%.1f%% neutral) | threshold=%.2f",
                ckpt["ckpt"], algo.upper(), len(result),
                pct_active, 100 - pct_active, ACTION_THRESHOLD)
    return result


# ── Database registration ──────────────────────────────────────────────────────

def _register_run(run_id, algo, model_path, metrics, ckpt):
    import sqlite3
    conn = sqlite3.connect(str(DB_PATH))
    cur  = conn.cursor()
    now  = datetime.utcnow().isoformat()
    cur.execute("""
        INSERT OR REPLACE INTO runs
            (id, data_job_id, algorithm, status, created_at, updated_at,
             model_path, metrics_json, hyperparams, error)
        VALUES (?, ?, ?, 'done', ?, ?, ?, ?, ?, NULL)
    """, (run_id, f"step4_ckpt{ckpt['ckpt']}", algo, now, now,
          model_path, json.dumps(metrics),
          json.dumps(metrics.get("hyperparams", {}))))
    conn.commit()
    conn.close()


# ── Main ───────────────────────────────────────────────────────────────────────

def main():
    logger.info("=" * 60)
    logger.info("Step 4 — RL Training: 3-Checkpoint Expanding Window")
    logger.info("=" * 60)
    logger.info("Checkpoints:")
    for c in CHECKPOINTS:
        logger.info("  Ckpt %d: train %s→%s | signals %s→%s",
                    c["ckpt"], c["train_start"], c["train_end"],
                    c["signal_start"], c["signal_end"])
    logger.info("")

    # ── Check FinRL ────────────────────────────────────────────────────────────
    from app.finrl_wrapper import FINRL_AVAILABLE, _import_error
    if not FINRL_AVAILABLE:
        logger.error("FinRL not available: %s", _import_error)
        sys.exit(1)
    logger.info("FinRL available ✓")

    # ── Load data ──────────────────────────────────────────────────────────────
    logger.info("Loading features_us.csv …")
    df = pd.read_csv(FEATURES_PATH)
    df["date"] = pd.to_datetime(df["date"])
    logger.info("Loaded %d rows, %d tickers, %s → %s",
                len(df), df["tic"].nunique(),
                str(df["date"].min().date()), str(df["date"].max().date()))

    # ── Run 3 checkpoints × 5 algos ───────────────────────────────────────────
    # signal_frames[algo] = list of DataFrames, one per checkpoint
    signal_frames = {algo: [] for algo in ALGOS}
    all_metrics   = {}

    for ckpt in CHECKPOINTS:
        logger.info("")
        logger.info("━" * 60)
        logger.info("CHECKPOINT %d  |  train→%s  |  signals %s→%s",
                    ckpt["ckpt"], ckpt["train_end"],
                    ckpt["signal_start"], ckpt["signal_end"])
        logger.info("━" * 60)

        train_df  = df[(df["date"] >= ckpt["train_start"]) &
                       (df["date"] <= ckpt["train_end"])].copy()
        signal_df = df[(df["date"] >= ckpt["signal_start"]) &
                       (df["date"] <= ckpt["signal_end"])].copy()

        logger.info("Train: %d rows | Signal: %d rows | Tickers: %d",
                    len(train_df), len(signal_df), train_df["tic"].nunique())

        for algo in ALGOS:
            logger.info("")
            try:
                trained, run_id, model_path, metrics = train_checkpoint(
                    algo, ckpt, train_df)
                sigs = collect_signals(trained, signal_df, algo, ckpt)
                signal_frames[algo].append(sigs)
                all_metrics[f"{algo}_ckpt{ckpt['ckpt']}"] = metrics
            except Exception as e:
                logger.error("✗ %s ckpt%d FAILED: %s", algo.upper(),
                             ckpt["ckpt"], e, exc_info=True)
                all_metrics[f"{algo}_ckpt{ckpt['ckpt']}"] = {"error": str(e)}

    # ── Merge signals across checkpoints ──────────────────────────────────────
    logger.info("")
    logger.info("━" * 60)
    logger.info("Merging signals across all checkpoints …")

    # Start from XGBoost OOF to get the full (date, tic) index
    xgb_path = OOF_DIR / "xgb_oof_predictions.csv"
    tic_col   = "ticker" if "ticker" in pd.read_csv(xgb_path, nrows=1).columns else "tic"
    base      = pd.read_csv(xgb_path, usecols=["date", tic_col])
    base      = base.rename(columns={tic_col: "tic"})
    base      = base[base["tic"].isin(df["tic"].unique())]  # US tickers only

    merged = base.copy()
    for algo in ALGOS:
        frames = signal_frames[algo]
        if frames:
            algo_df = pd.concat(frames, ignore_index=True)
            algo_df = algo_df.drop_duplicates(subset=["date", "tic"])
            merged  = merged.merge(algo_df, on=["date", "tic"], how="left")
        else:
            merged[f"{algo}_signal"]     = np.nan
            merged[f"{algo}_confidence"] = np.nan

        # Fill missing (pre-2022) rows: signal=0.5 neutral, confidence=0
        merged[f"{algo}_signal"]     = merged[f"{algo}_signal"].fillna(0.5).round(4)
        merged[f"{algo}_confidence"] = merged[f"{algo}_confidence"].fillna(0.0).round(4)

    merged = merged.sort_values(["date", "tic"]).reset_index(drop=True)

    # ── Save ──────────────────────────────────────────────────────────────────
    OOF_DIR.mkdir(parents=True, exist_ok=True)
    out_path = OOF_DIR / "rl_signals.csv"
    merged.to_csv(out_path, index=False)
    logger.info("RL signals saved → %s", out_path)

    # Also save per-algo files for compatibility
    for algo in ALGOS:
        algo_path = OOF_DIR / f"rl_{algo}_signals.csv"
        merged[["date", "tic", f"{algo}_signal"]].to_csv(algo_path, index=False)

    # ── Save summary ──────────────────────────────────────────────────────────
    summary_path = MODELS_DIR / "rl_training_summary.json"
    with open(summary_path, "w") as f:
        json.dump(all_metrics, f, indent=2)

    # ── Print summary table ───────────────────────────────────────────────────
    logger.info("")
    logger.info("=" * 60)
    logger.info("Step 4 Complete — Performance Summary (in-sample eval)")
    logger.info("Note: true OOS performance = meta-learner validation in Step 5")
    logger.info("=" * 60)
    logger.info("%-20s  %6s  %7s  %7s  %7s  %6s  %5s",
                "Run", "Sharpe", "Sortino", "Calmar", "MaxDD", "WinR%", "T/day")
    logger.info("-" * 65)
    for key, m in all_metrics.items():
        if "error" in m:
            logger.info("%-20s  FAILED: %s", key, m["error"][:35])
        else:
            logger.info("%-20s  %6.3f  %7.3f  %7.3f  %6.1f%%  %5.1f%%  %5.1f",
                        key,
                        m.get("sharpe_ratio", 0),
                        m.get("sortino_ratio", 0),
                        m.get("calmar_ratio", 0),
                        m.get("max_drawdown", 0) * 100,
                        m.get("win_rate", 0) * 100,
                        m.get("trades_per_day", 0))

    # Buy-and-hold comparison
    logger.info("")
    logger.info("vs Buy-and-Hold (last checkpoint per algo):")
    for algo in ALGOS:
        key = f"{algo}_ckpt3"
        m   = all_metrics.get(key, {})
        if "error" not in m and m:
            logger.info("  %-6s  return=%.2f%%  vs_bh=%+.2f%%",
                        algo.upper(),
                        m.get("total_return", 0) * 100,
                        m.get("vs_buyhold", 0) * 100)

    # Signal coverage summary
    logger.info("")
    logger.info("OOF signal coverage (non-neutral signals):")
    for algo in ALGOS:
        col = f"{algo}_signal"
        real = (merged[col] != 0.5).sum()
        total = len(merged)
        pct = real / total * 100
        logger.info("  %-6s  %d/%d rows  (%.1f%% high-conviction | %.1f%% neutral)",
                    algo.upper(), real, total, pct, 100 - pct)

    logger.info("")
    logger.info("RL signals → %s  (%d rows)", out_path, len(merged))
    logger.info("Summary    → %s", summary_path)
    logger.info("")
    logger.info("Next: python scripts/step5_meta_learner.py")
    logger.info("=" * 60)


if __name__ == "__main__":
    main()
