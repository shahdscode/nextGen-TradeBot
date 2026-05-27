"""
Signal card endpoints for the user-facing app.
"""
from fastapi import APIRouter, HTTPException, Query
from typing import Optional, List
from datetime import datetime, timedelta
from app.database import SessionLocal, Signal

router = APIRouter(prefix="/signals", tags=["signals"])


@router.get("/top")
def get_top_signals(
    market: str = Query("us"),
    limit: int = Query(20, ge=1, le=100),
    action: Optional[str] = Query(None),
    min_confidence: float = Query(0.0),
    hours: int = Query(48),
):
    """Get the most recent non-suppressed signals."""
    db = SessionLocal()
    try:
        cutoff = datetime.utcnow() - timedelta(hours=hours)
        q = db.query(Signal).filter(
            Signal.generated_at >= cutoff,
            Signal.confidence >= max(min_confidence, 0.55),
        )
        if market != "all":
            q = q.filter(Signal.market == market)
        if action:
            q = q.filter(Signal.action == action.upper())

        signals = q.order_by(Signal.confidence.desc()).limit(limit).all()
        return [_serialize(s) for s in signals]
    finally:
        db.close()


@router.get("/ticker/{ticker}")
def get_signal_for_ticker(ticker: str, market: str = Query("us")):
    """Get the latest signal for a specific ticker."""
    db = SessionLocal()
    try:
        sig = (
            db.query(Signal)
            .filter(Signal.ticker == ticker.upper(), Signal.market == market)
            .order_by(Signal.generated_at.desc())
            .first()
        )
        if not sig:
            raise HTTPException(status_code=404, detail=f"No signal found for {ticker}")
        return _serialize(sig)
    finally:
        db.close()


@router.get("/history/{ticker}")
def get_signal_history(ticker: str, market: str = Query("us"), limit: int = Query(30)):
    """Signal history for a ticker (for leaderboard / charting)."""
    db = SessionLocal()
    try:
        sigs = (
            db.query(Signal)
            .filter(Signal.ticker == ticker.upper(), Signal.market == market)
            .order_by(Signal.generated_at.desc())
            .limit(limit)
            .all()
        )
        return [_serialize(s) for s in sigs]
    finally:
        db.close()


@router.get("/leaderboard")
def get_leaderboard(market: str = Query("us"), hours: int = Query(168)):
    """
    Leaderboard: group signals by ticker and return those with the
    highest average confidence over the last `hours` hours.
    """
    db = SessionLocal()
    try:
        cutoff = datetime.utcnow() - timedelta(hours=hours)
        sigs = (
            db.query(Signal)
            .filter(Signal.generated_at >= cutoff, Signal.market == market)
            .order_by(Signal.generated_at.desc())
            .all()
        )

        by_ticker: dict = {}
        for s in sigs:
            t = s.ticker
            if t not in by_ticker:
                by_ticker[t] = []
            by_ticker[t].append(s)

        rows = []
        for ticker, items in by_ticker.items():
            latest = items[0]
            avg_conf = sum(i.confidence for i in items) / len(items)
            rows.append({
                "ticker": ticker,
                "latest_action": latest.action,
                "latest_confidence": round(latest.confidence, 4),
                "avg_confidence": round(avg_conf, 4),
                "signal_count": len(items),
                "regime": latest.regime,
                "risk_level": latest.risk_level,
                "generated_at": latest.generated_at.isoformat() if latest.generated_at else None,
            })

        rows.sort(key=lambda r: r["avg_confidence"], reverse=True)
        return rows[:20]
    finally:
        db.close()


def _serialize(sig: Signal) -> dict:
    return {
        "id": sig.id,
        "ticker": sig.ticker,
        "action": sig.action,
        "confidence": sig.confidence,
        "confidence_pct": round(sig.confidence * 100, 1),
        "regime": sig.regime,
        "model_breakdown": {
            "xgboost": {"probability": sig.xgb_prob},
            "lstm": {"probability": sig.lstm_prob},
            "ppo": {"signal": sig.ppo_signal},
        },
        "sentiment": {"score": sig.sentiment_score},
        "shap_reasons": sig.shap_features or [],
        "risk_level": sig.risk_level,
        "stop_loss_pct": sig.stop_loss_pct,
        "market": sig.market,
        "generated_at": sig.generated_at.isoformat() if sig.generated_at else None,
    }
