"""
End-to-end alpha pipeline: validate data → XGB per ticker → hybrid PPO.
"""
from __future__ import annotations

import uuid
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

import pandas as pd

from app.config import settings
from app.database import SessionLocal, Job, Run
from app.services.walk_forward import WALK_FORWARD_PRESETS, RECOMMENDED_TICKERS
from app.services.price_data import detect_dataset_quality

MIN_TICKERS = 3
MIN_ROWS_PER_TICKER = 200
MIN_XGB_AUC = 0.52


def get_research_preset(name: str = "research_v1") -> Dict[str, Any]:
    return WALK_FORWARD_PRESETS.get(name, WALK_FORWARD_PRESETS["research_v1"])


def validate_data_job(data_job_id: str) -> Dict[str, Any]:
    """Check CSV exists, tickers, date range, Yahoo quality."""
    path = Path(settings.data_dir) / data_job_id / "data.csv"
    issues: List[str] = []
    checks: List[str] = []

    if not path.exists():
        return {"ok": False, "issues": [f"data.csv not found for job {data_job_id}"], "checks": []}

    df = pd.read_csv(path)
    if df.empty:
        return {"ok": False, "issues": ["CSV is empty"], "checks": []}

    if "tic" not in df.columns:
        issues.append("Missing 'tic' column — re-download with multiple tickers")
    tickers = sorted(df["tic"].unique().tolist()) if "tic" in df.columns else []
    if len(tickers) < MIN_TICKERS:
        issues.append(f"Only {len(tickers)} ticker(s) — use ≥{MIN_TICKERS} (apply recommended list on Data page)")

    if "date" in df.columns:
        df["date"] = pd.to_datetime(df["date"])
        checks.append(f"Date range: {df['date'].min().date()} → {df['date'].max().date()}")
        per_ticker = df.groupby("tic").size() if "tic" in df.columns else pd.Series()
        thin = [t for t, n in per_ticker.items() if n < MIN_ROWS_PER_TICKER]
        if thin:
            issues.append(f"Thin history for: {thin[:5]} (<{MIN_ROWS_PER_TICKER} rows)")

    quality = detect_dataset_quality(df, tickers) if tickers else {}
    if quality.get("issues"):
        issues.extend(quality["issues"][:3])

    preset = get_research_preset()
    return {
        "ok": len(issues) == 0,
        "issues": issues,
        "checks": checks,
        "tickers": tickers,
        "row_count": len(df),
        "quality": quality,
        "preset": preset,
        "recommended_tickers": RECOMMENDED_TICKERS,
    }


def list_xgb_runs_for_job(data_job_id: str) -> List[Dict[str, Any]]:
    db = SessionLocal()
    try:
        runs = (
            db.query(Run)
            .filter(Run.data_job_id == data_job_id, Run.algorithm == "xgboost", Run.status == "done")
            .order_by(Run.created_at.desc())
            .all()
        )
        out = []
        for r in runs:
            m = r.metrics_json or {}
            hp = r.hyperparams or {}
            out.append({
                "run_id": r.id,
                "ticker": hp.get("ticker", "?"),
                "mean_auc": m.get("mean_auc", 0),
                "mean_accuracy": m.get("mean_accuracy", 0),
                "model_path": r.model_path,
            })
        return out
    finally:
        db.close()


def best_xgb_run_per_ticker(data_job_id: str) -> Dict[str, str]:
    """ticker → run_id with highest mean_auc for that data job."""
    runs = list_xgb_runs_for_job(data_job_id)
    best: Dict[str, Dict[str, Any]] = {}
    for r in runs:
        t = r["ticker"]
        if t not in best or r["mean_auc"] > best[t]["mean_auc"]:
            best[t] = r
    return {t: v["run_id"] for t, v in best.items()}


def pick_primary_xgb_run_id(data_job_id: str) -> Optional[str]:
    """Best AUC run among tickers; prefers AAPL/MSFT/SPY if tied."""
    runs = list_xgb_runs_for_job(data_job_id)
    if not runs:
        return None
    priority = {"AAPL": 3, "MSFT": 2, "SPY": 2, "GOOGL": 1}
    runs.sort(key=lambda r: (r["mean_auc"], priority.get(r["ticker"], 0)), reverse=True)
    if runs[0]["mean_auc"] < MIN_XGB_AUC:
        return runs[0]["run_id"]  # still return best effort with warning
    return runs[0]["run_id"]


def queue_xgb_batch(data_job_id: str, tickers: Optional[List[str]] = None, n_trials: int = 25) -> Dict[str, Any]:
    """Queue one XGBoost Celery task per ticker."""
    from app.tasks.ml_tasks import train_xgboost_task

    val = validate_data_job(data_job_id)
    if not val["ok"] and not tickers:
        return {"ok": False, "validation": val, "runs": []}

    if not tickers:
        tickers = val.get("tickers") or []
    # Prefer liquid names from recommended list when present in CSV
    rec = [t for t in RECOMMENDED_TICKERS if t in tickers]
    tickers = rec if len(rec) >= MIN_TICKERS else tickers[:12]

    queued = []
    db = SessionLocal()
    try:
        for ticker in tickers:
            run_id = str(uuid.uuid4())
            run = Run(
                id=run_id,
                data_job_id=data_job_id,
                algorithm="xgboost",
                model_type="xgboost",
                status="pending",
                created_at=datetime.utcnow(),
                hyperparams={"ticker": ticker, "n_trials": n_trials, "batch": True},
            )
            db.add(run)
            queued.append({"ticker": ticker, "run_id": run_id})
        db.commit()
    finally:
        db.close()

    for q in queued:
        train_xgboost_task.delay(q["run_id"], data_job_id, q["ticker"], n_trials)

    return {
        "ok": True,
        "validation": val,
        "queued": queued,
        "message": f"Queued XGBoost for {len(queued)} tickers. Wait for done, then train PPO.",
    }


def pipeline_status(data_job_id: str) -> Dict[str, Any]:
    """Summarize XGB + PPO readiness for a data job."""
    xgb_runs = list_xgb_runs_for_job(data_job_id)
    pending = [r for r in xgb_runs if False]  # all listed are done

    db = SessionLocal()
    try:
        xgb_pending = (
            db.query(Run)
            .filter(Run.data_job_id == data_job_id, Run.algorithm == "xgboost", Run.status.in_(["pending", "running"]))
            .count()
        )
        ppo_runs = (
            db.query(Run)
            .filter(Run.data_job_id == data_job_id, Run.algorithm == "ppo")
            .order_by(Run.created_at.desc())
            .limit(5)
            .all()
        )
        ppo_list = [
            {"run_id": r.id, "status": r.status, "metrics": r.metrics_json}
            for r in ppo_runs
        ]
    finally:
        db.close()

    primary_xgb = pick_primary_xgb_run_id(data_job_id)
    good_xgb = [r for r in xgb_runs if (r.get("mean_auc") or 0) >= MIN_XGB_AUC]

    preset = get_research_preset()
    return {
        "data_job_id": data_job_id,
        "xgb_done": len(xgb_runs),
        "xgb_pending": xgb_pending,
        "xgb_quality_ok": len(good_xgb),
        "primary_xgb_run_id": primary_xgb,
        "xgb_by_ticker": best_xgb_run_per_ticker(data_job_id),
        "xgb_runs": xgb_runs,
        "ppo_runs": ppo_list,
        "ready_for_ppo": primary_xgb is not None and xgb_pending == 0,
        "train_window": preset["train"],
        "test_window": preset["test"],
        "min_xgb_auc": MIN_XGB_AUC,
    }
