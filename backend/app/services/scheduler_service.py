"""
Lightweight daily auto-rebalance scheduler for paper trading.

A daemon thread wakes periodically and, once per day after the US market close,
re-runs the active paper session's model on live DOW30 data and rebalances the
paper portfolio. No external scheduler dependency (no APScheduler/cron).

The session's run_id selects the mode:
  run_id == "meta_learner"  → full 7-model meta-learner ensemble
  otherwise                 → that single RL model
"""
from __future__ import annotations

import logging
import threading
import time
import uuid
from datetime import datetime, timezone

logger = logging.getLogger(__name__)

REBALANCE_HOUR_UTC = 21      # ~after US close (16:00–17:00 ET)
CHECK_INTERVAL_SEC = 1800    # check every 30 min
_last_run_date: str | None = None
_started = False


def _apply(alloc: dict, cash: float, db, PaperSession):
    """Update the active PaperSession positions to the model's target allocation."""
    from sqlalchemy import desc
    row = (db.query(PaperSession)
           .filter(PaperSession.running == True)  # noqa: E712
           .order_by(desc(PaperSession.created_at)).first())
    if not row:
        return False

    positions, invested = {}, 0.0
    for tic, qty in alloc["target"].items():
        if qty and qty > 0:
            px = float(alloc["prices"].get(tic, 0.0))
            if px > 0:
                positions[tic] = {"qty": round(qty, 6), "entry_price": round(px, 4)}
                invested += qty * px
    row.positions = positions
    row.cash = round(max(0.0, cash - invested), 2)
    row.symbols = alloc["tickers"]
    row.updated_at = datetime.utcnow()
    db.commit()
    logger.info("Daily rebalance applied: %s (%d positions, $%.0f invested)",
                alloc.get("message", ""), len(positions), invested)
    return True


def _run_daily_rebalance():
    from app.database import SessionLocal, PaperSession
    from app.services.live_trading_service import (
        generate_live_allocation, generate_meta_allocation,
    )
    db = SessionLocal()
    try:
        from sqlalchemy import desc
        row = (db.query(PaperSession)
               .filter(PaperSession.running == True)  # noqa: E712
               .order_by(desc(PaperSession.created_at)).first())
        if not row:
            logger.info("Daily rebalance: no active paper session — skipping")
            return
        cash = float(row.initial_cash or 100_000.0)
        run_id = row.run_id or ""
        if run_id == "meta_learner":
            alloc = generate_meta_allocation(cash)
        elif run_id:
            alloc = generate_live_allocation(run_id, cash)
        else:
            logger.info("Daily rebalance: session has no run_id — skipping")
            return
        if alloc.get("ok"):
            _apply(alloc, cash, db, PaperSession)
        else:
            logger.warning("Daily rebalance allocation failed: %s", alloc.get("message"))
    except Exception:
        logger.exception("Daily rebalance crashed")
    finally:
        db.close()


def _loop():
    global _last_run_date
    while True:
        try:
            now = datetime.now(timezone.utc)
            today = now.strftime("%Y-%m-%d")
            if now.hour >= REBALANCE_HOUR_UTC and _last_run_date != today:
                logger.info("Triggering daily paper-trading rebalance for %s", today)
                _run_daily_rebalance()
                _last_run_date = today
        except Exception:
            logger.exception("Scheduler loop error")
        time.sleep(CHECK_INTERVAL_SEC)


def start_scheduler():
    """Start the daily rebalance daemon thread (idempotent)."""
    global _started
    if _started:
        return
    _started = True
    t = threading.Thread(target=_loop, name="paper-rebalance-scheduler", daemon=True)
    t.start()
    logger.info("Paper-trading daily rebalance scheduler started (UTC hour=%d)", REBALANCE_HOUR_UTC)
