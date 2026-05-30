from app.celery_app import celery_app
from app.database import SessionLocal, Run
from app.services import train_service
from datetime import datetime


@celery_app.task(bind=True, name="train_tasks.train")
def train_task(self, run_id: str, data_job_id: str, algorithm: str,
               hyperparams: dict, market: str = "us"):
    db = SessionLocal()
    try:
        run = db.query(Run).filter(Run.id == run_id).first()
        run.status = "running"
        run.updated_at = datetime.utcnow()
        db.commit()

        result = train_service.train_agent(
            run_id=run_id,
            data_job_id=data_job_id,
            algorithm=algorithm,
            hyperparams=hyperparams,
            market=market,
        )

        run.status = "done"
        run.model_path = result["model_path"]
        run.metrics_json = result["metrics"]
        run.updated_at = datetime.utcnow()
        db.commit()
        return {"status": "done", "model_path": result["model_path"]}

    except Exception as e:
        run = db.query(Run).filter(Run.id == run_id).first()
        run.status = "failed"
        run.error = str(e)
        run.updated_at = datetime.utcnow()
        db.commit()
        raise
    finally:
        db.close()
