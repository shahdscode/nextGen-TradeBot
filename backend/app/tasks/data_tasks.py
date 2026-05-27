from app.celery_app import celery_app
from app.database import SessionLocal, Job
from app.services import data_service
from datetime import datetime


@celery_app.task(bind=True, name="data_tasks.download")
def download_task(self, job_id: str, tickers, start_date, end_date, source, timeframe, indicators):
    db = SessionLocal()
    try:
        job = db.query(Job).filter(Job.id == job_id).first()
        job.status = "running"
        job.updated_at = datetime.utcnow()
        db.commit()

        result_path = data_service.download_data(
            job_id=job_id,
            tickers=tickers,
            start_date=start_date,
            end_date=end_date,
            source=source,
            timeframe=timeframe,
            indicators=indicators,
        )

        job.status = "done"
        job.result_path = result_path
        job.updated_at = datetime.utcnow()
        db.commit()
        return {"status": "done", "result_path": result_path}

    except Exception as e:
        job = db.query(Job).filter(Job.id == job_id).first()
        job.status = "failed"
        job.error = str(e)
        job.updated_at = datetime.utcnow()
        db.commit()
        raise
    finally:
        db.close()
