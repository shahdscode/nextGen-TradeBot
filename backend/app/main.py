from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from app.database import create_tables
from app import finrl_wrapper
from app.routers import data, training, backtest, paper_trading

app = FastAPI(
    title="FinRL Dashboard API",
    description="REST API for training, backtesting, and paper trading FinRL agents",
    version="1.0.0",
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


@app.get("/health")
def health():
    return {"status": "ok"}


@app.get("/")
def root():
    return {
        "name": "FinRL Dashboard API",
        "status": "ok",
        "docs": "/docs",
        "health": "/health",
        "api_info": "/api/info",
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


app.include_router(data.router, prefix="/api")
app.include_router(training.router, prefix="/api")
app.include_router(backtest.router, prefix="/api")
app.include_router(paper_trading.router, prefix="/api")
