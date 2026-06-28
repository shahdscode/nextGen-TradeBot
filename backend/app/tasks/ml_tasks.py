import uuid
import logging
from datetime import datetime
from app.celery_app import celery_app
from app.database import SessionLocal, Run, Job

logger = logging.getLogger(__name__)


@celery_app.task(bind=True, name="ml_tasks.train_xgboost")
def train_xgboost_task(self, run_id: str, data_job_id: str, ticker: str,
                       n_trials: int = 30, market: str = "us"):
    from app.services.xgboost_service import train_xgboost
    db = SessionLocal()
    try:
        run = db.query(Run).filter(Run.id == run_id).first()
        run.status = "running"
        run.updated_at = datetime.utcnow()
        db.commit()

        result = train_xgboost(run_id=run_id, data_job_id=data_job_id,
                               ticker=ticker, n_trials=n_trials, market=market)

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


@celery_app.task(bind=True, name="ml_tasks.train_lstm")
def train_lstm_task(self, run_id: str, data_job_id: str, ticker: str,
                    epochs: int = 30, market: str = "us"):
    from app.services.lstm_service import train_lstm
    db = SessionLocal()
    try:
        run = db.query(Run).filter(Run.id == run_id).first()
        run.status = "running"
        run.updated_at = datetime.utcnow()
        db.commit()

        result = train_lstm(run_id=run_id, data_job_id=data_job_id,
                            ticker=ticker, epochs=epochs, market=market)

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


@celery_app.task(bind=True, name="ml_tasks.generate_signals")
def generate_signals_task(self, job_id: str, tickers: list, market: str = "us",
                           xgb_run_id: str = None, lstm_run_id: str = None,
                           ppo_run_id: str = None, data_job_id: str = None):
    import pandas as pd
    from pathlib import Path
    from app.config import settings
    from app.services.fusion_service import generate_full_signal, production_fusion_flags

    db = SessionLocal()
    try:
        job = db.query(Job).filter(Job.id == job_id).first()
        job.status = "running"
        job.updated_at = datetime.utcnow()
        db.commit()

        fusion = production_fusion_flags(db)
        xgb_model_path  = _get_model_path(db, xgb_run_id)
        lstm_model_path = _get_model_path(db, lstm_run_id)

        df = None
        if data_job_id:
            data_path = Path(settings.data_dir) / data_job_id / "data.csv"
            if data_path.exists():
                df = pd.read_csv(data_path)

        deploy_sigs = {}
        if not xgb_model_path and not lstm_model_path:
            try:
                from app.services.fusion_service import deployable_base_signals
                deploy_sigs = deployable_base_signals(market)
            except Exception as e:
                logger.warning("deployable base signals failed: %s", e)

        cards = []
        for ticker in tickers:
            try:
                ds = deploy_sigs.get(ticker)
                card = generate_full_signal(
                    ticker=ticker,
                    market=market,
                    df=df,
                    xgb_model_path=xgb_model_path,
                    lstm_model_path=lstm_model_path,
                    ppo_run_id=ppo_run_id,
                    xgb_prob_override=(ds["xgb"] if ds else None),
                    lstm_prob_override=(ds["lstm"] if ds else None),
                    shap_features_override=(ds["shap"] if ds else None),
                    use_meta_learner=fusion["use_meta_learner"],
                    meta_learner_path=fusion["meta_learner_path"],
                    use_adaptive_weights=fusion["use_adaptive_weights"],
                    calibrator_path=fusion["calibrator_path"],
                    db_session=db,
                )
                cards.append(card)
            except Exception as e:
                cards.append({"ticker": ticker, "error": str(e)})

        job.status = "done"
        job.meta = {
            "signals_generated": len(cards),
            "tickers": tickers,
            "fusion_method": fusion.get("use_meta_learner") and "meta_learner"
                             or (fusion.get("use_adaptive_weights") and "ewma" or "fixed"),
        }
        job.updated_at = datetime.utcnow()
        db.commit()
        return {"status": "done", "count": len(cards)}
    except Exception as e:
        job = db.query(Job).filter(Job.id == job_id).first()
        job.status = "failed"
        job.error = str(e)
        job.updated_at = datetime.utcnow()
        db.commit()
        raise
    finally:
        db.close()


def _get_model_path(db, run_id: str):
    if not run_id:
        return None
    run = db.query(Run).filter(Run.id == run_id).first()
    return run.model_path if run else None
