"""
Paper trading router.
Session state is persisted to the `paper_sessions` DB table so it survives server
restarts.  In-memory dict is used as a fast cache; DB is the source of truth.
"""
import hashlib
import uuid
from datetime import datetime
from typing import Any, List

import requests
from fastapi import APIRouter, HTTPException, Depends

from app.config import settings
from app.database import SessionLocal, PaperSession
from app.services.auth_service import require_auth


def _apply_user_alpaca(user):
    """Point the Alpaca client at the logged-in user's own keys for this request."""
    from app.services import alpaca_service
    alpaca_service.use_credentials(
        getattr(user, "alpaca_api_key", None),
        getattr(user, "alpaca_api_secret", None),
    )

router = APIRouter(prefix="/paper-trading", tags=["paper-trading"])

MT5_CONFIGURED = bool(settings.mt5_gateway_url)

# In-memory cache — populated from DB on first use.
_SESSION_CACHE: dict[str, Any] = {}


# ── DB helpers ────────────────────────────────────────────────────────────────

def _load_active_session() -> dict[str, Any] | None:
    """Return the most recent running session from DB, or None."""
    db = SessionLocal()
    try:
        row = (
            db.query(PaperSession)
            .filter(PaperSession.running.is_(True))
            .order_by(PaperSession.started_at.desc())
            .first()
        )
        if row:
            return _row_to_dict(row)
        # Fall back to most recent stopped session so the UI can still see history
        row = (
            db.query(PaperSession)
            .order_by(PaperSession.created_at.desc())
            .first()
        )
        return _row_to_dict(row) if row else None
    finally:
        db.close()


def _row_to_dict(row: PaperSession) -> dict[str, Any]:
    return {
        "session_id":   row.id,
        "running":      row.running,
        "run_id":       row.run_id,
        "symbols":      row.symbols or [],
        "timeframe":    row.timeframe or "M15",
        "initial_cash": row.initial_cash,
        "cash":         row.cash,
        "positions":    row.positions or {},
        "started_at":   row.started_at.isoformat() if row.started_at else None,
        "stopped_at":   row.stopped_at.isoformat() if row.stopped_at else None,
    }


def _save_session(s: dict[str, Any]) -> PaperSession:
    """Upsert session dict to DB and return the ORM row."""
    db = SessionLocal()
    try:
        row = db.query(PaperSession).filter(PaperSession.id == s.get("session_id")).first()
        if row is None:
            row = PaperSession(id=s["session_id"])
            db.add(row)
        row.run_id       = s.get("run_id")
        row.symbols      = s.get("symbols", [])
        row.timeframe    = s.get("timeframe", "M15")
        row.initial_cash = s.get("initial_cash", 100_000.0)
        row.cash         = s.get("cash", 100_000.0)
        row.positions    = s.get("positions", {})
        row.running      = s.get("running", False)
        row.started_at   = (
            datetime.fromisoformat(s["started_at"])
            if isinstance(s.get("started_at"), str)
            else s.get("started_at")
        )
        row.stopped_at   = (
            datetime.fromisoformat(s["stopped_at"])
            if isinstance(s.get("stopped_at"), str)
            else s.get("stopped_at")
        )
        db.commit()
        db.refresh(row)
        return row
    finally:
        db.close()


def _get_session() -> dict[str, Any]:
    """Return the active in-memory session, loading from DB if needed."""
    global _SESSION_CACHE
    if not _SESSION_CACHE:
        loaded = _load_active_session()
        if loaded:
            _SESSION_CACHE = loaded
        else:
            # Bootstrap a blank session
            _SESSION_CACHE = {
                "session_id":   str(uuid.uuid4()),
                "running":      False,
                "run_id":       None,
                "symbols":      ["BTCUSDm", "ETHUSDm", "EURUSD"],
                "timeframe":    "M15",
                "initial_cash": 100_000.0,
                "cash":         100_000.0,
                "positions":    {},
                "started_at":   None,
                "stopped_at":   None,
            }
    return _SESSION_CACHE


# ── MT5 helpers ───────────────────────────────────────────────────────────────

def _check_mt5():
    if not MT5_CONFIGURED:
        raise HTTPException(
            status_code=501,
            detail="MT5 gateway not configured. Set MT5_GATEWAY_URL in .env",
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
    """Stable pseudo-price for offline gateway scenarios."""
    base = int(hashlib.sha256(symbol.encode("utf-8")).hexdigest()[:8], 16)
    return round(50 + (base % 50000) / 100.0, 2)


_EQUITY_PX_CACHE: dict[str, tuple[float, float]] = {}   # symbol -> (price, ts)

def _equity_price(symbol: str) -> float | None:
    """Latest daily close for a US equity via Yahoo (30s cache). None on failure."""
    import time
    now = time.time()
    hit = _EQUITY_PX_CACHE.get(symbol)
    if hit and now - hit[1] < 30:
        return hit[0]
    try:
        import yfinance as yf
        h = yf.Ticker(symbol).history(period="5d", auto_adjust=True)
        if h.empty:
            return None
        px = float(h["Close"].iloc[-1])
        _EQUITY_PX_CACHE[symbol] = (px, now)
        return px
    except Exception:
        return None


# ── Endpoints ─────────────────────────────────────────────────────────────────

@router.get("/status")
def get_status():
    s = _get_session()
    return {
        "configured": MT5_CONFIGURED,
        "message":    "MT5 gateway connected" if MT5_CONFIGURED else "Set MT5_GATEWAY_URL to enable paper trading",
        "gateway_url": settings.mt5_gateway_url if MT5_CONFIGURED else None,
        "running":     s["running"],
        "run_id":      s["run_id"],
        "symbols":     s["symbols"],
        "timeframe":   s["timeframe"],
        "session_id":  s["session_id"],
    }


@router.post("/start")
def start_trading(run_id: str, symbols: str = "BTCUSDm,ETHUSDm,EURUSD", timeframe: str = "M15",
                  initial_cash: float = 100_000.0):
    _check_mt5()

    symbol_list = [s.strip() for s in symbols.split(",") if s.strip()]
    if not symbol_list:
        raise HTTPException(status_code=400, detail="At least one symbol is required")

    global _SESSION_CACHE
    _SESSION_CACHE = {
        "session_id":   str(uuid.uuid4()),
        "running":      True,
        "run_id":       run_id,
        "symbols":      symbol_list,
        "timeframe":    timeframe.upper().strip() or "M15",
        "initial_cash": initial_cash,
        "cash":         initial_cash,
        "positions":    {},
        "started_at":   datetime.utcnow().isoformat(),
        "stopped_at":   None,
    }
    _save_session(_SESSION_CACHE)

    return {
        "message":    "MT5 paper trading started",
        "run_id":     run_id,
        "session_id": _SESSION_CACHE["session_id"],
        "symbols":    symbol_list,
        "timeframe":  _SESSION_CACHE["timeframe"],
    }


@router.post("/stop")
def stop_trading():
    _check_mt5()
    global _SESSION_CACHE
    s = _get_session()
    s["running"]    = False
    s["stopped_at"] = datetime.utcnow().isoformat()
    s["positions"]  = {}
    _SESSION_CACHE  = s
    _save_session(s)
    return {"message": "MT5 paper trading stopped", "session_id": s["session_id"]}


@router.get("/portfolio")
def get_portfolio():
    s = _get_session()

    if not MT5_CONFIGURED:
        return {
            "configured":      False,
            "portfolio_value": s["initial_cash"],
            "cash":            s["initial_cash"],
            "positions":       [],
            "daily_return":    0.0,
            "message":         "Configure MT5_GATEWAY_URL in .env for live paper trading",
        }

    if not s["running"]:
        return {
            "configured":      True,
            "running":         False,
            "portfolio_value": s["initial_cash"],
            "cash":            s["initial_cash"],
            "positions":       [],
            "daily_return":    0.0,
            "session_id":      s.get("session_id"),
            "message":         "Paper trading stopped. Use /start to begin.",
        }

    try:
        # Bootstrap positions on first portfolio call
        if not s["positions"]:
            budget_per_symbol = s["cash"] / max(1, len(s["symbols"]))
            for symbol in s["symbols"]:
                px = _latest_price(symbol, s["timeframe"])
                if not px or px <= 0:
                    px = _fallback_price(symbol)
                qty = round(budget_per_symbol / px, 6)
                if qty <= 0:
                    continue
                s["positions"][symbol] = {"qty": qty, "entry_price": px}

            invested = sum(
                pos["qty"] * pos["entry_price"] for pos in s["positions"].values()
            )
            s["cash"] = round(max(0.0, s["initial_cash"] - invested), 2)
            _SESSION_CACHE.update(s)
            _save_session(s)

        positions_out    = []
        total_market_val = 0.0

        for symbol, pos in s["positions"].items():
            qty     = float(pos["qty"])
            entry   = float(pos["entry_price"])
            # Price priority: MT5 gateway → Yahoo equity → deterministic fallback
            current = (_latest_price(symbol, s["timeframe"])
                       or _equity_price(symbol)
                       or _fallback_price(symbol))
            mktval  = qty * current
            cost    = qty * entry
            unreal  = mktval - cost

            total_market_val += mktval
            positions_out.append({
                "symbol":          symbol,
                "qty":             round(qty, 6),
                "entry_price":     round(entry, 4),
                "current_price":   round(current, 4),
                "market_value":    round(mktval, 2),
                "unrealized_pl":   round(unreal, 2),
                "unrealized_plpc": round(unreal / cost, 6) if cost > 0 else 0.0,
            })

        portfolio_value = round(s["cash"] + total_market_val, 2)
        daily_return    = (portfolio_value / s["initial_cash"] - 1.0) if s["initial_cash"] > 0 else 0.0

        return {
            "configured":      True,
            "running":         True,
            "run_id":          s["run_id"],
            "session_id":      s["session_id"],
            "timeframe":       s["timeframe"],
            "portfolio_value": portfolio_value,
            "cash":            s["cash"],
            "daily_return":    round(daily_return, 6),
            "positions":       positions_out,
            "message":         "Live gateway when reachable, deterministic fallback otherwise",
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/rebalance")
def rebalance(run_id: str | None = None, initial_cash: float = 100_000.0,
              mode: str = "rl"):
    """
    Model-driven trade decision on LIVE DOW30 data.

    mode="rl"   : run one trained RL model (pass run_id), use its live holdings.
    mode="meta" : full 7-model meta-learner ensemble (run_id ignored) — assembles
                  xgb + lstm + 5 RL signals + regime + VIX per stock, runs the
                  meta-learner, allocates ∝ meta probability among BUY stocks.

    Rebalances the paper account to the model's target. No MT5 required
    (US equities use the Yahoo feed).
    """
    from app.services.live_trading_service import generate_live_allocation, generate_meta_allocation

    global _SESSION_CACHE
    s = _get_session()
    cash = float(s.get("initial_cash") or initial_cash)

    if mode == "meta":
        rid = "meta_learner"
        alloc = generate_meta_allocation(cash)
    else:
        rid = run_id or s.get("run_id")
        if not rid:
            raise HTTPException(status_code=400,
                                detail="run_id required (pass run_id or start a session first)")
        alloc = generate_live_allocation(rid, cash)

    if not alloc.get("ok"):
        raise HTTPException(status_code=400, detail=alloc.get("message", "allocation failed"))

    # Rebalance paper positions to the model's target holdings
    positions, invested = {}, 0.0
    for tic, qty in alloc["target"].items():
        if qty and qty > 0:
            px = float(alloc["prices"].get(tic, 0.0))
            if px <= 0:
                continue
            positions[tic] = {"qty": round(qty, 6), "entry_price": round(px, 4)}
            invested += qty * px

    s.update({
        "run_id":       rid,
        "symbols":      alloc["tickers"],
        "timeframe":    "1d",
        "positions":    positions,
        "cash":         round(max(0.0, cash - invested), 2),
        "running":      True,
        "initial_cash": cash,
    })
    s.setdefault("session_id", str(uuid.uuid4()))
    s.setdefault("started_at", datetime.utcnow().isoformat())
    _SESSION_CACHE = s
    _save_session(s)

    return {
        "ok":             True,
        "as_of":          alloc["as_of"],
        "algorithm":      alloc["algorithm"],
        "message":        alloc["message"],
        "run_id":         rid,
        "session_id":     s["session_id"],
        "positions_held": len(positions),
        "invested":       round(invested, 2),
        "cash":           s["cash"],
        "signals":        alloc["signals"],
    }


@router.get("/alpaca/status")
def alpaca_status(user=Depends(require_auth)):
    """Alpaca paper account status + market clock (uses the user's own keys)."""
    from app.services import alpaca_service
    _apply_user_alpaca(user)
    if not alpaca_service.configured():
        return {"configured": False,
                "message": "Add your Alpaca API keys in Profile to enable paper trading"}
    try:
        acct = alpaca_service.get_account()
        return {"configured": True, "broker": "alpaca_paper",
                "market_open": alpaca_service.market_is_open(), **acct}
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"Alpaca error: {e}")


@router.get("/alpaca/portfolio")
def alpaca_portfolio(user=Depends(require_auth)):
    """Live positions + P&L from the user's Alpaca paper account."""
    from app.services import alpaca_service
    _apply_user_alpaca(user)
    if not alpaca_service.configured():
        return {"configured": False, "positions": [],
                "message": "Add your Alpaca API keys in Profile to enable paper trading"}
    try:
        return alpaca_service.portfolio_snapshot()
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"Alpaca error: {e}")


@router.post("/alpaca/risk-check")
def alpaca_risk_check(max_drawdown_pct: float = 0.15, user=Depends(require_auth)):
    """Run the drawdown kill-switch on the user's account."""
    from app.services import alpaca_service
    _apply_user_alpaca(user)
    if not alpaca_service.configured():
        raise HTTPException(status_code=400, detail="Alpaca not configured for this user")
    try:
        return alpaca_service.enforce_risk(max_drawdown_pct)
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"Alpaca error: {e}")


@router.post("/alpaca/rebalance")
def alpaca_rebalance(run_id: str | None = None, mode: str = "rl", user=Depends(require_auth)):
    """
    Run the model on live DOW30 data and rebalance the ALPACA paper account to
    the model's target weights (real broker orders). mode='rl' (single model,
    pass run_id) or mode='meta' (full 7-model ensemble).
    """
    from app.services import alpaca_service
    from app.services.live_trading_service import (
        generate_live_allocation, generate_meta_allocation)

    _apply_user_alpaca(user)
    if not alpaca_service.configured():
        raise HTTPException(status_code=400,
                            detail="Alpaca not configured — set keys in .env")

    s = _get_session()
    equity = None
    try:
        equity = alpaca_service.get_account()["equity"]
    except Exception:
        pass
    budget = equity or float(s.get("initial_cash") or 100_000.0)

    if mode == "meta":
        alloc = generate_meta_allocation(budget)
        rid = "meta_learner"
    else:
        rid = run_id or s.get("run_id")
        if not rid:
            raise HTTPException(status_code=400, detail="run_id required for mode=rl")
        alloc = generate_live_allocation(rid, budget)
    if not alloc.get("ok"):
        raise HTTPException(status_code=400, detail=alloc.get("message", "allocation failed"))

    # Convert model target (shares × price) → portfolio weights
    target_val = {t: alloc["target"].get(t, 0.0) * alloc["prices"].get(t, 0.0)
                  for t in alloc["tickers"]}
    total = sum(v for v in target_val.values() if v > 0)
    weights = {t: (v / total) for t, v in target_val.items() if v > 0} if total > 0 else {}

    result = alpaca_service.rebalance_to_weights(weights)

    # Persist session intent
    global _SESSION_CACHE
    s.update({"run_id": rid, "symbols": alloc["tickers"], "timeframe": "1d",
              "running": True, "initial_cash": float(s.get("initial_cash") or 100_000.0)})
    s.setdefault("session_id", str(uuid.uuid4()))
    _SESSION_CACHE = s
    _save_session(s)

    return {
        "ok": True, "broker": "alpaca_paper", "mode": mode, "run_id": rid,
        "as_of": alloc.get("as_of"), "model_message": alloc.get("message"),
        "weights": {t: round(w, 4) for t, w in weights.items()},
        **result,
    }


@router.get("/history")
def get_session_history(limit: int = 20):
    """Return past paper trading sessions (most recent first)."""
    db = SessionLocal()
    try:
        rows = (
            db.query(PaperSession)
            .order_by(PaperSession.created_at.desc())
            .limit(limit)
            .all()
        )
        return [
            {
                "session_id":   r.id,
                "run_id":       r.run_id,
                "symbols":      r.symbols,
                "timeframe":    r.timeframe,
                "initial_cash": r.initial_cash,
                "cash":         r.cash,
                "running":      r.running,
                "started_at":   r.started_at.isoformat() if r.started_at else None,
                "stopped_at":   r.stopped_at.isoformat() if r.stopped_at else None,
                "created_at":   r.created_at.isoformat() if r.created_at else None,
            }
            for r in rows
        ]
    finally:
        db.close()
