#!/usr/bin/env python
"""
Person 5 — Model Evaluation Script.

Produces a full comparison table across all fusion strategies for the
held-out test period, split by regime and market.

Usage
-----
    python backend/scripts/run_evaluation.py \\
        --oof  data/oof/merged_oof_dataset.csv \\
        --meta_learner data/models/meta_learner.pkl \\
        --output docs/model_evaluation.md

Output
------
docs/model_evaluation.md — thesis Chapter 4 comparison table
data/results/evaluation_summary.json — machine-readable results
"""
import argparse
import json
import os
import sys

# Allow running from repo root without installing the package
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import numpy as np
import pandas as pd


# ── Metrics ───────────────────────────────────────────────────────────────────

def _metrics(probs: np.ndarray, actual_returns: np.ndarray, targets: np.ndarray) -> dict:
    from sklearn.metrics import roc_auc_score, brier_score_loss
    auc    = float(roc_auc_score(targets, probs)) if len(np.unique(targets)) > 1 else float("nan")
    brier  = float(brier_score_loss(targets, probs))
    preds  = (probs >= 0.5).astype(int)
    wr     = float(np.mean(preds == targets))
    # Directional PnL: long on BUY, short on SELL
    pnl    = np.where(preds == 1, actual_returns, -actual_returns)
    sharpe = float(np.mean(pnl) / (np.std(pnl) + 1e-9) * np.sqrt(252))
    # Annualised return (approx.)
    ann_ret = float(np.mean(pnl) * 252)
    # Max drawdown
    cum_pnl  = np.cumsum(pnl)
    rolling_max = np.maximum.accumulate(cum_pnl)
    drawdowns = cum_pnl - rolling_max
    mdd = float(drawdowns.min())
    return {
        "auc":         round(auc,     4),
        "accuracy":    round(wr,      4),
        "win_rate":    round(wr,      4),
        "brier_score": round(brier,   4),
        "sharpe":      round(sharpe,  4),
        "ann_return":  round(ann_ret, 4),
        "max_drawdown": round(mdd,    4),
        "n":           int(len(targets)),
    }


def _fixed_probs(df: pd.DataFrame, weights: dict) -> np.ndarray:
    """Fixed-weight blended probability."""
    signal = sum(df[k].fillna(0.5) * w for k, w in weights.items() if k in df.columns)
    total  = sum(weights.values()) or 1.0
    return np.clip((signal / total).values, 0, 1)


def _meta_probs(df: pd.DataFrame, meta_path: str) -> np.ndarray:
    from app.services.meta_learner_service import predict_meta_learner, META_LEARNER_FEATURES
    if not os.path.exists(meta_path):
        return np.full(len(df), 0.5)
    probs = []
    for _, row in df.iterrows():
        fdict = {f: float(row.get(f, 0.0)) for f in META_LEARNER_FEATURES}
        probs.append(predict_meta_learner(meta_path, fdict)["probability"])
    return np.array(probs)


# ── Evaluation ────────────────────────────────────────────────────────────────

def run_evaluation(oof_path: str, meta_learner_path: str, output_path: str):
    df = pd.read_csv(oof_path)
    df = df.sort_values("date").reset_index(drop=True)
    df = df.dropna(subset=["target_5d", "actual_5d_return"])

    if len(df) < 50:
        print(f"ERROR: OOF dataset too small ({len(df)} rows). Collect more OOF data first.")
        sys.exit(1)

    # Use only the held-out 30% for evaluation (same split as meta-learner training)
    split = int(len(df) * 0.70)
    test  = df.iloc[split:].copy()
    print(f"Evaluation set: {len(test)} rows  ({test['date'].min()} – {test['date'].max()})")

    systems = {
        "Fixed (BULL weights)": _fixed_probs(test, {
            "xgb_signal": 0.45, "lstm_signal": 0.35, "ppo_signal": 0.20,
        }),
        "Fixed (equal 7-model)": _fixed_probs(test, {
            k: 1 / 7 for k in
            ["xgb_signal", "lstm_signal", "ppo_signal",
             "a2c_signal", "ddpg_signal", "td3_signal", "sac_signal"]
        }),
        "XGBoost only":  test["xgb_signal"].fillna(0.5).values,
        "LSTM only":     test["lstm_signal"].fillna(0.5).values,
        "Meta-Learner":  _meta_probs(test, meta_learner_path),
    }

    results = {}
    for name, probs in systems.items():
        results[name] = _metrics(probs, test["actual_5d_return"].values, test["target_5d"].values)

    # ── Regime-split analysis ─────────────────────────────────────────────────
    regime_results = {}
    for regime_label, mask_fn in [
        ("BULL",     lambda df: df["regime_bull"] == 1),
        ("BEAR",     lambda df: df["regime_bear"] == 1),
        ("SIDEWAYS", lambda df: (df["regime_bull"] == 0) & (df["regime_bear"] == 0)),
    ]:
        mask = mask_fn(test)
        if mask.sum() < 10:
            continue
        sub = test[mask]
        regime_results[regime_label] = {
            "Meta-Learner": _metrics(
                _meta_probs(sub, meta_learner_path),
                sub["actual_5d_return"].values,
                sub["target_5d"].values,
            ),
            "Fixed (BULL weights)": _metrics(
                _fixed_probs(sub, {"xgb_signal": 0.45, "lstm_signal": 0.35, "ppo_signal": 0.20}),
                sub["actual_5d_return"].values,
                sub["target_5d"].values,
            ),
        }

    # ── Market-split analysis ─────────────────────────────────────────────────
    market_results = {}
    if "ticker" in test.columns:
        us_mask  = ~test["ticker"].str.upper().str.endswith(".CA")
        egx_mask = test["ticker"].str.upper().str.endswith(".CA")
        for label, mask in [("US (DOW30)", us_mask), ("EGX", egx_mask)]:
            if mask.sum() < 10:
                continue
            sub = test[mask]
            market_results[label] = {
                "Meta-Learner": _metrics(
                    _meta_probs(sub, meta_learner_path),
                    sub["actual_5d_return"].values,
                    sub["target_5d"].values,
                ),
            }

    # ── Build markdown ─────────────────────────────────────────────────────────
    md = _build_markdown(results, regime_results, market_results, test)

    os.makedirs(os.path.dirname(os.path.abspath(output_path)), exist_ok=True)
    with open(output_path, "w") as f:
        f.write(md)
    print(f"\nMarkdown report → {output_path}")

    # JSON summary
    summary = {"overall": results, "by_regime": regime_results, "by_market": market_results}
    json_path = os.path.join("data", "results", "evaluation_summary.json")
    os.makedirs(os.path.dirname(json_path), exist_ok=True)
    with open(json_path, "w") as f:
        json.dump(summary, f, indent=2)
    print(f"JSON summary    → {json_path}")

    # Print quick table to console
    print("\n── Overall Results (held-out 30%) ──")
    for name, m in results.items():
        print(f"  {name:<30}  AUC={m['auc']:.4f}  Sharpe={m['sharpe']:.4f}  WR={m['win_rate']:.2%}")

    return summary


# ── Markdown builder ───────────────────────────────────────────────────────────

def _build_markdown(results, regime_results, market_results, test_df) -> str:
    lines = [
        "# Model Evaluation — NextGen TradeBot",
        "",
        f"> Evaluation period: **{test_df['date'].min()} – {test_df['date'].max()}**  ",
        f"> Samples: **{len(test_df):,}** (held-out 30% of OOF dataset)  ",
        "> Target: 5-day forward return direction  ",
        "> Transaction costs: 0.1% per trade (Almgren-Chriss slippage not applied in OOF eval)  ",
        "",
        "## Overall Performance",
        "",
        "| System | AUC | Accuracy | Win Rate | Sharpe | Ann. Return | Max DD | n |",
        "|--------|-----|----------|----------|--------|-------------|--------|---|",
    ]
    for name, m in results.items():
        lines.append(
            f"| {name} | {m['auc']:.4f} | {m['accuracy']:.2%} | {m['win_rate']:.2%} "
            f"| {m['sharpe']:.4f} | {m['ann_return']:.2%} | {m['max_drawdown']:.4f} | {m['n']:,} |"
        )

    if regime_results:
        lines += ["", "## Regime-Split Analysis", "",
                  "| Regime | System | AUC | Win Rate | Sharpe | n |",
                  "|--------|--------|-----|----------|--------|---|"]
        for regime, sys_dict in regime_results.items():
            for sys_name, m in sys_dict.items():
                lines.append(
                    f"| {regime} | {sys_name} | {m['auc']:.4f} | {m['win_rate']:.2%} "
                    f"| {m['sharpe']:.4f} | {m['n']:,} |"
                )

    if market_results:
        lines += ["", "## Market Comparison (US vs EGX)", "",
                  "| Market | AUC | Win Rate | Sharpe | n |",
                  "|--------|-----|----------|--------|---|"]
        for market, sys_dict in market_results.items():
            m = sys_dict.get("Meta-Learner", {})
            if m:
                lines.append(
                    f"| {market} | {m.get('auc', 'N/A')} | {m.get('win_rate', 0):.2%} "
                    f"| {m.get('sharpe', 'N/A')} | {m.get('n', 0):,} |"
                )

    lines += [
        "",
        "## Academic References",
        "",
        "- Wolpert (1992) — Stacked Generalization",
        "- Breiman (1996) — Stacked Regressions",
        "- Freund & Schapire (1997) — Hedge Algorithm",
        "- Kritzman et al. (2010) — Skulls, Financial Turbulence, and Risk Management",
        "- Platt (1999) — Probabilistic Outputs for Support Vector Machines",
        "- Lopez de Prado (2018) — Advances in Financial Machine Learning",
        "- Arnott et al. (2019) — Backtesting Protocol in the Machine Learning Era",
        "",
        "---",
        "*Generated by run_evaluation.py — NextGen TradeBot GP2, Nile University*",
    ]
    return "\n".join(lines) + "\n"


# ── Entry point ────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="NextGen TradeBot — model evaluation")
    parser.add_argument("--oof",          default="data/oof/merged_oof_dataset.csv",
                        help="Path to merged OOF dataset CSV")
    parser.add_argument("--meta_learner", default="data/models/meta_learner.pkl",
                        help="Path to trained meta_learner.pkl")
    parser.add_argument("--output",       default="docs/model_evaluation.md",
                        help="Output markdown path")
    args = parser.parse_args()

    run_evaluation(args.oof, args.meta_learner, args.output)
