"""
Signal fusion layer.

Combines XGBoost, LSTM, and up to 5 RL model signals with:
  1. Meta-learner (trained stacking ensemble) — highest priority
  2. Adaptive EWMA weights (self-updating daily)  — second priority
  3. Fixed regime-based weights (backward-compatible fallback)

Includes turbulence hard filter (Kritzman et al. 2010) and risk guardrails.
"""
import uuid
import logging
import numpy as np
from datetime import datetime
from typing import Any, Dict, List, Optional

from app.services.regime_service import get_current_regime, get_regime_weights
from app.services.sentiment_service import fetch_and_score
from app.database import SessionLocal, Signal

logger = logging.getLogger(__name__)

CONFIDENCE_THRESHOLD         = 0.55   # suppress signals below this
TURBULENCE_SUPPRESS_PERCENTILE = 90   # BUY suppression above this turbulence percentile


# ── Turbulence hard filter ────────────────────────────────────────────────────

def apply_turbulence_filter(
    fusion_result: Dict[str, Any],
    current_turbulence: float,
    turbulence_history: List[float],
) -> Dict[str, Any]:
    """
    Suppress BUY signals when turbulence is in the top 10th percentile.

    HOLD and SELL are not affected — downside protection asymmetry is
    intentional (Kritzman et al. 2010: extreme turbulence precedes drawdowns).
    """
    if fusion_result.get("action") != "BUY":
        return fusion_result
    if not turbulence_history or current_turbulence is None:
        return fusion_result

    threshold = np.percentile(turbulence_history, TURBULENCE_SUPPRESS_PERCENTILE)
    if current_turbulence > threshold:
        fusion_result = dict(fusion_result)   # don't mutate caller's dict
        fusion_result["action"]                = "HOLD"
        fusion_result["turbulence_suppressed"] = True
        logger.debug("Turbulence hard filter fired: %.2f > threshold %.2f",
                     current_turbulence, threshold)
    return fusion_result


# ── Core fusion ───────────────────────────────────────────────────────────────

def fuse_signals(
    xgb_signal: float,
    lstm_signal: float,
    ppo_signal: float,
    a2c_signal:  Optional[float] = None,
    ddpg_signal: Optional[float] = None,
    td3_signal:  Optional[float] = None,
    sac_signal:  Optional[float] = None,
    regime:      str             = "UNKNOWN",
    sentiment_score: Optional[float] = None,
    # New fusion modes
    use_meta_learner:     bool            = False,
    meta_learner_path:    Optional[str]   = None,
    use_adaptive_weights: bool            = False,
    db_session                            = None,
    # Extra context for meta-learner
    vix_zscore: float = 0.0,
) -> Dict[str, Any]:
    """
    Combine model outputs into a single fused confidence score.

    Priority order
    --------------
    1. use_meta_learner=True AND model exists → stacking meta-learner
    2. use_adaptive_weights=True              → EWMA weights from tracker
    3. Fallback                               → fixed regime-based weights
    """
    sent_score = float(sentiment_score or 0.0)

    # ── Option 1: Meta-learner ───────────────────────────────────────────────
    if use_meta_learner and meta_learner_path:
        try:
            from app.services.meta_learner_service import (
                predict_meta_learner,
                META_LEARNER_FEATURES,
            )
            regime_bull = 1 if regime == "BULL" else 0
            regime_bear = 1 if regime == "BEAR" else 0
            fdict = {
                "xgb_signal":    float(xgb_signal),
                "lstm_signal":   float(lstm_signal),
                "ppo_signal":    float(ppo_signal),
                "a2c_signal":    float(a2c_signal  or ppo_signal),
                "ddpg_signal":   float(ddpg_signal or ppo_signal),
                "td3_signal":    float(td3_signal  or ppo_signal),
                "sac_signal":    float(sac_signal  or ppo_signal),
                "regime_bull":   regime_bull,
                "regime_bear":   regime_bear,
                "sentiment_score": sent_score,
                "vix_zscore":    float(vix_zscore),
            }
            result = predict_meta_learner(meta_learner_path, fdict)
            confidence = float(np.clip(result["probability"], 0.0, 1.0))
            return {
                "confidence":          round(confidence, 4),
                "method":              "meta_learner",
                "raw_confidence":      round(confidence, 4),
                "sentiment_modifier":  0.0,
                "weights":             result.get("feature_contributions", {}),
            }
        except Exception as exc:
            logger.warning("Meta-learner fusion failed (%s) — falling through", exc)

    # ── Option 2: Adaptive EWMA weights ─────────────────────────────────────
    if use_adaptive_weights and db_session is not None:
        try:
            from app.services.ewma_tracker_service import get_current_weights
            w = get_current_weights(db_session)
            raw = (
                w.get("xgboost", 1 / 7) * float(xgb_signal) +
                w.get("lstm",    1 / 7) * float(lstm_signal) +
                w.get("ppo",     1 / 7) * float(ppo_signal) +
                w.get("a2c",     1 / 7) * float(a2c_signal  or ppo_signal) +
                w.get("ddpg",    1 / 7) * float(ddpg_signal or ppo_signal) +
                w.get("td3",     1 / 7) * float(td3_signal  or ppo_signal) +
                w.get("sac",     1 / 7) * float(sac_signal  or ppo_signal)
            )
            sentiment_modifier = float(np.clip(sent_score * 0.05, -0.05, 0.05))
            confidence = float(np.clip(raw + sentiment_modifier, 0.0, 1.0))
            return {
                "confidence":         round(confidence, 4),
                "method":             "ewma_adaptive",
                "raw_confidence":     round(raw, 4),
                "sentiment_modifier": round(sentiment_modifier, 4),
                "weights":            {k: v for k, v in w.items() if k in
                                       ["xgboost", "lstm", "ppo", "a2c", "ddpg", "td3", "sac"]},
            }
        except Exception as exc:
            logger.warning("EWMA adaptive fusion failed (%s) — falling through", exc)

    # ── Option 3: Fixed regime weights (original behaviour) ─────────────────
    weights = get_regime_weights(regime)
    raw = (
        weights["xgb"] * float(xgb_signal) +
        weights["lstm"] * float(lstm_signal) +
        weights["ppo"] * float(ppo_signal)
    )
    sentiment_modifier = float(np.clip(sent_score * 0.05, -0.05, 0.05))
    confidence = float(np.clip(raw + sentiment_modifier, 0.0, 1.0))

    return {
        "confidence":         round(confidence, 4),
        "method":             "fixed_regime",
        "raw_confidence":     round(raw, 4),
        "sentiment_modifier": round(sentiment_modifier, 4),
        "xgb_weight":         weights["xgb"],
        "lstm_weight":        weights["lstm"],
        "ppo_weight":         weights["ppo"],
    }


# ── Risk guardrails ────────────────────────────────────────────────────────────

def apply_risk_guardrails(
    confidence: float,
    regime: str,
) -> Dict[str, Any]:
    """Check confidence threshold and compute risk metadata."""
    suppressed = confidence < CONFIDENCE_THRESHOLD

    stop_loss_map = {"BULL": 2.5, "BEAR": 4.0, "SIDEWAYS": 3.0}
    stop_loss_pct = stop_loss_map.get(regime, 3.0)

    if confidence >= 0.70:
        risk_level = "LOW"
    elif confidence >= 0.60:
        risk_level = "MEDIUM"
    else:
        risk_level = "HIGH"

    return {
        "suppressed":           suppressed,
        "risk_level":           risk_level,
        "stop_loss_pct":        stop_loss_pct,
        "confidence_threshold": CONFIDENCE_THRESHOLD,
    }


# ── Signal card builder ────────────────────────────────────────────────────────

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
    # Optional extra model signals
    a2c_signal:  Optional[float] = None,
    ddpg_signal: Optional[float] = None,
    td3_signal:  Optional[float] = None,
    sac_signal:  Optional[float] = None,
) -> Dict[str, Any]:
    """Assemble the full signal card for display."""
    confidence = fused["confidence"]

    if guardrails["suppressed"] or fused.get("turbulence_suppressed"):
        action = "SUPPRESSED"
    elif confidence >= 0.58:
        action = "BUY"
    elif confidence <= 0.44:
        action = "SELL"
    else:
        action = "HOLD"

    model_breakdown: Dict[str, Any] = {
        "xgboost": {"probability": round(xgb_prob,   4)},
        "lstm":    {"probability": round(lstm_prob,   4)},
        "ppo":     {"signal":      round(ppo_signal,  4)},
    }
    if a2c_signal  is not None: model_breakdown["a2c"]  = {"signal": round(a2c_signal,  4)}
    if ddpg_signal is not None: model_breakdown["ddpg"] = {"signal": round(ddpg_signal, 4)}
    if td3_signal  is not None: model_breakdown["td3"]  = {"signal": round(td3_signal,  4)}
    if sac_signal  is not None: model_breakdown["sac"]  = {"signal": round(sac_signal,  4)}

    return {
        "id":              str(uuid.uuid4()),
        "ticker":          ticker,
        "market":          market,
        "action":          action,
        "confidence":      confidence,
        "confidence_pct":  round(confidence * 100, 1),
        "regime":          regime,
        "fusion_method":   fused.get("method", "fixed_regime"),
        "model_breakdown": model_breakdown,
        "sentiment": {
            "score":          sentiment.get("score",          0.0),
            "label":          sentiment.get("label",          "neutral"),
            "headline_count": sentiment.get("headline_count", 0),
        },
        "shap_reasons":  shap_features[:5],
        "risk_level":    guardrails["risk_level"],
        "stop_loss_pct": guardrails["stop_loss_pct"],
        "suppressed":    action == "SUPPRESSED",
        "generated_at":  datetime.utcnow().isoformat(),
    }


# ── Full signal pipeline ───────────────────────────────────────────────────────

def deployable_base_signals(market: str = "us") -> Dict[str, Dict]:
    """
    Compute per-ticker XGBoost + LSTM probabilities from the POOLED DEPLOYABLE
    models (data/models/deploy/). Returns {ticker: {xgb, lstm, shap}}.

    These are the same models that power live Alpaca trading, so signal
    generation no longer depends on per-ticker per-run model files (which the
    OOF training steps never saved). Includes SHAP top-features for explainability.
    """
    import pickle
    import numpy as np
    import pandas as pd
    from pathlib import Path
    from app.config import settings
    from app.services.live_trading_service import _latest_featured

    deploy = Path(settings.models_dir) / "deploy"
    if not (deploy / "xgb_deploy.pkl").exists() or not (deploy / "lstm_deploy.pt").exists():
        return {}

    featured, latest_date = _latest_featured()
    latest = featured[pd.to_datetime(featured["date"]) == latest_date].copy()
    out: Dict[str, Dict] = {}

    # XGBoost (pooled) + SHAP
    with open(deploy / "xgb_deploy.pkl", "rb") as f:
        xgb_bundle = pickle.load(f)
    xgb_model, xgb_feats = xgb_bundle["model"], xgb_bundle["features"]
    explainer = None
    try:
        import shap
        explainer = shap.TreeExplainer(xgb_model)
    except Exception:
        explainer = None
    for _, r in latest.iterrows():
        x = r[xgb_feats].values.astype(np.float32).reshape(1, -1)
        prob = float(xgb_model.predict_proba(x)[0][1])
        shap_top = []
        if explainer is not None:
            try:
                sv = explainer.shap_values(x)
                sv = sv[0] if isinstance(sv, list) else sv
                contribs = sorted(zip(xgb_feats, np.ravel(sv)),
                                  key=lambda kv: abs(kv[1]), reverse=True)[:5]
                shap_top = [{"feature": f, "shap_value": round(float(v), 4)} for f, v in contribs]
            except Exception:
                shap_top = []
        out[r["tic"]] = {"xgb": prob, "lstm": 0.5, "shap": shap_top}

    # LSTM (pooled, last-seq_len sequence per ticker)
    try:
        import torch, torch.nn as nn
        ck = torch.load(deploy / "lstm_deploy.pt")
        seq_len, lf = ck["seq_len"], ck["features"]
        with open(deploy / "lstm_scaler.pkl", "rb") as f:
            lstm_scaler = pickle.load(f)

        class LSTMClf(nn.Module):
            def __init__(self, n):
                super().__init__()
                self.lstm = nn.LSTM(n, 64, num_layers=2, batch_first=True, dropout=0.3)
                self.fc = nn.Linear(64, 1); self.sig = nn.Sigmoid()
            def forward(self, x):
                o, _ = self.lstm(x); return self.sig(self.fc(o[:, -1, :]))

        lstm_model = LSTMClf(ck["n_features"]); lstm_model.load_state_dict(ck["state_dict"]); lstm_model.eval()
        for tic in out:
            g = featured[featured["tic"] == tic].sort_values("date")
            if len(g) < seq_len:
                continue
            seq = lstm_scaler.transform(g[lf].values.astype(np.float32))[-seq_len:]
            with torch.no_grad():
                out[tic]["lstm"] = float(lstm_model(torch.tensor(seq).unsqueeze(0)).item())
    except Exception as exc:
        logger.warning("LSTM deployable inference failed: %s", exc)

    return out


def generate_full_signal(
    ticker: str,
    market: str                  = "us",
    df                           = None,
    xgb_model_path: Optional[str]   = None,
    lstm_model_path: Optional[str]  = None,
    ppo_run_id: Optional[str]       = None,
    # New RL model support
    a2c_run_id:  Optional[str] = None,
    ddpg_run_id: Optional[str] = None,
    td3_run_id:  Optional[str] = None,
    sac_run_id:  Optional[str] = None,
    # Turbulence filter
    turbulence: Optional[float]         = None,
    turbulence_history: Optional[List]  = None,
    # Fusion mode
    meta_learner_path:    Optional[str] = None,
    calibrator_path:      Optional[str] = None,
    use_meta_learner:     bool          = False,
    use_adaptive_weights: bool          = False,
    db_session                          = None,
    # Pre-computed base probabilities (e.g. from the pooled deployable models).
    # When provided, they bypass per-run model-path prediction.
    xgb_prob_override:  Optional[float] = None,
    lstm_prob_override: Optional[float] = None,
    shap_features_override: Optional[List[Dict]] = None,
) -> Dict[str, Any]:
    """
    Full signal generation pipeline for one ticker.
    Returns a signal card ready for DB persistence and frontend display.
    """
    regime    = get_current_regime(market)
    sentiment = fetch_and_score(ticker)

    # ── XGBoost ──────────────────────────────────────────────────────────────
    xgb_prob = 0.5 if xgb_prob_override is None else float(xgb_prob_override)
    shap_features: List[Dict] = shap_features_override or []
    if xgb_prob_override is None and xgb_model_path and df is not None:
        try:
            from app.services.xgboost_service import predict_xgboost
            from app.services.feature_service import build_features, prepare_xy, FEATURE_COLUMNS
            featured = build_features(df, ticker)
            if not featured.empty:
                X, _ = prepare_xy(featured.tail(1))
                result = predict_xgboost(X[0], xgb_model_path, FEATURE_COLUMNS)
                xgb_prob = result["probability"]
                shap_features = result.get("shap_features", [])
        except Exception as exc:
            logger.debug("XGB inference failed for %s: %s", ticker, exc)

    # ── LSTM ─────────────────────────────────────────────────────────────────
    lstm_prob = 0.5 if lstm_prob_override is None else float(lstm_prob_override)
    if lstm_prob_override is None and lstm_model_path and df is not None:
        try:
            from app.services.lstm_service import predict_lstm
            from app.services.feature_service import build_features, prepare_xy
            featured = build_features(df, ticker)
            if not featured.empty:
                X, _ = prepare_xy(featured.tail(30))
                result = predict_lstm(X, lstm_model_path)
                lstm_prob = result["probability"]
        except Exception as exc:
            logger.debug("LSTM inference failed for %s: %s", ticker, exc)

    # ── RL signals (all 5 models) ────────────────────────────────────────────
    ppo_signal  = _get_rl_signal(ppo_run_id,  "ppo",  ticker, market)
    a2c_signal  = _get_rl_signal(a2c_run_id,  "a2c",  ticker, market)
    ddpg_signal = _get_rl_signal(ddpg_run_id, "ddpg", ticker, market)
    td3_signal  = _get_rl_signal(td3_run_id,  "td3",  ticker, market)
    sac_signal  = _get_rl_signal(sac_run_id,  "sac",  ticker, market)

    # Calibration (optional)
    if calibrator_path:
        from app.services.calibration_service import calibrate_score
        xgb_prob  = calibrate_score(xgb_prob,  calibrator_path)
        lstm_prob = calibrate_score(lstm_prob, calibrator_path)

    # ── Fuse ──────────────────────────────────────────────────────────────────
    fused = fuse_signals(
        xgb_signal=xgb_prob, lstm_signal=lstm_prob, ppo_signal=ppo_signal,
        a2c_signal=a2c_signal, ddpg_signal=ddpg_signal,
        td3_signal=td3_signal, sac_signal=sac_signal,
        regime=regime, sentiment_score=sentiment.get("score", 0.0),
        use_meta_learner=use_meta_learner, meta_learner_path=meta_learner_path,
        use_adaptive_weights=use_adaptive_weights, db_session=db_session,
    )

    guardrails = apply_risk_guardrails(fused["confidence"], regime)

    # ── Turbulence hard filter ────────────────────────────────────────────────
    if turbulence is not None and turbulence_history:
        fused = apply_turbulence_filter(fused, turbulence, turbulence_history)
        guardrails["turbulence_suppressed"] = fused.get("turbulence_suppressed", False)

    card = build_signal_card(
        ticker=ticker, market=market, fused=fused, guardrails=guardrails,
        xgb_prob=xgb_prob, lstm_prob=lstm_prob, ppo_signal=ppo_signal,
        sentiment=sentiment, regime=regime, shap_features=shap_features,
        a2c_signal=a2c_signal, ddpg_signal=ddpg_signal,
        td3_signal=td3_signal, sac_signal=sac_signal,
    )

    _persist_signal(card)
    return card


# ── PPO / RL signal helper ─────────────────────────────────────────────────────

def _get_ppo_signal(ppo_run_id: Optional[str], ticker: str, market: str) -> float:
    """Backward-compat alias — delegates to _get_rl_signal."""
    return _get_rl_signal(ppo_run_id, "ppo", ticker, market)


def _get_rl_signal(
    run_id: Optional[str],
    algorithm: str,
    ticker: str,
    market: str,
) -> float:
    """
    Extract a normalised RL allocation signal in [0, 1].

    Priority
    --------
    1. Explicit run_id
    2. Most-recently published RL run for this algorithm + market
    3. Most-recently completed RL run for this algorithm + market
    4. Hard fallback: 0.5 (neutral)

    Reward → signal mapping (linear rescale):
      signal = clip((reward + 500) / 1000, 0.30, 0.70)
    """
    try:
        from app.database import SessionLocal, Run

        _db = SessionLocal()
        run = None

        if run_id:
            run = _db.query(Run).filter(Run.id == run_id).first()

        if run is None:
            run = (
                _db.query(Run)
                .filter(
                    Run.published.is_(True),
                    Run.status == "done",
                    Run.algorithm == algorithm,
                    Run.market == market,
                )
                .order_by(Run.updated_at.desc())
                .first()
            )

        if run is None:
            run = (
                _db.query(Run)
                .filter(
                    Run.status == "done",
                    Run.algorithm == algorithm,
                    Run.market == market,
                )
                .order_by(Run.updated_at.desc())
                .first()
            )

        _db.close()

        if run is None or not run.metrics_json:
            return 0.5

        reward = float(run.metrics_json.get("final_reward", 0))
        return float(np.clip((reward + 500) / 1000, 0.30, 0.70))
    except Exception:
        return 0.5


# ── DB persistence ────────────────────────────────────────────────────────────

def _persist_signal(card: Dict[str, Any]):
    db = SessionLocal()
    try:
        mb = card.get("model_breakdown", {})
        sig = Signal(
            id             = card["id"],
            ticker         = card["ticker"],
            action         = card["action"],
            confidence     = card["confidence"],
            regime         = card.get("regime"),
            xgb_prob       = mb.get("xgboost", {}).get("probability"),
            lstm_prob      = mb.get("lstm",    {}).get("probability"),
            ppo_signal     = mb.get("ppo",     {}).get("signal"),
            sentiment_score = card["sentiment"]["score"],
            shap_features  = card.get("shap_reasons"),
            risk_level     = card.get("risk_level"),
            stop_loss_pct  = card.get("stop_loss_pct"),
            market         = card.get("market", "us"),
            generated_at   = datetime.utcnow(),
        )
        db.add(sig)
        db.commit()
    except Exception:
        db.rollback()
    finally:
        db.close()
