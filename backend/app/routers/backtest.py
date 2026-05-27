import json
import uuid
from pathlib import Path
from typing import Optional
from fastapi import APIRouter, HTTPException, Query
from app.config import settings
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

    backtest_task.delay(
        backtest_id, req.run_id, req.test_start, req.test_end,
        req.initial_capital, req.commission_pct, req.slippage_pct,
        req.max_position_pct, req.cooldown_days,
    )
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
        baselines=result.get("baselines"),
        walk_forward_periods=result.get("walk_forward_periods"),
        walk_forward_summary=result.get("walk_forward_summary"),
        stress_tests=result.get("stress_tests"),
        rl_sanity=result.get("rl_sanity"),
        overfitting_report=result.get("overfitting_report"),
        regime_analysis=result.get("regime_analysis"),
        significance_tests=result.get("significance_tests"),
        methodology_notes=result.get("methodology_notes"),
        data_source=result.get("data_source"),
        data_quality=result.get("data_quality"),
        transaction_costs=result.get("transaction_costs"),
        price_note=result.get("price_note"),
        step_log_summary=result.get("step_log_summary"),
        error=bt.error,
    )


@router.get("/{backtest_id}/step-log")
def get_step_log(
    backtest_id: str,
    page: int = Query(0, ge=0, description="Page number (0-indexed)"),
    size: int = Query(100, ge=1, le=1000, description="Rows per page"),
):
    """
    Return a paginated view of the per-step debug log.
    Each row contains: step, date, portfolio_value, cash, positions,
    prices, signals/actions, indicators, reward.
    The full JSONL file lives at results/{backtest_id}/step_log.jsonl.
    """
    log_path = Path(settings.results_dir) / backtest_id / "step_log.jsonl"
    if not log_path.exists():
        raise HTTPException(status_code=404, detail="Step log not found for this backtest")

    rows = []
    try:
        with open(log_path) as f:
            for line in f:
                line = line.strip()
                if line:
                    rows.append(json.loads(line))
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Error reading step log: {exc}")

    total = len(rows)
    start = page * size
    end   = start + size
    return {
        "backtest_id": backtest_id,
        "total_steps": total,
        "page":        page,
        "size":        size,
        "rows":        rows[start:end],
    }


@router.get("")
def list_backtests(run_id: Optional[str] = Query(None)):
    db = SessionLocal()
    q = db.query(Backtest).order_by(Backtest.created_at.desc())
    if run_id:
        q = q.filter(Backtest.run_id == run_id)
    bts = q.all()
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
