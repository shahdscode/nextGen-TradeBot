from celery import Celery
from app.config import settings

celery_app = Celery(
    "finrl_worker",
    broker=settings.redis_url,
    backend=settings.redis_url,
    include=[
        "app.tasks.data_tasks",
        "app.tasks.train_tasks",
        "app.tasks.backtest_tasks",
        "app.tasks.ml_tasks",
    ]
)

celery_app.conf.update(
    task_serializer="json",
    accept_content=["json"],
    result_serializer="json",
    timezone="UTC",
    enable_utc=True,
    task_track_started=True,
    task_soft_time_limit=7200,
    task_time_limit=8000,
    # macOS + ML libs can crash with prefork due fork/ObjC runtime interactions.
    worker_pool="solo",
    worker_concurrency=1,
)
