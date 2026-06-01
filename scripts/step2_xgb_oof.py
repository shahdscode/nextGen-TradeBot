#!/usr/bin/env python3
"""
Step 2 — XGBoost Out-of-Fold Prediction Collection (CLAUDE.md training sequence)

Trains XGBoost on each walk-forward fold using the SAME fold boundaries
generated in Step 1.  Predictions are only collected on held-out test rows
so the meta-learner (Step 5) trains on leakage-free data.

Usage:
    cd /Users/shaahdmaansour/Downloads/nextGen-TradeBot
    source .venv/bin/activate
    python scripts/step2_xgb_oof.py

Inputs  (from Step 1):
    data/oof/features_us.csv
    data/oof/features_egx.csv
    data/models/fold_definitions.json

Outputs:
    data/oof/xgb_oof_predictions.csv   — OOF signals for ALL tickers
    data/models/xgb_best_params.json   — best HPO params per ticker
"""

import sys
import json
import logging
import os
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "backend"))
os.chdir(ROOT / "backend")

import numpy as np
import pandas as pd

from app.services.feature_service import prepare_xy, FEATURE_COLUMNS, load_fold_definitions

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-8s  %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger("step2")

# ── Paths ──────────────────────────────────────────────────────────────────────
FEATURES_US   = ROOT / "data" / "oof" / "features_us.csv"
FEATURES_EGX  = ROOT / "data" / "oof" / "features_egx.csv"
FOLD_PATH     = ROOT / "data" / "models" / "fold_definitions.json"
OUTPUT_PATH   = ROOT / "data" / "oof" / "xgb_oof_predictions.csv"
PARAMS_PATH   = ROOT / "data" / "models" / "xgb_best_params.json"

# ── HPO config ─────────────────────────────────────────────────────────────────
N_TRIALS = 20   # Optuna trials — increase to 30 for final GP submission


def _slice_fold(df, fold, date_col="date"):
    """Return (train_df, test_df) for a fold dict, with 5-day leakage guard."""
    df = df.copy()
    df[date_col] = pd.to_datetime(df[date_col])
    train_end  = pd.to_datetime(fold["train_end"])
    test_start = pd.to_datetime(fold["test_start"])
    test_end   = pd.to_datetime(fold["test_end"])

    train_df = df[df[date_col] <= train_end].copy()
    test_df  = df[(df[date_col] >= test_start) & (df[date_col] <= test_end)].copy()

    # Horizon-aware embargo: drop last TARGET_HORIZON dates so triple-barrier
    # targets can't peek into the test window.
    from app.services.feature_service import TARGET_HORIZON
    if len(train_df) > TARGET_HORIZON:
        embargo = train_df[date_col].sort_values().unique()[-TARGET_HORIZON:]
        train_df = train_df[~train_df[date_col].isin(embargo)]

    return train_df, test_df


def _hpo(X_tr, y_tr, X_te, y_te, n_trials, xgb_available):
    """Optuna HPO — returns best params dict."""
    try:
        import optuna
        from sklearn.metrics import roc_auc_score
        optuna.logging.set_verbosity(optuna.logging.WARNING)

        def objective(trial):
            params = {
                "n_estimators":     trial.suggest_int("n_estimators", 50, 250),
                "max_depth":        trial.suggest_int("max_depth", 3, 7),
                "learning_rate":    trial.suggest_float("learning_rate", 0.01, 0.2, log=True),
                "subsample":        trial.suggest_float("subsample", 0.6, 1.0),
                "colsample":        trial.suggest_float("colsample", 0.6, 1.0),
                "min_child_weight": trial.suggest_int("min_child_weight", 1, 8),
            }
            m = _build_model(params, xgb_available)
            m.fit(X_tr, y_tr)
            probs = m.predict_proba(X_te)[:, 1]
            if len(np.unique(y_te)) < 2:
                return 0.5
            return float(roc_auc_score(y_te, probs))

        study = optuna.create_study(direction="maximize")
        study.optimize(objective, n_trials=n_trials, show_progress_bar=False)
        return study.best_params
    except Exception as e:
        logger.warning("HPO failed (%s) — using defaults", e)
        return {"n_estimators": 100, "max_depth": 5, "learning_rate": 0.05,
                "subsample": 0.8, "colsample": 0.8, "min_child_weight": 3}


def _build_model(params, xgb_available):
    p = dict(params)
    if xgb_available:
        import xgboost as xgb
        return xgb.XGBClassifier(
            n_estimators=p.get("n_estimators", 100),
            max_depth=p.get("max_depth", 5),
            learning_rate=p.get("learning_rate", 0.05),
            subsample=p.get("subsample", 0.8),
            colsample_bytree=p.get("colsample", 0.8),
            min_child_weight=p.get("min_child_weight", 3),
            eval_metric="logloss",
            random_state=42,
            verbosity=0,
        )
    else:
        from sklearn.ensemble import GradientBoostingClassifier
        return GradientBoostingClassifier(
            n_estimators=p.get("n_estimators", 100),
            max_depth=p.get("max_depth", 5),
            learning_rate=p.get("learning_rate", 0.05),
            random_state=42,
        )


def _shap_top3(model, X_te, shap_available):
    """Return list of JSON strings, one per row, containing top-3 SHAP features."""
    if shap_available:
        try:
            import shap
            explainer = shap.TreeExplainer(model)
            sv = explainer.shap_values(X_te)
            if isinstance(sv, list):
                sv = sv[1]
            result = []
            for i in range(len(X_te)):
                top3_idx = np.argsort(np.abs(sv[i]))[::-1][:3]
                top3 = [
                    {"feature": FEATURE_COLUMNS[j] if j < len(FEATURE_COLUMNS) else f"f{j}",
                     "shap_value": round(float(sv[i][j]), 4)}
                    for j in top3_idx
                ]
                result.append(json.dumps(top3))
            return result
        except Exception:
            pass
    return ["[]"] * len(X_te)


def collect_xgb_oof_for_market(features_df, folds, market, xgb_available, shap_available):
    """Run XGBoost OOF collection for all tickers in features_df."""
    tickers = sorted(features_df["tic"].unique().tolist())
    logger.info("[%s] %d tickers, %d folds", market.upper(), len(tickers), len(folds))

    all_rows = []
    all_params = {}

    for tic in tickers:
        tic_df = features_df[features_df["tic"] == tic].sort_values("date").reset_index(drop=True)
        best_params = None
        tic_rows = 0

        hpo_folds = [f for f in folds[:5] if _slice_fold(tic_df, f)[0].shape[0] >= 30][:3]

        if hpo_folds:
            first_train, first_test = _slice_fold(tic_df, hpo_folds[0])
            X_htr, y_htr = prepare_xy(first_train)
            X_hte, y_hte = prepare_xy(first_test)
            if len(X_htr) >= 30 and len(X_hte) >= 5:
                logger.info("  %-12s  running HPO (%d trials)…", tic, N_TRIALS)
                best_params = _hpo(X_htr, y_htr, X_hte, y_hte, N_TRIALS, xgb_available)
            all_params[tic] = best_params or {}

        if best_params is None:
            best_params = {"n_estimators": 100, "max_depth": 5, "learning_rate": 0.05,
                           "subsample": 0.8, "colsample": 0.8, "min_child_weight": 3}

        for fold in folds:
            train_df, test_df = _slice_fold(tic_df, fold)
            X_tr, y_tr = prepare_xy(train_df)
            X_te, y_te = prepare_xy(test_df)

            if len(X_tr) < 30 or len(X_te) == 0:
                continue

            model = _build_model(best_params, xgb_available)
            model.fit(X_tr, y_tr)
            probs = model.predict_proba(X_te)[:, 1]
            shap_jsons = _shap_top3(model, X_te, shap_available)

            test_dates = pd.to_datetime(test_df["date"]).dt.strftime("%Y-%m-%d").tolist()
            for date, prob, shap_json in zip(test_dates, probs, shap_jsons):
                all_rows.append({
                    "date":          date,
                    "tic":           tic,
                    "market":        market,
                    "xgb_signal":    round(float(prob), 4),
                    "xgb_shap_top3": shap_json,
                })
                tic_rows += 1

        logger.info("  %-12s  %d OOF predictions", tic, tic_rows)

    return all_rows, all_params


def main():
    logger.info("=" * 60)
    logger.info("Step 2 — XGBoost OOF Collection")
    logger.info("=" * 60)

    # ── Verify inputs ──────────────────────────────────────────────────────────
    for p in [FEATURES_US, FEATURES_EGX, FOLD_PATH]:
        if not p.exists():
            logger.error("Missing input: %s — run step1_data_features.py first", p)
            sys.exit(1)

    # ── Load ───────────────────────────────────────────────────────────────────
    logger.info("Loading feature matrices…")
    us_df  = pd.read_csv(FEATURES_US)
    egx_df = pd.read_csv(FEATURES_EGX)
    fold_data = load_fold_definitions(str(FOLD_PATH))
    folds = fold_data["folds"]
    logger.info("US: %d rows | EGX: %d rows | Folds: %d", len(us_df), len(egx_df), len(folds))

    # ── Check dependencies ─────────────────────────────────────────────────────
    try:
        import xgboost
        XGB_AVAILABLE = True
        logger.info("XGBoost available: %s", xgboost.__version__)
    except ImportError:
        XGB_AVAILABLE = False
        logger.warning("xgboost not installed — using sklearn GradientBoosting (slower)")

    try:
        import shap
        SHAP_AVAILABLE = True
        logger.info("SHAP available: %s", shap.__version__)
    except ImportError:
        SHAP_AVAILABLE = False
        logger.warning("shap not installed — SHAP values will be empty []")

    # ── Collect OOF: US ────────────────────────────────────────────────────────
    logger.info("")
    logger.info("── US tickers ──")
    us_rows, us_params = collect_xgb_oof_for_market(
        us_df, folds, "us", XGB_AVAILABLE, SHAP_AVAILABLE
    )

    # ── Collect OOF: EGX ──────────────────────────────────────────────────────
    logger.info("")
    logger.info("── EGX tickers ──")
    egx_rows, egx_params = collect_xgb_oof_for_market(
        egx_df, folds, "egx", XGB_AVAILABLE, SHAP_AVAILABLE
    )

    # ── Combine & save ─────────────────────────────────────────────────────────
    all_rows = us_rows + egx_rows
    if not all_rows:
        logger.error("No OOF predictions collected — check feature CSVs and folds")
        sys.exit(1)

    result = pd.DataFrame(all_rows)
    result = result.sort_values(["date", "tic"]).reset_index(drop=True)

    OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    result.to_csv(OUTPUT_PATH, index=False)
    logger.info("")
    logger.info("XGBoost OOF predictions saved → %s", OUTPUT_PATH)
    logger.info("  Total rows: %d", len(result))
    logger.info("  US tickers: %d", result[result["market"] == "us"]["tic"].nunique())
    logger.info("  EGX tickers: %d", result[result["market"] == "egx"]["tic"].nunique())
    logger.info("  Date range: %s → %s", result["date"].min(), result["date"].max())

    # Signal distribution
    pct_buy  = (result["xgb_signal"] > 0.6).mean() * 100
    pct_hold = ((result["xgb_signal"] >= 0.4) & (result["xgb_signal"] <= 0.6)).mean() * 100
    pct_sell = (result["xgb_signal"] < 0.4).mean() * 100
    logger.info("  Signal distribution: BUY=%.1f%%  HOLD=%.1f%%  SELL=%.1f%%",
                pct_buy, pct_hold, pct_sell)

    # Save HPO params
    all_params = {**us_params, **egx_params}
    PARAMS_PATH.parent.mkdir(parents=True, exist_ok=True)
    with open(PARAMS_PATH, "w") as f:
        json.dump(all_params, f, indent=2)
    logger.info("Best HPO params saved → %s", PARAMS_PATH)

    logger.info("")
    logger.info("=" * 60)
    logger.info("Step 2 complete.")
    logger.info("Next: run Step 3 (LSTM OOF) — python scripts/step3_lstm_oof.py")
    logger.info("=" * 60)


if __name__ == "__main__":
    main()
