"""
Safe bridge for FinRL metadata.

Do NOT import finrl at module load — on some macOS/Anaconda setups it segfaults
(exit 139) and kills uvicorn before Python can catch an exception.

Set FINRL_ENABLE=1 to probe finrl in a subprocess (for /api/info status only).
RL training still requires a working finrl install in a dedicated venv.
"""
from __future__ import annotations

import os
import subprocess
import sys
from typing import List, Dict, Any

# Static defaults (same as finrl.config_tickers / finrl.config)
DOW_30_TICKER = [
    "AXP", "AMGN", "AAPL", "BA", "CAT", "CSCO", "CVX", "GS",
    "HD", "HON", "IBM", "INTC", "JNJ", "JPM", "KO", "MCD",
    "MMM", "MRK", "MSFT", "NKE", "PG", "TRV", "UNH", "CRM",
    "VZ", "V", "WBA", "WMT", "DIS", "DOW",
]
INDICATORS = [
    "macd", "boll_ub", "boll_lb", "rsi_30", "cci_30",
    "dx_30", "close_30_sma", "close_60_sma",
]

FINRL_AVAILABLE = False
_import_error = ""
_probe_done = False


def _probe_finrl() -> None:
    """Check finrl in a child process so a segfault does not kill the API."""
    global FINRL_AVAILABLE, _import_error, _probe_done
    if _probe_done:
        return
    _probe_done = True

    if os.environ.get("FINRL_ENABLE", "").lower() not in ("1", "true", "yes"):
        _import_error = (
            "FinRL import disabled at startup (avoids segfault on some Anaconda builds). "
            "Set FINRL_ENABLE=1 to probe, or use a project venv with finrl==0.3.7."
        )
        return

    try:
        proc = subprocess.run(
            [sys.executable, "-c", "from finrl.config import INDICATORS; print('ok')"],
            capture_output=True,
            text=True,
            timeout=45,
        )
        if proc.returncode == 0:
            FINRL_AVAILABLE = True
            _import_error = ""
        else:
            err = (proc.stderr or proc.stdout or "").strip()
            _import_error = err or f"finrl probe exited with code {proc.returncode}"
    except subprocess.TimeoutExpired:
        _import_error = "finrl import probe timed out"
    except Exception as e:
        _import_error = str(e)


SUPPORTED_AGENTS = {
    "ppo": {
        "name": "PPO",
        "description": (
            "Proximal Policy Optimization — tuned for noisy finance: lower LR, "
            "larger batches, entropy decay, anti-churn reward wrappers at train time."
        ),
        "library": "stable-baselines3",
        "default_hyperparams": {
            "n_steps": 4096,
            "ent_coef": 0.01,
            "learning_rate": 3e-5,
            "batch_size": 512,
            "n_epochs": 15,
            "clip_range": 0.1,
            "gae_lambda": 0.99,
            "total_timesteps": 400_000,
            "cooldown_days": 5,
            "trade_penalty": 0.001,
            "turnover_penalty": 0.002,
            "action_smooth": 0.9,
            "max_position_change": 0.10,
            "entropy_decay_final": 0.0001,
            "reward_mode": "alpha_relative",
            "curriculum_phases": [
                {"start": "2020-01-01", "end": "2021-12-31"},
                {"start": "2022-01-01", "end": "2022-12-31"},
                {"start": "2023-01-01", "end": "2023-12-31"},
            ],
        },
    },
    "a2c": {
        "name": "A2C",
        "description": "Advantage Actor-Critic. Faster training, lower sample efficiency.",
        "library": "stable-baselines3",
        "default_hyperparams": {
            "n_steps": 5,
            "ent_coef": 0.01,
            "learning_rate": 0.0007,
            "total_timesteps": 200_000,
        },
    },
    "ddpg": {
        "name": "DDPG",
        "description": "Deep Deterministic Policy Gradient. Continuous action spaces.",
        "library": "stable-baselines3",
        "default_hyperparams": {
            "batch_size": 128,
            "buffer_size": 50000,
            "learning_rate": 0.001,
            "total_timesteps": 200_000,
        },
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
            "total_timesteps": 200_000,
        },
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
            "total_timesteps": 200_000,
        },
    },
}

SUPPORTED_DATA_SOURCES = {
    "yahoo": {
        "name": "Yahoo Finance",
        "description": "Free, no API key required.",
        "requires_key": False,
    },
    "alpaca": {
        "name": "Alpaca Markets",
        "description": "Real-time and historical. Requires API key.",
        "requires_key": True,
    },
    "mt5": {
        "name": "MT5 Demo Gateway",
        "description": "Candles via MT5 gateway API (/candles).",
        "requires_key": True,
    },
}


def get_agents() -> Dict[str, Any]:
    return SUPPORTED_AGENTS


def get_tickers() -> List[str]:
    """Deprecated: use get_tickers_by_source() instead"""
    return DOW_30_TICKER


EGX_30_TICKERS = [
    "COMI.CA",
    "HRHO.CA",
    "ETEL.CA",
    "TMGH.CA",
    "EFIH.CA",
    "EKHO.CA",
    "PHDC.CA",
    "OCDI.CA",
    "ABUK.CA",
    "ORAS.CA",
]

EGX_30_BENCHMARK = "^CASE30"


def get_tickers_by_source() -> Dict[str, List[str]]:
    mt5_tickers = [
        "EURUSD", "GBPUSD", "USDJPY", "AUDUSD", "USDCAD", "NZDUSD",
        "EURJPY", "GBPJPY", "EURGBP", "EURCAD", "AUDNZD", "AUDCAD",
        "AUDJPY", "CADJPY", "CHFUSD", "EURAUD", "EURCHF", "GBPAUD",
        "GBPCAD", "GBPCHF", "NZDJPY", "USDCHF",
        "XAUUSD", "XAGUSD", "XPTUSD", "XPDUSD",
        "BRENT", "WTIUSD",
        "SP500", "USTEC", "DAX", "FTSE100", "CAC40", "NIKKEI", "HSI", "ASX200",
        "BTCUSD", "ETHUSD", "LTCUSD", "XRPUSD", "ADAUSD", "DOGEUSD",
        "BTCUSDm", "ETHUSDm",
        "AAPL", "MSFT", "GOOGL", "AMZN", "TSLA", "NVDA", "META", "NFLX",
    ]
    yahoo_tickers = list(
        dict.fromkeys(
            DOW_30_TICKER
            + ["SPY", "QQQ", "XLF", "XLE", "IWM", "VTI", "GLD", "TLT"]
        )
    )
    return {
        "yahoo": yahoo_tickers,
        "yahoo_egx": EGX_30_TICKERS,
        "alpaca": DOW_30_TICKER,
        "mt5": mt5_tickers,
    }


def get_indicators(include_rl_extras: bool = False) -> List[str]:
    if include_rl_extras:
        from app.services.rl_features import RL_ALPHA_FEATURES
        return INDICATORS + [i for i in RL_ALPHA_FEATURES if i not in INDICATORS]
    return list(INDICATORS)


def get_data_sources() -> Dict[str, Any]:
    return SUPPORTED_DATA_SOURCES


def get_finrl_status() -> Dict[str, Any]:
    _probe_finrl()
    return {
        "available": FINRL_AVAILABLE,
        "error": _import_error if not FINRL_AVAILABLE else None,
    }
