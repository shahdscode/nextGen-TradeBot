import uuid
from fastapi import APIRouter, HTTPException
from app.database import SessionLocal, Run
from app.models.schemas import TrainRequest, RunResponse
from app.tasks.train_tasks import train_task
from app import finrl_wrapper
from datetime import datetime

router = APIRouter(prefix="/train", tags=["training"])


def _mark_stale_running_runs(db, stale_minutes: int = 30):
    cutoff = datetime.utcnow().timestamp() - stale_minutes * 60
    runs = db.query(Run).filter(Run.status == "running").all()
    updated = False
    for r in runs:
        ts = r.updated_at.timestamp() if r.updated_at else r.created_at.timestamp()
        if ts < cutoff: 
            r.status = "failed"
            r.error = "Run timed out or worker was interrupted"
            r.updated_at = datetime.utcnow()
            updated = True
    if updated:
        db.commit()


@router.post("", response_model=RunResponse)
def train(req: TrainRequest):
    run_id = str(uuid.uuid4())
    db = SessionLocal()
    run = Run(
        id=run_id,
        data_job_id=req.data_job_id,
        algorithm=req.algorithm,
        status="pending",
        created_at=datetime.utcnow(),
        hyperparams=req.hyperparams,
    )
    db.add(run)
    db.commit()
    db.close()

    hp = dict(req.hyperparams or {})
    if req.train_start:
        hp["train_start"] = req.train_start
    if req.train_end:
        hp["train_end"] = req.train_end
    if req.xgb_run_id:
        hp["xgb_run_id"] = req.xgb_run_id
    if req.lstm_run_id:
        hp["lstm_run_id"] = req.lstm_run_id
    train_task.delay(run_id, req.data_job_id, req.algorithm, hp)
    return RunResponse(run_id=run_id, algorithm=req.algorithm, status="pending")


@router.get("/runs", response_model=list[RunResponse])
def list_runs():
    db = SessionLocal()
    _mark_stale_running_runs(db)
    runs = db.query(Run).order_by(Run.created_at.desc()).all()
    db.close()
    return [
        RunResponse(
            run_id=r.id,
            algorithm=r.algorithm,
            status=r.status,
            created_at=str(r.created_at),
            updated_at=str(r.updated_at),
            model_path=r.model_path,
            metrics=r.metrics_json,
            error=r.error,
            published=bool(r.published) if r.published is not None else False,
            market=r.market,
        )
        for r in runs
    ]


@router.get("/runs/{run_id}", response_model=RunResponse)
def get_run(run_id: str):
    db = SessionLocal()
    _mark_stale_running_runs(db)
    run = db.query(Run).filter(Run.id == run_id).first()
    db.close()
    if not run:
        raise HTTPException(status_code=404, detail="Run not found")
    return RunResponse(
        run_id=run.id,
        algorithm=run.algorithm,
        status=run.status,
        created_at=str(run.created_at),
        updated_at=str(run.updated_at),
        model_path=run.model_path,
        metrics=run.metrics_json,
        error=run.error,
    )


@router.get("/agents")
def list_agents():
    return {"agents": finrl_wrapper.get_agents()}


@router.post("/runs/{run_id}/publish")
def publish_run(run_id: str):
    db = SessionLocal()
    run = db.query(Run).filter(Run.id == run_id).first()
    if not run:
        db.close()
        raise HTTPException(status_code=404, detail="Run not found")
    if run.status != "done":
        db.close()
        raise HTTPException(status_code=400, detail="Only completed runs can be published")
    run.published = True
    run.updated_at = datetime.utcnow()
    db.commit()
    db.close()
    return {"run_id": run_id, "published": True}


@router.post("/runs/{run_id}/unpublish")
def unpublish_run(run_id: str):
    db = SessionLocal()
    run = db.query(Run).filter(Run.id == run_id).first()
    if not run:
        db.close()
        raise HTTPException(status_code=404, detail="Run not found")
    run.published = False
    run.updated_at = datetime.utcnow()
    db.commit()
    db.close()
    return {"run_id": run_id, "published": False}


@router.get("/runs/published")
def list_published_runs():
    db = SessionLocal()
    runs = db.query(Run).filter(Run.published == True, Run.status == "done").order_by(Run.created_at.desc()).all()
    db.close()
    return [
        RunResponse(
            run_id=r.id,
            algorithm=r.algorithm,
            status=r.status,
            created_at=str(r.created_at),
            model_path=r.model_path,
            metrics=r.metrics_json,
        )
        for r in runs
    ]
