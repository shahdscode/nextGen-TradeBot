#!/usr/bin/env python3
"""
Experiment — Regime-Conditional Stacking for the Meta-Learner.

Tests whether teaching the stack *which base model to trust in which regime*
(via interaction features and/or a non-linear meta-learner) beats the current
additive logistic stack.

Three meta-learners, identical time-ordered 70/30 split (no leakage):
  A. Logistic (baseline)              — 7 signals + regime_bull/bear + vix_zscore
  B. Logistic + interactions          — A  +  signal×{bull, bear, vix}  (21 extra terms)
  C. XGBoost meta                     — same features as B, non-linear (captures interactions)

Reports AUC / accuracy / Brier for each, plus the AUC delta vs baseline.
Does NOT touch the production meta-learner — pure evaluation.

Usage:
    cd /Users/shaahdmaansour/Downloads/nextGen-TradeBot
    source .venv/bin/activate
    python scripts/experiment_meta_regime.py
"""
import sys, json
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "backend"))

import numpy as np
import pandas as pd
from sklearn.linear_model import LogisticRegression
from sklearn.preprocessing import StandardScaler
from sklearn.metrics import roc_auc_score, accuracy_score, brier_score_loss

OOF = ROOT / "data" / "oof" / "merged_oof_dataset.csv"
SIGNALS = ["xgb_signal", "lstm_signal", "ppo_signal", "a2c_signal",
           "ddpg_signal", "td3_signal", "sac_signal"]
REGIME = ["regime_bull", "regime_bear", "vix_zscore"]
CONTEXT = REGIME + (["sentiment_score"] if True else [])


def load():
    df = pd.read_csv(OOF)
    df["date"] = pd.to_datetime(df["date"])
    df = df.sort_values("date").reset_index(drop=True)
    # context columns may be missing → default to 0
    for c in SIGNALS + REGIME + ["sentiment_score"]:
        if c not in df.columns:
            df[c] = 0.0
    return df


def add_interactions(df):
    """signal × {bull, bear, vix} for every base model."""
    cols = []
    for s in SIGNALS:
        for r in REGIME:
            name = f"{s}__x__{r}"
            df[name] = df[s] * df[r]
            cols.append(name)
    return cols


def split(df, feats):
    sub = df.dropna(subset=feats + ["target_5d"]).reset_index(drop=True)
    X = sub[feats].values.astype(np.float32)
    y = sub["target_5d"].values.astype(int)
    cut = int(len(sub) * 0.70)
    return X[:cut], X[cut:], y[:cut], y[cut:]


def eval_logistic(df, feats, scale=True):
    Xtr, Xv, ytr, yv = split(df, feats)
    if scale:
        sc = StandardScaler().fit(Xtr)
        Xtr, Xv = sc.transform(Xtr), sc.transform(Xv)
    m = LogisticRegression(C=1.0, max_iter=1000, random_state=42, solver="lbfgs")
    m.fit(Xtr, ytr)
    p = m.predict_proba(Xv)[:, 1]
    return _metrics(yv, p, len(ytr), len(yv))


def eval_xgb(df, feats):
    Xtr, Xv, ytr, yv = split(df, feats)
    try:
        import xgboost as xgb
        m = xgb.XGBClassifier(
            n_estimators=250, max_depth=3, learning_rate=0.04,
            subsample=0.8, colsample_bytree=0.8, min_child_weight=5,
            reg_lambda=1.0, eval_metric="logloss", random_state=42, verbosity=0)
    except ImportError:
        from sklearn.ensemble import GradientBoostingClassifier
        m = GradientBoostingClassifier(n_estimators=250, max_depth=3, learning_rate=0.04, subsample=0.8)
    m.fit(Xtr, ytr)
    p = m.predict_proba(Xv)[:, 1]
    return _metrics(yv, p, len(ytr), len(yv))


def _metrics(y, p, ntr, nv):
    return {
        "auc": round(float(roc_auc_score(y, p)), 4) if len(np.unique(y)) > 1 else 0.5,
        "acc": round(float(accuracy_score(y, (p > 0.5).astype(int))), 4),
        "brier": round(float(brier_score_loss(y, p)), 4),
        "n_train": ntr, "n_val": nv,
    }


def main():
    print("=" * 66)
    print("Experiment — Regime-Conditional Stacking")
    print("=" * 66)
    df = load()
    print(f"Dataset: {len(df):,} rows | {df['ticker'].nunique()} tickers | "
          f"{df['date'].min().date()} → {df['date'].max().date()}")
    print(f"Target up-rate: {df['target_5d'].mean():.3f}\n")

    base_feats = SIGNALS + CONTEXT
    inter_cols = add_interactions(df)
    inter_feats = base_feats + inter_cols

    A = eval_logistic(df, base_feats)
    B = eval_logistic(df, inter_feats)
    C = eval_xgb(df, inter_feats)

    print(f"{'Meta-learner':<34}{'AUC':>8}{'Acc':>9}{'Brier':>9}{'ΔAUC':>9}")
    print("-" * 66)
    def row(name, m):
        d = m["auc"] - A["auc"]
        print(f"{name:<34}{m['auc']:>8.4f}{m['acc']:>9.4f}{m['brier']:>9.4f}{d:>+9.4f}")
    row("A. Logistic (baseline)", A)
    row("B. Logistic + interactions", B)
    row("C. XGBoost meta (non-linear)", C)
    print("-" * 66)
    print(f"   interaction terms added: {len(inter_cols)} "
          f"(7 signals × 3 regime vars)\n")

    best = max([("A", A), ("B", B), ("C", C)], key=lambda kv: kv[1]["auc"])
    print(f"Best: {best[0]}  (AUC {best[1]['auc']:.4f})")
    if best[1]["auc"] - A["auc"] < 0.005:
        print("Verdict: regime-conditioning gives < +0.005 AUC — efficiency ceiling holds.")
    else:
        print(f"Verdict: regime-conditioning improves AUC by "
              f"{best[1]['auc']-A['auc']:+.4f} — meaningful for the thesis.")

    out = ROOT / "data" / "models" / "meta_regime_experiment.json"
    out.write_text(json.dumps(
        {"baseline": A, "logistic_interactions": B, "xgboost_meta": C,
         "n_interaction_terms": len(inter_cols)}, indent=2))
    print(f"\nSaved → {out}")
    print("=" * 66)


if __name__ == "__main__":
    main()
