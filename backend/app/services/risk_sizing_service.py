"""
Volatility-based position sizing + portfolio risk limits.

The allocation layer answers "WHICH stocks to buy". This module answers the
second, equally important question a professional engine must answer:
"HOW MUCH of each?".

Instead of spreading capital proportional to model conviction (which ignores
risk), we size every position so that being stopped out loses a fixed, small
fraction of equity. A low-volatility name therefore gets a larger dollar
position than a jumpy one for the same dollar risk — classic ATR / volatility
targeting.

Hard caps then bound the portfolio:
  * risk_per_trade_pct   — $ risked per position if its stop is hit (e.g. 1%)
  * max_position_pct     — no single name exceeds this share of equity
  * max_sector_pct       — no single sector exceeds this share of equity (US)
  * max_gross_exposure   — total invested ≤ this × equity (leverage ceiling)

References:
  Van Tharp — position sizing / R-multiples
  Volatility targeting (risk parity-style per-name risk budgeting)
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, asdict
from typing import Dict, Iterable, Optional

logger = logging.getLogger(__name__)


# DOW-30 sector map (GICS-style, static — constituents change rarely). Used for
# the max-sector-exposure cap on US allocations. EGX has no bundled map yet, so
# sector caps are simply skipped when a ticker isn't found here.
DOW30_SECTORS: Dict[str, str] = {
    "AAPL": "Technology", "MSFT": "Technology", "IBM": "Technology",
    "CSCO": "Technology", "INTC": "Technology", "CRM": "Technology",
    "NVDA": "Technology",
    "AMZN": "Consumer Discretionary", "HD": "Consumer Discretionary",
    "MCD": "Consumer Discretionary", "NKE": "Consumer Discretionary",
    "SBUX": "Consumer Discretionary",
    "KO": "Consumer Staples", "PG": "Consumer Staples", "WMT": "Consumer Staples",
    "JPM": "Financials", "GS": "Financials", "AXP": "Financials",
    "TRV": "Financials", "V": "Financials",
    "JNJ": "Health Care", "UNH": "Health Care", "MRK": "Health Care",
    "AMGN": "Health Care",
    "CAT": "Industrials", "BA": "Industrials", "HON": "Industrials",
    "MMM": "Industrials",
    "CVX": "Energy",
    "DIS": "Communication Services", "VZ": "Communication Services",
    "DOW": "Materials",
}

# Fallback stop distance when ATR is missing/zero: a fixed % of price.
_DEFAULT_STOP_PCT = 0.08
# Conviction floor — a barely-above-0.5 signal still gets this fraction of full
# size (so size scales with edge but never collapses to ~0).
_CONVICTION_FLOOR = 0.5


def volatility_regime(
    turbulence: "list[float] | None" = None,
    vix_zscore: Optional[float] = None,
    high_pct: float = 0.85,
    low_pct: float = 0.40,
) -> Dict[str, object]:
    """
    Classify the current volatility regime and return a risk multiplier.

    Uses the percentile rank of the latest turbulence within its own recent
    history (works for both US and EGX), escalated by VIX z-score for US.

      HIGH   → turbulence in top 15% (or VIX z > 1.5)  → shrink risk  (×0.5)
      LOW    → turbulence in bottom 40%                → expand risk  (×1.25)
      NORMAL → otherwise                               → unchanged    (×1.0)

    Returns {"vol_regime", "risk_scale", "turbulence_pct"}.
    Based on Kritzman et al. (2010) financial turbulence.
    """
    scale_map = {"HIGH": 0.5, "NORMAL": 1.0, "LOW": 1.25}
    pct = None
    if turbulence:
        arr = [float(x) for x in turbulence if x is not None]
        if len(arr) >= 20:
            latest = arr[-1]
            pct = sum(1 for x in arr if x <= latest) / len(arr)
    if (pct is not None and pct >= high_pct) or (vix_zscore is not None and vix_zscore > 1.5):
        regime = "HIGH"
    elif pct is not None and pct <= low_pct:
        regime = "LOW"
    else:
        regime = "NORMAL"
    return {"vol_regime": regime, "risk_scale": scale_map[regime],
            "turbulence_pct": round(pct, 3) if pct is not None else None}


@dataclass
class RiskConfig:
    risk_per_trade_pct: float = 0.01     # risk 1% of equity per position
    atr_stop_mult: float = 2.0           # stop = entry − 2·ATR
    max_position_pct: float = 0.20       # ≤ 20% equity in one name
    max_sector_pct: float = 0.40         # ≤ 40% equity in one sector (US)
    max_gross_exposure: float = 1.0      # ≤ 100% equity invested (1.0 = no leverage)
    take_profit_mult: float = 3.0        # target = entry + 3·ATR (1.5 R:R vs 2·ATR stop)
    min_position_pct: float = 0.005      # drop dust positions below 0.5% equity

    @classmethod
    def from_dict(cls, d: Optional[dict]) -> "RiskConfig":
        if not d:
            return cls()
        valid = {k: d[k] for k in cls().__dict__ if k in d and d[k] is not None}
        return cls(**valid)


def size_positions(
    candidates: Iterable[str],
    prices: Dict[str, float],
    atr: Dict[str, float],
    equity: float,
    conviction: Optional[Dict[str, float]] = None,
    sectors: Optional[Dict[str, str]] = None,
    config: Optional[RiskConfig] = None,
    target_weights: Optional[Dict[str, float]] = None,
) -> Dict[str, object]:
    """
    Size a set of long candidates by volatility and risk limits.

    Two base-sizing modes:
      * ATR risk-based (default) — each position sized so a 2·ATR stop-out loses
        risk_per_trade_pct of equity, scaled by conviction edge.
      * Portfolio-weight (when `target_weights` given, e.g. from
        portfolio_service) — base dollars = weight × equity × max_gross_exposure.
    Either way the SAME caps (per-name, per-sector, gross) and ATR stops/targets
    are applied afterward.

    Parameters
    ----------
    candidates : tickers to buy (already filtered / top-K by the allocator)
    prices     : {ticker: entry price}
    atr        : {ticker: ATR(14)}; missing/0 → fixed-% stop fallback
    equity     : account equity to deploy
    conviction : {ticker: prob 0..1}; scales size by edge above 0.5 (ATR mode)
    sectors    : {ticker: sector}; enables the sector cap (optional)
    config     : RiskConfig (defaults: 1% risk, 2·ATR stop, 20%/40%/100% caps)
    target_weights : {ticker: weight} from portfolio optimization; switches to
                     portfolio-weight base sizing when provided

    Returns
    -------
    {
      "positions": {ticker: {weight, dollars, shares, entry, stop_price,
                             take_profit, risk_dollars, atr, sector}},
      "gross_exposure": float,        # invested / equity after caps
      "n_positions": int,
      "cash_weight": float,
      "config": {...},
      "notes": [str, ...],
    }
    """
    cfg = config or RiskConfig()
    conviction = conviction or {}
    sectors = sectors or {}
    notes: list[str] = []
    cands = [t for t in candidates if prices.get(t, 0) > 0 and equity > 0]

    risk_dollars = equity * cfg.risk_per_trade_pct
    raw: Dict[str, dict] = {}

    # Portfolio-weight mode: normalize provided weights over the usable candidates.
    wsum = 0.0
    if target_weights is not None:
        wsum = sum(max(0.0, target_weights.get(t, 0.0)) for t in cands)

    for t in cands:
        px = float(prices[t])
        a = float(atr.get(t, 0.0) or 0.0)
        stop_dist = cfg.atr_stop_mult * a if a > 0 else _DEFAULT_STOP_PCT * px
        if stop_dist <= 0:
            continue
        if target_weights is not None:
            # Base dollars from portfolio weights, scaled to the gross budget.
            if wsum <= 0:
                continue
            w = max(0.0, target_weights.get(t, 0.0)) / wsum
            dollars = w * equity * cfg.max_gross_exposure
        else:
            # ATR risk-based: position whose stop-out loss == risk_dollars.
            dollars = risk_dollars * (px / stop_dist)
            # Scale by conviction edge: prob 0.5→floor, 1.0→full
            if t in conviction:
                edge = max(0.0, min(1.0, (conviction[t] - 0.5) / 0.5))
                dollars *= _CONVICTION_FLOOR + (1.0 - _CONVICTION_FLOOR) * edge
        raw[t] = {
            "dollars": dollars, "entry": px, "atr": a,
            "stop_price": round(px - stop_dist, 4),
            "take_profit": round(px + cfg.take_profit_mult * a, 4) if a > 0
                           else round(px * (1 + cfg.take_profit_mult * _DEFAULT_STOP_PCT), 4),
            "risk_dollars": round(risk_dollars, 2),
            "sector": sectors.get(t, ""),
        }

    # ── Cap 1: per-position ≤ max_position_pct ──────────────────────────────────
    pos_cap = cfg.max_position_pct * equity
    for t, p in raw.items():
        if p["dollars"] > pos_cap:
            p["dollars"] = pos_cap

    # ── Cap 2: per-sector ≤ max_sector_pct (only when sectors known) ────────────
    if sectors:
        sec_cap = cfg.max_sector_pct * equity
        by_sec: Dict[str, float] = {}
        for t, p in raw.items():
            if p["sector"]:
                by_sec[p["sector"]] = by_sec.get(p["sector"], 0.0) + p["dollars"]
        for sec, total in by_sec.items():
            if total > sec_cap and total > 0:
                scale = sec_cap / total
                for t, p in raw.items():
                    if p["sector"] == sec:
                        p["dollars"] *= scale
                notes.append(f"sector '{sec}' scaled to {cfg.max_sector_pct:.0%} cap")

    # ── Cap 3: gross exposure ≤ max_gross_exposure × equity (leverage ceiling) ──
    gross = sum(p["dollars"] for p in raw.values())
    max_gross = cfg.max_gross_exposure * equity
    if gross > max_gross and gross > 0:
        scale = max_gross / gross
        for p in raw.values():
            p["dollars"] *= scale
        notes.append(f"gross exposure scaled to {cfg.max_gross_exposure:.0%} cap")
        gross = max_gross

    # ── Finalize: drop dust, compute shares/weights ─────────────────────────────
    min_dollars = cfg.min_position_pct * equity
    positions: Dict[str, dict] = {}
    invested = 0.0
    for t, p in raw.items():
        if p["dollars"] < min_dollars:
            continue
        shares = p["dollars"] / p["entry"]
        positions[t] = {
            "weight": round(p["dollars"] / equity, 6),
            "dollars": round(p["dollars"], 2),
            "shares": round(shares, 4),
            "entry": round(p["entry"], 4),
            "stop_price": p["stop_price"],
            "take_profit": p["take_profit"],
            "risk_dollars": p["risk_dollars"],
            "atr": round(p["atr"], 4),
            "sector": p["sector"],
        }
        invested += p["dollars"]

    return {
        "positions": positions,
        "gross_exposure": round(invested / equity, 6) if equity > 0 else 0.0,
        "n_positions": len(positions),
        "cash_weight": round(max(0.0, 1.0 - invested / equity), 6) if equity > 0 else 1.0,
        "config": asdict(cfg),
        "notes": notes,
    }
