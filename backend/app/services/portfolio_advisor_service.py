"""
Rule-based AI Portfolio Advisor — interprets analytics for the command center.

No LLM required: synthesizes regime, confidence, allocation, beta, drawdown,
and recent trades into plain-language guidance.
"""
from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional


def ai_confidence_from_signals(signals: List[Dict]) -> Dict[str, Any]:
    if not signals:
        return {"pct": None, "label": "UNKNOWN", "detail": "No recent signals available."}
    avg = sum(float(s.get("confidence") or 0) for s in signals) / len(signals)
    spreads = []
    for s in signals:
        mb = s.get("model_breakdown") or {}
        vals = [
            (mb.get("xgboost") or {}).get("probability"),
            (mb.get("lstm") or {}).get("probability"),
            (mb.get("ppo") or {}).get("signal"),
        ]
        vals = [v for v in vals if v is not None]
        if len(vals) >= 2:
            spreads.append(max(vals) - min(vals))
    disagreement = sum(spreads) / len(spreads) if spreads else 0.0
    pct = round(avg * 100)
    if disagreement > 0.22:
        label = "LOW"
    elif pct >= 68:
        label = "HIGH"
    elif pct >= 52:
        label = "MEDIUM"
    else:
        label = "LOW"
    detail = (
        "High disagreement between base models"
        if disagreement > 0.22
        else f"Based on {len(signals)} evaluated stocks"
    )
    return {"pct": pct, "label": label, "detail": detail, "disagreement": round(disagreement, 3)}


def portfolio_health_score(
    analytics: Dict[str, Any],
    confidence: Dict[str, Any],
    regime: str,
    drawdown_breached: bool = False,
    meta_loaded: bool = False,
) -> int:
    score = 72
    div = float(analytics.get("diversification_score") or 0)
    cash = float(analytics.get("cash_pct") or 100)
    holdings = int(analytics.get("holdings_count") or 0)
    beta = analytics.get("portfolio_beta")

    if holdings == 0:
        score = 55
    else:
        if div >= 10:
            score += 12
        elif div >= 5:
            score += 8
        elif div >= 3:
            score += 4
        if 5 <= cash <= 25:
            score += 5
        elif cash > 50:
            score -= 5

    if confidence.get("label") == "HIGH":
        score += 10
    elif confidence.get("label") == "LOW":
        score -= 8

    if meta_loaded:
        score += 5

    if regime == "BEAR" and cash < 30 and holdings > 0:
        score -= 12
    elif regime == "BULL" and holdings > 0:
        score += 3

    if beta is not None:
        if beta < 0.9:
            score += 4
        elif beta > 1.3:
            score -= 6

    if drawdown_breached:
        score -= 20

    return int(max(0, min(100, round(score))))


def build_alerts(
    trades: List[Dict],
    analytics: Dict[str, Any],
    drawdown: Optional[float] = None,
    drawdown_breached: bool = False,
) -> List[Dict[str, str]]:
    alerts: List[Dict[str, str]] = []
    cutoff = datetime.utcnow() - timedelta(hours=48)

    if drawdown_breached:
        alerts.append({
            "level": "critical",
            "message": f"Drawdown kill-switch active — portfolio drawdown exceeded limit ({(drawdown or 0)*100:.1f}%).",
        })
    elif drawdown is not None and drawdown > 0.10:
        alerts.append({
            "level": "warning",
            "message": f"Drawdown has increased to {drawdown*100:.1f}% — monitor risk closely.",
        })

    top_sector = (analytics.get("largest_sector") or {})
    if top_sector.get("value", 0) > 35:
        alerts.append({
            "level": "info",
            "message": f"Concentrated sector exposure: {top_sector.get('name')} at {top_sector.get('value')}%.",
        })

    for t in trades[:15]:
        ts = t.get("created_at")
        if not ts:
            continue
        try:
            dt = datetime.fromisoformat(ts.replace("Z", "+00:00")).replace(tzinfo=None)
        except Exception:
            continue
        if dt < cutoff:
            continue
        action = (t.get("action") or "").upper()
        ticker = t.get("ticker") or "?"
        if action == "BUY":
            alerts.append({"level": "info", "message": f"New BUY on {ticker}"})
        elif action == "SELL":
            alerts.append({"level": "warning", "message": f"SELL executed on {ticker}"})

    if not alerts and int(analytics.get("holdings_count") or 0) == 0:
        alerts.append({
            "level": "info",
            "message": "No open positions — run a meta rebalance on Paper Trading to deploy capital.",
        })

    return alerts[:8]


def generate_advisor_insight(
    analytics: Dict[str, Any],
    confidence: Dict[str, Any],
    regime: str,
    drawdown: Optional[float] = None,
    drawdown_breached: bool = False,
    performance_source: str = "sim",
) -> Dict[str, Any]:
    """Return structured portfolio insight paragraphs + recommendation."""
    paragraphs: List[str] = []
    holdings = int(analytics.get("holdings_count") or 0)
    top_sector = analytics.get("largest_sector") or {}
    beta = analytics.get("portfolio_beta")
    div = analytics.get("diversification_score")
    cash = analytics.get("cash_pct")
    conf_label = confidence.get("label", "UNKNOWN")

    if holdings == 0:
        paragraphs.append(
            "Your portfolio is currently in cash with no active positions. "
            "The AI signal feed is running, but capital has not been deployed yet."
        )
        return {
            "title": "Portfolio Insight",
            "paragraphs": paragraphs,
            "recommendation": "Consider a meta-learner rebalance on Paper Trading when you are ready to allocate.",
            "tone": "neutral",
        }

    if top_sector.get("name") and top_sector.get("value", 0) > 30:
        paragraphs.append(
            f"Your portfolio is overweight {top_sector['name']} ({top_sector['value']:.1f}% of invested capital) "
            f"relative to a balanced multi-sector posture."
        )
    elif top_sector.get("name"):
        paragraphs.append(
            f"Largest sector exposure is {top_sector['name']} at {top_sector.get('value', 0):.1f}% — "
            "within a reasonable range for a concentrated AI-selected portfolio."
        )

    if beta is not None:
        if beta < 0.85:
            paragraphs.append(
                f"Portfolio beta is {beta:.2f}, indicating lower sensitivity to broad market moves than the S&P 500."
            )
        elif beta > 1.15:
            paragraphs.append(
                f"Portfolio beta is {beta:.2f}, so returns may amplify market swings more than a typical index fund."
            )
        else:
            paragraphs.append(f"Portfolio beta is {beta:.2f}, roughly in line with the market.")

    if div is not None and holdings > 0:
        paragraphs.append(
            f"Diversification remains {'strong' if div >= 8 else 'moderate'} "
            f"(effective holdings ≈ {div:.1f} across {holdings} positions)."
        )

    paragraphs.append(
        f"Current market regime is {regime or 'UNKNOWN'}, and meta-learner confidence is {conf_label}."
    )

    if cash is not None:
        paragraphs.append(f"Cash allocation is {cash:.1f}% of total portfolio value.")

    recommendation = "No immediate action is recommended."
    tone = "positive"

    if drawdown_breached:
        recommendation = "Risk limits breached — review positions and consider reducing exposure until drawdown recovers."
        tone = "critical"
    elif drawdown is not None and drawdown > 0.12:
        recommendation = (
            "Drawdown is elevated. Consider trimming the weakest positions or raising cash if bearish conditions persist."
        )
        tone = "warning"
    elif regime == "BEAR" and (cash or 0) < 25:
        recommendation = "Bear regime detected with high invested exposure — defensive posture or higher cash may be prudent."
        tone = "warning"
    elif conf_label == "LOW":
        recommendation = "Model disagreement is elevated — wait for clearer consensus before adding risk."
        tone = "caution"
    elif conf_label == "HIGH" and regime == "BULL":
        recommendation = "Conditions favor the current AI posture — monitor stops and rebalance on schedule."
        tone = "positive"

    return {
        "title": "Portfolio Insight",
        "paragraphs": paragraphs,
        "recommendation": recommendation,
        "tone": tone,
        "source": performance_source,
    }
