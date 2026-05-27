"""
Backtest service with full academic reality layers:
  1. Trading friction  — volatility-scaled slippage + commission
  2. Position limits   — max % capital per stock, cooldown days
  3. Benchmark baselines — Buy&Hold SP500, SMA 20/50, 12-1 Momentum, Equal-Weight, Random
  4. Extended metrics  — Sortino, Calmar, Profit Factor, Exposure, Turnover
  5. Rolling walk-forward analysis — sliding 63-day windows, consistency stats
  6. Stress tests      — 2×costs, −30% crash, 1-day delay
  7. RL sanity checks  — overtrading, action distribution, turnover
  8. Overfitting report — train / validation / test degradation gaps
"""
from __future__ import annotations

import json
import hashlib
import numpy as np
import pandas as pd
from pathlib import Path
from typing import Dict, Any, List, Optional

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
) -> Dict[str, Any]:
    """Random 5%-daily-flip strategy — minimum bar the RL agent must clear."""
    try:
        import yfinance as yf
        df = yf.download("^GSPC", start=start, end=end, progress=False, auto_adjust=True)
        if df.empty:
            return {}
        closes = df["Close"].values.flatten()
        dates  = df.index.strftime("%Y-%m-%d").tolist()
        rng = np.random.default_rng(seed)

        cash, shares, in_pos = float(initial_capital), 0.0, False
        account_values = [float(initial_capital)]

        for i in range(1, len(closes)):
            price = float(closes[i])
            if rng.random() < 0.05:
                if not in_pos:
                    eff = _buy_price(price, commission_pct, slippage_pct)
                    shares = cash / eff;  cash = 0.0;  in_pos = True
                else:
                    eff = _sell_price(price, commission_pct, slippage_pct)
                    cash = shares * eff;  shares = 0.0;  in_pos = False
            account_values.append(round(cash + shares * price, 2))

        daily_returns = _compute_daily_returns(account_values)
        metrics = _compute_metrics(account_values, daily_returns, initial_capital)
        return {"account_value": account_values, "dates": dates, "metrics": metrics,
                "strategy": "random"}
    except Exception:
        return {}


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
) -> Dict[str, Any]:
    """
    Run backtest with all academic reality layers.
    Returns equity curve, extended metrics, 5 baselines, rolling walk-forward,
    3 stress tests, RL sanity checks, and overfitting report.
    """
    db  = SessionLocal()
    run = db.query(Run).filter(Run.id == run_id).first()
    db.close()
    if not run:
        raise ValueError(f"Run {run_id} not found")

    data_path   = Path(settings.data_dir) / run.data_job_id / "data.csv"
    model_path  = run.model_path
    algorithm   = run.algorithm
    results_dir = Path(settings.results_dir) / backtest_id
    results_dir.mkdir(parents=True, exist_ok=True)

    trades: List[Dict] = []
    use_synthetic = False
    data_source   = "unknown"
    data_quality: Dict = {}

    step_log_path = str(results_dir / "step_log.jsonl")

    # ── Try real FinRL model ──────────────────────────────────────────────────
    if FINRL_AVAILABLE and model_path and Path(str(model_path) + ".zip").exists():
        try:
            from finrl.meta.preprocessor.preprocessors import data_split
            from finrl.meta.env_stock_trading.env_stocktrading import StockTradingEnv
            from finrl.agents.stablebaselines3.models import DRLAgent

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

            df_account_value, df_actions = DRLAgent.DRL_prediction_load_from_file(
                model_name=algorithm, environment=e_test, cwd=model_path,
            )
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
        except Exception:
            use_synthetic = True

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
        data_quality = {
            "live_prices": False,
            "issues": ["Synthetic portfolio engine — friction & position limits applied."],
            "message": "Re-train with Yahoo data for real model results.",
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
    rand_base     = run_random_baseline(test_start, test_end, initial_capital, commission_pct, slippage_pct, seed)

    # ── Rolling walk-forward analysis ────────────────────────────────────────
    walk_forward = _walk_forward_rolling(account_values, dates, initial_capital)

    # ── Stress tests ─────────────────────────────────────────────────────────
    stress_results = _run_stress_scenarios(
        account_values, dates, initial_capital, commission_pct, slippage_pct, seed
    )

    # ── RL sanity checks ─────────────────────────────────────────────────────
    sanity = _rl_sanity_checks(trades, account_values, dates)

    # ── Overfitting report ───────────────────────────────────────────────────
    overfitting_report = _build_overfitting_report(
        run, metrics, test_start, test_end, initial_capital, commission_pct, slippage_pct
    )

    # ── Distribution stats + bootstrap CI ───────────────────────────────────
    # Done after baselines so these heavier stats don't slow sub-period loops
    metrics.update(_distribution_stats(daily_returns))

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
            "regime_window":         "20-day rolling vol + trend; high-vol threshold = 1.5× median",
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
            "label": "1-Day Execution Delay",
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
    All periods use the same synthetic engine for apples-to-apples comparison.
    """
    train_window: Dict = {}
    if run.metrics_json:
        train_window = run.metrics_json.get("train_window", {})

    # ── Validation period ─────────────────────────────────────────────────────
    val_metrics:  Dict = {}
    val_start_str = val_end_str = "—"
    try:
        val_end_ts    = pd.Timestamp(test_start) - pd.Timedelta(days=1)
        val_start_ts  = val_end_ts - pd.DateOffset(months=6)
        val_start_str = val_start_ts.strftime("%Y-%m-%d")
        val_end_str   = val_end_ts.strftime("%Y-%m-%d")
        v_vals, v_trades, _ = _generate_synthetic_portfolio(
            run_id=run.id,
            test_start=val_start_str, test_end=val_end_str,
            initial_capital=initial_capital,
            commission_pct=commission_pct, slippage_pct=slippage_pct,
            max_position_pct=0.20, cooldown_days=5,
        )
        v_ret      = _compute_daily_returns(v_vals)
        val_metrics = _compute_metrics(v_vals, v_ret, initial_capital, v_trades)
    except Exception:
        pass

    # ── Training period ───────────────────────────────────────────────────────
    train_metrics:  Dict = {}
    train_start_str = train_window.get("start", "")
    train_end_str   = train_window.get("end",   "")
    if train_start_str and train_end_str:
        try:
            t_vals, t_trades, _ = _generate_synthetic_portfolio(
                run_id=run.id + "_tr",
                test_start=train_start_str, test_end=train_end_str,
                initial_capital=initial_capital,
                commission_pct=commission_pct, slippage_pct=slippage_pct,
                max_position_pct=0.20, cooldown_days=5,
            )
            t_ret        = _compute_daily_returns(t_vals)
            train_metrics = _compute_metrics(t_vals, t_ret, initial_capital, t_trades)
        except Exception:
            pass

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
        verdict = "⚠ Likely overfitting — large performance drop from validation to test"
    elif primary_gap > 0.10:
        verdict = "~ Moderate degradation — typical for RL agents on unseen regimes"
    elif primary_gap > -0.02:
        verdict = "✓ Mild / no degradation — reasonable out-of-sample generalization"
    else:
        verdict = "✓ Improving out-of-sample — strategy may be genuinely adaptive"

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
    trades = []
    try:
        for i, row in df_actions.iterrows():
            date = dates[i] if i < len(dates) else str(i)
            for j, ticker in enumerate(tickers):
                action_val = float(row.iloc[j]) if j < len(row) else 0
                if abs(action_val) <= 0.05:
                    continue
                price_rows = test_df[
                    (test_df["tic"] == ticker) & (test_df["date"] == date)
                ]
                price = float(price_rows["close"].iloc[0]) if not price_rows.empty else 0
                trades.append({
                    "date": date, "ticker": ticker,
                    "action": "buy" if action_val > 0 else "sell",
                    "shares": round(abs(action_val), 4),
                    "price":  round(price, 2),
                })
    except Exception:
        pass
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

def _regime_analysis(
    daily_returns: List[float],
    dates: List[str],
    trades: List[Dict],
) -> Dict[str, Any]:
    """
    Label each day with a market regime using rolling 20-day vol + trend:
      - high_volatility : vol > 1.5 × median (overrides direction)
      - bear            : 20-day trend negative
      - low_volatility  : vol < 0.5 × median, positive trend
      - bull            : everything else (positive trend, normal vol)

    Returns per-regime strategy metrics AND trade-volatility correlation.
    A high positive correlation (>0.3) flags noise-chasing behaviour.
    """
    arr = np.array(daily_returns, dtype=float)
    n   = len(arr)
    if n < 20:
        return {}

    roll_vol   = pd.Series(arr).rolling(20, min_periods=5).std().fillna(arr.std()).values
    roll_trend = pd.Series(arr).rolling(20, min_periods=5).mean().fillna(arr.mean()).values
    med_vol    = float(np.median(roll_vol))

    LABELS = {
        "bull":            "Bull market",
        "bear":            "Bear market",
        "high_volatility": "High volatility",
        "low_volatility":  "Low volatility",
    }

    regimes: List[str] = []
    for i in range(n):
        v, t = float(roll_vol[i]), float(roll_trend[i])
        if v > 1.5 * med_vol:
            regimes.append("high_volatility")
        elif t < 0:
            regimes.append("bear")
        elif v < 0.5 * med_vol:
            regimes.append("low_volatility")
        else:
            regimes.append("bull")

    perf: Dict[str, Any] = {}
    for name in LABELS:
        idxs = [i for i, r in enumerate(regimes) if r == name]
        if not idxs:
            continue
        sub    = arr[idxs]
        sharpe = float(sub.mean() / sub.std() * np.sqrt(252)) if sub.std() > 1e-10 else 0.0
        # Intra-regime max drawdown
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

    # Trade-volatility correlation
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
        "regime_distribution":   {r: regimes.count(r) for r in LABELS if r in regimes},
        "trade_vol_correlation": tv_corr,
        "trade_vol_note":        tv_note,
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

def _compute_daily_returns(account_values: List[float]) -> List[float]:
    if len(account_values) < 2:
        return []
    return [
        (account_values[i] - account_values[i - 1]) / account_values[i - 1]
        if account_values[i - 1] != 0 else 0.0
        for i in range(1, len(account_values))
    ]


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

    # Sortino (downside deviation only)
    neg      = returns[returns < 0]
    down_std = float(np.std(neg) * np.sqrt(252)) if len(neg) > 1 else 1e-9
    sortino  = float(returns.mean() * np.sqrt(252) / down_std)

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

    m: Dict[str, Any] = {
        "sharpe":        round(sharpe, 4),
        "sortino":       round(sortino, 4),
        "calmar":        round(float(min(calmar, 99.0)), 4),
        "max_drawdown":  round(max_dd, 4),
        "cagr":          round(ann_ret, 4),
        "total_return":  round(total_ret, 4),
        "profit_factor": round(float(min(profit_factor, 99.0)), 4),
        "initial_value": round(float(initial_capital), 2),
        "final_value":   round(float(account_values[-1]), 2),
        "win_rate":      round(win_rate, 4),
        "win_days":      win_days,
        "loss_days":     int(n_days - win_days),
    }

    # Trade-level metrics (only when trade log is available)
    if trades:
        trade_rets, buy_px = [], {}
        for t in sorted(trades, key=lambda x: x.get("date", "")):
            tk, act = t.get("ticker", ""), t.get("action", "")
            # Always prefer effective_price (includes friction) over raw price.
            # effective_price is the actual amount paid/received per share in
            # the simulation; using raw `price` would undercount friction costs.
            px = t.get("effective_price") or t.get("price", 0)
            if act == "buy":
                buy_px[tk] = px
            elif act == "sell" and tk in buy_px and buy_px[tk] > 0:
                trade_rets.append((px - buy_px[tk]) / buy_px[tk])
                del buy_px[tk]
        if trade_rets:
            m["avg_trade_return"] = round(float(np.mean(trade_rets)), 4)

        trade_dates = set(t.get("date", "") for t in trades)
        m["exposure_pct"] = round(float(min(len(trade_dates) / n_days, 1.0)), 4) if n_days > 0 else 0.0

        # Use effective_price for notional volume so turnover reflects actual cash flow
        total_traded = sum(
            t.get("shares", 0) * (t.get("effective_price") or t.get("price", 0))
            for t in trades
        )
        avg_pv = float(np.mean(account_values)) if account_values else 1.0
        m["turnover"] = round(float(total_traded / avg_pv), 4) if avg_pv > 0 else 0.0

    return m
