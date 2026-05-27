"""
Institutional-style execution: Almgren-Chriss impact, ADV caps, urgency coupling.

Participation rules (explicit)
------------------------------
• Scope: **per asset**, **per calendar day**, **per side** (buy/sell tracked separately).
• Each order: notional capped at ``participation_cap × ADV`` for that day.
• **Cumulative** daily participation: sum of filled notionals per (ticker, date, side)
  cannot exceed ``participation_cap × ADV``.
• **Portfolio-wide** daily cap is NOT applied (multi-asset strategies can use full
  per-name liquidity up to each name's ADV cap).

Execution horizon (T)
-------------------
Daily bars → ``EXECUTION_HORIZON_DAYS = 1``. Impact uses √(Q / (V·T)).
If you move to intraday or multi-day slices, set T to the execution window in days.
"""
from __future__ import annotations

from typing import Dict, List, Optional, Tuple

import numpy as np

# ── Explicit execution horizon (Almgren-Chriss time scaling) ─────────────────
EXECUTION_HORIZON_DAYS: float = 1.0

# Per-order max fraction of that day's ADV (single fill attempt)
PARTICIPATION_CAP: float = 0.10

# Rolling window for adaptive ADV (trading days)
ADV_ROLLING_WINDOW: int = 20

# Temporary impact coefficient (liquid US equities, Almgren et al. 2005)
ALMGREN_ETA: float = 0.14

PARTICIPATION_RULES: Dict[str, str] = {
    "scope": "per_asset_per_day_per_side",
    "single_order_cap": f"{PARTICIPATION_CAP * 100:.0f}% of rolling ADV",
    "cumulative_daily_cap": f"{PARTICIPATION_CAP * 100:.0f}% of rolling ADV per side",
    "portfolio_aggregate_cap": "none",
    "execution_horizon_days": str(EXECUTION_HORIZON_DAYS),
    "impact_formula": "spread + η·σ·√(Q/(V·T))",
}


def almgren_chriss_slippage(
    base_slippage: float,
    recent_returns: List[float],
    participation_rate: float,
    liquidity_factor: float = 1.0,
    execution_horizon_days: float = EXECUTION_HORIZON_DAYS,
    urgency_multiplier: float = 1.0,
) -> float:
    """
    Temporary impact with explicit horizon T (days).

    participation_rate = Q_notional / V_adv (order size vs daily ADV).
    Impact term: η · σ · √(Q / (V · T))  =  η · σ · √(participation_rate / T).

    When T=1 and one bar = one day, this matches the standard single-day formulation.
    """
    vol = (
        float(np.std(recent_returns[-20:]))
        if len(recent_returns) >= 5
        else base_slippage * 2.0
    )
    t_horizon = max(float(execution_horizon_days), 1e-6)
    rate_over_horizon = max(participation_rate, 1e-12) / t_horizon
    impact = ALMGREN_ETA * vol * float(np.sqrt(rate_over_horizon))
    raw = (base_slippage + impact / max(liquidity_factor, 0.1)) * max(urgency_multiplier, 1.0)
    return min(raw, base_slippage * 5.0)


def urgency_multiplier(intended_notional: float, filled_notional: float) -> float:
    """
    Couple partial fills to worse prices: unfilled fraction → urgency premium.
    Capped at +50% slippage multiplier when fill is heavily constrained.
    """
    if intended_notional <= 0:
        return 1.0
    fill_frac = min(1.0, filled_notional / intended_notional)
    if fill_frac >= 0.999:
        return 1.0
    return 1.0 + 0.5 * (1.0 - fill_frac)


def rolling_adv_notional(
    close_prices: List[float],
    static_adv: float,
    day_index: int,
    dollar_volumes: Optional[List[float]] = None,
) -> float:
    """
    Adaptive ADV: rolling mean of daily dollar volume when available,
    else static ADV scaled by recent vs long-run volatility (liquidity stress proxy).
    """
    if dollar_volumes and day_index < len(dollar_volumes):
        start = max(0, day_index - ADV_ROLLING_WINDOW + 1)
        window = [v for v in dollar_volumes[start : day_index + 1] if v and v > 0]
        if len(window) >= 5:
            return float(np.mean(window))

    if day_index < 5 or day_index >= len(close_prices):
        return static_adv

    rets = []
    for j in range(max(1, day_index - 60), day_index + 1):
        if close_prices[j - 1] > 0:
            rets.append((close_prices[j] - close_prices[j - 1]) / close_prices[j - 1])
    if len(rets) < 5:
        return static_adv

    vol_recent = float(np.std(rets[-20:]))
    vol_long = float(np.std(rets)) or vol_recent or 0.01
    stress = np.clip(vol_recent / vol_long, 0.5, 2.5)
    return static_adv / stress


def remaining_participation_capacity(
    adv: float,
    cumulative_filled_today: float,
) -> float:
    """Notional still available under per-day cumulative ADV cap."""
    cap = adv * PARTICIPATION_CAP
    return max(0.0, cap - cumulative_filled_today)


def cap_order_notional(
    intended_notional: float,
    adv: float,
    cumulative_filled_today: float,
) -> Tuple[float, bool]:
    """
    Apply single-order and cumulative daily caps.
    Returns (allowed_notional, was_partial).
    """
    remaining = remaining_participation_capacity(adv, cumulative_filled_today)
    single_cap = adv * PARTICIPATION_CAP
    allowed = min(intended_notional, single_cap, remaining)
    partial = allowed < intended_notional - 1e-6
    return max(0.0, allowed), partial


def model_documentation() -> Dict[str, object]:
    return {
        **PARTICIPATION_RULES,
        "almgren_eta": ALMGREN_ETA,
        "adv_rolling_window_days": ADV_ROLLING_WINDOW,
        "urgency_premium": "slippage × (1 + 0.5×(1−fill_fraction)) when partial",
        "slippage_cap_multiple": 5.0,
    }
