from pydantic import BaseModel
from typing import List, Optional, Dict, Any


# ── Data ──────────────────────────────────────────────────────────────────────

class DataDownloadRequest(BaseModel):
    tickers: List[str]
    start_date: str
    end_date: str
    source: str = "yahoo"
    timeframe: Optional[str] = None
    indicators: Optional[List[str]] = None


class JobStatusResponse(BaseModel):
    job_id: str
    status: str
    error: Optional[str] = None
    result_path: Optional[str] = None
    meta: Optional[Dict[str, Any]] = None


# ── Training ──────────────────────────────────────────────────────────────────

class TrainRequest(BaseModel):
    data_job_id: str
    algorithm: str
    hyperparams: Optional[Dict[str, Any]] = None


class RunResponse(BaseModel):
    run_id: str
    algorithm: str
    status: str
    created_at: Optional[str] = None
    updated_at: Optional[str] = None
    model_path: Optional[str] = None
    metrics: Optional[Dict[str, Any]] = None
    error: Optional[str] = None


# ── Backtest ──────────────────────────────────────────────────────────────────

class BacktestRequest(BaseModel):
    run_id: str
    test_start: str
    test_end: str
    initial_capital: float = 1_000_000.0


class TradeAction(BaseModel):
    date: str
    ticker: str
    action: str        # "buy" | "sell" | "hold"
    shares: float
    price: float


class BacktestResponse(BaseModel):
    backtest_id: str
    run_id: str
    status: str
    initial_capital: Optional[float] = None
    account_value: Optional[List[float]] = None
    daily_return: Optional[List[float]] = None
    dates: Optional[List[str]] = None
    metrics: Optional[Dict[str, float]] = None
    trades: Optional[List[Dict[str, Any]]] = None
    benchmark: Optional[Dict[str, Any]] = None
    error: Optional[str] = None
