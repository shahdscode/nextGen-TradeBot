from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from app.database import create_tables
from app import finrl_wrapper
from app.routers import data, training, backtest, paper_trading
from app.routers import auth, ml, signals, market, research, mobile

app = FastAPI(
    title="NextGen TradeBot API",
    description="AI-powered trading signals with XGBoost, LSTM, and FinRL PPO",
    version="2.0.0",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.on_event("startup")
def on_startup():
    create_tables()
    # Ensure default admin exists for first run
    _seed_default_admin()


def _seed_default_admin():
    try:
        from app.services.auth_service import create_user, get_user_by_username
        if not get_user_by_username("admin"):
            create_user(username="admin", password="admin123", role="admin", email="admin@tradebot.local")
    except Exception:
        pass


@app.get("/health")
def health():
    return {"status": "ok"}


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
        "indicators": finrl_wrapper.get_indicators(),
        "data_sources": finrl_wrapper.get_data_sources(),
        "finrl_status": finrl_wrapper.get_finrl_status(),
    }


# ── Routers ──────────────────────────────────────────────────────────────────
app.include_router(auth.router, prefix="/api")
app.include_router(data.router, prefix="/api")
app.include_router(training.router, prefix="/api")
app.include_router(backtest.router, prefix="/api")
app.include_router(paper_trading.router, prefix="/api")
app.include_router(ml.router, prefix="/api")
app.include_router(signals.router, prefix="/api")
app.include_router(market.router, prefix="/api")
app.include_router(research.router, prefix="/api")
app.include_router(mobile.router, prefix="/api")
