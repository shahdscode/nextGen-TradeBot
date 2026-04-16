import hashlib
from datetime import datetime
from typing import Any

import requests
from fastapi import APIRouter, HTTPException

from app.config import settings

router = APIRouter(prefix="/paper-trading", tags=["paper-trading"])

MT5_CONFIGURED = bool(settings.mt5_gateway_url)

# In-memory paper session for demo/local usage.
PAPER_SESSION: dict[str, Any] = {
    "running": False,
    "run_id": None,
    "timeframe": "M15",
    "symbols": ["BTCUSDm", "ETHUSDm", "EURUSD"],
    "started_at": None,
    "cash": 100000.0,
    "initial_cash": 100000.0,
    "positions": {},
}


def _check_mt5():
    if not MT5_CONFIGURED:
        raise HTTPException(
            status_code=501,
            detail="MT5 gateway not configured. Set MT5_GATEWAY_URL in .env"
        )


def _mt5_headers() -> dict[str, str]:
    headers = {"accept": "application/json"}
    if settings.mt5_api_key:
        headers["x-api-key"] = settings.mt5_api_key
    return headers


def _latest_price(symbol: str, timeframe: str) -> float | None:
    try:
        base_url = settings.mt5_gateway_url.rstrip("/")
        resp = requests.get(
            f"{base_url}/candles",
            params={"symbol": symbol, "timeframe": timeframe, "bars": 2},
            headers=_mt5_headers(),
            timeout=8,
        )
        resp.raise_for_status()
        payload = resp.json()
        if not isinstance(payload, list) or not payload:
            return None
        close_val = payload[-1].get("close")
        return float(close_val) if close_val is not None else None
    except Exception:
        return None


def _fallback_price(symbol: str) -> float:
    # Stable pseudo-price for offline gateway scenarios.
    base = int(hashlib.sha256(symbol.encode("utf-8")).hexdigest()[:8], 16)
    return round(50 + (base % 50000) / 100.0, 2)


@router.get("/status")
def get_status():
    return {
        "configured": MT5_CONFIGURED,
        "message": "MT5 gateway connected" if MT5_CONFIGURED else "Set MT5_GATEWAY_URL to enable paper trading",
        "gateway_url": settings.mt5_gateway_url if MT5_CONFIGURED else None,
        "running": PAPER_SESSION["running"],
        "run_id": PAPER_SESSION["run_id"],
        "symbols": PAPER_SESSION["symbols"],
        "timeframe": PAPER_SESSION["timeframe"],
    }


@router.post("/start")
def start_trading(run_id: str, symbols: str = "BTCUSDm,ETHUSDm,EURUSD", timeframe: str = "M15"):
    _check_mt5()

    symbol_list = [s.strip() for s in symbols.split(",") if s.strip()]
    if not symbol_list:
        raise HTTPException(status_code=400, detail="At least one symbol is required")

    PAPER_SESSION["running"] = True
    PAPER_SESSION["run_id"] = run_id
    PAPER_SESSION["symbols"] = symbol_list
    PAPER_SESSION["timeframe"] = timeframe.upper().strip() or "M15"
    PAPER_SESSION["started_at"] = datetime.utcnow().isoformat()
    PAPER_SESSION["cash"] = PAPER_SESSION["initial_cash"]
    PAPER_SESSION["positions"] = {}

    return {
        "message": "MT5 paper trading started",
        "run_id": run_id,
        "symbols": PAPER_SESSION["symbols"],
        "timeframe": PAPER_SESSION["timeframe"],
    }


@router.post("/stop")
def stop_trading():
    _check_mt5()
    PAPER_SESSION["running"] = False
    PAPER_SESSION["run_id"] = None
    PAPER_SESSION["positions"] = {}
    PAPER_SESSION["cash"] = PAPER_SESSION["initial_cash"]
    return {"message": "MT5 paper trading stopped"}


@router.get("/portfolio")
def get_portfolio():
    if not MT5_CONFIGURED:
        return {
            "configured": False,
            "portfolio_value": PAPER_SESSION["initial_cash"],
            "cash": PAPER_SESSION["initial_cash"],
            "positions": [],
            "daily_return": 0.0,
            "message": "Mock data — configure MT5 gateway for paper trading",
        }

    if not PAPER_SESSION["running"]:
        return {
            "configured": True,
            "running": False,
            "portfolio_value": PAPER_SESSION["initial_cash"],
            "cash": PAPER_SESSION["initial_cash"],
            "positions": [],
            "daily_return": 0.0,
            "message": "Paper trading is stopped. Use /start to begin MT5 paper trading.",
        }

    try:
        # Bootstrap positions at first portfolio call using current quotes.
        if not PAPER_SESSION["positions"]:
            budget_per_symbol = PAPER_SESSION["cash"] / max(1, len(PAPER_SESSION["symbols"]))
            for symbol in PAPER_SESSION["symbols"]:
                px = _latest_price(symbol, PAPER_SESSION["timeframe"])
                if not px or px <= 0:
                    px = _fallback_price(symbol)
                qty = round(budget_per_symbol / px, 6)
                if qty <= 0:
                    continue
                PAPER_SESSION["positions"][symbol] = {"qty": qty, "entry_price": px}

            invested = sum(pos["qty"] * pos["entry_price"] for pos in PAPER_SESSION["positions"].values())
            PAPER_SESSION["cash"] = round(max(0.0, PAPER_SESSION["initial_cash"] - invested), 2)

        positions_out = []
        total_market_value = 0.0
        total_cost = 0.0

        for symbol, pos in PAPER_SESSION["positions"].items():
            qty = float(pos["qty"])
            entry = float(pos["entry_price"])
            current = _latest_price(symbol, PAPER_SESSION["timeframe"]) or _fallback_price(symbol)
            market_value = qty * current
            cost = qty * entry
            unrealized = market_value - cost
            unrealized_plpc = (unrealized / cost) if cost > 0 else 0.0

            total_market_value += market_value
            total_cost += cost

            positions_out.append(
                {
                    "symbol": symbol,
                    "qty": round(qty, 6),
                    "market_value": round(market_value, 2),
                    "unrealized_pl": round(unrealized, 2),
                    "unrealized_plpc": round(unrealized_plpc, 6),
                }
            )

        portfolio_value = round(PAPER_SESSION["cash"] + total_market_value, 2)
        daily_return = (portfolio_value / PAPER_SESSION["initial_cash"] - 1.0) if PAPER_SESSION["initial_cash"] > 0 else 0.0

        return {
            "configured": True,
            "running": True,
            "run_id": PAPER_SESSION["run_id"],
            "timeframe": PAPER_SESSION["timeframe"],
            "portfolio_value": portfolio_value,
            "cash": PAPER_SESSION["cash"],
            "daily_return": round(daily_return, 6),
            "positions": positions_out,
            "message": "MT5 paper portfolio (live gateway when reachable, offline fallback otherwise)",
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
