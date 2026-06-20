"""
FinCast forecasting endpoints.

The model is heavy (3.7 GB) and CPU-bound here, so forecasts run as async Celery
jobs: POST returns a job_id immediately; GET polls for the result. A cached
result is returned if a fresh one exists for the ticker.
"""
import uuid
from datetime import datetime, timedelta

from fastapi import APIRouter, HTTPException, Query

from app.database import SessionLocal, Job

router = APIRouter(prefix="/fincast", tags=["fincast"])

_FRESH_MINUTES = 60   # reuse a forecast computed within the last hour


@router.get("/status")
def fincast_status():
    """Whether the FinCast weights + code are present and ready."""
    from app.services.fincast_service import available, CONTEXT_LEN, HORIZON_LEN
    av = available()
    return {**av, "context_len": CONTEXT_LEN, "horizon_len": HORIZON_LEN,
            "model": "fincast_v1+5min_adapter"}


@router.post("/forecast")
def request_forecast(ticker: str = Query(...), market: str = Query("us"),
                     force: bool = Query(False)):
    """Queue a FinCast forecast. Returns a cached job if one is recent, else a
    new job_id to poll via GET /fincast/forecast/{job_id}."""
    from app.services.fincast_service import available
    if not available()["ready"]:
        raise HTTPException(status_code=503,
                            detail="FinCast model not installed on this server.")

    ticker = ticker.strip().upper()
    db = SessionLocal()
    try:
        if not force:
            cutoff = datetime.utcnow() - timedelta(minutes=_FRESH_MINUTES)
            recent = (
                db.query(Job)
                .filter(Job.type == "fincast_forecast", Job.status == "done",
                        Job.updated_at >= cutoff)
                .order_by(Job.updated_at.desc()).all()
            )
            for j in recent:
                if (j.meta or {}).get("ticker") == ticker and (j.meta or {}).get("market") == market:
                    return {"job_id": j.id, "status": "done", "cached": True, "result": j.meta}

        job_id = str(uuid.uuid4())
        job = Job(id=job_id, type="fincast_forecast", status="pending",
                  created_at=datetime.utcnow(),
                  meta={"ticker": ticker, "market": market})
        db.add(job); db.commit()
    finally:
        db.close()

    from app.tasks.fincast_tasks import fincast_forecast_task
    fincast_forecast_task.delay(job_id=job_id, ticker=ticker, market=market)
    return {"job_id": job_id, "status": "pending", "ticker": ticker, "market": market}


@router.get("/forecast/{job_id}")
def get_forecast(job_id: str):
    """Poll a forecast job. Returns status and, when done, the forecast result."""
    db = SessionLocal()
    try:
        job = db.query(Job).filter(Job.id == job_id).first()
        if not job:
            raise HTTPException(status_code=404, detail="Forecast job not found")
        return {"job_id": job.id, "status": job.status,
                "result": job.meta if job.status == "done" else None,
                "error": job.error}
    finally:
        db.close()


@router.post("/backtest")
def request_backtest(ticker: str = Query(...), market: str = Query("us"),
                     test_windows: int = Query(2000, ge=200, le=4000),
                     force: bool = Query(False)):
    """Queue a FinCast contextual-bandit backtest (faithful port of the FinCast
    notebook). Returns a recent cached result if available, else a job_id to poll
    via GET /fincast/backtest/{job_id}."""
    from app.services.fincast_service import available
    if not available()["ready"]:
        raise HTTPException(status_code=503,
                            detail="FinCast model not installed on this server.")

    ticker = ticker.strip().upper()
    db = SessionLocal()
    try:
        if not force:
            cutoff = datetime.utcnow() - timedelta(minutes=_FRESH_MINUTES)
            recent = (
                db.query(Job)
                .filter(Job.type == "fincast_backtest", Job.status == "done",
                        Job.updated_at >= cutoff)
                .order_by(Job.updated_at.desc()).all()
            )
            for j in recent:
                m = j.meta or {}
                if m.get("ticker") == ticker and m.get("market") == market:
                    return {"job_id": j.id, "status": "done", "cached": True, "result": m}

        job_id = str(uuid.uuid4())
        job = Job(id=job_id, type="fincast_backtest", status="pending",
                  created_at=datetime.utcnow(),
                  meta={"ticker": ticker, "market": market})
        db.add(job); db.commit()
    finally:
        db.close()

    from app.tasks.fincast_tasks import fincast_backtest_task
    fincast_backtest_task.delay(job_id=job_id, ticker=ticker, market=market,
                                test_windows=test_windows)
    return {"job_id": job_id, "status": "pending", "ticker": ticker, "market": market}


@router.get("/backtest/{job_id}")
def get_backtest(job_id: str):
    """Poll a FinCast backtest job."""
    db = SessionLocal()
    try:
        job = db.query(Job).filter(Job.id == job_id).first()
        if not job:
            raise HTTPException(status_code=404, detail="Backtest job not found")
        return {"job_id": job.id, "status": job.status,
                "result": job.meta if job.status == "done" else None,
                "error": job.error}
    finally:
        db.close()
