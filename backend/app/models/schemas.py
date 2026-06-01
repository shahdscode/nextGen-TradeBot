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


class TickerValidateRequest(BaseModel):
    source: str
    tickers: List[str]


class TickerValidateResponse(BaseModel):
    valid: bool
    source: str
    tickers: List[str] = []
    invalid: List[str] = []
    allowed_count: int = 0
    message: str = ""


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
    train_start: Optional[str] = None
    train_end: Optional[str] = None
    # Hybrid alpha: optional completed ML run IDs (probabilities → PPO state)
    xgb_run_id: Optional[str] = None
    lstm_run_id: Optional[str] = None


class RunResponse(BaseModel):
    run_id: str
    algorithm: str
    status: str
    created_at: Optional[str] = None
    updated_at: Optional[str] = None
    model_path: Optional[str] = None
    metrics: Optional[Dict[str, Any]] = None
    error: Optional[str] = None
    published: Optional[bool] = None
    market: Optional[str] = None
    data_job_id: Optional[str] = None   # used by frontend to detect checkpoints


# ── Backtest ──────────────────────────────────────────────────────────────────

class BacktestRequest(BaseModel):
    run_id: str
    test_start: str
    test_end: str
    initial_capital: float = 1_000_000.0
    # Trading friction
    commission_pct: float = 0.001   # 0.1% per trade
    slippage_pct:   float = 0.001   # 0.1% per trade
    # Position constraints
    max_position_pct: float = 0.20  # max 20% capital per stock
    cooldown_days:    int   = 5     # min days between trades on same ticker (PPO stability)


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
    metrics: Optional[Dict[str, Any]] = None
    trades: Optional[List[Dict[str, Any]]] = None
    benchmark: Optional[Dict[str, Any]] = None
    baselines: Optional[Dict[str, Any]] = None
    walk_forward_periods: Optional[List[Dict[str, Any]]] = None
    walk_forward_summary: Optional[Dict[str, Any]] = None
    stress_tests: Optional[Dict[str, Any]] = None
    rl_sanity: Optional[Dict[str, Any]] = None
    overfitting_report: Optional[Dict[str, Any]] = None
    regime_analysis: Optional[Dict[str, Any]] = None
    significance_tests: Optional[Dict[str, Any]] = None
    methodology_notes: Optional[Dict[str, Any]] = None
    data_source: Optional[str] = None
    data_quality: Optional[Dict[str, Any]] = None
    transaction_costs: Optional[Dict[str, Any]] = None
    price_note: Optional[str] = None
    step_log_summary: Optional[Dict[str, Any]] = None
    error: Optional[str] = None
