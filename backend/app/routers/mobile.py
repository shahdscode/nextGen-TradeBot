"""
Mobile-optimized aggregate endpoints (fewer round-trips, clearer payloads).
"""
from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, Query, Depends

from app.database import SessionLocal, Backtest, Run
from app.services.pipeline_service import pipeline_status as get_pipeline_status
from app.services.auth_service import get_current_user, get_user_id

router = APIRouter(prefix="/mobile", tags=["mobile"])


@router.get("/health")
def mobile_health():
    """Quick connectivity check for the app splash / login screen."""
    from app.routers.market import market_data_status

    mkt = market_data_status()
    return {
        "api_ok": True,
        "live_market_ok": mkt.get("live_market_ok", False),
        "message": mkt.get("message", ""),
    }


@router.get("/dashboard")
def mobile_dashboard(market: str = Query("us"), user=Depends(get_current_user)):
    """Home tab: regime, movers, top signals, recent backtests in one call."""
    import logging
    from fastapi import HTTPException
    from app.routers.market import market_overview, market_data_status
    from app.routers.signals import get_top_signals
    from app.services.regime_service import get_regime_info

    log = logging.getLogger(__name__)

    try:
        regime = get_regime_info(market=market)
    except Exception as exc:
        log.warning("dashboard regime failed: %s", exc)
        regime = {"current_regime": "SIDEWAYS", "source": "unavailable"}

    try:
        movers = market_overview(market=market)
    except HTTPException:
        raise
    except Exception as exc:
        log.warning("dashboard movers failed: %s", exc)
        movers = []

    try:
        # Pass every arg explicitly: get_top_signals has FastAPI Query(...)
        # defaults that only resolve over HTTP. Called in-process, the unset
        # params stay as Query objects (e.g. hours=Query(48)) and blow up in
        # timedelta. Supplying real values keeps the in-process call working.
        signals = get_top_signals(market=market, limit=5, action=None,
                                  min_confidence=0.0, hours=48)
    except Exception as exc:
        log.warning("dashboard signals failed: %s", exc)
        signals = []

    status = market_data_status()

    db = SessionLocal()
    try:
        bt_q = db.query(Backtest).filter(Backtest.status == "done")
        if user and user.role != "admin":
            bt_q = bt_q.filter(Backtest.user_id == get_user_id(user))
        recent_bt = bt_q.order_by(Backtest.created_at.desc()).limit(5).all()
        done_runs = (
            db.query(Run)
            .filter(Run.status == "done")
            .order_by(Run.created_at.desc())
            .limit(10)
            .all()
        )
    finally:
        db.close()

    return {
        "market_status": status,
        "regime": regime,
        "movers": movers,
        "top_signals": signals,
        "recent_backtests": [
            {
                "backtest_id": bt.id,
                "run_id": bt.run_id,
                "test_start": bt.test_start,
                "test_end": bt.test_end,
                "total_return": (bt.result_json or {}).get("metrics", {}).get("total_return"),
                "sharpe": (bt.result_json or {}).get("metrics", {}).get("sharpe"),
            }
            for bt in recent_bt
        ],
        "training_runs": [
            {
                "run_id": r.id,
                "algorithm": r.algorithm,
                "status": r.status,
                "metrics": r.metrics_json or {},
                "published": bool(r.published),
            }
            for r in done_runs
        ],
    }


@router.get("/latest-backtest")
def mobile_latest_backtest(run_id: str = Query(...)):
    """Latest completed backtest for a training run (Simulator tab)."""
    db = SessionLocal()
    try:
        bt = (
            db.query(Backtest)
            .filter(Backtest.run_id == run_id, Backtest.status == "done")
            .order_by(Backtest.created_at.desc())
            .first()
        )
        if not bt:
            return {"found": False, "run_id": run_id}
        result = bt.result_json or {}
        return {
            "found": True,
            "backtest_id": bt.id,
            "run_id": bt.run_id,
            "status": bt.status,
            "test_start": bt.test_start,
            "test_end": bt.test_end,
            **result,
        }
    finally:
        db.close()


@router.get("/pipeline-status/{data_job_id}")
def mobile_pipeline_status(data_job_id: str):
    return get_pipeline_status(data_job_id)
