import logging
import warnings
from pydantic_settings import BaseSettings
from pathlib import Path

logger = logging.getLogger(__name__)

_DEFAULT_JWT_SECRET = "nextgen-tradebot-secret-change-in-production"



# Project root = one level above the backend/ directory
_PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
_DATA_ROOT = str(_PROJECT_ROOT / "data")


class Settings(BaseSettings):
    redis_url: str = "redis://localhost:6379/0"
    # Absolute path so the API, Celery workers, and training scripts ALL use the
    # same DB regardless of working directory. Previously relative ('./finrl.db')
    # which silently created a second DB under backend/ that diverged from the
    # project-root data/finrl.db used by the training scripts.
    # SQLite for local dev; Supabase/PostgreSQL for hosted production.
    # Supabase (pooler, recommended):
    #   DATABASE_URL=postgresql://postgres.[ref]:[password]@aws-0-[region].pooler.supabase.com:6543/postgres
    database_url: str = f"sqlite:///{_PROJECT_ROOT / 'data' / 'finrl.db'}"
    database_ssl_mode: str = "require"       # Supabase requires SSL; use "disable" for local Postgres
    database_pool_size: int = 5
    database_max_overflow: int = 10
    data_dir: str = str(_PROJECT_ROOT / "data" / "datasets")
    models_dir: str = str(_PROJECT_ROOT / "data" / "models")
    results_dir: str = str(_PROJECT_ROOT / "data" / "results")
    oof_dir: str = str(_PROJECT_ROOT / "data" / "oof")
    alpaca_api_key: str = ""
    alpaca_api_secret: str = ""
    alpaca_base_url: str = "https://paper-api.alpaca.markets"
    mt5_gateway_url: str = "http://51.21.209.128:8000"
    mt5_api_key: str = ""
    mt5_timeframe: str = "M15"
    # Auth
    jwt_secret_key: str = _DEFAULT_JWT_SECRET
    jwt_algorithm: str = "HS256"
    jwt_expire_minutes: int = 60 * 24  # 24 hours
    # Fernet key (urlsafe-base64, 32 bytes) for encrypting stored secrets like
    # per-user Alpaca API keys. If empty, derived from JWT_SECRET_KEY.
    # Generate: python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
    secret_encryption_key: str = ""
    # Email (verification + password reset). When SMTP is unset, emails are
    # logged to the console (dev fallback) instead of being sent.
    smtp_host: str = ""
    smtp_port: int = 587
    smtp_user: str = ""
    smtp_password: str = ""
    smtp_use_tls: bool = True
    email_from: str = "NextGen TradeBot <no-reply@nextgentradebot.local>"
    app_base_url: str = "http://localhost:5173"   # used to build verify/reset links
    require_email_verification: bool = False       # block login until verified when True
    # External data
    newsapi_key: str = ""
    # Market UI: when False, only Yahoo/NewsAPI data (no training CSV or synthetic placeholders)
    market_allow_demo_fallback: bool = False
    # RL / backtest friction (commission + half-spread proxy via slippage_bps)
    buy_cost_pct: float = 0.001
    sell_cost_pct: float = 0.001
    slippage_bps: float = 5.0
    # Deployment / multi-user SaaS
    environment: str = "development"  # development | production
    log_level: str = "INFO"           # DEBUG | INFO | WARNING | ERROR
    allow_public_register: bool = True
    cors_origins: str = (
        "http://localhost:5173,http://localhost:80,http://127.0.0.1:5173,"
        "https://nextgen-tradebot-self.vercel.app"
    )
    seed_admin: bool = False  # set SEED_ADMIN=true to create default admin in production

    class Config:
        # Absolute path to the project-root .env so the API/workers/scripts all
        # read the same file regardless of working directory (backend/ vs root).
        env_file = str(_PROJECT_ROOT / ".env")


settings = Settings()

if settings.environment == "production" and settings.jwt_secret_key == _DEFAULT_JWT_SECRET:
    raise RuntimeError(
        "Refusing to start in production with the default JWT_SECRET_KEY. "
        "Set JWT_SECRET_KEY in .env to a strong random value."
    )

# ── Security check: warn loudly if JWT secret is still the insecure default ──
if settings.jwt_secret_key == _DEFAULT_JWT_SECRET and settings.environment != "production":
    _msg = (
        "\n" + "=" * 70 + "\n"
        "  SECURITY WARNING: JWT_SECRET_KEY is set to the default development\n"
        "  value. Any token signed with this secret can be forged by anyone\n"
        "  who reads the source code.\n\n"
        "  Set a strong random secret in your .env file before deployment:\n"
        "    JWT_SECRET_KEY=$(python -c \"import secrets; print(secrets.token_hex(32))\")\n"
        + "=" * 70
    )
    warnings.warn(_msg, stacklevel=2)
    logger.warning("JWT_SECRET_KEY is using the insecure default — set JWT_SECRET_KEY in .env")

for d in [settings.data_dir, settings.models_dir, settings.results_dir, settings.oof_dir]:
    Path(d).mkdir(parents=True, exist_ok=True)
