import uuid
from fastapi import APIRouter, HTTPException
from app.database import SessionLocal, Backtest
from app.models.schemas import BacktestRequest, BacktestResponse
from app.tasks.backtest_tasks import backtest_task
from datetime import datetime

router = APIRouter(prefix="/backtest", tags=["backtest"])


@router.post("", response_model=BacktestResponse)
def create_backtest(req: BacktestRequest):
    backtest_id = str(uuid.uuid4())
    db = SessionLocal()
    bt = Backtest(
        id=backtest_id,
        run_id=req.run_id,
        status="pending",
        created_at=datetime.utcnow(),
        test_start=req.test_start,
        test_end=req.test_end,
    )
    db.add(bt)
    db.commit()
    db.close()

    backtest_task.delay(backtest_id, req.run_id, req.test_start, req.test_end, req.initial_capital)
    return BacktestResponse(backtest_id=backtest_id, run_id=req.run_id, status="pending",
                            initial_capital=req.initial_capital)


@router.get("/{backtest_id}", response_model=BacktestResponse)
def get_backtest(backtest_id: str):
    db = SessionLocal()
    bt = db.query(Backtest).filter(Backtest.id == backtest_id).first()
    db.close()
    if not bt:
        raise HTTPException(status_code=404, detail="Backtest not found")

    result = bt.result_json or {}
    return BacktestResponse(
        backtest_id=bt.id,
        run_id=bt.run_id,
        status=bt.status,
        initial_capital=result.get("initial_capital"),
        account_value=result.get("account_value"),
        daily_return=result.get("daily_return"),
        dates=result.get("dates"),
        metrics=result.get("metrics"),
        trades=result.get("trades"),
        benchmark=result.get("benchmark"),
        error=bt.error,
    )


@router.get("")
def list_backtests():
    db = SessionLocal()
    bts = db.query(Backtest).order_by(Backtest.created_at.desc()).all()
    db.close()
    return [
        {
            "backtest_id": bt.id,
            "run_id": bt.run_id,
            "status": bt.status,
            "test_start": bt.test_start,
            "test_end": bt.test_end,
            "created_at": str(bt.created_at),
            "metrics": (bt.result_json or {}).get("metrics"),
        }
        for bt in bts
    ]
