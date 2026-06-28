from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from app.config import settings
from app.database import create_tables
from app import finrl_wrapper
from app.routers import auth, paper_trading, signals, market

# ML/RL routers — only loaded when heavy dependencies are installed
try:
    from app.routers import data, training, backtest, ml, research, mobile
    _ml_available = True
except ImportError:
    _ml_available = False

app = FastAPI(
    title="NextGen TradeBot API",
    description="AI-powered trading signals with XGBoost, LSTM, and FinRL PPO",
    version="2.0.0",
)

_cors = [o.strip() for o in settings.cors_origins.split(",") if o.strip()]
app.add_middleware(
    CORSMiddleware,
    allow_origins=_cors if _cors else ["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.on_event("startup")
def on_startup():
    create_tables()
    _seed_default_admin()
    _backfill_legacy_user_ids()
    try:
        from app.services.scheduler_service import start_scheduler
        start_scheduler()
    except Exception:
        pass


def _seed_default_admin():
    if settings.environment == "production" and not settings.seed_admin:
        return
    try:
        from app.services.auth_service import create_user, get_user_by_username
        if not get_user_by_username("admin"):
            create_user(username="admin", password="admin123", role="admin", email="admin@tradebot.local")
    except Exception:
        pass


def _backfill_legacy_user_ids():
    try:
        from app.database import SessionLocal, User, PaperSession, Backtest, Job
        db = SessionLocal()
        try:
            admin = db.query(User).filter(User.username == "admin").first()
            if not admin:
                return
            uid = admin.id
            changed = False
            for model in (PaperSession, Backtest, Job):
                for row in db.query(model).filter(model.user_id.is_(None)).all():
                    row.user_id = uid
                    changed = True
            if changed:
                db.commit()
        finally:
            db.close()
    except Exception:
        pass


@app.get("/health")
def health():
    return {"status": "ok", "environment": settings.environment}


@app.get("/")
def root():
    return {
        "name": "NextGen TradeBot API",
        "status": "ok",
        "docs": "/docs",
        "health": "/health",
        "api_info": "/api/info",
        "version": "2.0.0",
    }


@app.get("/api/info")
def info():
    return {
        "agents": finrl_wrapper.get_agents(),
        "tickers_by_source": finrl_wrapper.get_tickers_by_source(),
        "ticker_catalogs": finrl_wrapper.get_ticker_catalogs(),
        "indicators": finrl_wrapper.get_indicators(),
        "data_sources": finrl_wrapper.get_data_sources(),
        "finrl_status": finrl_wrapper.get_finrl_status(),
        "environment": settings.environment,
        "allow_public_register": settings.allow_public_register,
    }


# ── Routers ──────────────────────────────────────────────────────────────────
app.include_router(auth.router, prefix="/api")
app.include_router(paper_trading.router, prefix="/api")
app.include_router(signals.router, prefix="/api")
app.include_router(market.router, prefix="/api")

if _ml_available:
    app.include_router(data.router, prefix="/api")
    app.include_router(training.router, prefix="/api")
    app.include_router(backtest.router, prefix="/api")
    app.include_router(ml.router, prefix="/api")
    app.include_router(research.router, prefix="/api")
    app.include_router(mobile.router, prefix="/api")
