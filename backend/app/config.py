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
    database_url: str = f"sqlite:///{_PROJECT_ROOT / 'data' / 'finrl.db'}"
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
    # External data
    newsapi_key: str = ""
    # Market UI: when False, only Yahoo/NewsAPI data (no training CSV or synthetic placeholders)
    market_allow_demo_fallback: bool = False
    # RL / backtest friction (commission + half-spread proxy via slippage_bps)
    buy_cost_pct: float = 0.001
    sell_cost_pct: float = 0.001
    slippage_bps: float = 5.0

    class Config:
        # Absolute path to the project-root .env so the API/workers/scripts all
        # read the same file regardless of working directory (backend/ vs root).
        env_file = str(_PROJECT_ROOT / ".env")


settings = Settings()

# ── Security check: warn loudly if JWT secret is still the insecure default ──
if settings.jwt_secret_key == _DEFAULT_JWT_SECRET:
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
