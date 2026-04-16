from pydantic_settings import BaseSettings
from pathlib import Path


class Settings(BaseSettings):
    redis_url: str = "redis://localhost:6379/0"
    database_url: str = "sqlite:///./finrl.db"
    data_dir: str = "./data/datasets"
    models_dir: str = "./data/models"
    results_dir: str = "./data/results"
    alpaca_api_key: str = ""
    alpaca_api_secret: str = ""
    alpaca_base_url: str = "https://paper-api.alpaca.markets"
    mt5_gateway_url: str = "http://51.21.209.128:8000"
    mt5_api_key: str = ""
    mt5_timeframe: str = "M15"

    class Config:
        env_file = ".env"


settings = Settings()

for d in [settings.data_dir, settings.models_dir, settings.results_dir]:
    Path(d).mkdir(parents=True, exist_ok=True)
