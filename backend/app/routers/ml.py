"""
ML training endpoints for XGBoost and LSTM models.
These are admin-only endpoints that trigger async Celery jobs.
"""
import uuid
from datetime import datetime
from fastapi import APIRouter, HTTPException, Depends
from pydantic import BaseModel
from typing import Optional

from app.database import SessionLocal, Run, Job
from app.models.schemas import RunResponse
from app.tasks.ml_tasks import train_xgboost_task, train_lstm_task, generate_signals_task
from app.services.regime_service import get_regime_info, train_regime_model

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
def train_xgboost(req: XGBTrainRequest):
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
def train_lstm(req: LSTMTrainRequest):
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
def train_regime(market: str = "us"):
    result = train_regime_model(market=market)
    return result


@router.get("/regime")
def get_regime(market: str = "us"):
    return get_regime_info(market=market)


@router.post("/signals/generate")
def generate_signals(req: SignalGenerateRequest):
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
