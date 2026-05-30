import logging
import threading
import uuid
from fastapi import APIRouter, HTTPException

logger = logging.getLogger(__name__)


def _enqueue_download(task_args: tuple) -> str:
    """Queue via Celery when a worker is up; otherwise run in a background thread."""
    try:
        from app.celery_app import celery_app

        ping = celery_app.control.inspect().ping()
        if ping:
            download_task.delay(*task_args)
            return "pending"
    except Exception as exc:
        logger.warning("Celery queue unavailable (%s) — using background thread", exc)

    def _run():
        try:
            download_task(*task_args)
        except Exception:
            logger.exception("Background data download failed for job %s", task_args[0])

    threading.Thread(target=_run, daemon=True).start()
    return "pending"
from app.database import SessionLocal, Job
from app.models.schemas import (
    DataDownloadRequest,
    JobStatusResponse,
    TickerValidateRequest,
    TickerValidateResponse,
)
from app.ticker_catalog import validate_tickers_for_source
from app.tasks.data_tasks import download_task
from app.services.data_service import get_preview
from app import finrl_wrapper
from datetime import datetime

router = APIRouter(prefix="/data", tags=["data"])


@router.post("/validate-tickers", response_model=TickerValidateResponse)
def validate_tickers(req: TickerValidateRequest):
    result = validate_tickers_for_source(req.source, req.tickers)
    return TickerValidateResponse(**result)


@router.post("/download", response_model=JobStatusResponse)
def download(req: DataDownloadRequest):
    check = validate_tickers_for_source(req.source, req.tickers)
    if not check["valid"]:
        raise HTTPException(status_code=400, detail=check["message"])

    job_id = str(uuid.uuid4())
    db = SessionLocal()
    job = Job(
        id=job_id,
        type="data",
        status="pending",
        created_at=datetime.utcnow(),
        meta={
            "tickers": check["tickers"],
            "start_date": req.start_date,
            "end_date": req.end_date,
            "source": req.source,
            "timeframe": req.timeframe,
        },
    )
    db.add(job)
    db.commit()
    db.close()

    task_args = (
        job_id,
        check["tickers"],
        req.start_date,
        req.end_date,
        req.source,
        req.timeframe,
        req.indicators or finrl_wrapper.get_indicators(),
    )
    status = _enqueue_download(task_args)
    return JobStatusResponse(job_id=job_id, status=status)


@router.get("/status/{job_id}", response_model=JobStatusResponse)
def status(job_id: str):
    db = SessionLocal()
    job = db.query(Job).filter(Job.id == job_id).first()
    db.close()
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")
    return JobStatusResponse(
        job_id=job.id,
        status=job.status,
        error=job.error,
        result_path=job.result_path,
        meta=job.meta,
    )


@router.get("/preview/{job_id}")
def preview(job_id: str, n: int = 20):
    db = SessionLocal()
    job = db.query(Job).filter(Job.id == job_id).first()
    db.close()
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")
    if job.status != "done":
        raise HTTPException(status_code=400, detail=f"Job status is {job.status}, not done")
    if not job.result_path:
        raise HTTPException(status_code=400, detail="No result path stored")
    rows = get_preview(job.result_path, n)
    return {"job_id": job_id, "rows": rows, "count": len(rows)}


@router.get("/jobs")
def list_jobs():
    """List all data download jobs."""
    db = SessionLocal()
    jobs = db.query(Job).filter(Job.type == "data").order_by(Job.created_at.desc()).all()
    db.close()
    return [
        JobStatusResponse(
            job_id=j.id,
            status=j.status,
            error=j.error,
            result_path=j.result_path,
            meta=j.meta,
        )
        for j in jobs
    ]


@router.get("/indicators")
def indicators():
    return {"indicators": finrl_wrapper.get_indicators()}
