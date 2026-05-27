"""
Market regime detection using 3-state Gaussian HMM.
States: BULL, BEAR, SIDEWAYS.
Falls back to VIX threshold rules when hmmlearn is unavailable.
"""
import json
import numpy as np
import pandas as pd
from pathlib import Path
from typing import Dict, Any, Tuple, Optional

from app.config import settings

try:
    from hmmlearn.hmm import GaussianHMM
    HMM_AVAILABLE = True
except ImportError:
    HMM_AVAILABLE = False

try:
    import yfinance as yf
    YF_AVAILABLE = True
except ImportError:
    YF_AVAILABLE = False

REGIME_WEIGHTS = {
    "BULL":     {"xgb": 0.45, "lstm": 0.35, "ppo": 0.20},
    "BEAR":     {"xgb": 0.35, "lstm": 0.30, "ppo": 0.35},
    "SIDEWAYS": {"xgb": 0.40, "lstm": 0.33, "ppo": 0.27},
}

REGIME_MODEL_PATH = str(Path(settings.models_dir) / "regime_model.json")


def train_regime_model(market: str = "us") -> Dict[str, Any]:
    """Train (or retrain) the HMM regime model and persist state thresholds."""
    features = _fetch_regime_features(market)
    if features is None or len(features) < 50:
        return _synthetic_regime_result()

    if HMM_AVAILABLE:
        try:
            model = GaussianHMM(n_components=3, covariance_type="full", n_iter=200, random_state=42)
            model.fit(features)
            labels = model.predict(features)
            # Map states to regime names by mean return (ascending = BEAR < SIDEWAYS < BULL)
            state_returns = {s: features[labels == s, 0].mean() for s in range(3)}
            sorted_states = sorted(state_returns, key=lambda s: state_returns[s])
            state_map = {sorted_states[0]: "BEAR", sorted_states[1]: "SIDEWAYS", sorted_states[2]: "BULL"}
            current_regime = state_map[int(labels[-1])]

            result = {
                "market": market,
                "current_regime": current_regime,
                "state_map": {str(k): v for k, v in state_map.items()},
                "means": [features[labels == s, 0].mean() for s in range(3)],
                "method": "hmm",
            }
        except Exception:
            result = _rule_based_regime(features)
    else:
        result = _rule_based_regime(features)

    Path("./data/models").mkdir(parents=True, exist_ok=True)
    with open(REGIME_MODEL_PATH, "w") as f:
        json.dump(result, f)

    return result


def get_current_regime(market: str = "us") -> str:
    """Return current regime label: BULL | BEAR | SIDEWAYS."""
    try:
        with open(REGIME_MODEL_PATH) as f:
            data = json.load(f)
        # Refresh if stale (older than 1 day) — simple check via the saved result
        return data.get("current_regime", "BULL")
    except Exception:
        pass

    result = train_regime_model(market)
    return result.get("current_regime", "BULL")


def get_regime_weights(regime: str) -> Dict[str, float]:
    return REGIME_WEIGHTS.get(regime, REGIME_WEIGHTS["SIDEWAYS"])


def get_regime_info(market: str = "us") -> Dict[str, Any]:
    try:
        with open(REGIME_MODEL_PATH) as f:
            data = json.load(f)
        data["weights"] = get_regime_weights(data.get("current_regime", "BULL"))
        if data.get("method") == "synthetic":
            data["source"] = "demo"
        elif data.get("method") in ("hmm", "rule_based"):
            data["source"] = "live"
        else:
            data["source"] = "cached"
        return data
    except Exception:
        features = _fetch_regime_features(market)
        if features is not None and len(features) >= 50:
            result = _rule_based_regime(features)
            result["market"] = market
            result["weights"] = get_regime_weights(result["current_regime"])
            result["source"] = "live"
            return result
        if not settings.market_allow_demo_fallback:
            return {
                "market": market,
                "current_regime": "SIDEWAYS",
                "weights": get_regime_weights("SIDEWAYS"),
                "method": "unavailable",
                "source": "unavailable",
            }
        regime = get_current_regime(market)
        return {
            "market": market,
            "current_regime": regime,
            "weights": get_regime_weights(regime),
            "method": "cached",
            "source": "demo",
        }


# ── Internal helpers ─────────────────────────────────────────────────────────

def _fetch_regime_features(market: str) -> Optional[np.ndarray]:
    if not YF_AVAILABLE:
        return None
    try:
        if market == "egx":
            idx = yf.download("^CASE30", period="3y", progress=False, auto_adjust=True)
        else:
            idx = yf.download("^GSPC", period="3y", progress=False, auto_adjust=True)
            vix = yf.download("^VIX", period="3y", progress=False, auto_adjust=True)

        if idx.empty:
            return None

        if hasattr(idx.columns, "levels"):
            idx.columns = [str(c[0]) for c in idx.columns]
        if market != "egx" and not vix.empty and hasattr(vix.columns, "levels"):
            vix.columns = [str(c[0]) for c in vix.columns]

        returns = idx["Close"].pct_change().dropna()
        vol = returns.rolling(20).std().dropna()

        if market != "egx" and not vix.empty:
            vix_vals = vix["Close"].reindex(vol.index).ffill().bfill()
            features = np.column_stack([
                returns.reindex(vol.index).fillna(0).values,
                vol.values,
                vix_vals.values,
            ])
        else:
            features = np.column_stack([
                returns.reindex(vol.index).fillna(0).values,
                vol.values,
            ])

        return features.astype(np.float64)
    except Exception:
        return None


def _rule_based_regime(features: np.ndarray) -> Dict[str, Any]:
    """Simple rule: last 20-day return + volatility level determines regime."""
    recent_return = float(features[-20:, 0].mean()) if len(features) >= 20 else 0.0
    recent_vol = float(features[-20:, 1].mean()) if len(features) >= 20 else 0.01
    vol_90th = float(np.percentile(features[:, 1], 90)) if len(features) > 0 else 0.02

    if recent_return > 0.0003 and recent_vol < vol_90th:
        regime = "BULL"
    elif recent_return < -0.0003 or recent_vol >= vol_90th:
        regime = "BEAR"
    else:
        regime = "SIDEWAYS"

    return {"current_regime": regime, "method": "rule_based", "recent_return": round(recent_return, 6)}


def _synthetic_regime_result() -> Dict[str, Any]:
    import random
    regime = random.choice(["BULL", "BULL", "SIDEWAYS"])
    return {"current_regime": regime, "method": "synthetic"}
