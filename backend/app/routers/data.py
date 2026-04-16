import uuid
from fastapi import APIRouter, HTTPException
from app.database import SessionLocal, Job
from app.models.schemas import DataDownloadRequest, JobStatusResponse
from app.tasks.data_tasks import download_task
from app.services.data_service import get_preview
from app import finrl_wrapper
from datetime import datetime

router = APIRouter(prefix="/data", tags=["data"])


@router.post("/download", response_model=JobStatusResponse)
def download(req: DataDownloadRequest):
    job_id = str(uuid.uuid4())
    db = SessionLocal()
    job = Job(
        id=job_id,
        type="data",
        status="pending",
        created_at=datetime.utcnow(),
        meta={
            "tickers": req.tickers,
            "start_date": req.start_date,
            "end_date": req.end_date,
            "source": req.source,
            "timeframe": req.timeframe,
        },
    )
    db.add(job)
    db.commit()
    db.close()

    download_task.delay(
        job_id,
        req.tickers,
        req.start_date,
        req.end_date,
        req.source,
        req.timeframe,
        req.indicators or finrl_wrapper.get_indicators(),
    )
    return JobStatusResponse(job_id=job_id, status="pending")


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


@router.get("/indicators")
def indicators():
    return {"indicators": finrl_wrapper.get_indicators()}
