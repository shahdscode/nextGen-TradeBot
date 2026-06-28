from sqlalchemy import create_engine, Column, String, DateTime, JSON, Float, Text, Boolean, Integer, inspect, text
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker
from datetime import datetime
from app.config import settings


def _normalize_database_url(url: str) -> str:
    """Normalize Supabase/Heroku-style URLs for SQLAlchemy + psycopg2."""
    if url.startswith("postgres://"):
        return url.replace("postgres://", "postgresql+psycopg2://", 1)
    if url.startswith("postgresql://") and "+psycopg2" not in url and "+asyncpg" not in url:
        return url.replace("postgresql://", "postgresql+psycopg2://", 1)
    return url


def _build_engine():
    url = _normalize_database_url(settings.database_url)
    is_sqlite = url.startswith("sqlite")

    if is_sqlite:
        return create_engine(url, connect_args={"check_same_thread": False})

    connect_args = {}
    if "supabase.co" in url or "supabase.com" in url:
        connect_args["sslmode"] = settings.database_ssl_mode or "require"

    return create_engine(
        url,
        pool_pre_ping=True,
        pool_size=settings.database_pool_size,
        max_overflow=settings.database_max_overflow,
        connect_args=connect_args,
    )


engine = _build_engine()
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base = declarative_base()


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def is_sqlite() -> bool:
    return engine.dialect.name == "sqlite"


def is_postgres() -> bool:
    return engine.dialect.name == "postgresql"


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
    user_id = Column(String, nullable=True, index=True)  # NULL = system/scheduler job
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
    user_id = Column(String, nullable=True, index=True)
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
    user_id = Column(String, nullable=True, index=True)
    run_id = Column(String, nullable=True)
    symbols = Column(JSON, default=list)
    timeframe = Column(String, default="M15")
    initial_cash = Column(Float, default=100_000.0)
    cash = Column(Float, default=100_000.0)
    positions = Column(JSON, default=dict)   # {symbol: {qty, entry_price}}
    running = Column(Boolean, default=False)
    auto_enabled = Column(Boolean, default=False)  # scheduler auto-rebalances if True
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


class TradeLog(Base):
    """
    Explainable record of every trade DECISION the engine acts on.

    One row per ticker per rebalance that produced a BUY or SELL. Stores not
    just what was traded but WHY — the meta probability, per-model signals,
    regime, volatility regime, sizing rationale (weight, stop, target, risk),
    and a snapshot of key indicators — so any trade can be audited after the
    fact and the AI's behavior is transparent.
    """
    __tablename__ = "trade_logs"
    id            = Column(String, primary_key=True)
    session_id    = Column(String, nullable=True)          # paper session / broker
    venue         = Column(String, nullable=True)          # "sim" | "alpaca"
    market        = Column(String, default="us")
    ticker        = Column(String, nullable=False)
    action        = Column(String, nullable=False)         # "BUY" | "SELL"
    shares        = Column(Float,  nullable=True)
    price         = Column(Float,  nullable=True)
    weight        = Column(Float,  nullable=True)          # target weight of equity
    # ── rationale ──
    meta_prob     = Column(Float,  nullable=True)          # calibrated probability
    regime        = Column(String, nullable=True)          # BULL | BEAR | SIDEWAYS
    vol_regime    = Column(String, nullable=True)          # HIGH | NORMAL | LOW
    sizing_method = Column(String, nullable=True)
    stop_price    = Column(Float,  nullable=True)
    take_profit   = Column(Float,  nullable=True)
    risk_dollars  = Column(Float,  nullable=True)
    model_signals = Column(JSON,   nullable=True)          # {xgb, lstm, ppo, ...}
    indicators    = Column(JSON,   nullable=True)          # {rsi_14, macd, atr, ...}
    reason        = Column(String, nullable=True)          # human-readable summary
    created_at    = Column(DateTime, default=datetime.utcnow)


_LEGACY_MIGRATIONS = [
    ("users", "alpaca_api_key TEXT"),
    ("users", "alpaca_api_secret TEXT"),
    ("runs", "model_type TEXT DEFAULT 'rl'"),
    ("runs", "published BOOLEAN DEFAULT FALSE"),
    ("runs", "market TEXT DEFAULT 'us'"),
    ("backtests", "initial_capital DOUBLE PRECISION DEFAULT 1000000.0"),
    ("paper_sessions", "auto_enabled BOOLEAN DEFAULT FALSE"),
    ("paper_sessions", "user_id TEXT"),
    ("backtests", "user_id TEXT"),
    ("jobs", "user_id TEXT"),
]

_LEGACY_MIGRATIONS_SQLITE = [
    ("users", "alpaca_api_key TEXT"),
    ("users", "alpaca_api_secret TEXT"),
    ("runs", "model_type TEXT DEFAULT 'rl'"),
    ("runs", "published INTEGER DEFAULT 0"),
    ("runs", "market TEXT DEFAULT 'us'"),
    ("backtests", "initial_capital REAL DEFAULT 1000000.0"),
    ("paper_sessions", "auto_enabled INTEGER DEFAULT 0"),
    ("paper_sessions", "user_id TEXT"),
    ("backtests", "user_id TEXT"),
    ("jobs", "user_id TEXT"),
]


def _column_exists(conn, table: str, column: str) -> bool:
    inspector = inspect(conn)
    try:
        cols = {c["name"] for c in inspector.get_columns(table)}
    except Exception:
        return False
    return column in cols


def _add_column_if_missing(conn, table: str, col_def: str):
    column = col_def.split()[0]
    if _column_exists(conn, table, column):
        return

    if is_postgres():
        stmt = f"ALTER TABLE {table} ADD COLUMN IF NOT EXISTS {col_def}"
    else:
        stmt = f"ALTER TABLE {table} ADD COLUMN {col_def}"

    try:
        conn.execute(text(stmt))
        conn.commit()
    except Exception:
        conn.rollback()


def create_tables():
    Base.metadata.create_all(bind=engine)
    migrations = _LEGACY_MIGRATIONS_SQLITE if is_sqlite() else _LEGACY_MIGRATIONS
    with engine.connect() as conn:
        for table, col_def in migrations:
            _add_column_if_missing(conn, table, col_def)
    ModelPerformanceScore.__table__.create(bind=engine, checkfirst=True)
    TradeLog.__table__.create(bind=engine, checkfirst=True)
