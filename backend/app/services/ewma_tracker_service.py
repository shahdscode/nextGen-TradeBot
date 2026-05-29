"""
Adaptive EWMA Performance Tracker.

After each trading day:
1. Check whether each model's signal was correct
2. Update EWMA performance score for each model
3. Compute fusion weights proportional to scores
4. Persist to model_performance_scores table

Decay factor λ=0.94 gives a ~16-day effective half-life so recent
performance matters more than history from months ago.

All 7 models are tracked independently — the market decides which
RL algorithm is most accurate right now, not a human-chosen weight.

Academic reference
------------------
Freund & Schapire (1997) — A Decision-Theoretic Generalization of
On-Line Learning and an Application to Boosting (Hedge Algorithm)
"""
import logging
import uuid
from datetime import datetime
from typing import Any, Dict, List, Optional

import numpy as np

logger = logging.getLogger(__name__)

MODEL_KEYS   = ["xgboost", "lstm", "ppo", "a2c", "ddpg", "td3", "sac"]
EWMA_DECAY   = 0.94    # λ — 0.94 ≈ 16-day effective half-life
MIN_WEIGHT   = 0.02    # floor so no model is completely ignored
INITIAL_SCORE = 0.5    # all models start equal


# ── Initialisation ─────────────────────────────────────────────────────────────

def initialize_tracker(db_session) -> None:
    """
    Create initial equal scores for all 7 models.
    Only runs once — silently skips if rows already exist.
    """
    from app.database import ModelPerformanceScore

    today = datetime.utcnow().strftime("%Y-%m-%d")
    existing = (
        db_session.query(ModelPerformanceScore)
        .filter(ModelPerformanceScore.model_key.in_(MODEL_KEYS))
        .first()
    )
    if existing is not None:
        logger.debug("EWMA tracker already initialised — skipping")
        return

    for key in MODEL_KEYS:
        row = ModelPerformanceScore(
            id            = str(uuid.uuid4()),
            date          = today,
            model_key     = key,
            ewma_score    = INITIAL_SCORE,
            daily_correct = None,
            weight        = 1.0 / len(MODEL_KEYS),
        )
        db_session.add(row)
    db_session.commit()
    logger.info("EWMA tracker initialised with equal scores for %d models", len(MODEL_KEYS))


# ── Daily update ────────────────────────────────────────────────────────────────

def update_scores_for_date(
    date: str,
    model_predictions: Dict[str, float],
    actual_returns: Dict[str, float],
    db_session,
) -> Dict[str, float]:
    """
    Update EWMA scores based on outcomes for one trading date.

    Parameters
    ----------
    date               : "YYYY-MM-DD" of the day being evaluated
    model_predictions  : {model_key: signal (0-1)} — signal generated YESTERDAY
    actual_returns     : {ticker: realized_return_today (float)}
    db_session         : SQLAlchemy session

    Returns
    -------
    New scores dict: {model_key: new_ewma_score}

    Algorithm
    ---------
    For each model:
        predicted_up = signal > 0.5
        actual_up    = mean(actual_returns) > 0       # cross-ticker average
        correct      = 1.0 if predicted_up == actual_up else 0.0
        new_score    = λ × old_score + (1 − λ) × correct
    """
    from app.database import ModelPerformanceScore

    if not actual_returns:
        logger.warning("update_scores_for_date: empty actual_returns for %s — skipping", date)
        return {}

    avg_return = float(np.mean(list(actual_returns.values())))
    actual_up  = avg_return > 0

    # Get latest score for each model
    latest: Dict[str, float] = {}
    for key in MODEL_KEYS:
        row = (
            db_session.query(ModelPerformanceScore)
            .filter(ModelPerformanceScore.model_key == key)
            .order_by(ModelPerformanceScore.date.desc())
            .first()
        )
        latest[key] = row.ewma_score if row is not None else INITIAL_SCORE

    new_scores: Dict[str, float] = {}
    for key in MODEL_KEYS:
        signal       = float(model_predictions.get(key, 0.5))
        predicted_up = signal > 0.5
        correct      = 1.0 if predicted_up == actual_up else 0.0

        new_score    = EWMA_DECAY * latest[key] + (1 - EWMA_DECAY) * correct
        new_scores[key] = float(new_score)

    # Compute normalised weights with floor
    weights = _scores_to_weights(new_scores)

    # Persist
    for key in MODEL_KEYS:
        signal       = float(model_predictions.get(key, 0.5))
        predicted_up = signal > 0.5
        correct      = 1.0 if predicted_up == actual_up else 0.0

        row = ModelPerformanceScore(
            id            = str(uuid.uuid4()),
            date          = date,
            model_key     = key,
            ewma_score    = round(new_scores[key], 6),
            daily_correct = correct,
            weight        = round(weights[key], 6),
        )
        db_session.add(row)

    db_session.commit()
    logger.info("EWMA scores updated for %s: top=%s (%.3f)",
                date,
                max(new_scores, key=new_scores.get),
                max(new_scores.values()))
    return new_scores


# ── Weight retrieval ────────────────────────────────────────────────────────────

def get_current_weights(db_session) -> Dict[str, Any]:
    """
    Return the most-recent normalised fusion weights for all 7 models.

    Returns
    -------
    {
      "xgboost": float, "lstm": float, "ppo": float,
      "a2c": float, "ddpg": float, "td3": float, "sac": float,
      "method":     "ewma_adaptive",
      "updated_at": "YYYY-MM-DD"
    }
    Falls back to equal weights if no scores exist.
    """
    from app.database import ModelPerformanceScore

    scores: Dict[str, float] = {}
    latest_date = "—"
    for key in MODEL_KEYS:
        row = (
            db_session.query(ModelPerformanceScore)
            .filter(ModelPerformanceScore.model_key == key)
            .order_by(ModelPerformanceScore.date.desc())
            .first()
        )
        if row is not None:
            scores[key] = row.ewma_score
            if row.date > latest_date:
                latest_date = row.date
        else:
            scores[key] = INITIAL_SCORE

    weights = _scores_to_weights(scores)
    weights["method"]     = "ewma_adaptive"
    weights["updated_at"] = latest_date
    return weights


# ── Weight history ──────────────────────────────────────────────────────────────

def get_weight_history(days: int = 30, db_session=None) -> List[Dict[str, Any]]:
    """
    Return the last ``days`` days of weight evolution for all models.

    Used for the admin dashboard chart showing how weights shift over time.

    Returns
    -------
    List of dicts: [{date, xgboost, lstm, ppo, a2c, ddpg, td3, sac, top_model}]
    sorted ascending by date.
    """
    from app.database import ModelPerformanceScore

    rows = (
        db_session.query(ModelPerformanceScore)
        .order_by(ModelPerformanceScore.date.desc())
        .limit(days * len(MODEL_KEYS))
        .all()
    )

    # Group by date
    by_date: Dict[str, Dict[str, float]] = {}
    for row in rows:
        d = row.date
        if d not in by_date:
            by_date[d] = {}
        by_date[d][row.model_key] = row.ewma_score

    history = []
    for date in sorted(by_date.keys()):
        scores  = by_date[date]
        weights = _scores_to_weights({k: scores.get(k, INITIAL_SCORE) for k in MODEL_KEYS})
        entry   = {"date": date}
        entry.update({k: round(weights[k], 4) for k in MODEL_KEYS})
        entry["top_model"] = max(MODEL_KEYS, key=lambda k: weights[k])
        history.append(entry)

    return history[-days:]


# ── Internal helpers ────────────────────────────────────────────────────────────

def _scores_to_weights(scores: Dict[str, float]) -> Dict[str, float]:
    """Convert raw EWMA scores to fusion weights with MIN_WEIGHT floor, sum=1."""
    raw = {k: max(float(scores.get(k, INITIAL_SCORE)), MIN_WEIGHT) for k in MODEL_KEYS}
    total = sum(raw.values())
    return {k: round(v / total, 6) for k, v in raw.items()}
