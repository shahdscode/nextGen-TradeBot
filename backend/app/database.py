from sqlalchemy import create_engine, Column, String, DateTime, JSON, Float, Text, Boolean, Integer
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker
from sqlalchemy import text
from datetime import datetime
from app.config import settings

engine = create_engine(
    settings.database_url,
    connect_args={"check_same_thread": False}
)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base = declarative_base()


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


class User(Base):
    __tablename__ = "users"
    id = Column(String, primary_key=True)
    username = Column(String, unique=True, nullable=False)
    email = Column(String, unique=True, nullable=True)
    hashed_password = Column(String, nullable=False)
    role = Column(String, default="user")  # "admin" | "user"
    is_active = Column(Boolean, default=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    # Per-user Alpaca paper-trading credentials (each user trades their own account)
    alpaca_api_key = Column(String, nullable=True)
    alpaca_api_secret = Column(String, nullable=True)


class Job(Base):
    __tablename__ = "jobs"
    id = Column(String, primary_key=True)
    type = Column(String)
    status = Column(String, default="pending")
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    result_path = Column(String, nullable=True)
    error = Column(Text, nullable=True)
    meta = Column(JSON, nullable=True)


class Run(Base):
    __tablename__ = "runs"
    id = Column(String, primary_key=True)
    data_job_id = Column(String, nullable=True)
    algorithm = Column(String)
    model_type = Column(String, default="rl")  # "rl" | "xgboost" | "lstm"
    status = Column(String, default="pending")
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    model_path = Column(String, nullable=True)
    metrics_json = Column(JSON, nullable=True)
    hyperparams = Column(JSON, nullable=True)
    error = Column(Text, nullable=True)
    published = Column(Boolean, default=False)
    market = Column(String, default="us")  # "us" | "egx"


class Backtest(Base):
    __tablename__ = "backtests"
    id = Column(String, primary_key=True)
    run_id = Column(String)
    status = Column(String, default="pending")
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    test_start = Column(String, nullable=True)
    test_end = Column(String, nullable=True)
    initial_capital = Column(Float, default=1_000_000.0)
    result_json = Column(JSON, nullable=True)
    error = Column(Text, nullable=True)


class Signal(Base):
    __tablename__ = "signals"
    id = Column(String, primary_key=True)
    ticker = Column(String, nullable=False)
    action = Column(String, nullable=False)       # "BUY" | "SELL" | "HOLD"
    confidence = Column(Float, nullable=False)
    regime = Column(String, nullable=True)         # "BULL" | "BEAR" | "SIDEWAYS"
    xgb_prob = Column(Float, nullable=True)
    lstm_prob = Column(Float, nullable=True)
    ppo_signal = Column(Float, nullable=True)
    sentiment_score = Column(Float, nullable=True)
    shap_features = Column(JSON, nullable=True)    # [{name, value, contribution}]
    risk_level = Column(String, nullable=True)     # "LOW" | "MEDIUM" | "HIGH"
    stop_loss_pct = Column(Float, nullable=True)
    market = Column(String, default="us")
    generated_at = Column(DateTime, default=datetime.utcnow)


class SentimentScore(Base):
    __tablename__ = "sentiment_scores"
    id = Column(String, primary_key=True)
    ticker = Column(String, nullable=False)
    score = Column(Float, nullable=False)
    label = Column(String, nullable=True)   # "positive" | "negative" | "neutral"
    headline_count = Column(Integer, default=0)
    generated_at = Column(DateTime, default=datetime.utcnow)


class PaperSession(Base):
    """Persistent paper trading session — survives server restarts."""
    __tablename__ = "paper_sessions"
    id = Column(String, primary_key=True)
    run_id = Column(String, nullable=True)
    symbols = Column(JSON, default=list)
    timeframe = Column(String, default="M15")
    initial_cash = Column(Float, default=100_000.0)
    cash = Column(Float, default=100_000.0)
    positions = Column(JSON, default=dict)   # {symbol: {qty, entry_price}}
    running = Column(Boolean, default=False)
    started_at = Column(DateTime, nullable=True)
    stopped_at = Column(DateTime, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)


class ModelPerformanceScore(Base):
    """
    Daily EWMA performance scores for the adaptive weight tracker.

    One row per (date, model_key).  The EWMA score is updated after each
    trading day once actual 5-day returns are known.  Fusion weights are
    derived from these scores by ewma_tracker_service.get_current_weights().
    """
    __tablename__ = "model_performance_scores"
    id           = Column(String, primary_key=True)
    date         = Column(String, nullable=False)          # "YYYY-MM-DD"
    model_key    = Column(String, nullable=False)          # "xgboost" | "lstm" | "ppo" | …
    ewma_score   = Column(Float,  nullable=False)          # current EWMA value 0-1
    daily_correct = Column(Float, nullable=True)           # 1.0 / 0.0 / 0.5
    weight        = Column(Float, nullable=True)           # normalised fusion weight
    created_at   = Column(DateTime, default=datetime.utcnow)


def _add_column_if_missing(conn, table: str, col_def: str):
    try:
        conn.execute(text(f"ALTER TABLE {table} ADD COLUMN {col_def}"))
        conn.commit()
    except Exception:
        pass


def create_tables():
    Base.metadata.create_all(bind=engine)
    # Migrate existing tables with new columns (SQLite does not support ADD COLUMN IF NOT EXISTS)
    with engine.connect() as conn:
        _add_column_if_missing(conn, "users", "alpaca_api_key TEXT")
        _add_column_if_missing(conn, "users", "alpaca_api_secret TEXT")
        _add_column_if_missing(conn, "runs", "model_type TEXT DEFAULT 'rl'")
        _add_column_if_missing(conn, "runs", "published INTEGER DEFAULT 0")
        _add_column_if_missing(conn, "runs", "market TEXT DEFAULT 'us'")
        _add_column_if_missing(conn, "backtests", "initial_capital REAL DEFAULT 1000000.0")
    # NEW: model_performance_scores table (created via create_all above if missing)
    ModelPerformanceScore.__table__.create(bind=engine, checkfirst=True)
