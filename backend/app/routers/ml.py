"""
ML training endpoints for XGBoost, LSTM, and stacking meta-learner.
These are admin-only endpoints that trigger async Celery jobs.
"""
import os
import uuid
from datetime import datetime
from fastapi import APIRouter, HTTPException, Depends
from pydantic import BaseModel
from typing import List, Optional

from app.database import SessionLocal, Run, Job
from app.models.schemas import RunResponse
from app.tasks.ml_tasks import train_xgboost_task, train_lstm_task, generate_signals_task
from app.tasks.meta_tasks import collect_oof_task, train_meta_learner_task, calibrate_model_task
from app.services.regime_service import get_regime_info, train_regime_model
from app.services.auth_service import require_admin
from app.config import settings

router = APIRouter(prefix="/ml", tags=["ml"])


class XGBTrainRequest(BaseModel):
    data_job_id: str
    ticker: str
    n_trials: int = 30
    market: str = "us"


class LSTMTrainRequest(BaseModel):
    data_job_id: str
    ticker: str
    epochs: int = 30
    market: str = "us"


class SignalGenerateRequest(BaseModel):
    tickers: list
    market: str = "us"
    xgb_run_id: Optional[str] = None
    lstm_run_id: Optional[str] = None
    ppo_run_id: Optional[str] = None
    data_job_id: Optional[str] = None


@router.post("/train/xgboost", response_model=RunResponse)
def train_xgboost(req: XGBTrainRequest, _admin=Depends(require_admin)):
    run_id = str(uuid.uuid4())
    db = SessionLocal()
    try:
        run = Run(
            id=run_id,
            data_job_id=req.data_job_id,
            algorithm="xgboost",
            model_type="xgboost",
            status="pending",
            market=req.market,
            created_at=datetime.utcnow(),
            hyperparams={"ticker": req.ticker, "n_trials": req.n_trials},
        )
        db.add(run)
        db.commit()
    finally:
        db.close()

    train_xgboost_task.delay(run_id, req.data_job_id, req.ticker, req.n_trials)
    return RunResponse(run_id=run_id, algorithm="xgboost", status="pending")


@router.post("/train/lstm", response_model=RunResponse)
def train_lstm(req: LSTMTrainRequest, _admin=Depends(require_admin)):
    run_id = str(uuid.uuid4())
    db = SessionLocal()
    try:
        run = Run(
            id=run_id,
            data_job_id=req.data_job_id,
            algorithm="lstm",
            model_type="lstm",
            status="pending",
            market=req.market,
            created_at=datetime.utcnow(),
            hyperparams={"ticker": req.ticker, "epochs": req.epochs},
        )
        db.add(run)
        db.commit()
    finally:
        db.close()

    train_lstm_task.delay(run_id, req.data_job_id, req.ticker, req.epochs)
    return RunResponse(run_id=run_id, algorithm="lstm", status="pending")


@router.post("/train/regime")
def train_regime(market: str = "us", _admin=Depends(require_admin)):
    result = train_regime_model(market=market)
    return result


@router.get("/regime")
def get_regime(market: str = "us"):
    return get_regime_info(market=market)


@router.post("/signals/generate")
def generate_signals(req: SignalGenerateRequest, _admin=Depends(require_admin)):
    job_id = str(uuid.uuid4())
    db = SessionLocal()
    try:
        job = Job(
            id=job_id,
            type="signal_generation",
            status="pending",
            created_at=datetime.utcnow(),
            meta={"tickers": req.tickers, "market": req.market},
        )
        db.add(job)
        db.commit()
    finally:
        db.close()

    generate_signals_task.delay(
        job_id=job_id,
        tickers=req.tickers,
        market=req.market,
        xgb_run_id=req.xgb_run_id,
        lstm_run_id=req.lstm_run_id,
        ppo_run_id=req.ppo_run_id,
        data_job_id=req.data_job_id,
    )
    return {"job_id": job_id, "status": "pending", "tickers": req.tickers}


# ── OOF / Meta-learner / Calibration / EWMA endpoints ────────────────────────

class OOFCollectRequest(BaseModel):
    data_job_id: Optional[str] = None
    market:      str           = "us"
    train_months: int          = 12
    test_months:  int          = 1


class MetaLearnerTrainRequest(BaseModel):
    oof_dataset_path: Optional[str] = None  # defaults to settings.oof_dir/merged_oof_dataset.csv


class CalibrateRequest(BaseModel):
    run_id: str


@router.post("/oof/collect")
def collect_oof(req: OOFCollectRequest, _admin=Depends(require_admin)):
    """
    Trigger out-of-fold prediction collection for all trained base models.
    Dispatches a Celery task; returns job_id immediately.
    """
    job_id = str(uuid.uuid4())
    db = SessionLocal()
    try:
        job = Job(
            id=job_id,
            type="oof_collection",
            status="pending",
            created_at=datetime.utcnow(),
            meta={
                "market":       req.market,
                "data_job_id":  req.data_job_id,
                "train_months": req.train_months,
                "test_months":  req.test_months,
            },
        )
        db.add(job)
        db.commit()
    finally:
        db.close()

    collect_oof_task.delay(
        job_id=job_id,
        data_job_id=req.data_job_id,
        market=req.market,
        train_months=req.train_months,
        test_months=req.test_months,
    )
    return {"job_id": job_id, "status": "pending",
            "message": "OOF collection started — check /api/data/jobs for progress"}


@router.post("/train/meta-learner")
def train_meta_learner_endpoint(req: MetaLearnerTrainRequest, _admin=Depends(require_admin)):
    """
    Train the stacking meta-learner on collected OOF predictions.
    Returns run_id; actual training happens in Celery.
    """
    oof_path = req.oof_dataset_path or os.path.join(settings.oof_dir, "merged_oof_dataset.csv")
    if not os.path.exists(oof_path):
        raise HTTPException(
            status_code=404,
            detail=f"OOF dataset not found at {oof_path}. Run POST /api/ml/oof/collect first.",
        )

    run_id = str(uuid.uuid4())
    db = SessionLocal()
    try:
        run = Run(
            id=run_id,
            algorithm="meta_learner",
            model_type="meta_learner",
            status="pending",
            market="all",
            created_at=datetime.utcnow(),
            hyperparams={"oof_path": oof_path},
        )
        db.add(run)
        db.commit()
    finally:
        db.close()

    train_meta_learner_task.delay(run_id=run_id, oof_dataset_path=oof_path)
    return {"run_id": run_id, "status": "pending",
            "message": "Meta-learner training started"}


@router.post("/calibrate/{run_id}")
def calibrate_model(run_id: str, _admin=Depends(require_admin)):
    """
    Apply Platt scaling calibration to a trained XGBoost or LSTM model.
    Returns immediately; calibration runs asynchronously.
    """
    db = SessionLocal()
    try:
        run = db.query(Run).filter(Run.id == run_id).first()
        if not run:
            raise HTTPException(status_code=404, detail=f"Run {run_id} not found")
        if run.status != "done":
            raise HTTPException(status_code=400,
                                detail=f"Run {run_id} is not done (status: {run.status})")
    finally:
        db.close()

    job_id = str(uuid.uuid4())
    calibrate_model_task.delay(job_id=job_id, run_id=run_id)
    return {"job_id": job_id, "run_id": run_id, "status": "pending",
            "message": "Calibration started"}


@router.get("/weights/current")
def get_current_weights():
    """Return current EWMA adaptive fusion weights for all 7 models."""
    from app.services.ewma_tracker_service import get_current_weights as _get_weights
    db = SessionLocal()
    try:
        return _get_weights(db)
    finally:
        db.close()


@router.get("/weights/history")
def get_weight_history(days: int = 30):
    """Return weight evolution over the last N days (for admin dashboard chart)."""
    from app.services.ewma_tracker_service import get_weight_history as _get_history
    db = SessionLocal()
    try:
        return {"days": days, "history": _get_history(days=days, db_session=db)}
    finally:
        db.close()


@router.get("/performance/scores")
def get_performance_scores():
    """Return current EWMA scores for all 7 models (admin debugging)."""
    from app.services.ewma_tracker_service import get_current_weights as _get_weights
    from app.database import ModelPerformanceScore
    db = SessionLocal()
    try:
        weights = _get_weights(db)
        rows = (
            db.query(ModelPerformanceScore)
            .order_by(ModelPerformanceScore.date.desc(),
                      ModelPerformanceScore.model_key)
            .limit(7 * 7)   # last 7 days × 7 models
            .all()
        )
        scores = [
            {
                "date":          r.date,
                "model_key":     r.model_key,
                "ewma_score":    round(r.ewma_score, 4),
                "daily_correct": r.daily_correct,
                "weight":        round(r.weight or 0.0, 4),
            }
            for r in rows
        ]
        return {"current_weights": weights, "recent_scores": scores}
    finally:
        db.close()


@router.get("/meta/status")
def meta_status():
    """Whether the production meta-learner and EWMA tracker are active."""
    from app.services.fusion_service import meta_learner_status
    db = SessionLocal()
    try:
        return meta_learner_status(db)
    finally:
        db.close()
