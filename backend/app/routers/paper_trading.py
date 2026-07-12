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
from app.database import SessionLocal, PaperSession, User
from app.services.auth_service import require_auth, get_user_id


def _apply_user_alpaca(user):
    """Point the Alpaca client at the logged-in user's own keys for this request."""
    from app.services import alpaca_service
    from app.utils.crypto import decrypt_secret
    alpaca_service.use_credentials(
        decrypt_secret(getattr(user, "alpaca_api_key", None)),
        decrypt_secret(getattr(user, "alpaca_api_secret", None)),
    )

router = APIRouter(prefix="/paper-trading", tags=["paper-trading"])

MT5_CONFIGURED = bool(settings.mt5_gateway_url)

# ── Risk controls (applied on every rebalance) ───────────────────────────────
STOP_LOSS_PCT    = 0.08   # per-position: sell & skip a name down more than this
MAX_DRAWDOWN_PCT = 0.15   # portfolio kill-switch: liquidate above this drawdown

MAX_DRAWDOWN_PCT = 0.15   # portfolio kill-switch: liquidate above this drawdown


# ── DB helpers ────────────────────────────────────────────────────────────────

def _load_user_session(user_id: str) -> dict[str, Any] | None:
    """Return this user's active or most recent session."""
    db = SessionLocal()
    try:
        row = (
            db.query(PaperSession)
            .filter(PaperSession.user_id == user_id, PaperSession.running.is_(True))
            .order_by(PaperSession.started_at.desc())
            .first()
        )
        if row:
            return _row_to_dict(row)
        row = (
            db.query(PaperSession)
            .filter(PaperSession.user_id == user_id)
            .order_by(PaperSession.created_at.desc())
            .first()
        )
        return _row_to_dict(row) if row else None
    finally:
        db.close()


def _blank_session(user_id: str) -> dict[str, Any]:
    return {
        "session_id":   str(uuid.uuid4()),
        "user_id":      user_id,
        "running":      False,
        "run_id":       None,
        "symbols":      ["AAPL", "MSFT", "JPM"],
        "timeframe":    "1d",
        "initial_cash": 100_000.0,
        "cash":         100_000.0,
        "positions":    {},
        "auto_enabled": False,
        "started_at":   None,
        "stopped_at":   None,
    }


def _row_to_dict(row: PaperSession) -> dict[str, Any]:
    return {
        "session_id":   row.id,
        "user_id":      row.user_id,
        "running":      row.running,
        "run_id":       row.run_id,
        "symbols":      row.symbols or [],
        "timeframe":    row.timeframe or "M15",
        "initial_cash": row.initial_cash,
        "cash":         row.cash,
        "positions":    row.positions or {},
        "auto_enabled": bool(getattr(row, "auto_enabled", False)),
        "started_at":   row.started_at.isoformat() if row.started_at else None,
        "stopped_at":   row.stopped_at.isoformat() if row.stopped_at else None,
    }


def _save_session(s: dict[str, Any], user_id: str | None = None) -> PaperSession:
    """Upsert session dict to DB and return the ORM row."""
    db = SessionLocal()
    try:
        row = db.query(PaperSession).filter(PaperSession.id == s.get("session_id")).first()
        if row is None:
            row = PaperSession(id=s["session_id"])
            db.add(row)
        uid = user_id or s.get("user_id")
        if uid:
            row.user_id = uid
        row.run_id       = s.get("run_id")
        row.symbols      = s.get("symbols", [])
        row.timeframe    = s.get("timeframe", "M15")
        row.initial_cash = s.get("initial_cash", 100_000.0)
        row.cash         = s.get("cash", 100_000.0)
        row.positions    = s.get("positions", {})
        row.running      = s.get("running", False)
        row.auto_enabled = s.get("auto_enabled", False)
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


def _get_session(user: User) -> dict[str, Any]:
    """Return the user's session, bootstrapping a blank one if needed."""
    uid = get_user_id(user)
    loaded = _load_user_session(uid)
    if loaded:
        return loaded
    return _blank_session(uid)


def _user_session_ids(user: User) -> List[str]:
    db = SessionLocal()
    try:
        rows = db.query(PaperSession.id).filter(PaperSession.user_id == get_user_id(user)).all()
        return [r[0] for r in rows]
    finally:
        db.close()


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


import math

def _finite(x, default: float = 0.0) -> float:
    """Coerce to a JSON-safe float. NaN/Inf/None → default.

    MT5/Yahoo can return NaN prices, and `NaN or fallback` keeps the NaN
    (NaN is truthy), which then poisons the JSON response with non-compliant
    floats. Use this on every price/number that reaches the API."""
    try:
        v = float(x)
    except (TypeError, ValueError):
        return default
    return v if math.isfinite(v) else default


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


def _current_price(symbol: str, timeframe: str = "1d") -> float:
    """JSON-safe current price: MT5 gateway → Yahoo (incl. .CA EGX) → fallback."""
    return (_finite(_latest_price(symbol, timeframe), 0.0)
            or _finite(_equity_price(symbol), 0.0)
            or _fallback_price(symbol))


def _portfolio_value(s: dict[str, Any]) -> float:
    """Current cash + market value of held positions."""
    val = _finite(s.get("cash"), 0.0)
    for sym, pos in (s.get("positions") or {}).items():
        val += _finite(pos.get("qty")) * _current_price(sym, s.get("timeframe", "1d"))
    return round(val, 2)


def _stopped_out_positions(s: dict[str, Any]) -> dict[str, float]:
    """Held names whose unrealized loss breaches STOP_LOSS_PCT → {sym: plpc}."""
    out: dict[str, float] = {}
    for sym, pos in (s.get("positions") or {}).items():
        entry = _finite(pos.get("entry_price"))
        if entry <= 0:
            continue
        plpc = _current_price(sym, s.get("timeframe", "1d")) / entry - 1.0
        if plpc <= -STOP_LOSS_PCT:
            out[sym] = round(plpc, 4)
    return out


# ── Endpoints ─────────────────────────────────────────────────────────────────

@router.get("/status")
def get_status(user=Depends(require_auth)):
    s = _get_session(user)
    return {
        "configured": MT5_CONFIGURED,
        "message":    "MT5 gateway connected" if MT5_CONFIGURED else "Set MT5_GATEWAY_URL to enable paper trading",
        "gateway_url": settings.mt5_gateway_url if MT5_CONFIGURED else None,
        "running":     s["running"],
        "run_id":      s["run_id"],
        "symbols":     s["symbols"],
        "timeframe":   s["timeframe"],
        "session_id":  s["session_id"],
        "auto_enabled": s.get("auto_enabled", False),
    }


@router.post("/start")
def start_trading(run_id: str, symbols: str = "AAPL,MSFT,JPM", timeframe: str = "1d",
                  initial_cash: float = 100_000.0, user=Depends(require_auth)):
    symbol_list = [s.strip() for s in symbols.split(",") if s.strip()]
    if not symbol_list:
        raise HTTPException(status_code=400, detail="At least one symbol is required")

    uid = get_user_id(user)
    existing = _load_user_session(uid)
    if existing and existing.get("running"):
        raise HTTPException(status_code=400, detail="Session already running — stop it first")

    s = {
        "session_id":   str(uuid.uuid4()),
        "user_id":      uid,
        "running":      True,
        "run_id":       run_id,
        "symbols":      symbol_list,
        "timeframe":    timeframe.upper().strip() or "1d",
        "initial_cash": initial_cash,
        "cash":         initial_cash,
        "positions":    {},
        "auto_enabled": False,
        "started_at":   datetime.utcnow().isoformat(),
        "stopped_at":   None,
    }
    _save_session(s, user_id=uid)

    return {
        "message":    "Paper trading session started",
        "run_id":     run_id,
        "session_id": s["session_id"],
        "symbols":    symbol_list,
        "timeframe":  s["timeframe"],
    }


@router.post("/stop")
def stop_trading(user=Depends(require_auth)):
    s = _get_session(user)
    s["running"]    = False
    s["stopped_at"] = datetime.utcnow().isoformat()
    s["positions"]  = {}
    _save_session(s, user_id=get_user_id(user))
    return {"message": "Paper trading stopped", "session_id": s["session_id"]}


@router.get("/portfolio")
def get_portfolio(user=Depends(require_auth)):
    s = _get_session(user)

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
                px = _finite(_latest_price(symbol, s["timeframe"]), 0.0) or _finite(_equity_price(symbol), 0.0)
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
            _save_session(s, user_id=get_user_id(user))

        positions_out    = []
        total_market_val = 0.0

        for symbol, pos in s["positions"].items():
            qty     = _finite(pos.get("qty"))
            entry   = _finite(pos.get("entry_price"))
            # Price priority: MT5 gateway → Yahoo equity → deterministic fallback.
            # _finite() guards against NaN (which is truthy and would short-circuit
            # the `or` chain) before falling through to the next source.
            current = (_finite(_latest_price(symbol, s["timeframe"]), 0.0)
                       or _finite(_equity_price(symbol), 0.0)
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


@router.get("/analytics")
def portfolio_analytics(user=Depends(require_auth)):
    """
    Portfolio intelligence: sector/symbol allocation, diversification,
    largest holding, cash %, avg holding period, beta vs SPY (best-effort).
    """
    from app.services.portfolio_analytics_service import compute_portfolio_analytics
    from app.services.trade_log_service import get_trade_log as _get_trades
    from app.services import alpaca_service

    trades = _get_trades(limit=200, session_ids=_user_session_ids(user))

    sim_snap = get_portfolio(user)
    sim = compute_portfolio_analytics(sim_snap, trades)

    alpaca = None
    _apply_user_alpaca(user)
    if alpaca_service.configured():
        try:
            alpaca_snap = alpaca_service.portfolio_snapshot()
            alpaca = compute_portfolio_analytics(alpaca_snap, trades)
        except Exception:
            alpaca = {"has_positions": False, "error": "Could not load Alpaca portfolio"}

    return {"sim": sim, "alpaca": alpaca}


@router.get("/command-center")
def command_center(market: str = "us", user=Depends(require_auth)):
    """
    Daily command center — one payload for portfolio health, AI context,
    performance, opportunities, allocation, trades, alerts, and advisor insight.
    """
    from app.routers.signals import get_top_signals
    from app.services.regime_service import get_regime_info
    from app.services.fusion_service import meta_learner_status
    from app.services.portfolio_analytics_service import compute_portfolio_analytics
    from app.services.portfolio_advisor_service import (
        ai_confidence_from_signals,
        build_alerts,
        generate_advisor_insight,
        portfolio_health_score,
    )
    from app.services.trade_log_service import get_trade_log as _get_trades
    from app.services import alpaca_service

    db = SessionLocal()
    try:
        meta = meta_learner_status(db)
    finally:
        db.close()

    regime_info = get_regime_info(market=market)
    regime = regime_info.get("current_regime", "SIDEWAYS")
    signals = get_top_signals(market=market, limit=20, action=None, min_confidence=0.0, hours=48)
    confidence = ai_confidence_from_signals(signals)
    trades = _get_trades(limit=25, session_ids=_user_session_ids(user))

    sim_snap = get_portfolio(user)
    sim_an = compute_portfolio_analytics(sim_snap, trades, include_beta=False)

    alpaca_snap = None
    alpaca_an = None
    _apply_user_alpaca(user)
    if alpaca_service.configured():
        try:
            alpaca_snap = alpaca_service.portfolio_snapshot()
            alpaca_an = compute_portfolio_analytics(alpaca_snap, trades, include_beta=False)
        except Exception:
            pass

    # Prefer Alpaca when it has real positions; otherwise simulator
    use_alpaca = bool(alpaca_an and alpaca_an.get("has_positions"))
    analytics = alpaca_an if use_alpaca else sim_an
    perf_source = "alpaca" if use_alpaca else "sim"

    if use_alpaca and alpaca_snap:
        pv = float(alpaca_snap.get("portfolio_value") or 0)
        dr = float(alpaca_snap.get("daily_return") or 0)
        performance = {
            "source": "alpaca",
            "portfolio_value": pv,
            "daily_return_pct": round(dr * 100, 2),
            "daily_pl": round(pv * dr, 2) if pv else 0,
            "total_return_pct": round((alpaca_snap.get("total_return") or 0) * 100, 2),
            "drawdown": alpaca_snap.get("drawdown"),
            "drawdown_breached": bool(alpaca_snap.get("drawdown_breached")),
        }
    else:
        pv = float(sim_snap.get("portfolio_value") or sim_snap.get("initial_cash") or 0)
        dr = float(sim_snap.get("daily_return") or 0)
        performance = {
            "source": "sim",
            "portfolio_value": pv,
            "daily_return_pct": round(dr * 100, 2),
            "daily_pl": round(pv * dr, 2) if pv else 0,
            "total_return_pct": round(dr * 100, 2),
            "drawdown": None,
            "drawdown_breached": False,
        }

    drawdown = performance.get("drawdown")
    breached = performance.get("drawdown_breached", False)
    health = portfolio_health_score(
        analytics, confidence, regime,
        drawdown_breached=breached,
        meta_loaded=bool(meta.get("loaded")),
    )
    alerts = build_alerts(trades, analytics, drawdown=drawdown, drawdown_breached=breached)
    advisor = generate_advisor_insight(
        analytics, confidence, regime,
        drawdown=drawdown, drawdown_breached=breached,
        performance_source=perf_source,
    )

    opportunities = [s for s in signals if s.get("action") == "BUY"][:6]

    return {
        "market": market,
        "as_of": datetime.utcnow().isoformat() + "Z",
        "portfolio_health": health,
        "ai_confidence": confidence,
        "regime": regime_info,
        "meta_status": meta,
        "performance": performance,
        "analytics": analytics,
        "top_opportunities": opportunities,
        "recent_trades": trades[:8],
        "alerts": alerts,
        "advisor": advisor,
    }


@router.post("/rebalance")
def rebalance(run_id: str | None = None, initial_cash: float = 100_000.0,
              mode: str = "rl", market: str = "us", tickers: str | None = None,
              sizing_method: str = "risk",
              risk_per_trade_pct: float | None = None,
              max_position_pct: float | None = None,
              user=Depends(require_auth)):
    """
    Model-driven trade decision on LIVE data, into the simulated paper account.

    market  : "us" (DOW30) or "egx" (.CA names). EGX is simulation-only.
    tickers : optional CSV subset to trade (must belong to the market).
    mode="rl"   : one trained RL model (US only — RL is dimension-locked to DOW30).
    mode="meta" : meta-learner ensemble (works for US and EGX; EGX uses XGB+LSTM).

    Risk controls applied every rebalance:
      • Kill-switch — if portfolio drawdown > 15%, liquidate to cash and stop.
      • Stop-loss   — any held name down > 8% is sold and skipped this cycle.
      • Market decline — if the regime is BEAR the model goes to cash (no new buys).
    """
    from app.services.live_trading_service import generate_live_allocation, generate_meta_allocation

    s = _get_session(user)
    uid = get_user_id(user)
    cash = float(s.get("initial_cash") or initial_cash)
    market = (market or "us").lower()
    ticker_list = [t.strip().upper() for t in tickers.split(",") if t.strip()] if tickers else None

    # ── Risk 1: drawdown kill-switch (before any new allocation) ──────────────
    if s.get("positions"):
        cur_val = _portfolio_value(s)
        drawdown = (cur_val / cash - 1.0) if cash > 0 else 0.0
        if drawdown <= -MAX_DRAWDOWN_PCT:
            s.update({"positions": {}, "cash": cur_val, "running": True,
                      "initial_cash": cash, "user_id": uid})
            s.setdefault("session_id", str(uuid.uuid4()))
            _save_session(s, user_id=uid)
            return {
                "ok": True, "risk_action": "KILL_SWITCH",
                "drawdown": round(drawdown, 4), "threshold": -MAX_DRAWDOWN_PCT,
                "message": f"Drawdown {drawdown*100:.1f}% breached -{MAX_DRAWDOWN_PCT*100:.0f}% "
                           f"— liquidated all positions to cash.",
                "positions_held": 0, "cash": s["cash"], "session_id": s["session_id"],
            }

    # ── Risk 2: per-position stop-loss (names down > 8% are sold & skipped) ────
    stopped_out = _stopped_out_positions(s)

    # ── Risk-engine overrides (volatility sizing + portfolio optimization) ────
    rc = {k: v for k, v in {"risk_per_trade_pct": risk_per_trade_pct,
                            "max_position_pct": max_position_pct}.items() if v is not None}

    # ── Model allocation ──────────────────────────────────────────────────────
    if mode == "meta":
        rid = "meta_learner"
        alloc = generate_meta_allocation(cash, market=market, tickers=ticker_list,
                                         risk_config=rc or None, sizing_method=sizing_method)
    else:
        if market != "us":
            raise HTTPException(status_code=400,
                                detail="RL models are US-only — use mode='meta' for EGX.")
        rid = run_id or s.get("run_id")
        if not rid:
            raise HTTPException(status_code=400,
                                detail="run_id required (pass run_id or start a session first)")
        alloc = generate_live_allocation(rid, cash)

    if not alloc.get("ok"):
        raise HTTPException(status_code=400, detail=alloc.get("message", "allocation failed"))

    # ── Rebalance to target, excluding stopped-out names this cycle ───────────
    prev_positions = dict(s.get("positions") or {})
    positions, invested = {}, 0.0
    for tic, qty in alloc["target"].items():
        if tic in stopped_out:
            continue   # honor stop-loss: don't re-enter a name we just stopped out of
        if qty and qty > 0:
            px = float(alloc["prices"].get(tic, 0.0))
            if px <= 0:
                continue
            positions[tic] = {"qty": round(qty, 6), "entry_price": round(px, 4)}
            invested += qty * px

    s.update({
        "user_id":      uid,
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
    _save_session(s, user_id=uid)

    # ── Explainable trade logging (#4): record entries + exits with rationale ─
    if mode == "meta":
        executed = []
        for tic, p in positions.items():            # new/updated holdings → BUY
            if tic not in prev_positions:
                executed.append({"ticker": tic, "action": "BUY",
                                 "shares": p["qty"], "price": p["entry_price"]})
        for tic in prev_positions:                  # dropped holdings → SELL
            if tic not in positions:
                executed.append({"ticker": tic, "action": "SELL",
                                 "shares": prev_positions[tic].get("qty"),
                                 "price": float(alloc["prices"].get(tic, 0.0))})
        try:
            from app.services.trade_log_service import log_trades
            log_trades(alloc, executed, venue="sim", session_id=s["session_id"])
        except Exception:
            pass

    return {
        "ok":             True,
        "as_of":          alloc["as_of"],
        "algorithm":      alloc["algorithm"],
        "market":         market,
        "regime":         alloc.get("regime"),
        "defensive":      alloc.get("defensive", False),
        "message":        alloc["message"],
        "run_id":         rid,
        "session_id":     s["session_id"],
        "positions_held": len(positions),
        "invested":       round(invested, 2),
        "cash":           s["cash"],
        "stopped_out":    stopped_out,
        "signals":        alloc["signals"],
    }


@router.post("/suggest")
def suggest(market: str = "us", tickers: str | None = None,
            sizing_method: str = "risk",
            risk_per_trade_pct: float | None = None,
            max_position_pct: float | None = None,
            user=Depends(require_auth)):
    """
    Advisory ("helping") mode: compute the model's recommended actions WITHOUT
    executing. Returns per-ticker BUY/HOLD/SELL, target weights, regime, and any
    risk flags so the user can review and decide. Nothing is applied to the session.

    sizing_method: "risk" (ATR risk-based) | "risk_parity" | "min_variance" |
                   "max_sharpe" | "inverse_vol" | "conviction".
    """
    from app.services.live_trading_service import generate_meta_allocation

    s = _get_session(user)
    cash = float(s.get("initial_cash") or 100_000.0)
    market = (market or "us").lower()
    ticker_list = [t.strip().upper() for t in tickers.split(",") if t.strip()] if tickers else None
    rc = {k: v for k, v in {"risk_per_trade_pct": risk_per_trade_pct,
                            "max_position_pct": max_position_pct}.items() if v is not None}

    alloc = generate_meta_allocation(cash, market=market, tickers=ticker_list,
                                     risk_config=rc or None, sizing_method=sizing_method)
    if not alloc.get("ok"):
        raise HTTPException(status_code=400, detail=alloc.get("message", "allocation failed"))

    # Names currently held that breach the stop-loss → flagged as suggested exits
    stopped_out = _stopped_out_positions(s)

    # Build a ranked recommendation list (BUY first, by target dollar weight)
    prices = alloc.get("prices", {})
    target = alloc.get("target", {})
    total = sum((target.get(t, 0.0) * prices.get(t, 0.0)) for t in alloc["tickers"]) or 1.0
    stops = alloc.get("stops", {})
    recs = []
    for t in alloc["tickers"]:
        weight = (target.get(t, 0.0) * prices.get(t, 0.0)) / total
        rec = {"ticker": t, "action": alloc["signals"].get(t, "HOLD"),
               "target_weight": round(weight, 4),
               "stop_loss": t in stopped_out}
        if t in stops:                       # entry/stop/target from the risk engine
            rec["entry"] = prices.get(t)
            rec["stop_price"] = stops[t]["stop_price"]
            rec["take_profit"] = stops[t]["take_profit"]
        recs.append(rec)
    recs.sort(key=lambda r: (r["action"] != "BUY", -r["target_weight"]))

    sizing = alloc.get("sizing") or {}
    portfolio = alloc.get("portfolio") or {}
    return {
        "ok": True, "mode": "advisory", "as_of": alloc["as_of"], "market": market,
        "regime": alloc.get("regime"), "defensive": alloc.get("defensive", False),
        "vol_regime": alloc.get("vol_regime"),
        "message": alloc["message"], "stopped_out": stopped_out,
        "recommendations": recs,
        "sizing_method": alloc.get("sizing_method"),
        "gross_exposure": sizing.get("gross_exposure"),
        "cash_weight": sizing.get("cash_weight"),
        "risk_config": sizing.get("config"),
        "avg_correlation": portfolio.get("avg_correlation"),
        "note": "Advisory only — nothing was executed. Use Rebalance to apply.",
    }


@router.post("/auto")
def set_auto(enabled: bool, user=Depends(require_auth)):
    """Enable/disable automated scheduler rebalancing for the active session."""
    s = _get_session(user)
    s["auto_enabled"] = bool(enabled)
    s.setdefault("session_id", str(uuid.uuid4()))
    _save_session(s, user_id=get_user_id(user))
    return {"ok": True, "auto_enabled": s["auto_enabled"], "session_id": s["session_id"]}


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
def alpaca_rebalance(run_id: str | None = None, mode: str = "rl",
                     sizing_method: str = "risk", use_brackets: bool = False,
                     user=Depends(require_auth)):
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

    # ── Risk 1: drawdown kill-switch — liquidate & stop if breached ───────────
    try:
        risk = alpaca_service.enforce_risk(MAX_DRAWDOWN_PCT)
        if risk.get("liquidated"):
            return {"ok": True, "broker": "alpaca_paper", "risk_action": "KILL_SWITCH",
                    "message": f"Drawdown breached -{MAX_DRAWDOWN_PCT*100:.0f}% "
                               f"— liquidated all positions.", **risk}
    except Exception:
        pass

    s = _get_session(user)
    equity = None
    try:
        equity = alpaca_service.get_account()["equity"]
    except Exception:
        pass
    budget = equity or float(s.get("initial_cash") or 100_000.0)

    if mode == "meta":
        alloc = generate_meta_allocation(budget, market="us", sizing_method=sizing_method)
        rid = "meta_learner"
    else:
        rid = run_id or s.get("run_id")
        if not rid:
            raise HTTPException(status_code=400, detail="run_id required for mode=rl")
        alloc = generate_live_allocation(rid, budget)
    if not alloc.get("ok"):
        raise HTTPException(status_code=400, detail=alloc.get("message", "allocation failed"))

    # ── Risk 2: stop-loss — drop names already down > 8% from the target ──────
    # (weight→0 makes rebalance_to_weights close the position.)
    stopped_out = {}
    try:
        for p in alpaca_service.get_positions():
            plpc = _finite(p.get("unrealized_plpc"))
            if plpc <= -STOP_LOSS_PCT:
                stopped_out[p.get("symbol")] = round(plpc, 4)
    except Exception:
        pass

    # ── Execution: bracket orders (entry+stop+target) or plain weight rebalance ─
    if use_brackets and mode == "meta":
        # Build bracket targets from the risk engine's sized positions + stops.
        sized_positions = (alloc.get("sizing") or {}).get("positions", {})
        stops = alloc.get("stops", {})
        bracket_targets = {
            t: {"dollars": p["dollars"], "price": alloc["prices"].get(t, p.get("entry", 0.0)),
                "stop_price": stops.get(t, {}).get("stop_price"),
                "take_profit": stops.get(t, {}).get("take_profit")}
            for t, p in sized_positions.items() if t not in stopped_out
        }
        result = alpaca_service.rebalance_with_brackets(bracket_targets)
        weights = {t: round(p["weight"], 4) for t, p in sized_positions.items()
                   if t not in stopped_out}
    else:
        # Convert model target (shares × price) → portfolio weights
        target_val = {t: alloc["target"].get(t, 0.0) * alloc["prices"].get(t, 0.0)
                      for t in alloc["tickers"] if t not in stopped_out}
        total = sum(v for v in target_val.values() if v > 0)
        weights = {t: (v / total) for t, v in target_val.items() if v > 0} if total > 0 else {}
        result = alpaca_service.rebalance_to_weights(weights)

    # Persist session intent
    uid = get_user_id(user)
    s.update({"user_id": uid, "run_id": rid, "symbols": alloc["tickers"], "timeframe": "1d",
              "running": True, "initial_cash": float(s.get("initial_cash") or 100_000.0)})
    s.setdefault("session_id", str(uuid.uuid4()))
    _save_session(s, user_id=uid)

    # ── Explainable trade logging (#4): record the broker orders submitted ────
    if mode == "meta":
        executed = [{"ticker": o.get("symbol"),
                     "action": (o.get("side") or "").upper(),
                     "shares": None,
                     "price": float(alloc["prices"].get(o.get("symbol"), 0.0))}
                    for o in result.get("orders", []) if o.get("symbol")]
        try:
            from app.services.trade_log_service import log_trades
            log_trades(alloc, executed, venue="alpaca", session_id=s["session_id"])
        except Exception:
            pass

    return {
        "ok": True, "broker": "alpaca_paper", "mode": mode, "run_id": rid,
        "as_of": alloc.get("as_of"), "model_message": alloc.get("message"),
        "regime": alloc.get("regime"), "defensive": alloc.get("defensive", False),
        "stopped_out": stopped_out,
        "weights": {t: round(w, 4) for t, w in weights.items()},
        **result,
    }


@router.get("/trade-log")
def get_trade_log(limit: int = 50, session_id: str | None = None, ticker: str | None = None,
                  user=Depends(require_auth)):
    """
    Explainable trade journal scoped to this user's paper sessions.
    """
    from app.services.trade_log_service import get_trade_log as _get
    allowed = _user_session_ids(user)
    if session_id and session_id not in allowed:
        raise HTTPException(status_code=404, detail="Session not found")
    return _get(limit=limit, session_id=session_id, ticker=ticker, session_ids=allowed if not session_id else None)


@router.get("/trade-log/{trade_id}")
def get_trade_decision(trade_id: str, user=Depends(require_auth)):
    """Full decision trace for one trade (Decision Explorer)."""
    from app.database import TradeLog
    from app.services.decision_explorer_service import build_decision_trace

    allowed = _user_session_ids(user)
    db = SessionLocal()
    try:
        row = db.query(TradeLog).filter(TradeLog.id == trade_id).first()
        if not row:
            raise HTTPException(status_code=404, detail="Trade not found")
        if allowed is not None and row.session_id not in allowed:
            raise HTTPException(status_code=404, detail="Trade not found")
        return build_decision_trace(row)
    finally:
        db.close()


@router.get("/history")
def get_session_history(limit: int = 20, user=Depends(require_auth)):
    """Return this user's past paper trading sessions."""
    db = SessionLocal()
    try:
        rows = (
            db.query(PaperSession)
            .filter(PaperSession.user_id == get_user_id(user))
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
