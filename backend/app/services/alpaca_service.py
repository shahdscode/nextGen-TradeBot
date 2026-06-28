"""
Alpaca paper-trading broker integration.

Unlike the Yahoo-simulated rebalance (which tracks a portfolio internally),
this submits REAL orders to an Alpaca paper account and reads back actual
positions + P&L. Alpaca trades US equities (DOW30) — the exact assets the
models were trained on — so it's a true broker-grade paper-trading venue.

Free: Alpaca paper accounts cost nothing. Keys live in .env
(ALPACA_API_KEY / ALPACA_API_SECRET / ALPACA_BASE_URL).
"""
from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional

import requests

from app.config import settings

logger = logging.getLogger(__name__)

import contextvars

_BASE = (settings.alpaca_base_url or "https://paper-api.alpaca.markets").rstrip("/")

# Per-request credentials override. The router sets this from the logged-in
# user's saved keys so each user trades their OWN Alpaca paper account. When
# unset (scheduler / web-admin), it falls back to the global .env keys.
_creds_var: "contextvars.ContextVar" = contextvars.ContextVar("alpaca_creds", default=None)


def use_credentials(api_key: str | None, api_secret: str | None) -> None:
    """Set the Alpaca creds for the current request context (per-user)."""
    _creds_var.set((api_key, api_secret) if (api_key and api_secret) else None)


def _active_creds():
    c = _creds_var.get()
    if c and c[0] and c[1]:
        return c
    return (settings.alpaca_api_key, settings.alpaca_api_secret)


def configured() -> bool:
    k, s = _active_creds()
    return bool(k and s)


def _headers() -> Dict[str, str]:
    k, s = _active_creds()
    return {"APCA-API-KEY-ID": k, "APCA-API-SECRET-KEY": s}


import time as _time

_TIMEOUT = (8, 20)   # (connect, read) seconds
_RETRIES = 3         # retry transient network blips before failing


def _request(method: str, path: str, **kwargs):
    """HTTP with retries on transient connection/read timeouts (not on 4xx)."""
    url = f"{_BASE}/v2{path}"
    last_exc = None
    for attempt in range(_RETRIES):
        try:
            return requests.request(method, url, headers=_headers(), timeout=_TIMEOUT, **kwargs)
        except (requests.exceptions.ConnectTimeout,
                requests.exceptions.ReadTimeout,
                requests.exceptions.ConnectionError) as exc:
            last_exc = exc
            if attempt < _RETRIES - 1:
                _time.sleep(0.8 * (attempt + 1))   # brief backoff, then retry
            continue
    raise RuntimeError(
        "Alpaca is unreachable right now (network timeout after retries). "
        "Check your connection and try again."
    ) from last_exc


def _get(path: str, **params):
    r = _request("GET", path, params=params or None)
    r.raise_for_status()
    return r.json()


def _post(path: str, payload: dict):
    r = _request("POST", path, json=payload)
    if r.status_code >= 400:
        raise RuntimeError(f"Alpaca {path} → {r.status_code}: {r.text[:200]}")
    return r.json()


# ── Account / market state ─────────────────────────────────────────────────────

def get_account() -> Dict[str, Any]:
    a = _get("/account")
    return {
        "status":          a.get("status"),
        "equity":          float(a.get("equity", 0)),
        "cash":            float(a.get("cash", 0)),
        "buying_power":    float(a.get("buying_power", 0)),
        "portfolio_value": float(a.get("portfolio_value", 0)),
        "last_equity":     float(a.get("last_equity", 0)),
    }


def market_is_open() -> bool:
    try:
        return bool(_get("/clock").get("is_open", False))
    except Exception:
        return False


def get_positions() -> List[Dict[str, Any]]:
    out = []
    for p in _get("/positions"):
        out.append({
            "symbol":          p["symbol"],
            "qty":             float(p["qty"]),
            "entry_price":     float(p["avg_entry_price"]),
            "current_price":   float(p["current_price"]),
            "market_value":    float(p["market_value"]),
            "unrealized_pl":   float(p["unrealized_pl"]),
            "unrealized_plpc": float(p["unrealized_plpc"]),
        })
    return out


def get_portfolio_history(period: str = "all", timeframe: str = "1D") -> Dict[str, Any]:
    """
    Account equity curve since inception (Alpaca tracks it natively).
    Returns {timestamps[], equity[], base_value, total_return, total_pl}.
    """
    try:
        h = _get("/account/portfolio/history", period=period, timeframe=timeframe)
        eq = [float(x) for x in (h.get("equity") or []) if x is not None]
        base = float(h.get("base_value") or (eq[0] if eq else 0.0))
        last = eq[-1] if eq else base
        total_ret = (last / base - 1.0) if base > 0 else 0.0
        return {
            "timestamps":   h.get("timestamp", []),
            "equity":       eq,
            "base_value":   round(base, 2),
            "total_return": round(total_ret, 6),
            "total_pl":     round(last - base, 2),
        }
    except Exception as exc:
        logger.warning("portfolio history failed: %s", exc)
        return {"timestamps": [], "equity": [], "base_value": 0.0,
                "total_return": 0.0, "total_pl": 0.0}


# ── Risk overlay ───────────────────────────────────────────────────────────────

DEFAULT_MAX_DRAWDOWN = 0.15   # 15% peak-to-current → kill switch


def drawdown_status(max_drawdown_pct: float = DEFAULT_MAX_DRAWDOWN) -> Dict[str, Any]:
    """
    Compute peak-to-current drawdown from the account equity curve.
    Returns {peak, current, drawdown, breached, threshold}.
    """
    hist = get_portfolio_history()
    eq = hist["equity"] or [get_account()["equity"]]
    peak = max(eq) if eq else 0.0
    cur  = eq[-1] if eq else 0.0
    dd = (peak - cur) / peak if peak > 0 else 0.0
    return {"peak": round(peak, 2), "current": round(cur, 2),
            "drawdown": round(dd, 4), "threshold": max_drawdown_pct,
            "breached": dd >= max_drawdown_pct}


def liquidate_all() -> Dict[str, Any]:
    """Close every open position (go to cash). Used by the kill-switch."""
    try:
        r = _request("DELETE", "/positions", params={"cancel_orders": "true"})
        closed = r.json() if r.status_code < 400 else []
        return {"ok": r.status_code < 400, "closed": len(closed) if isinstance(closed, list) else 0}
    except Exception as exc:
        logger.warning("liquidate_all failed: %s", exc)
        return {"ok": False, "closed": 0, "error": str(exc)}


def enforce_risk(max_drawdown_pct: float = DEFAULT_MAX_DRAWDOWN) -> Dict[str, Any]:
    """
    Kill switch: if drawdown ≥ threshold, liquidate all positions and report.
    Returns the drawdown status plus any action taken.
    """
    st = drawdown_status(max_drawdown_pct)
    if st["breached"]:
        action = liquidate_all()
        st["action"] = f"LIQUIDATED — drawdown {st['drawdown']*100:.1f}% ≥ {max_drawdown_pct*100:.0f}%"
        st["liquidated"] = action
        logger.warning("RISK KILL-SWITCH: %s", st["action"])
    else:
        st["action"] = "ok — within drawdown limit"
        st["liquidated"] = None
    return st


def portfolio_snapshot() -> Dict[str, Any]:
    acct = get_account()
    pos  = get_positions()
    daily = ((acct["equity"] / acct["last_equity"] - 1.0)
             if acct["last_equity"] > 0 else 0.0)
    hist = get_portfolio_history()
    dd   = drawdown_status()
    return {
        "configured":      True,
        "broker":          "alpaca_paper",
        "portfolio_value": round(acct["equity"], 2),
        "cash":            round(acct["cash"], 2),
        "buying_power":    round(acct["buying_power"], 2),
        "daily_return":    round(daily, 6),
        "total_return":    hist["total_return"],          # since inception
        "total_pl":        hist["total_pl"],
        "starting_value":  hist["base_value"],
        "equity_curve":    hist["equity"][-90:],          # last 90 points for a sparkline
        "drawdown":        dd["drawdown"],
        "drawdown_breached": dd["breached"],
        "market_open":     market_is_open(),
        "positions":       pos,
        "message":         "Live Alpaca paper account (real fills, US equities).",
    }


# ── Order submission ───────────────────────────────────────────────────────────

def _submit_notional(symbol: str, notional: float, side: str) -> Optional[dict]:
    """Submit a market order for a dollar amount (fractional shares)."""
    try:
        return _post("/orders", {
            "symbol":        symbol,
            "notional":      round(abs(notional), 2),
            "side":          side,
            "type":          "market",
            "time_in_force": "day",
        })
    except Exception as exc:
        logger.warning("Alpaca order %s %s $%.2f failed: %s", side, symbol, notional, exc)
        return None


def submit_bracket(symbol: str, qty: float, stop_loss: float,
                   take_profit: float, side: str = "buy") -> Optional[dict]:
    """
    Submit a bracket order: a market entry with attached protective stop-loss
    and take-profit legs. When either is hit, the other is cancelled (OCO).
    Alpaca brackets require whole-share qty and GTC time-in-force.

    Returns the parent order dict, or None on failure.
    """
    q = int(qty)
    if q <= 0 or not stop_loss or not take_profit or stop_loss <= 0 or take_profit <= 0:
        return None
    try:
        return _post("/orders", {
            "symbol":        symbol,
            "qty":           q,
            "side":          side,
            "type":          "market",
            "time_in_force": "gtc",
            "order_class":   "bracket",
            "take_profit":   {"limit_price": round(take_profit, 2)},
            "stop_loss":     {"stop_price":  round(stop_loss, 2)},
        })
    except Exception as exc:
        logger.warning("Alpaca bracket %s %s x%d failed: %s", side, symbol, q, exc)
        return None


def rebalance_with_brackets(targets: Dict[str, dict],
                            cash_buffer_pct: float = 0.02) -> Dict[str, Any]:
    """
    Open bracketed positions toward `targets` and flatten everything else.

    targets: {symbol: {"dollars", "price", "stop_price", "take_profit"}}

    For each target NOT already held, submits a bracket buy sized to
    qty = floor((1-buffer)·dollars / price) with the model's stop+target
    attached. Symbols held but not targeted are closed. Already-held targets
    are left alone so their existing protective legs stand.
    """
    acct = get_account()
    equity = acct["equity"] * (1.0 - max(0.0, min(cash_buffer_pct, 0.5)))
    held = {p["symbol"]: p for p in get_positions()}
    is_open = market_is_open()
    orders, closed, skipped = [], [], []

    for sym in list(held):                       # close unwanted positions first
        if sym not in targets:
            try:
                _request("DELETE", f"/positions/{sym}")
                closed.append(sym)
            except Exception:
                skipped.append(sym)

    for sym, t in targets.items():               # open new bracketed entries
        if sym in held:
            continue
        price = float(t.get("price") or 0.0)
        dollars = min(float(t.get("dollars") or 0.0), equity)
        if price <= 0 or dollars <= 0:
            continue
        qty = int(dollars / price)
        if qty < 1:
            skipped.append(sym)
            continue
        o = submit_bracket(sym, qty, t.get("stop_price"), t.get("take_profit"), side="buy")
        if o:
            orders.append({"symbol": sym, "side": "buy", "qty": qty,
                           "stop_loss": t.get("stop_price"),
                           "take_profit": t.get("take_profit"),
                           "order_id": o.get("id"), "status": o.get("status")})
        else:
            skipped.append(sym)

    return {
        "ok": True, "market_open": is_open, "order_class": "bracket",
        "orders": orders, "closed": closed, "skipped": skipped, "n_orders": len(orders),
        "note": ("Bracket orders submitted; entries fill at next open with stop+target."
                 if not is_open else "Bracket orders submitted to live paper market."),
        "account": get_account(),
    }


def rebalance_to_weights(target_weights: Dict[str, float],
                         min_trade_dollars: float = 50.0,
                         cash_buffer_pct: float = 0.02,
                         rebalance_band: float = 0.03) -> Dict[str, Any]:
    """
    Rebalance the Alpaca paper account toward target weights (sum ≤ 1 of equity).

    A cash_buffer_pct (default 2%) is held back so notional orders + price drift
    between calculation and fill can't push the account into negative cash /
    margin. Targets are scaled to (1 - buffer) of equity.

    No-trade band: a symbol is only traded if its weight drifts from target by
    more than `rebalance_band` (default 3%) of equity — this adds portfolio
    inertia and cuts churn/transaction drag from small signal noise.

    Computes per-symbol dollar deltas vs current positions and submits market
    orders (notional). Symbols not in target_weights are flattened (sold).
    Returns the submitted orders + resulting account snapshot.
    """
    acct       = get_account()
    full_equity = acct["equity"]
    # Deploy only (1 - buffer) of equity so we never overdraw cash on fills.
    equity = full_equity * (1.0 - max(0.0, min(cash_buffer_pct, 0.5)))
    positions = {p["symbol"]: p for p in get_positions()}

    # Current $ per symbol
    cur_val = {s: p["market_value"] for s, p in positions.items()}
    symbols = set(target_weights) | set(cur_val)

    orders, skipped, held = [], [], []
    is_open = market_is_open()
    band_dollars = rebalance_band * full_equity   # weight-drift no-trade zone

    # Sells first (free up buying power), then buys
    deltas = {}
    for s in symbols:
        tgt = equity * float(target_weights.get(s, 0.0))
        cur = cur_val.get(s, 0.0)
        deltas[s] = tgt - cur

    for s in sorted(symbols, key=lambda x: deltas[x]):   # sells (neg) first
        d = deltas[s]
        # No-trade band: skip small drifts unless we're fully exiting the name.
        fully_exiting = target_weights.get(s, 0.0) == 0.0 and s in positions
        if abs(d) < max(min_trade_dollars, band_dollars) and not fully_exiting:
            held.append(s)
            continue
        side = "buy" if d > 0 else "sell"
        # When fully exiting, close the position to avoid leftover fractional dust
        if side == "sell" and target_weights.get(s, 0.0) == 0.0 and s in positions:
            try:
                _request("DELETE", f"/positions/{s}")
                orders.append({"symbol": s, "side": "sell", "action": "close_position"})
                continue
            except Exception:
                pass
        o = _submit_notional(s, d, side)
        if o:
            orders.append({"symbol": s, "side": side, "notional": round(abs(d), 2),
                           "order_id": o.get("id"), "status": o.get("status")})
        else:
            skipped.append(s)

    return {
        "ok":            True,
        "market_open":   is_open,
        "orders":        orders,
        "skipped":       skipped,
        "n_orders":      len(orders),
        "held_in_band":  len(held),   # within no-trade band — left untouched
        "note": ("Orders submitted; they fill at the next market open."
                 if not is_open else "Orders submitted to live paper market."),
        "account":       get_account(),
    }
