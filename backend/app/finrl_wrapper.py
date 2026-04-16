"""
Safe import bridge for FinRL. All FinRL imports are isolated here
so import failures do not crash the FastAPI app at startup.
"""
import traceback
from typing import List, Dict, Any

FINRL_AVAILABLE = False
_import_error = ""

try:
    from finrl.config import INDICATORS
    from finrl.config_tickers import DOW_30_TICKER
    FINRL_AVAILABLE = True
except Exception as e:
    _import_error = traceback.format_exc()
    DOW_30_TICKER = [
        "AXP", "AMGN", "AAPL", "BA", "CAT", "CSCO", "CVX", "GS",
        "HD", "HON", "IBM", "INTC", "JNJ", "JPM", "KO", "MCD",
        "MMM", "MRK", "MSFT", "NKE", "PG", "TRV", "UNH", "CRM",
        "VZ", "V", "WBA", "WMT", "DIS", "DOW"
    ]
    INDICATORS = [
        "macd", "boll_ub", "boll_lb", "rsi_30", "cci_30",
        "dx_30", "close_30_sma", "close_60_sma"
    ]

SUPPORTED_AGENTS = {
    "ppo": {
        "name": "PPO",
        "description": "Proximal Policy Optimization. Stable, general-purpose baseline.",
        "library": "stable-baselines3",
        "default_hyperparams": {
            "n_steps": 2048,
            "ent_coef": 0.01,
            "learning_rate": 0.0003,
            "batch_size": 128,
            "n_epochs": 10,
            "total_timesteps": 5000
        }
    },
    "a2c": {
        "name": "A2C",
        "description": "Advantage Actor-Critic. Faster training, lower sample efficiency.",
        "library": "stable-baselines3",
        "default_hyperparams": {
            "n_steps": 5,
            "ent_coef": 0.01,
            "learning_rate": 0.0007,
            "total_timesteps": 5000
        }
    },
    "ddpg": {
        "name": "DDPG",
        "description": "Deep Deterministic Policy Gradient. Continuous action spaces.",
        "library": "stable-baselines3",
        "default_hyperparams": {
            "batch_size": 128,
            "buffer_size": 50000,
            "learning_rate": 0.001,
            "total_timesteps": 5000
        }
    },
    "td3": {
        "name": "TD3",
        "description": "Twin Delayed DDPG. Reduces overestimation bias.",
        "library": "stable-baselines3",
        "default_hyperparams": {
            "batch_size": 128,
            "buffer_size": 50000,
            "learning_rate": 0.001,
            "policy_delay": 2,
            "total_timesteps": 5000
        }
    },
    "sac": {
        "name": "SAC",
        "description": "Soft Actor-Critic. Entropy-regularized, robust exploration.",
        "library": "stable-baselines3",
        "default_hyperparams": {
            "batch_size": 128,
            "buffer_size": 100000,
            "learning_rate": 0.0003,
            "ent_coef": "auto",
            "total_timesteps": 5000
        }
    }
}

SUPPORTED_DATA_SOURCES = {
    "yahoo": {
        "name": "Yahoo Finance",
        "description": "Free, no API key required.",
        "requires_key": False
    },
    "alpaca": {
        "name": "Alpaca Markets",
        "description": "Real-time and historical. Requires API key.",
        "requires_key": True
    },
    "mt5": {
        "name": "MT5 Demo Gateway",
        "description": "Candles via MT5 gateway API (/candles).",
        "requires_key": True
    }
}


def get_agents() -> Dict[str, Any]:
    return SUPPORTED_AGENTS


def get_tickers() -> List[str]:
    """Deprecated: use get_tickers_by_source() instead"""
    return DOW_30_TICKER


def get_tickers_by_source() -> Dict[str, List[str]]:
    """Return available tickers for each data source"""
    mt5_tickers = [
        # Forex Majors
        "EURUSD", "GBPUSD", "USDJPY", "AUDUSD", "USDCAD", "NZDUSD",
        # Forex Crosses
        "EURJPY", "GBPJPY", "EURGBP", "EURCAD", "AUDNZD", "AUDCAD",
        "AUDJPY", "CADJPY", "CHFUSD", "EURAUD", "EURCHF", "GBPAUD",
        "GBPCAD", "GBPCHF", "NZDJPY", "USDCHF",
        # Metals
        "XAUUSD", "XAGUSD", "XPTUSD", "XPDUSD",
        # Energy
        "BRENT", "WTIUSD",
        # Indices
        "SP500", "USTEC", "DAX", "FTSE100", "CAC40", "NIKKEI", "HSI", "ASX200",
        # Cryptocurrencies
        "BTCUSD", "ETHUSD", "LTCUSD", "XRPUSD", "ADAUSD", "DOGEUSD",
        # Bitcoin and Ethereum with m suffix (demo variants)
        "BTCUSDm", "ETHUSDm",
        # US Stocks (for compatibility with DOW 30)
        "AAPL", "MSFT", "GOOGL", "AMZN", "TSLA", "NVDA", "META", "NFLX",
    ]
    
    return {
        "yahoo": DOW_30_TICKER,
        "alpaca": DOW_30_TICKER,
        "mt5": mt5_tickers,
    }


def get_indicators() -> List[str]:
    return INDICATORS


def get_data_sources() -> Dict[str, Any]:
    return SUPPORTED_DATA_SOURCES


def get_finrl_status() -> Dict[str, Any]:
    return {
        "available": FINRL_AVAILABLE,
        "error": _import_error if not FINRL_AVAILABLE else None
    }
