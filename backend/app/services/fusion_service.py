"""
Signal fusion layer.
Combines XGBoost, LSTM, PPO signals with regime-adjusted weights + sentiment modifier.
Produces an explainability card ready for the frontend.
"""
import uuid
import numpy as np
from datetime import datetime
from typing import Dict, Any, List, Optional

from app.services.regime_service import get_current_regime, get_regime_weights
from app.services.sentiment_service import fetch_and_score
from app.database import SessionLocal, Signal

CONFIDENCE_THRESHOLD = 0.55  # suppress signals below this


def fuse_signals(
    xgb_prob: float,
    lstm_prob: float,
    ppo_signal: float,  # 0–1, higher = more bullish allocation
    sentiment_score: float,
    regime: str,
) -> Dict[str, Any]:
    """Combine model outputs into a single fused confidence score."""
    weights = get_regime_weights(regime)

    # Weighted average of model probabilities
    raw = (
        weights["xgb"] * xgb_prob +
        weights["lstm"] * lstm_prob +
        weights["ppo"] * ppo_signal
    )

    # Sentiment modifier: ±5% max
    sentiment_modifier = np.clip(sentiment_score * 0.05, -0.05, 0.05)
    confidence = float(np.clip(raw + sentiment_modifier, 0.0, 1.0))

    return {
        "confidence": round(confidence, 4),
        "xgb_weight": weights["xgb"],
        "lstm_weight": weights["lstm"],
        "ppo_weight": weights["ppo"],
        "raw_confidence": round(raw, 4),
        "sentiment_modifier": round(sentiment_modifier, 4),
    }


def apply_risk_guardrails(
    confidence: float,
    regime: str,
) -> Dict[str, Any]:
    """Check confidence threshold and compute risk metadata."""
    suppressed = confidence < CONFIDENCE_THRESHOLD

    # Dynamic stop-loss based on regime
    stop_loss_map = {"BULL": 2.5, "BEAR": 4.0, "SIDEWAYS": 3.0}
    stop_loss_pct = stop_loss_map.get(regime, 3.0)

    # Risk level
    if confidence >= 0.70:
        risk_level = "LOW"
    elif confidence >= 0.60:
        risk_level = "MEDIUM"
    else:
        risk_level = "HIGH"

    return {
        "suppressed": suppressed,
        "risk_level": risk_level,
        "stop_loss_pct": stop_loss_pct,
        "confidence_threshold": CONFIDENCE_THRESHOLD,
    }


def build_signal_card(
    ticker: str,
    market: str,
    fused: Dict[str, Any],
    guardrails: Dict[str, Any],
    xgb_prob: float,
    lstm_prob: float,
    ppo_signal: float,
    sentiment: Dict[str, Any],
    regime: str,
    shap_features: List[Dict],
) -> Dict[str, Any]:
    """Assemble the full signal card for display."""
    confidence = fused["confidence"]

    if confidence >= 0.58:
        action = "BUY"
    elif confidence <= 0.44:
        action = "SELL"
    else:
        action = "HOLD"

    return {
        "id": str(uuid.uuid4()),
        "ticker": ticker,
        "market": market,
        "action": action,
        "confidence": confidence,
        "confidence_pct": round(confidence * 100, 1),
        "regime": regime,
        "model_breakdown": {
            "xgboost": {"probability": round(xgb_prob, 4), "weight": fused["xgb_weight"]},
            "lstm": {"probability": round(lstm_prob, 4), "weight": fused["lstm_weight"]},
            "ppo": {"signal": round(ppo_signal, 4), "weight": fused["ppo_weight"]},
        },
        "sentiment": {
            "score": sentiment.get("score", 0.0),
            "label": sentiment.get("label", "neutral"),
            "headline_count": sentiment.get("headline_count", 0),
        },
        "shap_reasons": shap_features[:5],
        "risk_level": guardrails["risk_level"],
        "stop_loss_pct": guardrails["stop_loss_pct"],
        "suppressed": guardrails["suppressed"],
        "generated_at": datetime.utcnow().isoformat(),
    }


def generate_full_signal(
    ticker: str,
    market: str = "us",
    df=None,
    xgb_model_path: Optional[str] = None,
    lstm_model_path: Optional[str] = None,
    ppo_run_id: Optional[str] = None,
) -> Dict[str, Any]:
    """
    Full signal generation pipeline for one ticker.
    Returns a signal card ready for DB persistence and frontend display.
    """
    regime = get_current_regime(market)
    sentiment = fetch_and_score(ticker)

    # ── XGBoost inference ────────────────────────────────────────────────────
    xgb_prob = 0.5
    shap_features = []
    if xgb_model_path and df is not None:
        try:
            from app.services.xgboost_service import predict_xgboost
            from app.services.feature_service import build_features, prepare_xy, FEATURE_COLUMNS
            featured = build_features(df, ticker)
            if not featured.empty:
                X, _ = prepare_xy(featured.tail(1))
                result = predict_xgboost(X[0], xgb_model_path, FEATURE_COLUMNS)
                xgb_prob = result["probability"]
                shap_features = result.get("shap_features", [])
        except Exception:
            pass

    # ── LSTM inference ───────────────────────────────────────────────────────
    lstm_prob = 0.5
    if lstm_model_path and df is not None:
        try:
            from app.services.lstm_service import predict_lstm
            from app.services.feature_service import build_features, prepare_xy
            featured = build_features(df, ticker)
            if not featured.empty:
                X, _ = prepare_xy(featured.tail(30))
                result = predict_lstm(X, lstm_model_path)
                lstm_prob = result["probability"]
        except Exception:
            pass

    # ── PPO signal ───────────────────────────────────────────────────────────
    ppo_signal = _get_ppo_signal(ppo_run_id, ticker, market)

    # ── Fuse ─────────────────────────────────────────────────────────────────
    fused = fuse_signals(xgb_prob, lstm_prob, ppo_signal, sentiment.get("score", 0.0), regime)
    guardrails = apply_risk_guardrails(fused["confidence"], regime)

    card = build_signal_card(
        ticker=ticker,
        market=market,
        fused=fused,
        guardrails=guardrails,
        xgb_prob=xgb_prob,
        lstm_prob=lstm_prob,
        ppo_signal=ppo_signal,
        sentiment=sentiment,
        regime=regime,
        shap_features=shap_features,
    )

    # ── Persist to DB ────────────────────────────────────────────────────────
    _persist_signal(card)

    return card


def _get_ppo_signal(ppo_run_id: Optional[str], ticker: str, market: str) -> float:
    """
    Extract a normalised PPO allocation signal from [0, 1].

    Priority:
    1. Use the explicitly supplied run_id.
    2. If no run_id, look for the most-recently published RL run for the same market.
    3. If none published, use the most-recently completed RL run.
    4. Hard fallback: 0.5 (neutral).

    Reward → signal mapping (Almgren-Chriss inspired linear rescale):
      signal = clip((reward + 500) / 1000, 0.30, 0.70)
    This maps reward=0 → 0.5, reward=+500 → 1.0 (capped at 0.70),
    reward=-500 → 0.0 (floored at 0.30).
    """
    try:
        from app.database import SessionLocal, Run

        db = SessionLocal()

        run = None
        # 1. Explicit run_id
        if ppo_run_id:
            run = db.query(Run).filter(Run.id == ppo_run_id).first()

        # 2. Most recently published RL run for this market
        if run is None:
            run = (
                db.query(Run)
                .filter(
                    Run.published.is_(True),
                    Run.status == "done",
                    Run.model_type == "rl",
                    Run.market == market,
                )
                .order_by(Run.updated_at.desc())
                .first()
            )

        # 3. Most recently completed RL run for this market (unpublished OK)
        if run is None:
            run = (
                db.query(Run)
                .filter(
                    Run.status == "done",
                    Run.model_type == "rl",
                    Run.market == market,
                )
                .order_by(Run.updated_at.desc())
                .first()
            )

        db.close()

        if run is None or not run.metrics_json:
            return 0.5

        reward = float(run.metrics_json.get("final_reward", 0))
        return float(np.clip((reward + 500) / 1000, 0.30, 0.70))
    except Exception:
        return 0.5


def _persist_signal(card: Dict[str, Any]):
    db = SessionLocal()
    try:
        sig = Signal(
            id=card["id"],
            ticker=card["ticker"],
            action=card["action"],
            confidence=card["confidence"],
            regime=card.get("regime"),
            xgb_prob=card["model_breakdown"]["xgboost"]["probability"],
            lstm_prob=card["model_breakdown"]["lstm"]["probability"],
            ppo_signal=card["model_breakdown"]["ppo"]["signal"],
            sentiment_score=card["sentiment"]["score"],
            shap_features=card.get("shap_reasons"),
            risk_level=card.get("risk_level"),
            stop_loss_pct=card.get("stop_loss_pct"),
            market=card.get("market", "us"),
            generated_at=datetime.utcnow(),
        )
        db.add(sig)
        db.commit()
    except Exception:
        db.rollback()
    finally:
        db.close()
