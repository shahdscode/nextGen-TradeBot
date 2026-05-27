from app.celery_app import celery_app
from app.database import SessionLocal, Backtest
from app.services import backtest_service
from datetime import datetime


@celery_app.task(bind=True, name="backtest_tasks.run")
def backtest_task(
    self,
    backtest_id: str,
    run_id: str,
    test_start: str,
    test_end: str,
    initial_capital: float = 1_000_000.0,
    commission_pct: float = 0.001,
    slippage_pct: float = 0.001,
    max_position_pct: float = 0.20,
    cooldown_days: int = 5,
):
    db = SessionLocal()
    try:
        bt = db.query(Backtest).filter(Backtest.id == backtest_id).first()
        bt.status = "running"
        bt.updated_at = datetime.utcnow()
        db.commit()

        result = backtest_service.run_backtest(
            backtest_id=backtest_id,
            run_id=run_id,
            test_start=test_start,
            test_end=test_end,
            initial_capital=initial_capital,
            commission_pct=commission_pct,
            slippage_pct=slippage_pct,
            max_position_pct=max_position_pct,
            cooldown_days=cooldown_days,
        )

        bt.status = "done"
        bt.result_json = result
        bt.updated_at = datetime.utcnow()
        db.commit()
        return {"status": "done"}

    except Exception as e:
        bt = db.query(Backtest).filter(Backtest.id == backtest_id).first()
        bt.status = "failed"
        bt.error = str(e)
        bt.updated_at = datetime.utcnow()
        db.commit()
        raise
    finally:
        db.close()
