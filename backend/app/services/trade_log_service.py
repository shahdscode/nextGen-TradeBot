"""
Explainable trade logging.

Persists WHY each trade happened, not just that it happened. Given an allocation
result (from live_trading_service) and the list of trades actually executed,
writes one TradeLog row per trade capturing the meta probability, per-model
votes, regime, volatility regime, sizing rationale, and a key-indicator snapshot.

This makes the engine auditable: any position can be traced back to the exact
signals and risk posture that produced it.
"""
from __future__ import annotations

import logging
import uuid
from typing import Any, Dict, List, Optional

from app.database import SessionLocal, TradeLog

logger = logging.getLogger(__name__)


def _reason(action: str, ticker: str, meta_prob: Optional[float],
            regime: Optional[str], vol_regime: Optional[str],
            weight: Optional[float], stop: Optional[float],
            tp: Optional[float], votes: Dict[str, Any]) -> str:
    bits = [f"{action} {ticker}"]
    if meta_prob is not None:
        bits.append(f"meta {meta_prob:.2f}")
    if votes:
        top = ", ".join(f"{k}={v}" for k, v in list(votes.items())[:3])
        bits.append(f"models[{top}]")
    if regime or vol_regime:
        bits.append(f"regime {regime or '?'}/{vol_regime or '?'}")
    if weight is not None:
        bits.append(f"weight {weight:.0%}")
    if stop is not None and tp is not None:
        bits.append(f"stop {stop} / target {tp}")
    return " — ".join(bits)


def log_trades(alloc: Dict[str, Any], executed: List[Dict[str, Any]],
               venue: str, session_id: Optional[str] = None,
               db=None) -> int:
    """
    Write a TradeLog row for each executed trade.

    alloc    : the dict returned by generate_meta_allocation (has meta_prob,
               stops, sizing, regime, vol_regime, model_signals, indicators).
    executed : [{ticker, action, shares, price}] actually traded this cycle.
    venue    : "sim" | "alpaca".
    Returns number of rows written.
    """
    if not executed:
        return 0
    own_db = db is None
    db = db or SessionLocal()
    market = alloc.get("market", "us")
    regime = alloc.get("regime")
    vol_regime = (alloc.get("vol_regime") or {}).get("vol_regime")
    sizing_method = alloc.get("sizing_method")
    stops = alloc.get("stops", {})
    positions = (alloc.get("sizing") or {}).get("positions", {})
    meta_prob = alloc.get("meta_prob", {})
    model_signals = alloc.get("model_signals", {})
    indicators = alloc.get("indicators", {})

    n = 0
    try:
        for tr in executed:
            t = tr.get("ticker")
            action = (tr.get("action") or "").upper()
            if not t or action not in ("BUY", "SELL"):
                continue
            pos = positions.get(t, {})
            st = stops.get(t, {})
            votes = model_signals.get(t, {})
            row = TradeLog(
                id=str(uuid.uuid4()),
                session_id=session_id, venue=venue, market=market,
                ticker=t, action=action,
                shares=tr.get("shares"), price=tr.get("price"),
                weight=pos.get("weight"),
                meta_prob=meta_prob.get(t),
                regime=regime, vol_regime=vol_regime, sizing_method=sizing_method,
                stop_price=st.get("stop_price"), take_profit=st.get("take_profit"),
                risk_dollars=pos.get("risk_dollars"),
                model_signals=votes or None,
                indicators=indicators.get(t) or None,
                reason=_reason(action, t, meta_prob.get(t), regime, vol_regime,
                               pos.get("weight"), st.get("stop_price"),
                               st.get("take_profit"), votes),
            )
            db.add(row)
            n += 1
        db.commit()
    except Exception:
        db.rollback()
        logger.exception("log_trades failed")
    finally:
        if own_db:
            db.close()
    return n


def get_trade_log(limit: int = 50, session_id: Optional[str] = None,
                  ticker: Optional[str] = None,
                  session_ids: Optional[List[str]] = None) -> List[Dict[str, Any]]:
    """Return recent trade-log rows (newest first), optionally filtered."""
    db = SessionLocal()
    try:
        q = db.query(TradeLog)
        if session_id:
            q = q.filter(TradeLog.session_id == session_id)
        elif session_ids is not None:
            if not session_ids:
                return []
            q = q.filter(TradeLog.session_id.in_(session_ids))
        if ticker:
            q = q.filter(TradeLog.ticker == ticker.upper())
        rows = q.order_by(TradeLog.created_at.desc()).limit(limit).all()
        return [{
            "id": r.id, "created_at": r.created_at.isoformat() if r.created_at else None,
            "venue": r.venue, "market": r.market, "ticker": r.ticker,
            "action": r.action, "shares": r.shares, "price": r.price,
            "weight": r.weight, "meta_prob": r.meta_prob,
            "regime": r.regime, "vol_regime": r.vol_regime,
            "sizing_method": r.sizing_method,
            "stop_price": r.stop_price, "take_profit": r.take_profit,
            "risk_dollars": r.risk_dollars,
            "model_signals": r.model_signals, "indicators": r.indicators,
            "reason": r.reason,
        } for r in rows]
    finally:
        db.close()
