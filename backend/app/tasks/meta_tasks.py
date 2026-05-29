"""
Celery tasks for meta-learner pipeline:
  - OOF collection (collect_oof_task)
  - Meta-learner training (train_meta_learner_task)
  - Model calibration (calibrate_model_task)

Follows the same pattern as ml_tasks.py:
  - @celery_app.task(bind=True, name="...")
  - Run/Job status updated running → done | failed
  - try/except/finally with db.close()
"""
import os
import uuid
from datetime import datetime

from app.celery_app import celery_app
from app.database import SessionLocal, Run, Job
from app.config import settings


@celery_app.task(bind=True, name="meta_tasks.collect_oof")
def collect_oof_task(
    self,
    job_id: str,
    data_job_id: str = None,
    market: str = "us",
    train_months: int = 12,
    test_months: int = 1,
):
    """
    Collect out-of-fold predictions from all trained base models.

    1. Loads feature data from the completed data job
    2. Computes cross-sectional momentum rank
    3. Downloads VIX (US tickers)
    4. Generates fold definitions → saved to data/models/fold_definitions.json
    5. Runs XGBoost OOF, LSTM OOF, RL signals
    6. Merges + saves → data/oof/merged_oof_dataset.csv
    """
    import pandas as pd
    from pathlib import Path
    from app.services.feature_service import (
        add_cross_sectional_rank,
        download_vix,
        generate_walk_forward_folds,
        save_fold_definitions,
    )
    from app.services.oof_collector_service import (
        collect_xgb_oof,
        collect_lstm_oof,
        collect_rl_signals,
        merge_oof_predictions,
        save_oof_dataset,
    )

    db = SessionLocal()
    try:
        job = db.query(Job).filter(Job.id == job_id).first()
        if job:
            job.status = "running"
            job.updated_at = datetime.utcnow()
            db.commit()

        # ── Load feature data ──────────────────────────────────────────────
        data_path = None
        if data_job_id:
            data_job = db.query(Job).filter(Job.id == data_job_id).first()
            if data_job and data_job.result_path:
                data_path = data_job.result_path

        if data_path is None:
            # Fall back to first available parquet/csv in data_dir
            for ext in ("*.parquet", "*.csv"):
                import glob
                matches = sorted(glob.glob(os.path.join(settings.data_dir, ext)))
                if matches:
                    data_path = matches[-1]
                    break

        if data_path is None:
            raise FileNotFoundError("No feature data found. Run a data download job first.")

        if data_path.endswith(".parquet"):
            df = pd.read_parquet(data_path)
        else:
            df = pd.read_csv(data_path)

        # ── Cross-sectional rank (must happen before per-ticker build_features) ──
        df = add_cross_sectional_rank(df)

        # ── VIX (US tickers only) ──────────────────────────────────────────
        vix_df = None
        if market == "us":
            dates = pd.to_datetime(df["date"])
            vix_df = download_vix(
                str(dates.min().date()),
                str(dates.max().date()),
            )

        # ── Fold definitions ───────────────────────────────────────────────
        fold_path = os.path.join(settings.models_dir, "fold_definitions.json")
        if not os.path.exists(fold_path):
            # Generate folds from feature data (pick one ticker to define dates)
            sample_ticker = df["tic"].iloc[0]
            sample = df[df["tic"] == sample_ticker].copy()
            sample = sample.sort_values("date")
            folds = generate_walk_forward_folds(
                sample, train_months=train_months, test_months=test_months
            )
            save_fold_definitions(folds, fold_path, train_months, test_months)

        # ── XGBoost OOF ───────────────────────────────────────────────────
        xgb_oof  = collect_xgb_oof(df, fold_path, vix_df=vix_df)
        save_oof_dataset(xgb_oof,  os.path.join(settings.oof_dir, "xgb_oof_predictions.csv"))

        # ── LSTM OOF ──────────────────────────────────────────────────────
        lstm_oof = collect_lstm_oof(df, fold_path, vix_df=vix_df)
        save_oof_dataset(lstm_oof, os.path.join(settings.oof_dir, "lstm_oof_predictions.csv"))

        # ── RL signals (use whatever published models exist) ───────────────
        rl_model_paths = {}
        for alg in ("ppo", "a2c", "ddpg", "td3", "sac"):
            run = (
                db.query(Run)
                .filter(
                    Run.published.is_(True),
                    Run.status == "done",
                    Run.algorithm == alg,
                    Run.market == market,
                )
                .order_by(Run.updated_at.desc())
                .first()
            )
            if run and run.model_path:
                rl_model_paths[alg] = run.model_path

        # Use fold definitions for test period
        from app.services.feature_service import load_fold_definitions, build_features, prepare_xy
        fold_defs = load_fold_definitions(fold_path)
        last_fold = fold_defs["folds"][-1]

        # Build test df from last fold period
        test_rows = df[
            (pd.to_datetime(df["date"]).astype(str) >= last_fold["test_start"]) &
            (pd.to_datetime(df["date"]).astype(str) <= last_fold["test_end"])
        ].copy()

        rl_signals = collect_rl_signals(rl_model_paths, test_rows)
        save_oof_dataset(rl_signals, os.path.join(settings.oof_dir, "rl_signals.csv"))

        # ── Regime & sentiment history (stub — populated over time) ──────
        regime_history    = pd.DataFrame(columns=["date", "regime"])
        sentiment_history = pd.DataFrame(columns=["date", "ticker", "sentiment_score"])

        # ── Merge ─────────────────────────────────────────────────────────
        merged = merge_oof_predictions(
            xgb_oof, lstm_oof, rl_signals,
            regime_history, sentiment_history, df,
        )
        merged_path = os.path.join(settings.oof_dir, "merged_oof_dataset.csv")
        save_oof_dataset(merged, merged_path)

        if job:
            job.status = "done"
            job.result_path = merged_path
            job.updated_at = datetime.utcnow()
            job.meta = {**(job.meta or {}), "n_rows": len(merged), "path": merged_path}
            db.commit()

        return {"status": "done", "n_rows": len(merged), "path": merged_path}

    except Exception as exc:
        if job:
            job = db.query(Job).filter(Job.id == job_id).first()
            if job:
                job.status = "failed"
                job.error = str(exc)
                job.updated_at = datetime.utcnow()
                db.commit()
        raise
    finally:
        db.close()


@celery_app.task(bind=True, name="meta_tasks.train_meta_learner")
def train_meta_learner_task(self, run_id: str, oof_dataset_path: str):
    """
    Train the logistic regression meta-learner on OOF predictions.
    """
    from app.services.meta_learner_service import train_meta_learner

    db = SessionLocal()
    try:
        run = db.query(Run).filter(Run.id == run_id).first()
        if run:
            run.status = "running"
            run.updated_at = datetime.utcnow()
            db.commit()

        model_path = os.path.join(settings.models_dir, "meta_learner.pkl")
        result = train_meta_learner(
            oof_dataset_path=oof_dataset_path,
            model_save_path=model_path,
        )

        if run:
            run.status = "done"
            run.model_path = model_path
            run.metrics_json = {
                "auc":         result["auc"],
                "accuracy":    result["accuracy"],
                "brier_score": result["brier_score"],
                "n_train":     result["n_train"],
                "n_val":       result["n_val"],
                "top_features": result["top_features"],
            }
            run.updated_at = datetime.utcnow()
            db.commit()

        return {"status": "done", "model_path": model_path, "metrics": result}

    except Exception as exc:
        if run:
            run = db.query(Run).filter(Run.id == run_id).first()
            if run:
                run.status = "failed"
                run.error = str(exc)
                run.updated_at = datetime.utcnow()
                db.commit()
        raise
    finally:
        db.close()


@celery_app.task(bind=True, name="meta_tasks.calibrate_model")
def calibrate_model_task(self, job_id: str, run_id: str):
    """
    Fit Platt scaling calibration for a trained XGBoost or LSTM run.

    Uses OOF predictions as the calibration set (correctly held-out).
    Saves calibrator.pkl and a reliability diagram PNG.
    """
    import numpy as np
    import pandas as pd
    from app.services.calibration_service import fit_calibrator, plot_reliability_diagram

    db = SessionLocal()
    try:
        job = db.query(Job).filter(Job.id == job_id).first()
        if job:
            job.status = "running"
            job.updated_at = datetime.utcnow()
            db.commit()

        run = db.query(Run).filter(Run.id == run_id).first()
        if not run:
            raise ValueError(f"Run {run_id} not found")

        algorithm = run.algorithm  # "xgboost" or "lstm"
        signal_col = f"{algorithm}_signal" if algorithm != "xgboost" else "xgb_signal"

        # Load OOF dataset as the calibration source
        oof_path = os.path.join(settings.oof_dir, "merged_oof_dataset.csv")
        if not os.path.exists(oof_path):
            raise FileNotFoundError(f"Merged OOF dataset not found: {oof_path}")

        oof = pd.read_csv(oof_path)
        if signal_col not in oof.columns or "target_5d" not in oof.columns:
            raise ValueError(f"OOF dataset missing columns: {signal_col} or target_5d")

        raw_scores     = oof[signal_col].dropna().values.astype(np.float32)
        actual_outcomes = oof.loc[oof[signal_col].notna(), "target_5d"].values.astype(int)

        calibrator_path  = os.path.join(settings.models_dir, f"calibrator_{run_id[:8]}.pkl")
        diagram_path     = os.path.join(settings.results_dir, f"reliability_{run_id[:8]}.png")

        cal_result = fit_calibrator(raw_scores, actual_outcomes, calibrator_path)
        plot_reliability_diagram(cal_result["reliability_data"], diagram_path)

        if job:
            job.status = "done"
            job.result_path = calibrator_path
            job.updated_at = datetime.utcnow()
            job.meta = {
                **(job.meta or {}),
                "brier_before":          cal_result["brier_score_before"],
                "brier_after":           cal_result["brier_score_after"],
                "reliability_diagram":   diagram_path,
                "calibrator_path":       calibrator_path,
            }
            db.commit()

        return {
            "status":           "done",
            "calibrator_path":  calibrator_path,
            "brier_before":     cal_result["brier_score_before"],
            "brier_after":      cal_result["brier_score_after"],
            "reliability_diagram": diagram_path,
        }

    except Exception as exc:
        if job:
            job = db.query(Job).filter(Job.id == job_id).first()
            if job:
                job.status = "failed"
                job.error = str(exc)
                job.updated_at = datetime.utcnow()
                db.commit()
        raise
    finally:
        db.close()
