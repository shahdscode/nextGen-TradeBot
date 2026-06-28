"""
Portfolio intelligence metrics for paper-trading dashboards.

Sector/symbol allocation, diversification, cash weight, largest position,
average holding period (from trade log), and optional beta vs SPY.
"""
from __future__ import annotations

import logging
from datetime import datetime
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)


def _position_weights(positions: List[Dict], portfolio_value: float, cash: float) -> List[Dict]:
    pv = float(portfolio_value or 0)
    if pv <= 0:
        return []
    out = []
    for p in positions or []:
        sym = p.get("symbol") or p.get("tic")
        mv = float(p.get("market_value") or 0)
        if not sym or mv <= 0:
            continue
        out.append({
            "symbol": sym.upper(),
            "market_value": mv,
            "weight": mv / pv,
        })
    cash_w = float(cash or 0) / pv if pv > 0 else 0
    if cash_w > 0.001:
        out.append({"symbol": "CASH", "market_value": float(cash or 0), "weight": cash_w})
    return out


def _sector_allocation(weights: List[Dict], sector_map: Dict[str, str]) -> List[Dict]:
    buckets: Dict[str, float] = {}
    for w in weights:
        if w["symbol"] == "CASH":
            buckets["Cash"] = buckets.get("Cash", 0) + w["weight"]
            continue
        sec = sector_map.get(w["symbol"], "Other")
        buckets[sec] = buckets.get(sec, 0) + w["weight"]
    return [{"name": k, "value": round(v * 100, 2)} for k, v in sorted(buckets.items(), key=lambda x: -x[1])]


def _symbol_allocation(weights: List[Dict], top_n: int = 8) -> List[Dict]:
    invested = [w for w in weights if w["symbol"] != "CASH"]
    invested.sort(key=lambda x: -x["weight"])
    rows = [{"name": w["symbol"], "value": round(w["weight"] * 100, 2)} for w in invested[:top_n]]
    other = sum(w["weight"] for w in invested[top_n:])
    if other > 0.001:
        rows.append({"name": "Other", "value": round(other * 100, 2)})
    cash = next((w for w in weights if w["symbol"] == "CASH"), None)
    if cash and cash["weight"] > 0.001:
        rows.append({"name": "Cash", "value": round(cash["weight"] * 100, 2)})
    return rows


def _diversification_score(weights: List[Dict]) -> float:
    invested = [w["weight"] for w in weights if w["symbol"] != "CASH"]
    if not invested:
        return 0.0
    hhi = sum(w * w for w in invested)
    if hhi <= 0:
        return 0.0
    return round(1.0 / hhi, 2)


def _avg_holding_days(trade_rows: List[Dict], held_symbols: List[str]) -> Optional[float]:
    if not trade_rows or not held_symbols:
        return None
    held = {s.upper() for s in held_symbols}
    now = datetime.utcnow()
    days_list = []
    for sym in held:
        buys = [
            r for r in trade_rows
            if (r.get("ticker") or "").upper() == sym and (r.get("action") or "").upper() == "BUY"
        ]
        if not buys:
            continue
        buys.sort(key=lambda r: r.get("created_at") or "", reverse=True)
        ts = buys[0].get("created_at")
        if not ts:
            continue
        try:
            dt = datetime.fromisoformat(ts.replace("Z", "+00:00")).replace(tzinfo=None)
            days_list.append(max(0, (now - dt).days))
        except Exception:
            pass
    return round(sum(days_list) / len(days_list), 1) if days_list else None


def _portfolio_beta(tickers: List[str], weights: List[float]) -> Optional[float]:
    """Weighted beta vs SPY over ~60 trading days (best-effort)."""
    if not tickers or not weights or len(tickers) != len(weights):
        return None
    try:
        import pandas as pd
        import yfinance as yf

        syms = ["SPY"] + list(dict.fromkeys(tickers))
        hist = yf.download(syms, period="3mo", progress=False, auto_adjust=True)
        if hist is None or hist.empty:
            return None
        close = hist["Close"] if "Close" in hist.columns else hist
        rets = close.pct_change().dropna()
        if "SPY" not in rets.columns or len(rets) < 20:
            return None
        spy_r = rets["SPY"]
        betas: List[float] = []
        wts: List[float] = []
        for t, w in zip(tickers, weights):
            if t not in rets.columns:
                continue
            merged = pd.concat([rets[t], spy_r], axis=1).dropna()
            if len(merged) < 15:
                continue
            var = merged.iloc[:, 1].var()
            if var <= 0:
                continue
            betas.append(merged.cov().iloc[0, 1] / var)
            wts.append(w)
        if not betas:
            return None
        total = sum(wts)
        return round(sum(b * wt for b, wt in zip(betas, wts)) / total, 2) if total > 0 else None
    except Exception as exc:
        logger.debug("portfolio beta skipped: %s", exc)
        return None


def compute_portfolio_analytics(
    portfolio: Dict[str, Any],
    trade_rows: Optional[List[Dict]] = None,
    sector_map: Optional[Dict[str, str]] = None,
    include_beta: bool = True,
) -> Dict[str, Any]:
    """
    Build allocation + risk summary from a portfolio snapshot dict.
    Expects keys: portfolio_value, cash, positions[{symbol, market_value}].
    """
    from app.services.risk_sizing_service import DOW30_SECTORS

    sector_map = sector_map or DOW30_SECTORS
    pv = float(portfolio.get("portfolio_value") or 0)
    cash = float(portfolio.get("cash") or 0)
    positions = portfolio.get("positions") or []
    weights = _position_weights(positions, pv, cash)

    invested = [w for w in weights if w["symbol"] != "CASH"]
    largest = max(invested, key=lambda w: w["weight"]) if invested else None
    top_sector = _sector_allocation(weights, sector_map)
    held_syms = [w["symbol"] for w in invested]

    tickers = [w["symbol"] for w in invested]
    wvals = [w["weight"] for w in invested]
    total_inv = sum(wvals)
    pairs = sorted(zip(tickers, wvals), key=lambda x: -x[1])[:8]
    if pairs and total_inv > 0 and include_beta:
        t8, w8 = zip(*pairs)
        wsum = sum(w8)
        beta = _portfolio_beta(list(t8), [w / wsum for w in w8])
    else:
        beta = None

    return {
        "portfolio_value": round(pv, 2),
        "cash_pct": round(cash / pv * 100, 1) if pv > 0 else 0,
        "holdings_count": len(invested),
        "largest_position": {
            "symbol": largest["symbol"],
            "pct": round(largest["weight"] * 100, 2),
        } if largest else None,
        "largest_sector": top_sector[0] if top_sector else None,
        "diversification_score": _diversification_score(weights),
        "sector_allocation": top_sector,
        "symbol_allocation": _symbol_allocation(weights),
        "avg_holding_days": _avg_holding_days(trade_rows or [], held_syms),
        "portfolio_beta": beta,
        "has_positions": len(invested) > 0,
    }
