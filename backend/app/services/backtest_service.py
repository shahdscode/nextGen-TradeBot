"""
Backtest service with full academic reality layers:
  1. Trading friction  — volatility-scaled slippage + commission
  2. Position limits   — max % capital per stock, cooldown days
  3. Benchmark baselines — Buy&Hold SP500, SMA 20/50, 12-1 Momentum, Equal-Weight, Random
  4. Extended metrics  — Sortino, Calmar, Profit Factor, trade-day frequency, Turnover
  5. Rolling walk-forward analysis — sliding 63-day windows, consistency stats
  6. Stress tests      — 2×costs, −30% crash, 1-day delay
  7. RL sanity checks  — overtrading, action distribution, turnover
  8. Overfitting report — train / validation / test degradation gaps
"""
from __future__ import annotations

import json
import hashlib
import logging
import numpy as np
import pandas as pd
from pathlib import Path
from typing import Dict, Any, List, Optional

logger = logging.getLogger(__name__)

from app.config import settings
from app import finrl_wrapper
from app.database import SessionLocal, Run
from app.services.trading_config import finrl_env_kwargs, transaction_costs_summary
from app.services.market_data_merge import overlay_yahoo_closes
from app.services.execution_model import (
    EXECUTION_HORIZON_DAYS,
    PARTICIPATION_CAP,
    almgren_chriss_slippage,
    cap_order_notional,
    model_documentation,
    rolling_adv_notional,
    urgency_multiplier,
)

FINRL_AVAILABLE = finrl_wrapper.FINRL_AVAILABLE

# ── Module-level constants ────────────────────────────────────────────────────

# Re-export for API notes (rules defined in execution_model.py)
_ADV_PARTICIPATION_CAP: float = PARTICIPATION_CAP

# All step-log JSONL rows carry this for schema-migration safety.
_LOG_SCHEMA_VERSION: int = 1

# Deterministic replay contract (enforced on write; documented in log header)
_STEP_LOG_REPLAY_RULES: Dict[str, Any] = {
    "ordering": "rows sorted by strictly increasing step; duplicate steps rejected on write",
    "anchors": "rows with _full:true contain prices + indicators — safe mid-stream entry points",
    "deltas": "non-_full rows omit prices; replay from nearest prior _full anchor only",
    "mid_stream_start": "consumers MUST begin at step 0 or the first _full row after header",
    "missing_steps": "gaps allowed; state at step t requires replay from last anchor ≤ t",
}


# ── FinRL prediction (Gym/SB3 API-compatible rollout) ─────────────────────────

def _finrl_predict(algorithm: str, model_path: str, env):
    """
    Deterministic rollout of a trained SB3 model through a FinRL StockTradingEnv.

    Replaces FinRL's DRLAgent.DRL_prediction_load_from_file(), which is broken
    against the installed gymnasium/SB3 version (it passes the (obs, info) reset
    tuple straight into model.predict()). We handle both the Gym 5-tuple step
    and the (obs, info) reset here.

    Returns (df_account_value, df_actions) using the env's own memory savers,
    so downstream _parse_trades / _write_finrl_step_log stay unchanged.
    """
    from stable_baselines3 import PPO, A2C, DDPG, TD3, SAC
    algo_map = {"ppo": PPO, "a2c": A2C, "ddpg": DDPG, "td3": TD3, "sac": SAC}
    cls = algo_map.get(algorithm.lower())
    if cls is None:
        raise ValueError(f"Unsupported RL algorithm for backtest: {algorithm}")

    model = cls.load(model_path)

    reset_out = env.reset()
    obs = reset_out[0] if isinstance(reset_out, tuple) else reset_out
    done = False
    while not done:
        action, _ = model.predict(obs, deterministic=True)
        step_out = env.step(action)
        if len(step_out) == 5:            # Gym API: obs, reward, terminated, truncated, info
            obs, _, terminated, truncated, _ = step_out
            done = bool(terminated or truncated)
        else:                              # legacy 4-tuple
            obs, _, done, _ = step_out

    return env.save_asset_memory(), env.save_action_memory()


# ── Effective price helpers ───────────────────────────────────────────────────

def _buy_price(price: float, commission: float, slippage: float) -> float:
    return price * (1.0 + commission + slippage)

def _sell_price(price: float, commission: float, slippage: float) -> float:
    return price * (1.0 - commission - slippage)


def _dynamic_slippage(
    base_slippage: float,
    recent_returns: List[float],
    participation_rate: float = 0.001,
    liquidity_factor: float = 1.0,
    urgency_mult: float = 1.0,
) -> float:
    """
    Almgren-Chriss with explicit horizon T (days): η·σ·√(Q/(V·T)).

    participation_rate = Q/V (order notional / ADV). See execution_model.py.
    """
    return almgren_chriss_slippage(
        base_slippage,
        recent_returns,
        participation_rate,
        liquidity_factor,
        EXECUTION_HORIZON_DAYS,
        urgency_mult,
    )


# ── Benchmark baselines ───────────────────────────────────────────────────────

def fetch_sp500_benchmark(
    start: str, end: str, initial_capital: float,
    commission_pct: float = 0.001, slippage_pct: float = 0.001,
) -> Dict[str, Any]:
    """Buy-and-hold S&P 500 with single entry/exit friction."""
    try:
        import yfinance as yf
        df = yf.download("^GSPC", start=start, end=end, progress=False, auto_adjust=True)
        if df.empty:
            return {}
        closes = df["Close"].values.flatten().tolist()
        dates  = df.index.strftime("%Y-%m-%d").tolist()
        if not closes:
            return {}
        eff_buy  = _buy_price(closes[0],  commission_pct, slippage_pct)
        eff_sell = _sell_price(closes[-1], commission_pct, slippage_pct)
        shares   = initial_capital / eff_buy
        account_values = [round(initial_capital, 2)]
        for c in closes[1:]:
            account_values.append(round(shares * c, 2))
        account_values[-1] = round(shares * eff_sell, 2)
        daily_returns = _compute_daily_returns(account_values)
        metrics = _compute_metrics(account_values, daily_returns, initial_capital)
        return {"account_value": account_values, "dates": dates, "metrics": metrics,
                "strategy": "buy_hold_sp500"}
    except Exception:
        return {}


def run_sma_crossover_baseline(
    start: str, end: str, initial_capital: float,
    commission_pct: float = 0.001, slippage_pct: float = 0.001,
) -> Dict[str, Any]:
    """SMA 20/50 crossover on S&P 500 — golden/death cross with friction."""
    try:
        import yfinance as yf
        df = yf.download("^GSPC", start=start, end=end, progress=False, auto_adjust=True)
        if df.empty or len(df) < 60:
            return {}
        closes = df["Close"].values.flatten()
        dates  = df.index.strftime("%Y-%m-%d").tolist()
        sma20  = pd.Series(closes).rolling(20).mean().values
        sma50  = pd.Series(closes).rolling(50).mean().values

        cash, shares, in_pos = float(initial_capital), 0.0, False
        account_values = [float(initial_capital)]

        for i in range(1, len(closes)):
            price = float(closes[i])
            if np.isnan(sma20[i]) or np.isnan(sma50[i]):
                account_values.append(round(cash + shares * price, 2))
                continue
            if not in_pos and sma20[i - 1] <= sma50[i - 1] and sma20[i] > sma50[i]:
                eff = _buy_price(price, commission_pct, slippage_pct)
                shares = cash / eff;  cash = 0.0;  in_pos = True
            elif in_pos and sma20[i - 1] >= sma50[i - 1] and sma20[i] < sma50[i]:
                eff = _sell_price(price, commission_pct, slippage_pct)
                cash = shares * eff;  shares = 0.0;  in_pos = False
            account_values.append(round(cash + shares * price, 2))

        daily_returns = _compute_daily_returns(account_values)
        metrics = _compute_metrics(account_values, daily_returns, initial_capital)
        return {"account_value": account_values, "dates": dates, "metrics": metrics,
                "strategy": "sma_crossover_20_50"}
    except Exception:
        return {}


def run_momentum_baseline(
    start: str, end: str, initial_capital: float,
    commission_pct: float = 0.001, slippage_pct: float = 0.001,
) -> Dict[str, Any]:
    """
    12-1 month time-series momentum on S&P 500.
    Signal = 12-month return minus most-recent 1-month return.
    Long if signal > 0, flat (cash) otherwise. Rebalance monthly (~21 days).
    Skipping the last month avoids the well-documented short-term reversal.
    """
    try:
        import yfinance as yf
        fetch_start = (pd.Timestamp(start) - pd.DateOffset(months=14)).strftime("%Y-%m-%d")
        df = yf.download("^GSPC", start=fetch_start, end=end, progress=False, auto_adjust=True)
        if df.empty or len(df) < 60:
            return {}
        closes = df["Close"].values.flatten()
        dates  = df.index.strftime("%Y-%m-%d").tolist()
        test_idx   = next((i for i, d in enumerate(dates) if d >= start), 0)

        cash, shares, in_pos = float(initial_capital), 0.0, False
        account_values = [float(initial_capital)]
        out_dates      = [dates[test_idx]]
        last_rebal     = test_idx - 999

        for i in range(test_idx + 1, len(closes)):
            price = float(closes[i])
            if (i - last_rebal) >= 21:
                signal = 0.0
                if i >= 252:
                    r12 = (float(closes[i - 21]) - float(closes[i - 252])) / max(float(closes[i - 252]), 1e-9)
                    r1  = (float(closes[i])       - float(closes[i - 21]))  / max(float(closes[i - 21]),  1e-9)
                    signal = r12 - r1
                if signal > 0 and not in_pos:
                    eff = _buy_price(price, commission_pct, slippage_pct)
                    shares = cash / eff;  cash = 0.0;  in_pos = True
                elif signal <= 0 and in_pos:
                    eff = _sell_price(price, commission_pct, slippage_pct)
                    cash = shares * eff;  shares = 0.0;  in_pos = False
                last_rebal = i
            account_values.append(round(cash + shares * price, 2))
            out_dates.append(dates[i])

        daily_returns = _compute_daily_returns(account_values)
        metrics = _compute_metrics(account_values, daily_returns, initial_capital)
        return {"account_value": account_values, "dates": out_dates, "metrics": metrics,
                "strategy": "momentum_12_1"}
    except Exception:
        return {}


def run_equal_weight_baseline(
    start: str, end: str, initial_capital: float,
    commission_pct: float = 0.001, slippage_pct: float = 0.001,
) -> Dict[str, Any]:
    """
    Monthly-rebalanced equal-weight portfolio of SPY, QQQ, IWM, GLD, TLT.
    Represents a passive diversified benchmark commonly used in academic papers.
    Rebalance cost: round-trip friction on the full portfolio value each month.
    """
    ETFS = ["SPY", "QQQ", "IWM", "GLD", "TLT"]
    try:
        import yfinance as yf
        raw = yf.download(ETFS, start=start, end=end, progress=False, auto_adjust=True)
        closes_raw = raw["Close"] if "Close" in raw else pd.DataFrame()
        if isinstance(closes_raw, pd.Series):
            closes_raw = closes_raw.to_frame()
        closes = closes_raw.dropna(how="all") if not closes_raw.empty else pd.DataFrame()
        if closes.empty or len(closes) < 10:
            return {}
        available = [t for t in ETFS if t in closes.columns]
        n_assets  = len(available)
        if n_assets == 0:
            return {}
        dates  = closes.index.strftime("%Y-%m-%d").tolist()
        n      = len(dates)
        weight = 1.0 / n_assets

        # Initial buy
        pv        = float(initial_capital)
        shares_ew: Dict[str, float] = {}
        for t in available:
            p = float(closes[t].iloc[0])
            if p > 0:
                eff = _buy_price(p, commission_pct, slippage_pct)
                shares_ew[t] = pv * weight / eff
        account_values = [float(initial_capital)]
        last_rebal = 0

        for i in range(1, n):
            total_val = sum(
                shares_ew.get(t, 0.0) * float(closes[t].iloc[i])
                for t in available
                if not pd.isna(closes[t].iloc[i])
            )
            # Monthly rebalance (~21 trading days)
            if (i - last_rebal) >= 21:
                rebal_cost = total_val * (commission_pct + slippage_pct) * 2
                total_val -= rebal_cost
                for t in available:
                    px = float(closes[t].iloc[i])
                    if px > 0 and not pd.isna(closes[t].iloc[i]):
                        eff = _buy_price(px, commission_pct, slippage_pct)
                        shares_ew[t] = total_val * weight / eff
                last_rebal = i
            account_values.append(round(total_val, 2))

        daily_returns = _compute_daily_returns(account_values)
        metrics = _compute_metrics(account_values, daily_returns, initial_capital)
        return {"account_value": account_values, "dates": dates, "metrics": metrics,
                "strategy": "equal_weight_etf"}
    except Exception:
        return {}


def run_random_baseline(
    start: str, end: str, initial_capital: float,
    commission_pct: float = 0.001, slippage_pct: float = 0.001,
    seed: int = 42,
    tickers: Optional[List[str]] = None,
    n_hold: int = 10,
    rebalance_days: int = 21,
) -> Dict[str, Any]:
    """
    Monthly-rebalanced random stock picker from the same universe as the RL agent.

    Previous version flipped SPY long/cash with 5% daily probability — in a bull
    market that stayed ~fully invested with occasional cash, inheriting index beta
    and sometimes beating the agent on Sharpe. This version is a true no-skill
    stock-selection bar: random equal-weight subset, same friction model.
    """
    from app.services.live_trading_service import LIVE_TICKERS, _download_live

    universe = sorted({t.strip().upper() for t in (tickers or LIVE_TICKERS) if t})
    if not universe:
        return {}
    rng = np.random.default_rng(seed)
    n_hold = max(1, min(n_hold, len(universe)))

    try:
        raw = _download_live(universe, start, end)
        raw["d"] = pd.to_datetime(raw["date"]).dt.strftime("%Y-%m-%d")
        pivot = raw.pivot(index="d", columns="tic", values="close").sort_index()
        if pivot.empty or len(pivot) < 10:
            return {}
        dates = pivot.index.tolist()
        available = [c for c in pivot.columns if pivot[c].notna().sum() >= 10]
        if len(available) < n_hold:
            return {}

        holdings: Dict[str, float] = {}
        cash = float(initial_capital)
        account_values = [float(initial_capital)]
        last_rebal = -rebalance_days

        for i, d in enumerate(dates):
            prices = {
                t: float(pivot.loc[d, t])
                for t in available
                if pd.notna(pivot.loc[d, t]) and float(pivot.loc[d, t]) > 0
            }
            pv = cash + sum(holdings.get(t, 0.0) * prices.get(t, 0.0) for t in holdings)

            if i == 0 or (i - last_rebal) >= rebalance_days:
                # Liquidate
                for t, sh in list(holdings.items()):
                    px = prices.get(t, 0.0)
                    if px > 0 and sh > 0:
                        cash += sh * _sell_price(px, commission_pct, slippage_pct)
                holdings = {}

                pick = list(rng.choice(available, size=n_hold, replace=False))
                pv = cash
                friction = pv * (commission_pct + slippage_pct) * 2
                investable = max(0.0, pv - friction)
                cash = 0.0
                w = investable / n_hold
                for t in pick:
                    px = prices.get(t, 0.0)
                    if px > 0:
                        eff = _buy_price(px, commission_pct, slippage_pct)
                        holdings[t] = w / eff
                last_rebal = i
                pv = cash + sum(holdings.get(t, 0.0) * prices.get(t, 0.0) for t in holdings)

            account_values.append(round(pv, 2))

        daily_returns = _compute_daily_returns(account_values)
        metrics = _compute_metrics(account_values, daily_returns, initial_capital)
        return {
            "account_value": account_values,
            "dates": dates,
            "metrics": metrics,
            "strategy": "random_portfolio_equal_weight",
            "note": (
                f"No-skill baseline: each month pick {n_hold} random stocks from the "
                f"same {len(available)}-name universe, equal-weight, with identical "
                f"commission + slippage. Not SPY market-timing (which inherits index beta)."
            ),
        }
    except Exception:
        return {}


def _rl_holdings_timeseries(featured, algo, model_path, initial_cash):
    """Run an RL model over the window once; return {date_str: {tic: holding}}."""
    from app.services.live_trading_service import _make_env
    from stable_baselines3 import PPO, A2C, DDPG, TD3, SAC
    cls = {"ppo": PPO, "a2c": A2C, "ddpg": DDPG, "td3": TD3, "sac": SAC}[algo]
    env, tics, stock_dim = _make_env(featured, initial_cash)
    model = cls.load(model_path)
    reset_out = env.reset()
    obs = reset_out[0] if isinstance(reset_out, tuple) else reset_out
    out, done = {}, False
    while not done:
        action, _ = model.predict(obs, deterministic=True)
        step = env.step(action)
        if len(step) == 5:
            obs, _, term, trunc, _ = step; done = term or trunc
        else:
            obs, _, done, _ = step
        st = np.asarray(env.state, dtype=float)
        hold = st[1 + stock_dim: 1 + 2 * stock_dim]
        d = str(env.date_memory[-1]) if getattr(env, "date_memory", None) else None
        if d:
            out[d[:10]] = {tics[i]: float(hold[i]) for i in range(stock_dim)}
    return out, tics


def run_meta_backtest(backtest_id, run, test_start, test_end,
                      initial_capital=1_000_000.0, commission_pct=0.001,
                      slippage_pct=0.001, tickers=None) -> Dict[str, Any]:
    """
    Real backtest of the meta-learner ensemble.

    Builds the 7 base signals + regime + VIX per (day, stock) across the window,
    runs the meta-learner per row, then simulates a long-only portfolio that
    rebalances weekly to weights ∝ meta-probability among BUY stocks (p>0.5),
    with the same friction model. Reuses all baseline / walk-forward / stress /
    significance machinery so the result matches the standard backtest shape.
    """
    import pickle
    from app.services.feature_service import FEATURE_COLUMNS, download_vix
    from app.services.live_trading_service import _download_live, _build_featured, LIVE_TICKERS
    from app.services.meta_learner_service import predict_meta_learner

    results_dir = Path(settings.results_dir) / backtest_id
    results_dir.mkdir(parents=True, exist_ok=True)
    deploy = Path(settings.models_dir) / "deploy"
    meta_path = str(Path(settings.models_dir) / "meta_learner.pkl")

    if not (deploy / "xgb_deploy.pkl").exists() or not Path(meta_path).exists():
        raise ValueError("Meta backtest needs deployable base models + meta_learner.pkl "
                         "(run scripts/train_deployable_models.py and Step 5).")

    # ── Featured data for window + warmup ─────────────────────────────────────
    warmup_start = (pd.Timestamp(test_start) - pd.Timedelta(days=400)).strftime("%Y-%m-%d")
    raw   = _download_live(LIVE_TICKERS, warmup_start, test_end)
    vixdf = download_vix(warmup_start, test_end)
    featured = _build_featured(raw, vixdf)
    featured["date"] = pd.to_datetime(featured["date"])
    win = featured[(featured["date"] >= test_start) & (featured["date"] <= test_end)].copy()
    if win.empty:
        raise ValueError(f"No data for meta backtest window {test_start}…{test_end}")
    win["d"] = win["date"].dt.strftime("%Y-%m-%d")
    # Optional ticker subset
    if tickers:
        want = {t.strip().upper() for t in tickers}
        win = win[win["tic"].str.upper().isin(want)].copy()
        if win.empty:
            raise ValueError(f"None of the requested tickers {sorted(want)} are in the universe")
    dates = sorted(win["d"].unique())
    tics  = sorted(win["tic"].unique())

    # ── XGBoost + LSTM (deployable, pooled) ───────────────────────────────────
    with open(deploy / "xgb_deploy.pkl", "rb") as f:
        xb = pickle.load(f); xgb_model, xgb_feats = xb["model"], xb["features"]
    win_xgb = dict(zip(zip(win["d"], win["tic"]),
                       xgb_model.predict_proba(win[xgb_feats].values.astype(np.float32))[:, 1]))

    import torch, torch.nn as nn, pickle as pkl
    ck = torch.load(deploy / "lstm_deploy.pt"); seq_len = ck["seq_len"]; lf = ck["features"]
    with open(deploy / "lstm_scaler.pkl", "rb") as f:
        lstm_scaler = pkl.load(f)
    class _L(nn.Module):
        def __init__(s, n):
            super().__init__(); s.lstm = nn.LSTM(n, 64, 2, batch_first=True, dropout=0.3)
            s.fc = nn.Linear(64, 1); s.sig = nn.Sigmoid()
        def forward(s, x):
            o, _ = s.lstm(x); return s.sig(s.fc(o[:, -1, :]))
    lstm_model = _L(ck["n_features"]); lstm_model.load_state_dict(ck["state_dict"]); lstm_model.eval()
    lstm_sig = {}
    fe = featured.sort_values(["tic", "date"])
    for tic in tics:
        g = fe[fe["tic"] == tic]
        Xs = lstm_scaler.transform(g[lf].values.astype(np.float32))
        ds = g["date"].dt.strftime("%Y-%m-%d").tolist()
        with torch.no_grad():
            for i in range(seq_len - 1, len(Xs)):
                if ds[i] in set(dates):
                    seq = torch.tensor(Xs[i - seq_len + 1:i + 1]).unsqueeze(0)
                    lstm_sig[(ds[i], tic)] = float(lstm_model(seq).item())

    # ── 5 RL models → per-day holdings → per-stock signals ───────────────────
    db = SessionLocal()
    rl_sig = {}
    for a in ["ppo", "a2c", "ddpg", "td3", "sac"]:
        r = (db.query(Run).filter(Run.algorithm == a, Run.data_job_id == "step4_ckpt3").first()
             or db.query(Run).filter(Run.algorithm == a, Run.status == "done").first())
        if not r or not (r.model_path and Path(str(r.model_path) + ".zip").exists()):
            continue
        try:
            holds, _ = _rl_holdings_timeseries(featured, a, r.model_path, initial_capital)
            for d, hv in holds.items():
                mx = max(hv.values()) if hv else 0
                for t in tics:
                    rl_sig[(a, d, t)] = (0.5 + 0.5 * hv.get(t, 0) / mx) if mx > 0 else 0.5
        except Exception as exc:
            logger.warning("meta backtest RL %s failed: %s", a, exc)
    db.close()

    # ── Regime + VIX ──────────────────────────────────────────────────────────
    mkt = featured.groupby("date")["price_mom_20"].mean()
    thr = float(mkt.std() * 0.5)
    regime = {pd.Timestamp(d).strftime("%Y-%m-%d"): (int(v > thr), int(v < -thr))
              for d, v in mkt.items()}
    vix = dict(zip(zip(win["d"], win["tic"]), win["vix_zscore"].astype(float)))
    close = dict(zip(zip(win["d"], win["tic"]), win["close"].astype(float)))

    # ── Meta-learner probability per (day, stock) ─────────────────────────────
    prob = {}
    for d in dates:
        rb, rbear = regime.get(d, (0, 0))
        for t in tics:
            fd = {
                "xgb_signal": win_xgb.get((d, t), 0.5), "lstm_signal": lstm_sig.get((d, t), 0.5),
                "ppo_signal": rl_sig.get(("ppo", d, t), 0.5), "a2c_signal": rl_sig.get(("a2c", d, t), 0.5),
                "ddpg_signal": rl_sig.get(("ddpg", d, t), 0.5), "td3_signal": rl_sig.get(("td3", d, t), 0.5),
                "sac_signal": rl_sig.get(("sac", d, t), 0.5), "regime_bull": rb, "regime_bear": rbear,
                "sentiment_score": 0.0, "vix_zscore": vix.get((d, t), 0.0),
            }
            prob[(d, t)] = float(predict_meta_learner(meta_path, fd)["probability"])

    # ── Simulate long-only, weekly rebalance ∝ prob among BUYs (p>0.5) ───────
    cash = float(initial_capital); shares = {t: 0.0 for t in tics}
    account_values, trades = [], []
    for i, d in enumerate(dates):
        px = {t: close.get((d, t), 0.0) for t in tics}
        pv = cash + sum(shares[t] * px[t] for t in tics if px[t] > 0)
        if i % 5 == 0:   # weekly rebalance
            buys = {t: prob[(d, t)] for t in tics if prob.get((d, t), 0) > 0.5 and px[t] > 0}
            wsum = sum(buys.values())
            for t in tics:
                if px[t] <= 0:
                    continue
                tgt_val = pv * (buys.get(t, 0.0) / wsum) if wsum > 0 else 0.0
                cur_val = shares[t] * px[t]
                delta_val = tgt_val - cur_val
                if abs(delta_val) < pv * 0.01:   # ignore tiny rebalances
                    continue
                dshares = delta_val / px[t]
                if dshares > 0:
                    eff = _buy_price(px[t], commission_pct, slippage_pct)
                    cost = dshares * eff
                    if cost <= cash:
                        cash -= cost; shares[t] += dshares
                        trades.append({"date": d, "ticker": t, "action": "buy",
                                       "shares": round(dshares, 4), "price": round(px[t], 2),
                                       "effective_price": round(eff, 4),
                                       "technical_score": round(prob.get((d, t), 0.5), 4)})
                else:
                    eff = _sell_price(px[t], commission_pct, slippage_pct)
                    cash += -dshares * eff; shares[t] += dshares
                    trades.append({"date": d, "ticker": t, "action": "sell",
                                   "shares": round(-dshares, 4), "price": round(px[t], 2),
                                   "effective_price": round(eff, 4)})
        account_values.append(round(cash + sum(shares[t] * px[t] for t in tics if px[t] > 0), 2))

    # ── Metrics + full report (reuse standard machinery) ─────────────────────
    daily_returns = _compute_daily_returns(account_values)
    metrics = _compute_metrics(account_values, daily_returns, initial_capital, trades)
    seed = int(hashlib.sha256(run.id.encode()).hexdigest()[:8], 16)
    benchmark = fetch_sp500_benchmark(test_start, test_end, initial_capital, commission_pct, slippage_pct)
    result = {
        "initial_capital": initial_capital,
        "account_value":   account_values,
        "daily_return":    [round(r, 6) for r in daily_returns],
        "dates":           dates,
        "metrics":         metrics,
        "trades":          trades,
        "benchmark":       benchmark,
        "baselines": {
            "buy_hold":      benchmark,
            "sma_crossover": run_sma_crossover_baseline(test_start, test_end, initial_capital, commission_pct, slippage_pct),
            "momentum":      run_momentum_baseline(test_start, test_end, initial_capital, commission_pct, slippage_pct),
            "equal_weight":  run_equal_weight_baseline(test_start, test_end, initial_capital, commission_pct, slippage_pct),
            "random":        run_random_baseline(test_start, test_end, initial_capital, commission_pct, slippage_pct, seed),
        },
        "walk_forward_periods": _walk_forward_rolling(account_values, dates, initial_capital)["windows"],
        "walk_forward_summary": _walk_forward_rolling(account_values, dates, initial_capital)["summary"],
        "stress_tests":    _run_stress_scenarios(account_values, dates, initial_capital, commission_pct, slippage_pct, seed),
        "rl_sanity":       _rl_sanity_checks(trades, account_values, dates),
        "regime_analysis": _regime_analysis(daily_returns, dates, trades),
        "fundamental_attribution": build_fundamental_attribution(
            trades, test_start=test_start, test_end=test_end, signal_map=prob,
        ),
        "data_source":     "meta_learner_ensemble",
        "data_quality":    {"live_prices": True,
                            "message": f"Meta-learner ensemble — 7 base signals per stock, "
                                       f"weekly rebalance, fresh Yahoo data {warmup_start}→{test_end}.",
                            "issues": []},
        "transaction_costs": {"commission_pct": commission_pct, "slippage_pct": slippage_pct,
                              "note": "Long-only, weekly rebalance to weights ∝ meta-probability among BUY stocks."},
        "methodology_notes": {"model": "Meta-learner stacking ensemble (7 base models + regime + VIX)",
                              "allocation": "Long-only, weekly rebalance ∝ calibrated meta-probability (p>0.5)."},
    }
    metrics.update(_distribution_stats(daily_returns))
    with open(results_dir / "result.json", "w") as f:
        json.dump(result, f)
    return result


# ── Main backtest entry point ─────────────────────────────────────────────────

def run_backtest(
    backtest_id: str,
    run_id: str,
    test_start: str,
    test_end: str,
    initial_capital: float = 1_000_000.0,
    commission_pct: float  = 0.001,
    slippage_pct: float    = 0.001,
    max_position_pct: float = 0.20,
    cooldown_days: int = 5,
    tickers: Optional[List[str]] = None,
) -> Dict[str, Any]:
    """
    Run backtest with all academic reality layers.
    Returns equity curve, extended metrics, 5 baselines, rolling walk-forward,
    3 stress tests, RL sanity checks, and overfitting report.

    tickers: optional subset to backtest. Honored by the meta-learner path; RL
    models are dimension-locked to their training universe so the subset is
    ignored for them (the full universe is used).
    """
    db  = SessionLocal()
    run = db.query(Run).filter(Run.id == run_id).first()
    db.close()
    if not run:
        raise ValueError(f"Run {run_id} not found")

    # Meta-learner is a stacking model (.pkl), not a FinRL portfolio policy (.zip).
    # Route it to a dedicated backtest that simulates the ensemble allocation,
    # instead of silently falling back to the synthetic engine.
    if (run.algorithm or "").lower() == "meta_learner":
        return run_meta_backtest(backtest_id, run, test_start, test_end,
                                 initial_capital, commission_pct, slippage_pct,
                                 tickers=tickers)
    if tickers:
        logger.info("Ticker subset %s ignored for RL run %s (dimension-locked to "
                    "training universe)", tickers, run_id)

    data_path   = Path(settings.data_dir) / run.data_job_id / "data.csv"
    model_path  = run.model_path
    algorithm   = run.algorithm
    results_dir = Path(settings.results_dir) / backtest_id
    results_dir.mkdir(parents=True, exist_ok=True)

    trades: List[Dict] = []
    use_synthetic = False
    use_synthetic_reason: Optional[str] = None
    data_source   = "unknown"
    data_quality: Dict = {}

    step_log_path = str(results_dir / "step_log.jsonl")

    # Step-4 models were trained with the 25-feature matrix (features_us.csv),
    # NOT the 37-feature alpha pipeline. Detect them so we build a matching env.
    is_step4 = (run.data_job_id or "").startswith("step4")

    # ── Try real FinRL model ──────────────────────────────────────────────────
    if FINRL_AVAILABLE and model_path and Path(str(model_path) + ".zip").exists():
        try:
            from finrl.meta.preprocessor.preprocessors import data_split
            from finrl.meta.env_stock_trading.env_stocktrading import StockTradingEnv
            from finrl.agents.stablebaselines3.models import DRLAgent

            if is_step4:
                # ── Step-4 path: 25 raw features from the OOF feature matrix ──
                from app.services.feature_service import FEATURE_COLUMNS
                tech_indicators = list(FEATURE_COLUMNS)  # 25 features, single source of truth

                features_file = Path(settings.oof_dir) / "features_us.csv"
                if not features_file.exists():
                    raise FileNotFoundError(
                        f"Step-4 feature matrix not found at {features_file}. "
                        "Run scripts/step1_data_features.py first."
                    )
                df = pd.read_csv(features_file)
                test_df = data_split(df, test_start, test_end)
                overlay_msg = "Step-4 model — 25-feature matrix (cached features_us.csv)."
                # The static feature file ends at its last build date. If the test
                # window isn't fully covered (e.g. backtesting 2025 when the file
                # ends 2024), download FRESH OHLCV for the window + 400d warmup and
                # rebuild features so the REAL model runs on any window.
                file_end = pd.to_datetime(df["date"]).max() if not df.empty else None
                need_fresh = (
                    test_df.empty
                    or file_end is None
                    or file_end < pd.Timestamp(test_end) - pd.Timedelta(days=3)
                )
                if need_fresh:
                    from app.services.live_trading_service import (
                        _download_live, _build_featured, LIVE_TICKERS)
                    from app.services.feature_service import download_vix
                    warmup_start = (pd.Timestamp(test_start) - pd.Timedelta(days=400)).strftime("%Y-%m-%d")
                    raw = _download_live(LIVE_TICKERS, warmup_start, test_end)
                    vixdf = download_vix(warmup_start, test_end)
                    fresh = _build_featured(raw, vixdf)
                    # Match cached-CSV format: string dates (avoid Timestamp in JSON)
                    fresh["date"] = pd.to_datetime(fresh["date"]).dt.strftime("%Y-%m-%d")
                    test_df = data_split(fresh, test_start, test_end)
                    overlay_msg = (f"Step-4 model — features rebuilt from fresh Yahoo "
                                   f"download ({warmup_start}→{test_end}).")
                if test_df.empty:
                    raise ValueError(
                        f"No data available for {test_start}…{test_end} even after fresh "
                        "download. Check the test window (markets open? future dates?).")
                for ind in tech_indicators:
                    if ind not in test_df.columns:
                        test_df[ind] = 0.0
                overlay_info = {
                    "live_prices": True, "overlay": "features",
                    "message": overlay_msg, "issues": [],
                }
            else:
                # ── Legacy path: 37-feature alpha pipeline from a data job ────
                from app.services.rl_features import build_alpha_state_pipeline

                df      = pd.read_csv(data_path)
                test_df = data_split(df, test_start, test_end)
                tech_indicators = finrl_wrapper.get_indicators(include_rl_extras=True)
                test_df, overlay_info = overlay_yahoo_closes(
                    test_df, test_start, test_end, tech_indicators
                )
                run_meta = run.metrics_json or {}
                alpha_in = run_meta.get("alpha_inputs") or {}
                test_df = build_alpha_state_pipeline(
                    test_df,
                    xgb_run_id=alpha_in.get("xgb_run_id"),
                    lstm_run_id=alpha_in.get("lstm_run_id"),
                    data_job_id=run.data_job_id,
                )
                for ind in tech_indicators:
                    if ind not in test_df.columns:
                        test_df[ind] = 0.0

            tickers     = sorted(test_df["tic"].unique().tolist())
            stock_dim   = len(tickers)
            state_space = 1 + 2 * stock_dim + len(tech_indicators) * stock_dim

            env_kwargs = finrl_env_kwargs(stock_dim, state_space, tech_indicators, initial_capital)
            env_kwargs["buy_cost_pct"]  = [commission_pct + slippage_pct] * stock_dim
            env_kwargs["sell_cost_pct"] = [commission_pct + slippage_pct] * stock_dim

            e_test = StockTradingEnv(df=test_df, **env_kwargs)
            if not hasattr(e_test, "initial_total_asset"):
                e_test.initial_total_asset = initial_capital

            df_account_value, df_actions = _finrl_predict(algorithm, model_path, e_test)
            account_values = df_account_value["account_value"].tolist()
            dates  = df_account_value["date"].tolist() if "date" in df_account_value else []
            trades = _parse_trades(df_actions, test_df, tickers, dates)
            data_source  = "finrl_model"
            data_quality = {
                "live_prices": overlay_info.get("live_prices", False),
                "overlay":     overlay_info.get("overlay"),
                "message":     overlay_info.get("message", ""),
                "issues":      overlay_info.get("issues", []),
            }
            # Write FinRL step log reconstructed from account_value + actions frames
            _write_finrl_step_log(
                df_account_value, df_actions, tickers, tech_indicators,
                test_df, step_log_path,
            )
        except Exception as exc:
            import traceback
            use_synthetic = True
            use_synthetic_reason = f"{type(exc).__name__}: {exc}"
            logger.warning("Real FinRL backtest failed, falling back to synthetic: %s",
                           use_synthetic_reason)
            logger.debug("Backtest traceback:\n%s", traceback.format_exc())

    # ── Synthetic backtest with friction + constraints ────────────────────────
    if (not FINRL_AVAILABLE) or use_synthetic or \
       not (model_path and Path(str(model_path) + ".zip").exists()):

        account_values, trades, dates = _generate_synthetic_portfolio(
            run_id=run_id,
            test_start=test_start,
            test_end=test_end,
            initial_capital=initial_capital,
            commission_pct=commission_pct,
            slippage_pct=slippage_pct,
            max_position_pct=max_position_pct,
            cooldown_days=cooldown_days,
            step_log_path=step_log_path,
        )
        data_source  = "synthetic_backtest"
        _issues = ["Synthetic portfolio engine — friction & position limits applied."]
        if use_synthetic_reason:
            _issues.append(f"Real model backtest failed: {use_synthetic_reason}")
        data_quality = {
            "live_prices": False,
            "issues": _issues,
            "message": (
                f"Fell back to synthetic — real model could not run ({use_synthetic_reason})."
                if use_synthetic_reason else
                "Re-train with Yahoo data for real model results."
            ),
        }

    trades = _enrich_trades_with_yahoo_prices(trades, test_start, test_end)

    # ── Core metrics ─────────────────────────────────────────────────────────
    daily_returns = _compute_daily_returns(account_values)
    metrics       = _compute_metrics(account_values, daily_returns, initial_capital, trades)

    # ── Baselines (5 strategies) ─────────────────────────────────────────────
    seed          = int(hashlib.sha256(run_id.encode()).hexdigest()[:8], 16)
    benchmark     = fetch_sp500_benchmark(test_start, test_end, initial_capital, commission_pct, slippage_pct)
    sma_base      = run_sma_crossover_baseline(test_start, test_end, initial_capital, commission_pct, slippage_pct)
    momentum_base = run_momentum_baseline(test_start, test_end, initial_capital, commission_pct, slippage_pct)
    eq_weight_base = run_equal_weight_baseline(test_start, test_end, initial_capital, commission_pct, slippage_pct)
    rand_base     = run_random_baseline(
        test_start, test_end, initial_capital, commission_pct, slippage_pct, seed,
        tickers=tickers,
    )

    # ── Rolling walk-forward analysis ────────────────────────────────────────
    walk_forward = _walk_forward_rolling(account_values, dates, initial_capital)

    # ── Stress tests ─────────────────────────────────────────────────────────
    stress_results = _run_stress_scenarios(
        account_values, dates, initial_capital, commission_pct, slippage_pct, seed
    )

    # ── RL sanity checks ─────────────────────────────────────────────────────
    sanity = _rl_sanity_checks(trades, account_values, dates)

    # ── Overfitting report ───────────────────────────────────────────────────
    # Tag the engine so the report evaluates val/train with the SAME engine.
    metrics["_data_source"] = data_source
    overfitting_report = _build_overfitting_report(
        run, metrics, test_start, test_end, initial_capital, commission_pct, slippage_pct
    )
    metrics.pop("_data_source", None)   # internal flag, not for output

    # ── Distribution stats + bootstrap CI ───────────────────────────────────
    # Done after baselines so these heavier stats don't slow sub-period loops
    metrics.update(_distribution_stats(daily_returns))
    metrics.update(_compute_benchmark_relative_metrics(daily_returns, dates, benchmark, metrics))

    # ── Regime analysis ──────────────────────────────────────────────────────
    regime_analysis = _regime_analysis(daily_returns, dates, trades)

    # ── Statistical significance vs baselines (Diebold-Mariano) ─────────────
    significance_tests = _significance_tests(daily_returns, {
        "buy_hold":      benchmark,
        "sma_crossover": sma_base,
        "momentum":      momentum_base,
        "equal_weight":  eq_weight_base,
    })

    friction_summary = {
        "commission_pct":      commission_pct,
        "slippage_pct":        slippage_pct,
        "slippage_model":      f"Almgren-Chriss: base + η×σ×√(Q/(V·T)), T={EXECUTION_HORIZON_DAYS}d; urgency premium on partial fills",
        "execution_model_doc": model_documentation(),
        "total_round_trip_pct": round((commission_pct + slippage_pct) * 2 * 100, 3),
        "max_position_pct":    max_position_pct,
        "cooldown_days":       cooldown_days,
        "cooldown_note": (
            f"cooldown_days={cooldown_days} and max_position_pct constrain the SYNTHETIC "
            "baseline engine and shape the RL training reward (turnover penalty). They are "
            "NOT applied as a post-hoc filter to a trained RL agent's executed actions — the "
            "agent may rebalance the same ticker on consecutive days. Per-trade rows reflect "
            "the agent's raw allocation changes, so consecutive same-ticker trades are expected "
            "and do not violate a hard cooldown (there is none on the live policy)."
        ),
        "note": (
            f"Base friction: +{commission_pct*100:.2f}% commission per leg. "
            f"Slippage: Almgren-Chriss sqrt model — base {slippage_pct*100:.2f}% "
            f"+ 0.14×σ×√(Q/(V·T)), T={EXECUTION_HORIZON_DAYS} day. "
            f"Rolling {20}D ADV; per-ticker per-day per-side cumulative cap {_ADV_PARTICIPATION_CAP*100:.0f}% ADV. "
            f"Partial fills widen slippage (urgency premium). 1-bar execution delay."
        ),
    }

    result = {
        "initial_capital":       initial_capital,
        "account_value":         [round(v, 2) for v in account_values],
        "daily_return":          [round(r, 6) for r in daily_returns],
        "dates":                 dates,
        "metrics":               metrics,
        "trades":                trades,
        "benchmark":             benchmark,
        "baselines": {
            "buy_hold":      benchmark,
            "sma_crossover": sma_base,
            "momentum":      momentum_base,
            "equal_weight":  eq_weight_base,
            "random":        rand_base,
        },
        # Walk-forward: flat list for backward compat + summary dict
        "walk_forward_periods":  walk_forward["windows"],
        "walk_forward_summary":  walk_forward["summary"],
        "stress_tests":          stress_results,
        "rl_sanity":             sanity,
        "overfitting_report":    overfitting_report,
        "regime_analysis":       regime_analysis,
        "significance_tests":    significance_tests,
        "fundamental_attribution": build_fundamental_attribution(
            trades, test_start=test_start, test_end=test_end,
        ),
        "methodology_notes": {
            "slippage_model":        f"Almgren-Chriss: slip = base + η×σ×√(Q/(V·T)), T={EXECUTION_HORIZON_DAYS}d, η=0.14. Rolling ADV; urgency premium when partial.",
            "execution_model":       "1-bar delay: signal at close(T), fill at close(T+1). Participation: per asset, per calendar day, per side (buy/sell), cumulative ADV cap.",
            "fill_model":            f"Partial fills when order or cumulative daily notional exceeds {_ADV_PARTICIPATION_CAP*100:.0f}% rolling ADV. Slippage scales with unfilled fraction.",
            "walk_forward_type":     "segmented evaluation — agent weights are fixed (not retrained per window)",
            "fill_assumption":       "Partial fills + coupled slippage; see execution_model_doc in transaction_costs",
            "baseline_friction":     "all baselines use same commission rate + static base slippage",
            "bootstrap_resamples":   1000,
            "ci_level":              0.95,
            "dm_test":               "Diebold-Mariano with Newey-West HAC SE (lags=floor(n^(1/3)))",
            "regime_window":         "20-day rolling vol + trend; independent tags incl. VIX z>1 & earnings calendar",
        },
        "data_source":           data_source,
        "data_quality":          data_quality,
        "transaction_costs":     friction_summary,
        "price_note": (
            "Effective prices use Almgren-Chriss square-root impact model. "
            "Buy: exec_price × (1 + commission + slip). "
            "Sell: exec_price × (1 − commission − slip). "
            f"Slip = base + 0.14×σ×√(Q/(V·T)), T={EXECUTION_HORIZON_DAYS}d; partial fills add urgency premium. "
            "Signals at close(T); execute close(T+1). Per-ticker daily cumulative ADV cap per side."
        ),
        "step_log_summary":      _build_step_log_summary(step_log_path, trades, dates),
    }

    with open(results_dir / "result.json", "w") as f:
        json.dump(result, f)

    return result


# ── Step logging helpers ──────────────────────────────────────────────────────

def _write_finrl_step_log(
    df_account_value,
    df_actions,
    tickers: List[str],
    tech_indicators: List[str],
    test_df,
    log_path: str,
) -> None:
    """
    Reconstruct a per-step log from FinRL's prediction output.
    df_account_value: DataFrame with ['date', 'account_value']
    df_actions:       DataFrame with one column per ticker, one row per step
    Written as JSONL to log_path.
    """
    try:
        records = []
        dates_list = df_account_value["date"].tolist() if "date" in df_account_value.columns else []
        av_list    = df_account_value["account_value"].tolist()

        for i, (date, pv) in enumerate(zip(dates_list, av_list)):
            # Actions for this step
            raw_actions: Dict[str, float] = {}
            if df_actions is not None and i < len(df_actions):
                row = df_actions.iloc[i]
                for j, tk in enumerate(tickers):
                    raw_actions[tk] = round(float(row.iloc[j]) if j < len(row) else 0.0, 4)

            # Prices + indicators from test_df
            prices_step: Dict[str, float] = {}
            indics_step: Dict[str, Dict] = {}
            date_rows = test_df[test_df["date"] == date] if "date" in test_df.columns else pd.DataFrame()
            for tk in tickers:
                tk_row = date_rows[date_rows["tic"] == tk] if "tic" in date_rows.columns else pd.DataFrame()
                if not tk_row.empty:
                    prices_step[tk] = round(float(tk_row["close"].iloc[0]), 2)
                    indics_step[tk] = {
                        ind: round(float(tk_row[ind].iloc[0]), 4)
                        for ind in tech_indicators
                        if ind in tk_row.columns
                    }

            reward = 0.0
            if i > 0:
                prev = av_list[i - 1]
                reward = round((pv - prev) / prev, 8) if prev > 0 else 0.0

            records.append({
                "step":            i,
                "date":            str(date),
                "portfolio_value": round(float(pv), 2),
                "actions":         raw_actions,
                "prices":          prices_step,
                "indicators":      indics_step,
                "reward":          reward,
            })

        with open(log_path, "w") as f:
            # Header row — consumers MUST check this before interpreting step data
            header = {
                "v": _LOG_SCHEMA_VERSION,
                "_type": "header",
                "source": "finrl_reconstruction",
                "accuracy": "approximate",
                "warning": (
                    "FinRL step log is reconstructed from df_account_value + df_actions. "
                    "Actions represent raw policy outputs, not confirmed fills. "
                    "Reward alignment may drift at episode boundaries. "
                    "Use for qualitative debugging only — do not use for P&L attribution."
                ),
            }
            f.write(json.dumps(header) + "\n")
            for rec in records:
                f.write(json.dumps(rec) + "\n")
    except Exception:
        pass   # non-fatal


def _read_step_log_rows(log_path: str) -> List[Dict[str, Any]]:
    rows: List[Dict[str, Any]] = []
    try:
        with open(log_path) as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                rec = json.loads(line)
                if rec.get("_type") == "header":
                    continue
                rows.append(rec)
    except Exception:
        pass
    return rows


def _validate_step_log_monotonic(rows: List[Dict[str, Any]]) -> Dict[str, Any]:
    """Enforce strictly increasing step indices for deterministic replay."""
    issues: List[str] = []
    prev_step: Optional[int] = None
    for i, row in enumerate(rows):
        step = row.get("step")
        if step is None:
            issues.append(f"row {i}: missing step")
            continue
        if prev_step is not None and step <= prev_step:
            issues.append(f"row {i}: non-monotonic step {prev_step} -> {step}")
        prev_step = int(step)
    return {"monotonic": len(issues) == 0, "issues": issues, "row_count": len(rows)}


def _replay_step_log_state(rows: List[Dict[str, Any]], target_step: int) -> Optional[Dict[str, Any]]:
    """
    Reconstruct portfolio state at target_step using replay rules:
    prefer last _full anchor at or before target_step, then apply deltas.
    """
    if not rows:
        return None
    anchors = [r for r in rows if r.get("_full") and r.get("step", -1) <= target_step]
    if not anchors and rows[0].get("step", -1) > target_step:
        return None
    base = anchors[-1] if anchors else rows[0]
    state = {
        "step": base.get("step"),
        "portfolio_value": base.get("portfolio_value"),
        "cash": base.get("cash"),
        "positions": dict(base.get("positions") or {}),
        "prices": dict(base.get("prices") or {}),
    }
    for row in rows:
        s = row.get("step")
        if s is None or s <= state.get("step", -1) or s > target_step:
            continue
        for key in ("portfolio_value", "cash", "reward"):
            if key in row:
                state[key] = row[key]
        if row.get("positions"):
            state["positions"] = dict(row["positions"])
        if row.get("prices"):
            state["prices"] = dict(row["prices"])
        state["step"] = s
    return state if state.get("step") == target_step else state


def _build_step_log_summary(
    log_path: str,
    trades: List[Dict],
    dates: List[str],
) -> Dict[str, Any]:
    """
    Read JSONL step log: summary stats + replay validation (monotonic steps).
    """
    summary: Dict[str, Any] = {
        "total_steps":   len(dates),
        "total_trades":  len(trades),
        "log_path":      log_path,
        "sample_steps":  [],
        "replay_rules":  _STEP_LOG_REPLAY_RULES,
    }
    try:
        rows = _read_step_log_rows(log_path)
        validation = _validate_step_log_monotonic(rows)
        summary["replay_validation"] = validation

        if rows:
            rewards = [r.get("reward", 0.0) for r in rows if "reward" in r]
            if rewards:
                summary["avg_daily_reward"] = round(float(np.mean(rewards)), 6)
                summary["reward_std"]       = round(float(np.std(rewards)),  6)
                summary["max_reward"]       = round(float(np.max(rewards)),  6)
                summary["min_reward"]       = round(float(np.min(rewards)),  6)
            sample = rows[:5] + (rows[-5:] if len(rows) > 5 else [])
            summary["sample_steps"] = sample
            summary["total_logged_steps"] = len(rows)
            summary["full_snapshot_count"] = sum(1 for r in rows if r.get("_full"))
            last_step = rows[-1].get("step")
            if last_step is not None:
                summary["replay_at_last_step"] = _replay_step_log_state(rows, int(last_step))
    except Exception:
        pass

    return summary


# ── Synthetic portfolio with dynamic slippage ─────────────────────────────────

def _fetch_real_prices_for_simulation(
    tickers: List[str], test_start: str, test_end: str
) -> Dict[str, Dict[str, Any]]:
    """
    Fetch Yahoo closes + dollar volume for rolling ADV.
    Returns {ticker: {"close": {date: px}, "dollar_vol": {date: close*volume}}}.
    """
    try:
        import yfinance as yf

        raw = yf.download(
            tickers, start=test_start, end=test_end,
            progress=False, auto_adjust=True,
        )
        if raw is None or raw.empty:
            return {}

        result: Dict[str, Dict[str, Any]] = {}
        for ticker in tickers:
            try:
                if len(tickers) == 1:
                    close_col = raw["Close"]
                    vol_col = raw["Volume"] if "Volume" in raw.columns else None
                else:
                    close_col = raw["Close"][ticker]
                    vol_col = raw["Volume"][ticker] if "Volume" in raw.columns else None

                prices_map: Dict[str, float] = {}
                dv_map: Dict[str, float] = {}
                for dt in close_col.index:
                    c = close_col.loc[dt]
                    if pd.isna(c) or float(c) <= 0:
                        continue
                    dkey = dt.strftime("%Y-%m-%d")
                    px = round(float(c), 2)
                    prices_map[dkey] = px
                    if vol_col is not None:
                        v = vol_col.loc[dt]
                        if pd.notna(v) and float(v) > 0:
                            dv_map[dkey] = round(px * float(v), 2)

                if prices_map:
                    result[ticker] = {"close": prices_map, "dollar_vol": dv_map}
            except Exception:
                pass

        return result
    except Exception:
        return {}


def _generate_synthetic_portfolio(
    run_id: str,
    test_start: str,
    test_end: str,
    initial_capital: float,
    commission_pct: float,
    slippage_pct: float,
    max_position_pct: float,
    cooldown_days: int,
    step_log_path: Optional[str] = None,
) -> tuple:
    from app.services.price_data import TICKER_BASE_PRICE

    seed  = int(hashlib.sha256(run_id.encode()).hexdigest()[:8], 16)
    rng   = np.random.default_rng(seed)
    dates = pd.date_range(start=test_start, end=test_end, freq="B").strftime("%Y-%m-%d").tolist()
    n     = len(dates)

    tickers = ["AAPL", "MSFT", "GOOGL"]

    # --- Prefer real Yahoo prices; fall back to synthetic random walk per ticker ---
    real_series = _fetch_real_prices_for_simulation(tickers, test_start, test_end)

    prices: Dict[str, List[float]] = {}
    dollar_vol_series: Dict[str, List[float]] = {}
    for ticker in tickers:
        if ticker in real_series and len(real_series[ticker].get("close", {})) >= max(n // 2, 10):
            real_map = real_series[ticker]["close"]
            dv_map = real_series[ticker].get("dollar_vol", {})
            path: List[float] = []
            dv_path: List[float] = []
            last_px = float(TICKER_BASE_PRICE.get(ticker, 150.0))
            last_dv = 0.0
            for d in dates:
                px = real_map.get(d)
                if px and px > 0:
                    last_px = px
                path.append(last_px)
                dv = dv_map.get(d)
                if dv and dv > 0:
                    last_dv = dv
                dv_path.append(last_dv)
            prices[ticker] = path
            dollar_vol_series[ticker] = dv_path
        else:
            base = float(TICKER_BASE_PRICE.get(ticker, 150.0))
            path = [base]
            for _ in range(n - 1):
                path.append(round(path[-1] * (1.0 + float(rng.normal(0.0003, 0.013))), 2))
            prices[ticker] = path
            dollar_vol_series[ticker] = [0.0] * n

    from app.services.price_data import TICKER_ADV_NOTIONAL, _DEFAULT_ADV

    static_adv = {t: float(TICKER_ADV_NOTIONAL.get(t, _DEFAULT_ADV)) for t in tickers}

    cash       = float(initial_capital)
    positions  = {t: 0.0 for t in tickers}
    last_trade = {t: -cooldown_days - 1 for t in tickers}
    trades: List[Dict] = []
    account_values = [float(initial_capital)]
    step_log_buf: List[Dict] = []

    # Per (ticker, date, side) cumulative filled notional — resets each calendar day
    daily_participation: Dict[tuple, float] = {}

    pending_orders: List[Dict[str, Any]] = []

    def _recent_returns(ticker: str, idx: int) -> List[float]:
        recent_px = prices[ticker][max(0, idx - 21): idx]
        return [
            (recent_px[j] - recent_px[j - 1]) / recent_px[j - 1]
            for j in range(1, len(recent_px)) if recent_px[j - 1] > 0
        ]

    def _adv_at(ticker: str, idx: int) -> float:
        dv = dollar_vol_series.get(ticker)
        return rolling_adv_notional(
            prices[ticker],
            static_adv[ticker],
            idx,
            dollar_volumes=dv if dv and any(dv) else None,
        )

    for i in range(1, n):
        signals_this_step: Dict[str, int] = {t: 0 for t in tickers}
        trade_date = dates[i]
        daily_participation = {}

        for order in pending_orders:
            ticker      = order["ticker"]
            action      = order["action"]
            signal_day  = order["signal_day"]
            side        = "buy" if action == "buy" else "sell"
            exec_price  = prices[ticker][i]

            if i - last_trade[ticker] < cooldown_days:
                continue

            portfolio_value = cash + sum(positions[t] * prices[t][i] for t in tickers)
            recent_ret = _recent_returns(ticker, i)
            adv = _adv_at(ticker, i)
            part_key = (ticker, trade_date, side)
            cum_today = daily_participation.get(part_key, 0.0)

            if action == "buy" and positions[ticker] == 0 and cash > 1.0:
                intended = min(cash * 0.95, portfolio_value * max_position_pct)
                actual_spend, partial_fill = cap_order_notional(intended, adv, cum_today)
                if actual_spend < 1.0:
                    continue

                urg = urgency_multiplier(intended, actual_spend)
                participation_rate = actual_spend / adv
                dyn_slip = _dynamic_slippage(
                    slippage_pct, recent_ret, participation_rate, urgency_mult=urg
                )
                eff = _buy_price(exec_price, commission_pct, dyn_slip)
                shares = actual_spend / eff
                cash -= shares * eff
                positions[ticker] = shares
                last_trade[ticker] = i
                daily_participation[part_key] = cum_today + actual_spend

                trades.append({
                    "date":                   trade_date,
                    "ticker":                 ticker,
                    "action":                 "buy",
                    "shares":                 round(shares, 4),
                    "price":                  round(exec_price, 2),
                    "effective_price":        round(eff, 2),
                    "slippage_pct":           round(dyn_slip * 100, 4),
                    "friction_cost":          round(shares * exec_price * (commission_pct + dyn_slip), 2),
                    "portfolio_value_before": round(portfolio_value, 2),
                    "signal_date":            dates[signal_day],
                    "execution_date":         trade_date,
                    "participation_pct":      round(participation_rate * 100, 4),
                    "partial_fill":           partial_fill,
                    "adv_notional":           round(adv, 0),
                    "urgency_multiplier":     round(urg, 4),
                    "execution_horizon_days": EXECUTION_HORIZON_DAYS,
                })

            elif action == "sell" and positions[ticker] > 0:
                intended_notional = positions[ticker] * exec_price
                allowed_notional, partial_fill = cap_order_notional(
                    intended_notional, adv, cum_today
                )
                if allowed_notional < 1.0:
                    continue
                sell_shares = allowed_notional / exec_price
                urg = urgency_multiplier(intended_notional, allowed_notional)
                participation_rate = allowed_notional / adv
                dyn_slip = _dynamic_slippage(
                    slippage_pct, recent_ret, participation_rate, urgency_mult=urg
                )
                eff = _sell_price(exec_price, commission_pct, dyn_slip)
                proceeds = sell_shares * eff
                cash += proceeds
                positions[ticker] -= sell_shares
                if positions[ticker] < 0.0001:
                    positions[ticker] = 0.0
                last_trade[ticker] = i
                daily_participation[part_key] = cum_today + allowed_notional

                trades.append({
                    "date":                   trade_date,
                    "ticker":                 ticker,
                    "action":                 "sell",
                    "shares":                 round(sell_shares, 4),
                    "price":                  round(exec_price, 2),
                    "effective_price":        round(eff, 2),
                    "slippage_pct":           round(dyn_slip * 100, 4),
                    "friction_cost":          round(sell_shares * exec_price * (commission_pct + dyn_slip), 2),
                    "portfolio_value_before": round(portfolio_value, 2),
                    "signal_date":            dates[signal_day],
                    "execution_date":         trade_date,
                    "participation_pct":      round(participation_rate * 100, 4),
                    "partial_fill":           partial_fill,
                    "adv_notional":           round(adv, 0),
                    "urgency_multiplier":     round(urg, 4),
                    "execution_horizon_days": EXECUTION_HORIZON_DAYS,
                })

        pending_orders.clear()

        # ── PHASE 2: Generate tomorrow's signals (no executions yet) ─────────
        if i < n - 1:   # never signal on the last day — no execution day available
            for ticker in tickers:
                if i - last_trade[ticker] < cooldown_days:
                    continue

                signal = int(rng.choice([-1, 0, 1], p=[0.15, 0.70, 0.15]))
                signals_this_step[ticker] = signal

                if signal > 0 and positions[ticker] == 0 and cash > 1.0:
                    pending_orders.append({
                        "ticker": ticker, "action": "buy", "signal_day": i,
                    })
                elif signal < 0 and positions[ticker] > 0:
                    pending_orders.append({
                        "ticker": ticker, "action": "sell", "signal_day": i,
                    })

        # ── PHASE 3: EOD portfolio valuation ─────────────────────────────────
        eod_value = cash + sum(positions[t] * prices[t][i] for t in tickers)
        account_values.append(round(eod_value, 2))

        # ── PHASE 4: Step log entry (delta-compressed) ────────────────────────
        # Full indicator state logged every 5 steps; otherwise log only essentials.
        # Keeps log size manageable (5× reduction) without losing observability.
        if step_log_path is not None:
            prev_val = account_values[-2]
            reward   = round((eod_value - prev_val) / prev_val, 8) if prev_val > 0 else 0.0

            entry: Dict[str, Any] = {
                "v":               _LOG_SCHEMA_VERSION,
                "step":            i,
                "date":            dates[i],
                "portfolio_value": round(eod_value, 2),
                "cash":            round(cash, 2),
                "reward":          reward,
                "signals":         {t: v for t, v in signals_this_step.items() if v != 0},
                # Sparse positions: only non-zero holdings
                "positions":       {t: round(v, 4) for t, v in positions.items() if v > 0.0001},
            }

            # Full indicator snapshot every 5 steps (tagged _full=True for consumers)
            if i % 5 == 0:
                entry["_full"] = True
                entry["prices"] = {t: round(prices[t][i], 2) for t in tickers}
                px_snap: Dict[str, Dict] = {}
                for ticker in tickers:
                    recent_px  = prices[ticker][max(0, i - 21): i]
                    recent_ret = [
                        (recent_px[j] - recent_px[j - 1]) / recent_px[j - 1]
                        for j in range(1, len(recent_px)) if recent_px[j - 1] > 0
                    ]
                    vol = round(float(np.std(recent_ret)) if len(recent_ret) >= 3 else 0.0, 6)
                    px5  = prices[ticker][max(0, i - 5)]
                    px20 = prices[ticker][max(0, i - 20)]
                    px_now = prices[ticker][i]
                    px_snap[ticker] = {
                        "rolling_vol_20d": vol,
                        "price_mom_5":     round((px_now - px5)  / px5  if px5  > 0 else 0.0, 6),
                        "price_mom_20":    round((px_now - px20) / px20 if px20 > 0 else 0.0, 6),
                    }
                entry["indicators"] = px_snap

            step_log_buf.append(entry)

    if step_log_path and step_log_buf:
        try:
            validation = _validate_step_log_monotonic(step_log_buf)
            with open(step_log_path, "w") as _f:
                header = {
                    "v": _LOG_SCHEMA_VERSION,
                    "_type": "header",
                    "source": "synthetic_simulation",
                    "replay_rules": _STEP_LOG_REPLAY_RULES,
                    "execution_model": model_documentation(),
                }
                _f.write(json.dumps(header) + "\n")
                prev_step: Optional[int] = None
                for _entry in step_log_buf:
                    step = _entry.get("step")
                    if step is not None and prev_step is not None and step <= prev_step:
                        raise ValueError(f"non-monotonic step log: {prev_step} -> {step}")
                    prev_step = step
                    _f.write(json.dumps(_entry) + "\n")
            if not validation["monotonic"]:
                pass
        except Exception:
            pass

    return account_values, trades, dates


# ── Rolling walk-forward analysis ─────────────────────────────────────────────

def _walk_forward_rolling(
    account_values: List[float],
    dates: List[str],
    initial_capital: float,
    window: int = 63,   # ≈1 quarter of trading days
    step: int   = 21,   # ≈1 month step
) -> Dict[str, Any]:
    """
    Sliding-window walk-forward over the test period.
    window=63 ≈ 1 quarter; step=21 ≈ 1 month → overlapping windows.
    Returns per-window metrics + aggregate consistency statistics.
    """
    n = len(dates)
    windows: List[Dict] = []

    if n < window:
        # Fallback: simple 4-quarter split when period is too short
        q = max(n // 4, 5)
        for qi in range(4):
            s   = qi * q
            e   = (qi + 1) * q if qi < 3 else n
            sub = account_values[s: e + 1]
            if len(sub) < 5:
                continue
            ret = _compute_daily_returns(sub)
            m   = _compute_metrics(sub, ret, sub[0])
            label = f"Q{qi + 1}"
            windows.append({
                "start":   dates[s],
                "end":     dates[min(e, n - 1)],
                "label":   label,
                "period":  f"{label}: {dates[s]} → {dates[min(e, n-1)]}",
                "metrics": m,
            })
    else:
        idx  = 0
        wnum = 1
        while idx + window <= n:
            sub = account_values[idx: idx + window + 1]
            ret = _compute_daily_returns(sub)
            m   = _compute_metrics(sub, ret, sub[0])
            s   = dates[idx]
            e   = dates[min(idx + window - 1, n - 1)]
            label = f"W{wnum}"
            windows.append({
                "start":   s,
                "end":     e,
                "label":   label,
                "period":  f"{label}: {s} → {e}",
                "metrics": m,
            })
            idx  += step
            wnum += 1

    if not windows:
        return {"windows": [], "summary": {}}

    rets  = [w["metrics"].get("total_return", 0.0) for w in windows]
    shrps = [w["metrics"].get("sharpe",        0.0) for w in windows]
    dds   = [w["metrics"].get("max_drawdown",  0.0) for w in windows]
    n_pos = sum(1 for r in rets if r > 0)
    pct_p = round(n_pos / len(windows) * 100, 1) if windows else 0.0
    consistency = (
        "High"   if float(np.std(rets)) < 0.05 and pct_p >= 60 else
        "Low"    if pct_p < 40 else
        "Medium"
    )

    return {
        "windows": windows,
        "summary": {
            "n_windows":        len(windows),
            "positive_windows": n_pos,
            "pct_positive":     pct_p,
            "mean_return":      round(float(np.mean(rets)),  4),
            "std_return":       round(float(np.std(rets)),   4),
            "mean_sharpe":      round(float(np.mean(shrps)), 4),
            "mean_max_dd":      round(float(np.mean(dds)),   4),
            "consistency":      consistency,
        },
    }


# ── Stress tests ──────────────────────────────────────────────────────────────

def _run_stress_scenarios(
    base_values: List[float],
    dates: List[str],
    initial_capital: float,
    commission_pct: float,
    slippage_pct: float,
    seed: int,
) -> Dict[str, Any]:
    base_ret = _compute_daily_returns(base_values)
    n = len(base_values)

    # Scenario 1: 2× transaction costs as daily drag
    daily_drag = (commission_pct + slippage_pct) * 2 / 252
    stressed1  = [float(initial_capital)]
    for r in base_ret:
        stressed1.append(round(stressed1[-1] * (1.0 + r - daily_drag), 2))
    dr1 = _compute_daily_returns(stressed1)

    # Scenario 2: −30% crash 20% into the period
    crash_idx = max(5, n // 5)
    crashed   = list(base_values[:crash_idx])
    crashed.append(round(crashed[-1] * 0.70, 2))
    for i in range(crash_idx, n - 1):
        r = base_ret[i] if i < len(base_ret) else 0.0
        crashed.append(round(crashed[-1] * (1.0 + r), 2))
    dr2 = _compute_daily_returns(crashed)

    # Scenario 3: 1-day execution delay (shift returns by 1)
    delayed = [float(initial_capital)]
    for i in range(1, len(base_ret)):
        delayed.append(round(delayed[-1] * (1.0 + base_ret[i]), 2))
    dr3 = _compute_daily_returns(delayed)

    return {
        "high_costs": {
            "label": "2× Transaction Costs",
            "account_value": [round(v, 2) for v in stressed1],
            "dates": dates,
            "metrics": _compute_metrics(stressed1, dr1, initial_capital),
        },
        "crash_scenario": {
            "label": "Market Crash (−30% shock)",
            "account_value": [round(v, 2) for v in crashed],
            "dates": dates,
            "metrics": _compute_metrics(crashed, dr2, initial_capital),
        },
        "execution_delay": {
            "label": "Simplified Delay Sensitivity",
            "note": (
                "Sensitivity check only: daily returns are shifted by one bar. "
                "This is NOT a full execution replay (no re-simulation of fills, "
                "slippage, or position sizing). Improved performance here does not "
                "imply alpha from delayed execution."
            ),
            "account_value": [round(v, 2) for v in delayed],
            "dates": dates[:len(delayed)],
            "metrics": _compute_metrics(delayed, dr3, initial_capital),
        },
    }


# ── RL sanity checks ──────────────────────────────────────────────────────────

def _rl_sanity_checks(
    trades: List[Dict], account_values: List[float], dates: List[str]
) -> Dict[str, Any]:
    n_days   = max(len(dates), 1)
    n_trades = len(trades)
    tpd      = round(n_trades / n_days, 4)

    buys  = sum(1 for t in trades if t.get("action") == "buy")
    sells = sum(1 for t in trades if t.get("action") == "sell")
    total = buys + sells or 1
    buy_pct  = round(buys  / total * 100, 1)
    sell_pct = round(sells / total * 100, 1)

    overtrading = tpd > 2.0
    action_bias = buy_pct > 80 or sell_pct > 80

    total_traded = sum(
        t.get("shares", 0) * (t.get("effective_price") or t.get("price", 0))
        for t in trades
    )
    avg_portfolio = float(np.mean(account_values)) if account_values else 1.0
    turnover = round(total_traded / avg_portfolio, 4) if avg_portfolio > 0 else 0.0

    hold_periods: List[int] = []
    buy_day: Dict[str, int] = {}
    date_idx = {d: i for i, d in enumerate(dates)}
    for t in sorted(trades, key=lambda x: x.get("date", "")):
        ticker = t.get("ticker", "")
        action = t.get("action", "")
        day    = date_idx.get(t.get("date", ""), -1)
        if action == "buy":
            buy_day[ticker] = day
        elif action == "sell" and ticker in buy_day and buy_day[ticker] >= 0:
            hold_periods.append(day - buy_day[ticker])
            del buy_day[ticker]
    avg_hold = round(float(np.mean(hold_periods)), 1) if hold_periods else None

    # Average dynamic slippage used (if recorded)
    slip_vals = [t.get("slippage_pct") for t in trades if t.get("slippage_pct") is not None]
    avg_slip  = round(float(np.mean(slip_vals)), 4) if slip_vals else None

    issues = []
    if overtrading:
        issues.append("High trade frequency may indicate overfitting")
    if action_bias:
        issues.append(f"Action heavily biased ({buy_pct}% buy, {sell_pct}% sell)")
    if avg_hold is not None and avg_hold < 1:
        issues.append("Avg hold < 1 day — possible intraday flipping")

    return {
        "n_trades":          n_trades,
        "trades_per_day":    tpd,
        "buy_pct":           buy_pct,
        "sell_pct":          sell_pct,
        "overtrading_flag":  overtrading,
        "action_bias_flag":  action_bias,
        "turnover_rate":     turnover,
        "avg_hold_days":     avg_hold,
        "avg_slippage_pct":  avg_slip,
        "verdict": " | ".join(issues) if issues else "Pass — no obvious pathologies detected",
    }


def _real_model_account_values(
    run, test_start: str, test_end: str,
    initial_capital: float, commission_pct: float, slippage_pct: float,
) -> Optional[List[float]]:
    """
    Run the trained model on [test_start, test_end] and return account values.
    Lean version of run_backtest's real-model block (no step log / trades), used
    by the overfitting report so train/val/test all use the SAME real model.
    Returns None on any failure (caller falls back to the synthetic engine).
    """
    model_path = run.model_path
    if not (FINRL_AVAILABLE and model_path and Path(str(model_path) + ".zip").exists()):
        return None
    try:
        from finrl.meta.preprocessor.preprocessors import data_split
        from finrl.meta.env_stock_trading.env_stocktrading import StockTradingEnv

        is_step4 = (run.data_job_id or "").startswith("step4")
        if is_step4:
            from app.services.feature_service import FEATURE_COLUMNS
            tech = list(FEATURE_COLUMNS)
            ff = Path(settings.oof_dir) / "features_us.csv"
            if not ff.exists():
                return None
            df = pd.read_csv(ff)
            test_df = data_split(df, test_start, test_end)
            if test_df.empty:
                return None
            for ind in tech:
                if ind not in test_df.columns:
                    test_df[ind] = 0.0
        else:
            from app.services.rl_features import build_alpha_state_pipeline
            df = pd.read_csv(Path(settings.data_dir) / run.data_job_id / "data.csv")
            test_df = data_split(df, test_start, test_end)
            tech = finrl_wrapper.get_indicators(include_rl_extras=True)
            test_df, _ = overlay_yahoo_closes(test_df, test_start, test_end, tech)
            ai = (run.metrics_json or {}).get("alpha_inputs") or {}
            test_df = build_alpha_state_pipeline(test_df, ai.get("xgb_run_id"),
                                                 ai.get("lstm_run_id"), run.data_job_id)
            for ind in tech:
                if ind not in test_df.columns:
                    test_df[ind] = 0.0

        tickers     = sorted(test_df["tic"].unique().tolist())
        stock_dim   = len(tickers)
        state_space = 1 + 2 * stock_dim + len(tech) * stock_dim
        env_kwargs  = finrl_env_kwargs(stock_dim, state_space, tech, initial_capital)
        env_kwargs["buy_cost_pct"]  = [commission_pct + slippage_pct] * stock_dim
        env_kwargs["sell_cost_pct"] = [commission_pct + slippage_pct] * stock_dim
        e = StockTradingEnv(df=test_df, **env_kwargs)
        dav, _ = _finrl_predict(run.algorithm, model_path, e)
        return dav["account_value"].tolist()
    except Exception as exc:
        logger.debug("real-model window eval failed (%s–%s): %s", test_start, test_end, exc)
        return None


# ── Overfitting report ────────────────────────────────────────────────────────

def _build_overfitting_report(
    run,
    test_metrics: Dict[str, Any],
    test_start: str,
    test_end: str,
    initial_capital: float,
    commission_pct: float,
    slippage_pct: float,
) -> Dict[str, Any]:
    """
    Compare train → validation → test performance to detect overfitting.
    - Training period : from run.metrics_json["train_window"] if available
    - Validation period: auto-inferred as 6 months before test_start
    - Test period      : current backtest result (already computed)

    All periods are evaluated with the SAME engine as the test result: if the
    test used the real model, validation/train also use the real model (so the
    comparison is valid). Previously train/val used a synthetic engine while
    test used the real model — an apples-to-oranges comparison that produced
    nonsensical divergence (e.g. val -8% vs test +79%).
    """
    train_window: Dict = {}
    if run.metrics_json:
        train_window = run.metrics_json.get("train_window", {})

    test_is_real = (test_metrics.get("_data_source") == "finrl_model")

    def _eval_window(start: str, end: str, seed_suffix: str) -> Dict:
        # Prefer the real model when the test result is real, so all periods
        # are comparable. Fall back to the synthetic engine otherwise.
        if test_is_real:
            vals = _real_model_account_values(run, start, end, initial_capital,
                                              commission_pct, slippage_pct)
            if vals and len(vals) > 5:
                return _compute_metrics(vals, _compute_daily_returns(vals), initial_capital, [])
        try:
            vv, vt, _ = _generate_synthetic_portfolio(
                run_id=run.id + seed_suffix, test_start=start, test_end=end,
                initial_capital=initial_capital, commission_pct=commission_pct,
                slippage_pct=slippage_pct, max_position_pct=0.20, cooldown_days=5)
            return _compute_metrics(vv, _compute_daily_returns(vv), initial_capital, vt)
        except Exception:
            return {}

    # ── Validation period (6 months before test) ──────────────────────────────
    val_end_ts    = pd.Timestamp(test_start) - pd.Timedelta(days=1)
    val_start_ts  = val_end_ts - pd.DateOffset(months=6)
    val_start_str = val_start_ts.strftime("%Y-%m-%d")
    val_end_str   = val_end_ts.strftime("%Y-%m-%d")
    val_metrics   = _eval_window(val_start_str, val_end_str, "_val")

    # ── Training period ───────────────────────────────────────────────────────
    train_metrics:  Dict = {}
    train_start_str = train_window.get("start", "")
    train_end_str   = train_window.get("end",   "")
    if train_start_str and train_end_str:
        train_metrics = _eval_window(train_start_str, train_end_str, "_tr")

    # ── Degradation gaps ──────────────────────────────────────────────────────
    tr  = train_metrics.get("total_return")
    vr  = val_metrics.get("total_return")
    tst = test_metrics.get("total_return")
    gaps: Dict = {}
    if tr  is not None and vr  is not None: gaps["train_to_val"]  = round(float(tr  - vr),  4)
    if vr  is not None and tst is not None: gaps["val_to_test"]   = round(float(vr  - tst), 4)
    if tr  is not None and tst is not None: gaps["train_to_test"] = round(float(tr  - tst), 4)

    primary_gap = gaps.get("val_to_test", gaps.get("train_to_test", 0.0))
    if primary_gap > 0.20:
        verdict = ("Large positive train/validation-to-test gap (>20pp): strong evidence "
                   "of overfitting or regime-specific fit; treat test results with caution.")
    elif primary_gap > 0.10:
        verdict = ("Moderate degradation (10–20pp) from validation to test — consistent with "
                   "RL agents encountering unseen market regimes.")
    elif primary_gap > -0.02:
        verdict = ("Minimal degradation (≤10pp): performance is broadly stable across the "
                   "validation and test periods.")
    else:
        verdict = ("Test outperforms validation: performance divergence indicates sensitivity "
                   "to differing market-regime conditions across the two windows, not a "
                   "monotonic generalization signal — interpret with regime context.")

    return {
        "train": {
            "period":  f"{train_start_str} → {train_end_str}" if train_start_str else "Training period",
            "metrics": train_metrics,
        },
        "validation": {
            "period":  f"{val_start_str} → {val_end_str}",
            "metrics": val_metrics,
        },
        "test": {
            "period":  f"{test_start} → {test_end}",
            "metrics": test_metrics,
        },
        "gaps":    gaps,
        "verdict": verdict,
    }


# ── Trade enrichment ──────────────────────────────────────────────────────────

def _enrich_trades_with_yahoo_prices(
    trades: List[Dict], test_start: str, test_end: str
) -> List[Dict]:
    """
    Attaches a `live_price` reference field to each trade for display purposes.
    NEVER overwrites `price` (the simulation execution price) or `effective_price`.
    This prevents the display bug where Yahoo live prices (~$141) were shown as
    the execution price while effective_price remained at the synthetic level (~$176).
    """
    if not trades:
        return trades
    from app.services.price_data import fetch_close_on_date
    cache: dict = {}
    out = []
    for t in trades:
        row  = dict(t)
        live = fetch_close_on_date(row["ticker"], row["date"], cache)
        if live and live > 0:
            row["live_price"]   = round(live, 2)   # reference only — never overwrites execution price
            row["price_source"] = "yahoo"
        else:
            row["price_source"] = "dataset"
        out.append(row)
    return out


def _parse_trades(df_actions, test_df, tickers, dates) -> List[Dict]:
    """
    Convert a FinRL action frame into a trade log.

    df_actions from env.save_action_memory() is indexed by DATE (not an int),
    with one column per ticker. Earlier code assumed an integer index and
    crashed on the date index (caught by a bare except → 0 trades). We now
    handle both, and build a (date, ticker) → close price lookup for speed.
    """
    trades: List[Dict] = []
    try:
        # Fast price lookup keyed by normalised date string + ticker
        px_df = test_df.copy()
        px_df["_d"] = pd.to_datetime(px_df["date"]).dt.strftime("%Y-%m-%d")
        price_lookup = {
            (r["_d"], r["tic"]): float(r["close"])
            for _, r in px_df[["_d", "tic", "close"]].iterrows()
        }

        for pos, (idx, row) in enumerate(df_actions.iterrows()):
            # Index may be a date (save_action_memory) or an int (legacy)
            if isinstance(idx, (int, np.integer)):
                raw_date = dates[idx] if idx < len(dates) else str(idx)
            else:
                raw_date = idx
            date_str = pd.to_datetime(raw_date).strftime("%Y-%m-%d") \
                       if not isinstance(raw_date, str) else \
                       pd.to_datetime(raw_date, errors="coerce").strftime("%Y-%m-%d") \
                       if pd.to_datetime(raw_date, errors="coerce") is not pd.NaT else raw_date

            for j, ticker in enumerate(tickers):
                action_val = float(row.iloc[j]) if j < len(row) else 0.0
                if abs(action_val) <= 0.05:
                    continue
                price = price_lookup.get((date_str, ticker), 0.0)
                trades.append({
                    "date":   date_str,
                    "ticker": ticker,
                    "action": "buy" if action_val > 0 else "sell",
                    "shares": round(abs(action_val), 4),
                    "price":  round(price, 2),
                })
    except Exception as exc:
        logger.warning("_parse_trades failed: %s", exc)
    return trades


# ── Distribution statistics + bootstrap CI ───────────────────────────────────

def _distribution_stats(returns: List[float]) -> Dict[str, Any]:
    """
    Augments a metrics dict with:
      - return_skew / return_kurtosis (higher moments)
      - var_95 / cvar_95 (daily historical VaR & CVaR at 95%)
      - sharpe_ci (bootstrap 95% CI for Sharpe, 1000 resamples)
    Called after _compute_metrics() in run_backtest() to avoid adding
    the bootstrap overhead to walk-forward and stress-test sub-computations.
    """
    arr = np.array(returns, dtype=float)
    n   = len(arr)
    if n < 10:
        return {}

    result: Dict[str, Any] = {}

    # Skewness and excess kurtosis
    mu, sigma = arr.mean(), arr.std()
    if sigma > 1e-10:
        result["return_skew"]     = round(float(np.mean(((arr - mu) / sigma) ** 3)), 4)
        result["return_kurtosis"] = round(float(np.mean(((arr - mu) / sigma) ** 4) - 3), 4)

    # Historical VaR / CVaR at 95%
    if n >= 20:
        var_95  = float(np.percentile(arr, 5))
        tail    = arr[arr <= var_95]
        cvar_95 = float(tail.mean()) if len(tail) > 0 else var_95
        result["var_95"]  = round(var_95,  6)
        result["cvar_95"] = round(cvar_95, 6)

    # Bootstrap Sharpe ratio CI (1000 resamples)
    if n >= 30:
        rng = np.random.default_rng(42)
        boot: List[float] = []
        for _ in range(1000):
            s = rng.choice(arr, size=n, replace=True)
            sd = float(s.std())
            if sd > 1e-10:
                boot.append(float(s.mean() / sd * np.sqrt(252)))
        if boot:
            bs = np.array(boot)
            result["sharpe_ci"] = {
                "lower":  round(float(np.percentile(bs, 2.5)),  4),
                "upper":  round(float(np.percentile(bs, 97.5)), 4),
                "median": round(float(np.median(bs)),            4),
            }

    return result


# ── Regime analysis ───────────────────────────────────────────────────────────

def _is_earnings_season(date_str: str) -> bool:
    """US earnings clusters: late Jan/Apr/Jul/Oct and early following month."""
    try:
        from datetime import datetime
        d = datetime.strptime(str(date_str)[:10], "%Y-%m-%d")
        m, day = d.month, d.day
        if m in (1, 4, 7, 10) and day >= 10:
            return True
        if m in (2, 5, 8, 11) and day <= 14:
            return True
    except ValueError:
        pass
    return False


def _regime_day_tags(
    roll_vol: float,
    roll_trend: float,
    med_vol: float,
    vix_z: Optional[float],
    date_str: str,
    sideways_thresh: float = 0.0002,
) -> List[str]:
    """Independent regime tags — a day may belong to multiple categories."""
    tags: List[str] = []
    if abs(roll_trend) < sideways_thresh:
        tags.append("sideways")
    elif roll_trend < 0:
        tags.append("bear")
    else:
        tags.append("bull")

    if roll_vol < 0.5 * med_vol:
        tags.append("low_volatility")
    elif roll_vol > 1.5 * med_vol:
        tags.append("high_volatility")

    if vix_z is not None and vix_z > 1.0:
        tags.append("high_vix")
    if _is_earnings_season(date_str):
        tags.append("earnings_season")
    return tags


def _regime_analysis(
    daily_returns: List[float],
    dates: List[str],
    trades: List[Dict],
) -> Dict[str, Any]:
    """
    Multi-tag regime breakdown (20-day rolling vol + trend + VIX + earnings calendar).

    Each category is evaluated independently — a day can count in Bull AND Low volatility.
    Returns per-regime strategy metrics AND trade-volatility correlation.
    """
    arr = np.array(daily_returns, dtype=float)
    n   = len(arr)
    if n < 20:
        return {}

    roll_vol   = pd.Series(arr).rolling(20, min_periods=5).std().fillna(arr.std()).values
    roll_trend = pd.Series(arr).rolling(20, min_periods=5).mean().fillna(arr.mean()).values
    med_vol    = float(np.median(roll_vol))

    vix_z_by_date: Dict[str, float] = {}
    if dates:
        try:
            from app.services.feature_service import download_vix
            vix_df = download_vix(dates[0], dates[-1])
            if vix_df is not None and not vix_df.empty:
                for _, row in vix_df.iterrows():
                    vix_z_by_date[str(row["date"])[:10]] = float(row.get("vix_zscore", 0.0))
        except Exception:
            pass

    LABELS = {
        "bull":            "Bull market",
        "bear":            "Bear market",
        "sideways":        "Sideways market",
        "low_volatility":  "Low volatility",
        "high_volatility": "High volatility",
        "high_vix":        "High VIX",
        "earnings_season": "Earnings season",
    }
    DISPLAY_ORDER = list(LABELS.keys())

    day_tags: List[List[str]] = []
    for i in range(n):
        d_str = dates[i] if i < len(dates) else ""
        tags = _regime_day_tags(
            float(roll_vol[i]),
            float(roll_trend[i]),
            med_vol,
            vix_z_by_date.get(d_str[:10]) if d_str else None,
            d_str,
        )
        day_tags.append(tags)

    perf: Dict[str, Any] = {}
    for name in DISPLAY_ORDER:
        idxs = [i for i, tags in enumerate(day_tags) if name in tags]
        if not idxs:
            continue
        sub    = arr[idxs]
        sharpe = float(sub.mean() / sub.std() * np.sqrt(252)) if sub.std() > 1e-10 else 0.0
        cum    = np.cumprod(1.0 + sub)
        peak   = np.maximum.accumulate(cum)
        max_dd = float(np.max((peak - cum) / np.where(peak > 0, peak, 1)))
        perf[name] = {
            "label":             LABELS[name],
            "n_days":            len(idxs),
            "pct_of_period":     round(len(idxs) / n * 100, 1),
            "mean_daily_return": round(float(sub.mean()), 6),
            "sharpe_ann":        round(sharpe, 4),
            "win_rate":          round(float(np.mean(sub > 0)), 4),
            "max_drawdown":      round(max_dd, 4),
        }

    trade_dates = set(t.get("date", "") for t in trades)
    flags = np.array(
        [1.0 if (i < len(dates) and dates[i] in trade_dates) else 0.0 for i in range(n)]
    )
    tv_corr: Optional[float] = None
    if roll_vol.std() > 1e-10 and flags.std() > 1e-10:
        tv_corr = round(float(np.corrcoef(flags, roll_vol)[0, 1]), 4)
    tv_note = (
        "Agent trades more on volatile days — potential noise-chasing (review for overfitting)"
        if tv_corr is not None and tv_corr > 0.3 else
        "Agent trades less on volatile days — conservative, volatility-averse behaviour"
        if tv_corr is not None and tv_corr < -0.3 else
        "Trade frequency not strongly correlated with volatility — healthy signal"
    )

    return {
        "regime_performance":    perf,
        "regime_display_order":  DISPLAY_ORDER,
        "regime_distribution":   {name: sum(1 for tags in day_tags if name in tags) for name in LABELS},
        "trade_vol_correlation": tv_corr,
        "trade_vol_note":        tv_note,
        "methodology": (
            "Direction: 20-day mean return (bull/bear/sideways). "
            "Volatility: 20-day rolling std vs median (low/high). "
            "High VIX: VIX z-score > 1.0. Earnings: US calendar windows (late Jan/Apr/Jul/Oct). "
            "Categories are independent — days may appear in multiple rows."
        ),
    }


# ── Statistical significance (Diebold-Mariano) ───────────────────────────────

def _significance_tests(
    agent_returns: List[float],
    baselines: Dict[str, Dict],
) -> Dict[str, Any]:
    """
    Diebold-Mariano test for each baseline.
    H₀: E[d_t] = 0 where d_t = r_agent(t) − r_baseline(t).
    DM > 0 → agent outperforms. Newey-West HAC SE corrects for autocorrelation.
    Significance threshold: p < 0.05 (two-tailed).
    """
    agent = np.array(agent_returns, dtype=float)
    out:   Dict[str, Any] = {}

    for name, bdata in baselines.items():
        if not bdata:
            continue
        bvals = bdata.get("account_value")
        if not bvals or len(bvals) < 5:
            continue
        bret = np.array(_compute_daily_returns(bvals), dtype=float)

        min_len = min(len(agent), len(bret))
        if min_len < 10:
            continue
        d = agent[:min_len] - bret[:min_len]
        n = len(d)
        d_mean = float(d.mean())

        # Newey-West HAC variance (Bartlett kernel, lags = floor(n^(1/3)))
        lags   = max(1, int(n ** (1 / 3)))
        g0     = float(np.var(d, ddof=1))
        acov   = 0.0
        for lag in range(1, lags + 1):
            cov = float(np.cov(d[lag:], d[:-lag])[0, 1]) if len(d[lag:]) > 1 else 0.0
            acov += (1.0 - lag / (lags + 1)) * cov
        hac_var = (g0 + 2 * acov) / n
        if hac_var <= 0:
            continue

        dm_stat = d_mean / float(np.sqrt(hac_var))
        # Normal approximation (scipy optional)
        try:
            from scipy.stats import norm as _norm
            p_val = float(2 * (1 - _norm.cdf(abs(dm_stat))))
        except ImportError:
            z     = abs(dm_stat)
            # Abramowitz & Stegun approximation for standard normal CDF
            t_    = 1 / (1 + 0.2316419 * z)
            poly  = t_ * (0.319381530 + t_ * (-0.356563782 + t_ * (1.781477937 + t_ * (-1.821255978 + t_ * 1.330274429))))
            p_val = float(2 * (1 / np.sqrt(2 * np.pi) * np.exp(-z * z / 2)) * poly)
            p_val = max(0.0, min(1.0, p_val))

        sig = p_val < 0.05
        out[name] = {
            "dm_stat":       round(dm_stat, 4),
            "p_value":       round(p_val,   4),
            "significant":   sig,
            "agent_beats":   dm_stat > 0,
            "interpretation": (
                f"RL significantly outperforms {name.replace('_', ' ')} (p={p_val:.3f})"  if  sig and dm_stat > 0 else
                f"RL significantly underperforms {name.replace('_', ' ')} (p={p_val:.3f})" if sig and dm_stat <= 0 else
                f"No significant difference vs {name.replace('_', ' ')} (p={p_val:.3f})"
            ),
        }

    n_beats = sum(1 for r in out.values() if r["significant"] and r["agent_beats"])
    n_total = len(out)
    out["_summary"] = {
        "beats_significantly": n_beats,
        "total_tested":        n_total,
        "overall": (
            "RL agent significantly outperforms most baselines" if n_beats >= max(1, n_total * 0.6) else
            "RL agent matches or slightly beats baselines"      if n_beats >= 1 else
            "RL agent does not significantly outperform any tested baseline"
        ),
    }
    return out


# ── Metrics computation ───────────────────────────────────────────────────────

def _compute_benchmark_relative_metrics(
    agent_daily: List[float],
    agent_dates: List[str],
    benchmark: Optional[Dict[str, Any]],
    agent_metrics: Optional[Dict[str, Any]],
) -> Dict[str, Any]:
    """Excess return and information ratio vs buy-and-hold S&P 500."""
    if not benchmark or not agent_metrics:
        return {}
    bh_m = benchmark.get("metrics") or {}
    agent_tr = float(agent_metrics.get("total_return") or 0)
    bh_tr = float(bh_m.get("total_return") or 0)
    excess = agent_tr - bh_tr
    cagr_agent = float(agent_metrics.get("cagr") or 0)
    cagr_bh = float(bh_m.get("cagr") or 0)

    out: Dict[str, Any] = {
        "excess_return_vs_buy_hold": round(excess, 4),
        "alpha_vs_buy_hold": round(cagr_agent - cagr_bh, 4),
        "buy_hold_total_return": round(bh_tr, 4),
    }

    b_dates = benchmark.get("dates") or []
    b_av = benchmark.get("account_value") or []
    if len(b_av) < 2 or not agent_dates or len(agent_daily) < 5:
        out["information_ratio_vs_buy_hold"] = None
        out["tracking_error_vs_buy_hold"] = None
        out["beta_vs_buy_hold"] = None
        return out

    b_daily_map: Dict[str, float] = {}
    b_rets = _compute_daily_returns(b_av)
    for i, d in enumerate(b_dates[1:]):
        if i < len(b_rets):
            b_daily_map[str(d)[:10]] = b_rets[i]

    active: List[float] = []
    agent_aligned: List[float] = []
    bench_aligned: List[float] = []
    for i, d in enumerate(agent_dates[1:]):
        if i >= len(agent_daily):
            break
        br = b_daily_map.get(str(d)[:10])
        if br is not None:
            ar = agent_daily[i]
            active.append(ar - br)
            agent_aligned.append(ar)
            bench_aligned.append(br)

    if len(active) > 5 and float(np.std(active)) > 1e-10:
        te_ann = float(np.std(active, ddof=1) * np.sqrt(252))
        out["tracking_error_vs_buy_hold"] = round(te_ann, 4)
        out["information_ratio_vs_buy_hold"] = round(
            float(np.mean(active) / np.std(active, ddof=1) * np.sqrt(252)), 4
        )
    else:
        out["tracking_error_vs_buy_hold"] = None
        out["information_ratio_vs_buy_hold"] = None

    if len(agent_aligned) > 5:
        a = np.array(agent_aligned, dtype=float)
        b = np.array(bench_aligned, dtype=float)
        var_b = float(np.var(b, ddof=1))
        if var_b > 1e-12:
            out["beta_vs_buy_hold"] = round(float(np.cov(a, b)[0, 1] / var_b), 4)
        else:
            out["beta_vs_buy_hold"] = None
    else:
        out["beta_vs_buy_hold"] = None

    return out


def _compute_daily_returns(account_values: List[float]) -> List[float]:
    if len(account_values) < 2:
        return []
    return [
        (account_values[i] - account_values[i - 1]) / account_values[i - 1]
        if account_values[i - 1] != 0 else 0.0
        for i in range(1, len(account_values))
    ]


def _compute_trade_return_stats(
    trades: List[Dict],
    closing_prices: Optional[Dict[str, float]] = None,
) -> Dict[str, Any]:
    """
    FIFO lot matching per ticker (share-accurate).

    Previous logic kept one buy price per ticker and treated any sell as a full
    round-trip, which broke under partial rebalances (many sells unmatched →
    bogus negative avg_trade_return despite positive portfolio return).
    """
    from collections import defaultdict, deque

    lots: Dict[str, deque] = defaultdict(deque)  # ticker -> deque[[shares, px], ...]
    last_px: Dict[str, float] = {}
    closed_rets: List[float] = []
    closed_notionals: List[float] = []

    for t in sorted(trades, key=lambda x: x.get("date", "")):
        tk = (t.get("ticker") or "").strip()
        act = (t.get("action") or "").lower()
        px = float(t.get("effective_price") or t.get("price") or 0)
        sh = abs(float(t.get("shares") or 0))
        if not tk or px <= 0 or sh <= 1e-12:
            continue
        last_px[tk] = px

        if act == "buy":
            lots[tk].append([sh, px])
        elif act == "sell":
            remaining = sh
            while remaining > 1e-9 and lots[tk]:
                lot_sh, lot_px = lots[tk][0]
                matched = min(remaining, lot_sh)
                if lot_px > 0:
                    ret = (px - lot_px) / lot_px
                    closed_rets.append(ret)
                    closed_notionals.append(matched * lot_px)
                lot_sh -= matched
                remaining -= matched
                if lot_sh <= 1e-9:
                    lots[tk].popleft()
                else:
                    lots[tk][0][0] = lot_sh

    # Mark open lots to closing prices (or last trade price) for completeness
    mark_px = dict(last_px)
    if closing_prices:
        mark_px.update({k: float(v) for k, v in closing_prices.items() if v})
    open_rets: List[float] = []
    open_notionals: List[float] = []
    for tk, dq in lots.items():
        fpx = mark_px.get(tk, 0.0)
        if fpx <= 0:
            continue
        for lot_sh, lot_px in dq:
            if lot_sh > 1e-9 and lot_px > 0:
                open_rets.append((fpx - lot_px) / lot_px)
                open_notionals.append(lot_sh * lot_px)

    def _wmean(rets: List[float], weights: List[float]) -> Optional[float]:
        if not rets:
            return None
        if not weights or sum(weights) <= 0:
            return float(np.mean(rets))
        return float(np.average(rets, weights=weights))

    realized = _wmean(closed_rets, closed_notionals)
    incl_open = _wmean(closed_rets + open_rets, closed_notionals + open_notionals)

    return {
        "avg_trade_return": realized,
        "avg_trade_return_incl_open": incl_open,
        "trade_win_rate": round(float(np.mean(np.array(closed_rets) > 0)), 4) if closed_rets else None,
        "n_closed_lots": len(closed_rets),
        "n_open_lots": len(open_rets),
        "n_unmatched_sell_shares": 0,  # reserved; FIFO consumes sells against lots
    }


def refresh_trade_metrics(
    metrics: Optional[Dict[str, Any]],
    trades: Optional[List[Dict]],
    n_days: Optional[int] = None,
) -> Dict[str, Any]:
    """Recompute trade-level metrics from the trade log (fixes stale stored results)."""
    out = dict(metrics or {})
    if not trades:
        return out

    trade_stats = _compute_trade_return_stats(trades)
    if trade_stats.get("avg_trade_return") is not None:
        out["avg_trade_return"] = round(trade_stats["avg_trade_return"], 4)
    if trade_stats.get("avg_trade_return_incl_open") is not None:
        out["avg_trade_return_incl_open"] = round(trade_stats["avg_trade_return_incl_open"], 4)
    if trade_stats.get("trade_win_rate") is not None:
        out["trade_win_rate"] = trade_stats["trade_win_rate"]
    out["n_closed_lots"] = trade_stats.get("n_closed_lots", 0)
    out["n_open_lots"] = trade_stats.get("n_open_lots", 0)

    if n_days and n_days > 0:
        trade_dates = set(t.get("date", "") for t in trades)
        active = round(float(min(len(trade_dates) / n_days, 1.0)), 4)
        out["active_days_pct"] = active
        out["exposure_pct"] = active

    if "win_rate" in out and "daily_win_rate" not in out:
        out["daily_win_rate"] = out["win_rate"]

    return out


def _decision_from_score(score: float) -> str:
    if score > 0.60:
        return "BUY"
    if score < 0.40:
        return "SELL"
    return "HOLD"


def _technical_score_from_row(row: Dict[str, Any]) -> float:
    rsi = float(row.get("rsi_14", 50) or 50)
    mom = float(row.get("price_mom_20", 0) or 0)
    rsi_s = max(0.0, min(1.0, rsi / 100.0))
    mom_s = 0.5 + float(np.tanh(mom * 5)) * 0.5
    return round(0.5 * rsi_s + 0.5 * mom_s, 4)


def _fundamental_score_from_info(info: Dict[str, Any]) -> float:
    parts: List[float] = []
    pe = info.get("trailingPE")
    if pe is not None and 0 < float(pe) < 120:
        parts.append(max(0.0, 1.0 - abs(float(pe) - 20.0) / 50.0))
    pm = info.get("profitMargins")
    if pm is not None:
        parts.append(max(0.0, min(1.0, float(pm) * 2.5 + 0.35)))
    rg = info.get("revenueGrowth")
    if rg is not None:
        parts.append(max(0.0, min(1.0, float(rg) + 0.5)))
    de = info.get("debtToEquity")
    if de is not None and float(de) >= 0:
        parts.append(max(0.0, 1.0 - min(float(de) / 200.0, 1.0)))
    if not parts:
        return 0.5
    return round(float(np.mean(parts)), 4)


def _fetch_fundamental_scores(tickers: List[str]) -> Dict[str, float]:
    scores: Dict[str, float] = {}
    try:
        import yfinance as yf
        for tk in tickers:
            if not tk or tk.startswith("^"):
                continue
            if tk in _FUND_SCORE_CACHE:
                scores[tk] = _FUND_SCORE_CACHE[tk]
                continue
            try:
                info = yf.Ticker(tk).info or {}
                val = _fundamental_score_from_info(info)
                _FUND_SCORE_CACHE[tk] = val
                scores[tk] = val
            except Exception:
                _FUND_SCORE_CACHE[tk] = 0.5
                scores[tk] = 0.5
    except Exception:
        pass
    return scores


_FUND_SCORE_CACHE: Dict[str, float] = {}


def _build_feature_lookup(test_start: str, test_end: str, tickers: List[str]) -> Dict[tuple, Dict[str, Any]]:
    """{(date, ticker): feature_row} for technical scoring at trade time."""
    lookup: Dict[tuple, Dict[str, Any]] = {}
    if not tickers:
        return lookup
    try:
        from app.services.feature_service import download_vix, build_features
        from app.services.live_trading_service import _download_live
        warmup = (pd.Timestamp(test_start) - pd.Timedelta(days=120)).strftime("%Y-%m-%d")
        raw = _download_live(tickers, warmup, test_end)
        vix = download_vix(warmup, test_end)
        featured = raw.copy()
        featured["date"] = pd.to_datetime(featured["date"])
        parts = []
        for tic in sorted(set(tickers)):
            try:
                parts.append(build_features(raw, ticker=tic, vix_df=vix))
            except Exception:
                continue
        if not parts:
            return lookup
        fe = pd.concat(parts, ignore_index=True)
        fe["date"] = pd.to_datetime(fe["date"])
        fe = fe[(fe["date"] >= test_start) & (fe["date"] <= test_end)]
        for _, row in fe.iterrows():
            d = str(row["date"])[:10]
            tk = str(row.get("tic", "")).strip()
            if d and tk:
                lookup[(d, tk)] = row.to_dict()
    except Exception:
        pass
    return lookup


def build_fundamental_attribution(
    trades: List[Dict],
    test_start: Optional[str] = None,
    test_end: Optional[str] = None,
    signal_map: Optional[Dict[tuple, float]] = None,
) -> List[Dict[str, Any]]:
    """
    Per-trade explainability: technical vs fundamental scores and fused decision.

    Technical: ensemble/meta probability when available, else RSI+momentum proxy.
    Fundamental: yfinance trailing PE, margins, revenue growth, leverage (0–1).
    Final: 60% technical + 40% fundamental → BUY/HOLD/SELL bands.
    """
    if not trades:
        return []

    tickers = sorted({str(t.get("ticker", "")).strip().upper() for t in trades if t.get("ticker")})
    fund = _fetch_fundamental_scores(tickers)

    dates = [t.get("date", "")[:10] for t in trades if t.get("date")]
    t0 = test_start or (min(dates) if dates else "")
    t1 = test_end or (max(dates) if dates else "")
    feat_lookup = _build_feature_lookup(t0, t1, tickers) if t0 and t1 else {}

    rows: List[Dict[str, Any]] = []
    for t in trades:
        tk = str(t.get("ticker", "")).strip().upper()
        d = str(t.get("date", ""))[:10]
        if not tk or not d:
            continue

        tech = None
        if signal_map and (d, tk) in signal_map:
            tech = float(signal_map[(d, tk)])
        elif t.get("technical_score") is not None:
            tech = float(t["technical_score"])
        elif (d, tk) in feat_lookup:
            tech = _technical_score_from_row(feat_lookup[(d, tk)])
        else:
            tech = 0.5

        fund_s = fund.get(tk, 0.5)
        blended = round(0.6 * tech + 0.4 * fund_s, 4)
        decision = _decision_from_score(blended)

        rows.append({
            "date": d,
            "ticker": tk,
            "action": t.get("action"),
            "technical_score": round(tech, 4),
            "fundamental_score": round(fund_s, 4),
            "blended_score": blended,
            "final_decision": decision,
        })
    return rows


def enrich_backtest_result(result: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    """Patch stored backtest JSON with corrected labels and recomputed enrichments."""
    if not result:
        return {}
    out = dict(result)
    trades = out.get("trades") or []
    dates = out.get("dates") or []
    daily = out.get("daily_return") or []

    out["metrics"] = refresh_trade_metrics(
        out.get("metrics"),
        trades,
        n_days=len(daily),
    )
    if daily and out["metrics"].get("annualized_volatility") is None and len(daily) > 1:
        merged = dict(out["metrics"])
        merged["annualized_volatility"] = round(
            float(np.std(np.array(daily, dtype=float), ddof=1) * np.sqrt(252)), 4
        )
        out["metrics"] = merged

    if trades and dates and daily:
        out["regime_analysis"] = _regime_analysis(daily, dates, trades)

    stress = out.get("stress_tests") or {}
    delay = stress.get("execution_delay")
    if delay:
        delay = dict(delay)
        delay["label"] = "Simplified Delay Sensitivity"
        delay.setdefault(
            "note",
            "Sensitivity check only: shifts daily returns by one bar — not a full execution replay.",
        )
        stress = dict(stress)
        stress["execution_delay"] = delay
        out["stress_tests"] = stress

    if trades and not out.get("fundamental_attribution"):
        dlist = [t.get("date", "")[:10] for t in trades if t.get("date")]
        out["fundamental_attribution"] = build_fundamental_attribution(
            trades,
            test_start=min(dlist) if dlist else None,
            test_end=max(dlist) if dlist else None,
        )

    notes = dict(out.get("methodology_notes") or {})
    notes.setdefault(
        "trade_day_frequency",
        "trade_day_frequency / active_days_pct = share of backtest days with ≥1 trade — NOT capital deployed.",
    )
    notes.setdefault(
        "mean_closed_trade_return",
        "FIFO-matched closed lots; returns use effective_price (commission + slippage per leg).",
    )
    out["methodology_notes"] = notes

    benchmark = out.get("benchmark")
    if benchmark and out.get("metrics") and dates and daily:
        rel = _compute_benchmark_relative_metrics(daily, dates, benchmark, out["metrics"])
        merged = dict(out["metrics"])
        merged.update(rel)
        out["metrics"] = merged

    # Upgrade legacy SPY random-timing baseline (inflated Sharpe in bull markets)
    baselines = dict(out.get("baselines") or {})
    rand = baselines.get("random") or {}
    if dates and rand.get("strategy") == "random_timing_long_only":
        tc = out.get("transaction_costs") or {}
        seed = int(hashlib.sha256(f"{dates[0]}:{dates[-1]}".encode()).hexdigest()[:8], 16)
        new_rand = run_random_baseline(
            dates[0], dates[-1],
            float(out.get("initial_capital") or 1_000_000),
            float(tc.get("commission_pct") or 0.001),
            float(tc.get("slippage_pct") or 0.001),
            seed,
        )
        if new_rand:
            baselines["random"] = new_rand
            out["baselines"] = baselines

    return out


def _compute_metrics(
    account_values: List[float],
    daily_returns: List[float],
    initial_capital: float,
    trades: Optional[List[Dict]] = None,
) -> Dict[str, Any]:
    if not daily_returns:
        return {}
    returns  = np.array(daily_returns, dtype=float)
    n_days   = len(returns)
    total_ret = (account_values[-1] - account_values[0]) / account_values[0]
    ann_ret   = float((1.0 + total_ret) ** (252.0 / n_days) - 1.0) if n_days > 0 else 0.0

    # Sharpe
    sharpe = float(returns.mean() / returns.std() * np.sqrt(252)) \
             if returns.std() > 1e-10 else 0.0

    # Sortino (downside deviation only) — annualized the SAME way as Sharpe
    # (×√252 on the daily mean/downside-std ratio). Previous code pre-annualized
    # the denominator AND multiplied the numerator by √252, cancelling the
    # annualization → Sortino came out ~Sharpe/√252 (e.g. 0.18 vs 1.88). Bug.
    neg          = returns[returns < 0]
    down_std_day = float(np.std(neg)) if len(neg) > 1 else 1e-9   # DAILY downside dev
    sortino      = float(returns.mean() / (down_std_day + 1e-12) * np.sqrt(252)) \
                   if down_std_day > 1e-10 else 0.0

    # Max drawdown
    peak, max_dd = account_values[0], 0.0
    for v in account_values:
        if v > peak:
            peak = v
        dd = (peak - v) / peak if peak > 0 else 0.0
        if dd > max_dd:
            max_dd = dd

    # Calmar = CAGR / max_drawdown
    calmar = float(ann_ret / max_dd) if max_dd > 0.001 else float(min(ann_ret * 10, 99.0))

    # Profit factor = sum(positive daily rets) / |sum(negative daily rets)|
    pos  = float(returns[returns > 0].sum())
    neg_ = float(abs(returns[returns < 0].sum()))
    profit_factor = round(pos / neg_, 4) if neg_ > 1e-9 else float(min(pos * 100, 99.0))

    win_days  = int(np.sum(returns > 0))
    win_rate  = float(win_days / n_days) if n_days > 0 else 0.0
    ann_vol   = float(returns.std(ddof=1) * np.sqrt(252)) if n_days > 1 else 0.0

    m: Dict[str, Any] = {
        "sharpe":        round(sharpe, 4),
        "sortino":       round(sortino, 4),
        "calmar":        round(float(min(calmar, 99.0)), 4),
        "max_drawdown":  round(max_dd, 4),
        "cagr":          round(ann_ret, 4),
        "total_return":  round(total_ret, 4),
        "annualized_volatility": round(ann_vol, 4),
        "profit_factor": round(float(min(profit_factor, 99.0)), 4),
        "initial_value": round(float(initial_capital), 2),
        "final_value":   round(float(account_values[-1]), 2),
        "win_rate":      round(win_rate, 4),
        "daily_win_rate": round(win_rate, 4),  # explicit alias — NOT trade win rate
        "win_days":      win_days,
        "loss_days":     int(n_days - win_days),
    }

    # Trade-level metrics (only when trade log is available)
    if trades:
        trade_stats = _compute_trade_return_stats(trades)
        if trade_stats.get("avg_trade_return") is not None:
            m["avg_trade_return"] = round(trade_stats["avg_trade_return"], 4)
        if trade_stats.get("avg_trade_return_incl_open") is not None:
            m["avg_trade_return_incl_open"] = round(trade_stats["avg_trade_return_incl_open"], 4)
        if trade_stats.get("trade_win_rate") is not None:
            m["trade_win_rate"] = trade_stats["trade_win_rate"]
        m["n_closed_lots"] = trade_stats.get("n_closed_lots", 0)
        m["n_open_lots"] = trade_stats.get("n_open_lots", 0)

        # "active_days_pct" = fraction of days on which a trade occurred (trade
        # FREQUENCY), NOT capital deployed. Previously mislabeled "exposure_pct",
        # which readers misread as "mostly in cash". Keep exposure_pct as an alias
        # for backward compat but make the meaning explicit.
        trade_dates = set(t.get("date", "") for t in trades)
        active = round(float(min(len(trade_dates) / n_days, 1.0)), 4) if n_days > 0 else 0.0
        m["active_days_pct"] = active
        m["exposure_pct"]    = active   # legacy alias (trade-day frequency)

        # Use effective_price for notional volume so turnover reflects actual cash flow
        total_traded = sum(
            t.get("shares", 0) * (t.get("effective_price") or t.get("price", 0))
            for t in trades
        )
        avg_pv = float(np.mean(account_values)) if account_values else 1.0
        m["turnover"] = round(float(total_traded / avg_pv), 4) if avg_pv > 0 else 0.0

    return m
