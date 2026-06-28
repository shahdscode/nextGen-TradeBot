"""
Lightweight daily auto-rebalance scheduler for paper trading.

A daemon thread wakes periodically and, once per day after the US market close,
re-runs each user's auto-enabled paper session on live DOW30 data.

Per-user: each PaperSession with auto_enabled=True is rebalanced independently,
using that user's Alpaca paper keys when configured.
"""
from __future__ import annotations

import logging
import threading
import time
from datetime import datetime, timezone

logger = logging.getLogger(__name__)

REBALANCE_HOUR_UTC = 21
SIGNALS_HOUR_UTC   = 21
CHECK_INTERVAL_SEC = 1800
REBALANCE_WEEKDAY  = 0
_last_run_week: str | None = None
_last_signal_day: str | None = None
_last_ewma_day: str | None = None
_started = False


def _run_daily_signals():
    """Regenerate the shared signal feed for US + EGX once per day."""
    import uuid
    from app.database import SessionLocal, Job
    from app.tasks.ml_tasks import generate_signals_task
    from app.services.live_trading_service import LIVE_TICKERS, EGX_LIVE_TICKERS

    for market, tickers in (("us", LIVE_TICKERS), ("egx", EGX_LIVE_TICKERS)):
        job_id = str(uuid.uuid4())
        db = SessionLocal()
        try:
            db.add(Job(id=job_id, type="signal_generation", status="pending",
                       created_at=datetime.utcnow(),
                       meta={"tickers": tickers, "market": market, "scheduled": True}))
            db.commit()
        finally:
            db.close()
        generate_signals_task.delay(job_id=job_id, tickers=tickers, market=market)
        logger.info("Daily signal generation queued: %s (%d tickers)", market, len(tickers))


def _run_ewma_update():
    """Best-effort EWMA score update after market close (uses prior-day signals)."""
    import numpy as np
    from datetime import timedelta
    from app.database import SessionLocal, Signal
    from app.services.ewma_tracker_service import initialize_tracker, update_scores_for_date

    db = SessionLocal()
    try:
        initialize_tracker(db)
        yesterday = (datetime.now(timezone.utc) - timedelta(days=1)).strftime("%Y-%m-%d")
        recent = (
            db.query(Signal)
            .filter(Signal.market == "us")
            .order_by(Signal.generated_at.desc())
            .limit(500)
            .all()
        )
        rows = [r for r in recent if r.generated_at and r.generated_at.strftime("%Y-%m-%d") == yesterday]
        if not rows:
            logger.info("EWMA update: no US signals for %s — skipping", yesterday)
            return
        preds = {
            "xgboost": float(np.mean([r.xgb_prob or 0.5 for r in rows])),
            "lstm": float(np.mean([r.lstm_prob or 0.5 for r in rows])),
            "ppo": float(np.mean([r.ppo_signal or 0.5 for r in rows])),
            "a2c": float(np.mean([r.ppo_signal or 0.5 for r in rows])),
            "ddpg": float(np.mean([r.ppo_signal or 0.5 for r in rows])),
            "td3": float(np.mean([r.ppo_signal or 0.5 for r in rows])),
            "sac": float(np.mean([r.ppo_signal or 0.5 for r in rows])),
        }
        try:
            import yfinance as yf
            tickers = list({r.ticker for r in rows if r.ticker})[:10]
            if tickers:
                hist = yf.download(tickers, period="5d", progress=False, auto_adjust=True)
                rets = {}
                if hist is not None and not hist.empty:
                    close = hist["Close"] if "Close" in hist.columns else hist
                    for t in tickers:
                        try:
                            s = close[t] if hasattr(close, "columns") else close
                            if len(s) >= 2:
                                rets[t] = float(s.iloc[-1] / s.iloc[-2] - 1)
                        except Exception:
                            pass
                if rets:
                    update_scores_for_date(yesterday, preds, rets, db)
                    logger.info("EWMA scores updated for %s (%d tickers)", yesterday, len(rets))
        except Exception as exc:
            logger.warning("EWMA update skipped: %s", exc)
    finally:
        db.close()


def _apply_sim_session(row, alloc: dict, cash: float, db) -> bool:
    """Update one user's simulated PaperSession positions."""
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
    logger.info("Daily sim rebalance user=%s session=%s (%d positions)",
                row.user_id, row.id, len(positions))
    return True


def _rebalance_one_session(row, db) -> None:
    """Rebalance a single auto-enabled paper session (sim or Alpaca)."""
    from app.database import User
    from app.services.live_trading_service import (
        generate_live_allocation, generate_meta_allocation,
    )
    from app.services import alpaca_service

    user = db.query(User).filter(User.id == row.user_id).first() if row.user_id else None
    if user:
        alpaca_service.use_credentials(user.alpaca_api_key, user.alpaca_api_secret)

    cash = float(row.initial_cash or 100_000.0)
    run_id = row.run_id or ""
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
        logger.info("Weekly rebalance: session %s has no run_id — skipping", row.id)
        return
    if not alloc.get("ok"):
        logger.warning("Weekly rebalance failed session=%s: %s", row.id, alloc.get("message"))
        return

    if alpaca_service.configured():
        risk = alpaca_service.enforce_risk()
        if risk.get("breached"):
            logger.warning("Weekly rebalance halted session=%s: %s", row.id, risk.get("action"))
            return
        tv = {t: alloc["target"].get(t, 0.0) * alloc["prices"].get(t, 0.0)
              for t in alloc["tickers"]}
        tot = sum(v for v in tv.values() if v > 0)
        weights = {t: v / tot for t, v in tv.items() if v > 0} if tot > 0 else {}
        res = alpaca_service.rebalance_to_weights(weights)
        logger.info("Weekly Alpaca rebalance user=%s: %d orders",
                    row.user_id, res.get("n_orders", 0))
    else:
        _apply_sim_session(row, alloc, cash, db)


def _run_weekly_rebalance():
    """Rebalance every auto-enabled running session (per-user)."""
    from app.database import SessionLocal, PaperSession

    db = SessionLocal()
    try:
        rows = (
            db.query(PaperSession)
            .filter(PaperSession.running.is_(True), PaperSession.auto_enabled.is_(True))
            .all()
        )
        if not rows:
            logger.info("Weekly rebalance: no auto-enabled sessions — skipping")
            return
        for row in rows:
            try:
                _rebalance_one_session(row, db)
            except Exception:
                logger.exception("Weekly rebalance failed for session %s", row.id)
    except Exception:
        logger.exception("Weekly rebalance crashed")
    finally:
        db.close()


def _loop():
    global _last_run_week, _last_signal_day, _last_ewma_day
    while True:
        try:
            now = datetime.now(timezone.utc)
            iso_week = f"{now.isocalendar().year}-W{now.isocalendar().week}"
            iso_day = now.strftime("%Y-%m-%d")
            if now.hour >= SIGNALS_HOUR_UTC and _last_signal_day != iso_day:
                logger.info("Triggering daily signal generation (%s)", iso_day)
                _run_daily_signals()
                _last_signal_day = iso_day
            if now.hour >= SIGNALS_HOUR_UTC and _last_ewma_day != iso_day:
                _run_ewma_update()
                _last_ewma_day = iso_day
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
    _run_weekly_rebalance()


def trigger_daily_signals_now():
    _run_daily_signals()


def start_scheduler():
    global _started
    if _started:
        return
    _started = True
    t = threading.Thread(target=_loop, name="paper-rebalance-scheduler", daemon=True)
    t.start()
    logger.info("Paper-trading scheduler started (weekday=%d, UTC hour=%d)",
                REBALANCE_WEEKDAY, REBALANCE_HOUR_UTC)
