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
REBALANCE_WEEKDAY  = 0       # Monday — rebalance once per week (daily-trained
                             # models + weekly cadence avoids friction churn)
_last_run_week: str | None = None
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


def _run_weekly_rebalance():
    """
    Weekly hands-off rebalance of the active paper session's model.

    Routing:
      - If Alpaca is configured → submit real orders to the Alpaca paper account
        (model weights, with cash buffer).
      - Else → update the internal Yahoo-simulated session positions.
    Model: session.run_id == 'meta_learner' → ensemble, else single RL model.
    """
    from app.database import SessionLocal, PaperSession
    from app.services.live_trading_service import (
        generate_live_allocation, generate_meta_allocation,
    )
    from app.services import alpaca_service
    db = SessionLocal()
    try:
        from sqlalchemy import desc
        row = (db.query(PaperSession)
               .filter(PaperSession.running == True)  # noqa: E712
               .order_by(desc(PaperSession.created_at)).first())
        if not row:
            logger.info("Weekly rebalance: no active paper session — skipping")
            return
        cash = float(row.initial_cash or 100_000.0)
        run_id = row.run_id or ""
        # Use Alpaca equity as the budget when available
        if alpaca_service.configured():
            try:
                cash = alpaca_service.get_account()["equity"]
            except Exception:
                pass
        if run_id == "meta_learner":
            alloc = generate_meta_allocation(cash)
        elif run_id:
            alloc = generate_live_allocation(run_id, cash)
        else:
            logger.info("Weekly rebalance: session has no run_id — skipping")
            return
        if not alloc.get("ok"):
            logger.warning("Weekly rebalance allocation failed: %s", alloc.get("message"))
            return

        if alpaca_service.configured():
            # Model target (shares×price) → portfolio weights → Alpaca orders
            tv = {t: alloc["target"].get(t, 0.0) * alloc["prices"].get(t, 0.0)
                  for t in alloc["tickers"]}
            tot = sum(v for v in tv.values() if v > 0)
            weights = {t: v / tot for t, v in tv.items() if v > 0} if tot > 0 else {}
            res = alpaca_service.rebalance_to_weights(weights)
            logger.info("Weekly Alpaca rebalance: %s — %d orders (%s)",
                        alloc.get("message", ""), res.get("n_orders", 0), res.get("note", ""))
        else:
            _apply(alloc, cash, db, PaperSession)
    except Exception:
        logger.exception("Weekly rebalance crashed")
    finally:
        db.close()


def _loop():
    global _last_run_week
    while True:
        try:
            now = datetime.now(timezone.utc)
            iso_week = f"{now.isocalendar().year}-W{now.isocalendar().week}"
            # Rebalance once per ISO week, on REBALANCE_WEEKDAY after close hour
            if (now.weekday() == REBALANCE_WEEKDAY
                    and now.hour >= REBALANCE_HOUR_UTC
                    and _last_run_week != iso_week):
                logger.info("Triggering weekly paper-trading rebalance (%s)", iso_week)
                _run_weekly_rebalance()
                _last_run_week = iso_week
        except Exception:
            logger.exception("Scheduler loop error")
        time.sleep(CHECK_INTERVAL_SEC)


def trigger_rebalance_now():
    """Manual one-off trigger (used by an API endpoint / testing)."""
    _run_weekly_rebalance()


def start_scheduler():
    """Start the weekly rebalance daemon thread (idempotent)."""
    global _started
    if _started:
        return
    _started = True
    t = threading.Thread(target=_loop, name="paper-rebalance-scheduler", daemon=True)
    t.start()
    logger.info("Paper-trading weekly rebalance scheduler started "
                "(weekday=%d, UTC hour=%d, Alpaca-aware)", REBALANCE_WEEKDAY, REBALANCE_HOUR_UTC)
