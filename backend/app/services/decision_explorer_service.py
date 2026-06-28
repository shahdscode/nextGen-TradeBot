"""
Decision Explorer — full auditable trace for a single trade decision.

Assembles model votes, regime, technical snapshot, risk sizing, optional
fundamentals, and a plain-language final explanation from a TradeLog row.
"""
from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

MODEL_ORDER = ["xgb", "lstm", "ppo", "a2c", "ddpg", "td3", "sac"]
MODEL_LABELS = {
    "xgb": "XGBoost", "lstm": "LSTM", "ppo": "PPO", "a2c": "A2C",
    "ddpg": "DDPG", "td3": "TD3", "sac": "SAC",
}
INDICATOR_LABELS = {
    "rsi_14": "RSI",
    "macd": "MACD",
    "atr": "ATR",
    "price_mom_20": "20d Momentum",
    "vix_zscore": "VIX Z-Score",
}


def _vote(signal: float) -> str:
    if signal is None:
        return "—"
    s = float(signal)
    if s > 0.55:
        return "BUY"
    if s < 0.45:
        return "SELL"
    return "HOLD"


def _macd_label(val: Optional[float]) -> str:
    if val is None:
        return "—"
    return "Positive" if float(val) > 0 else "Negative" if float(val) < 0 else "Flat"


def _atr_label(val: Optional[float], price: Optional[float]) -> str:
    if val is None or not price:
        return "—"
    pct = float(val) / float(price) * 100
    if pct < 2:
        return "Low"
    if pct > 4:
        return "High"
    return "Medium"


def _fetch_fundamentals(ticker: str) -> Dict[str, Any]:
    """Best-effort Yahoo Finance fundamentals (US tickers)."""
    if not ticker or ticker.endswith(".CA"):
        return {}
    try:
        import yfinance as yf
        info = yf.Ticker(ticker).info or {}
        pe = info.get("trailingPE") or info.get("forwardPE")
        roe = info.get("returnOnEquity")
        rev = info.get("revenueGrowth")
        out: Dict[str, Any] = {}
        if pe is not None:
            out["pe_ratio"] = round(float(pe), 2)
        if roe is not None:
            out["roe_pct"] = round(float(roe) * 100, 1)
        if rev is not None:
            out["revenue_growth_pct"] = round(float(rev) * 100, 1)
        return out
    except Exception as exc:
        logger.debug("fundamentals skipped for %s: %s", ticker, exc)
        return {}


def _model_votes(model_signals: Optional[Dict]) -> List[Dict[str, Any]]:
    ms = model_signals or {}
    rows = []
    for key in MODEL_ORDER:
        if key not in ms:
            continue
        sig = float(ms[key])
        rows.append({
            "key": key,
            "model": MODEL_LABELS.get(key, key.upper()),
            "signal": round(sig, 4),
            "vote": _vote(sig),
        })
    return rows


def _agreement_stats(votes: List[Dict[str, Any]]) -> Dict[str, Any]:
    if not votes:
        return {"buy": 0, "hold": 0, "sell": 0, "majority": None, "agreement_pct": 0}
    counts = {"BUY": 0, "HOLD": 0, "SELL": 0}
    for v in votes:
        counts[v["vote"]] = counts.get(v["vote"], 0) + 1
    majority = max(counts, key=counts.get)
    agreement_pct = round(100 * counts[majority] / len(votes))
    return {
        "buy": counts["BUY"],
        "hold": counts["HOLD"],
        "sell": counts["SELL"],
        "majority": majority,
        "agreement_pct": agreement_pct,
    }


def _build_explanation(
    action: str,
    meta_prob: Optional[float],
    agreement: Dict[str, Any],
    regime: Optional[str],
    vol_regime: Optional[str],
    weight: Optional[float],
) -> str:
    parts: List[str] = []
    mp = float(meta_prob) if meta_prob is not None else None
    if mp is not None:
        if mp >= 0.7:
            parts.append("Meta-learner confidence is high")
        elif mp >= 0.55:
            parts.append("Meta-learner leans bullish")
        elif mp <= 0.3:
            parts.append("Meta-learner confidence is low")
        else:
            parts.append("Meta-learner is neutral")

    maj = agreement.get("majority")
    ap = agreement.get("agreement_pct", 0)
    if maj and ap >= 60:
        parts.append(f"with {ap}% agreement among base models ({maj})")
    elif ap < 50:
        parts.append("but base models disagree — proceed with caution")

    if regime == "BULL":
        parts.append("in a bull market regime")
    elif regime == "BEAR":
        parts.append("during a defensive bear regime")
    elif regime:
        parts.append(f"under a {regime.lower()} regime")

    if vol_regime == "HIGH":
        parts.append("while volatility is elevated")
    elif vol_regime == "LOW":
        parts.append("in a calm volatility environment")

    if weight is not None and weight > 0:
        parts.append(f"at a {weight*100:.1f}% portfolio weight within risk limits")

    if not parts:
        return (
            f"The engine executed {action} based on the fused meta-learner output "
            "and current risk posture."
        )
    text = parts[0]
    if len(parts) > 1:
        text += " " + ", ".join(parts[1:-1])
        if len(parts) > 2:
            text += f", and {parts[-1]}"
        else:
            text += f" {parts[-1]}"
    else:
        text += "."
    if not text.endswith("."):
        text += "."
    return text[0].upper() + text[1:]


def build_decision_trace(row) -> Dict[str, Any]:
    """Build full decision explorer payload from a TradeLog ORM row."""
    votes = _model_votes(row.model_signals)
    agreement = _agreement_stats(votes)
    ind = row.indicators or {}
    price = float(row.price) if row.price else None

    technicals = []
    for key, label in INDICATOR_LABELS.items():
        if key not in ind:
            continue
        val = ind[key]
        if key == "macd":
            display = _macd_label(val)
        elif key == "atr":
            display = _atr_label(val, price)
        elif key == "rsi_14":
            display = f"{float(val):.1f}"
        elif key == "price_mom_20":
            display = f"{float(val)*100:+.2f}%"
        elif key == "vix_zscore":
            display = f"{float(val):+.2f}"
        else:
            display = str(round(float(val), 4))
        technicals.append({"key": key, "label": label, "value": display, "raw": val})

    stop_pct = None
    target_pct = None
    if price and row.stop_price:
        stop_pct = round(abs(price - float(row.stop_price)) / price * 100, 2)
    if price and row.take_profit:
        target_pct = round(abs(float(row.take_profit) - price) / price * 100, 2)

    fundamentals = _fetch_fundamentals(row.ticker)

    return {
        "id": row.id,
        "ticker": row.ticker,
        "action": row.action,
        "market": row.market,
        "venue": row.venue,
        "created_at": row.created_at.isoformat() if row.created_at else None,
        "execution": {
            "shares": row.shares,
            "price": row.price,
            "notional": round(row.shares * row.price, 2) if row.shares and row.price else None,
        },
        "meta_probability": row.meta_prob,
        "meta_probability_pct": round(row.meta_prob * 100, 1) if row.meta_prob is not None else None,
        "model_votes": votes,
        "model_agreement": agreement,
        "regime": {
            "market": row.regime,
            "volatility": row.vol_regime,
        },
        "technicals": technicals,
        "fundamentals": fundamentals,
        "risk": {
            "position_size_pct": round(row.weight * 100, 2) if row.weight is not None else None,
            "stop_price": row.stop_price,
            "stop_loss_pct": stop_pct,
            "take_profit": row.take_profit,
            "target_pct": target_pct,
            "risk_dollars": row.risk_dollars,
            "sizing_method": row.sizing_method,
        },
        "summary_reason": row.reason,
        "final_explanation": _build_explanation(
            row.action, row.meta_prob, agreement, row.regime, row.vol_regime, row.weight,
        ),
    }
