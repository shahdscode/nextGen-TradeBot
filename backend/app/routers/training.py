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

    train_task.delay(run_id, req.data_job_id, req.algorithm, req.hyperparams or {})
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
