"""
Safe bridge for FinRL metadata.

FinRL has optional commercial dependencies (wrds, pyfolio, alpaca_trade_api)
that are imported at the top of its __init__.py.  We mock those with MagicMock
before importing so the rest of the library loads correctly.

On macOS/Anaconda, stable-baselines3 triggers a Keras → pyarrow segfault
(exit 139) at import time.  This does NOT affect the project .venv (Python 3.11)
which has a clean environment without Anaconda's Keras.  The probe therefore
tries a direct in-process import first; it only falls back to subprocess probing
(using sys.executable) as a last resort.
"""
from __future__ import annotations

import os
import subprocess
import sys
from typing import List, Dict, Any


def _mock_finrl_optional_deps() -> None:
    """
    Inject MagicMock stubs for FinRL's optional commercial / unavailable deps
    so that ``import finrl`` succeeds without needing wrds, pyfolio, etc.
    Must be called BEFORE any ``import finrl`` statement.
    """
    from unittest.mock import MagicMock
    for name in ("wrds", "pyfolio", "alpaca_trade_api"):
        if name not in sys.modules:
            sys.modules[name] = MagicMock()

from app.ticker_catalog import (
    DOW_30_TICKER,
    EGX_30_BENCHMARK,
    EGX_30_TICKERS,
    get_all_catalogs,
    get_tickers_by_source as _catalog_tickers_by_source,
)
INDICATORS = [
    "macd", "boll_ub", "boll_lb", "rsi_30", "cci_30",
    "dx_30", "close_30_sma", "close_60_sma",
]

FINRL_AVAILABLE = False
_import_error = ""
_probe_done = False


def _probe_finrl() -> None:
    """
    Detect FinRL availability.

    Strategy (in order):
    1. Direct in-process import with optional-dep mocks — fast, works in the
       project .venv (Python 3.11) which has a clean environment.
    2. Subprocess probe using sys.executable — fallback for environments where
       the direct import would crash (e.g. Anaconda base with Keras/pyarrow
       conflict).  Only runs when FINRL_ENABLE=1 is set.
    """
    global FINRL_AVAILABLE, _import_error, _probe_done
    if _probe_done:
        return
    _probe_done = True

    # ── Strategy 1: direct import (works in .venv) ─────────────────────────
    try:
        _mock_finrl_optional_deps()
        from finrl.meta.preprocessor.preprocessors import data_split          # noqa: F401
        from finrl.meta.env_stock_trading.env_stocktrading import StockTradingEnv  # noqa: F401
        from finrl.agents.stablebaselines3.models import DRLAgent             # noqa: F401
        from stable_baselines3 import PPO, A2C, DDPG, TD3, SAC               # noqa: F401
        FINRL_AVAILABLE = True
        _import_error = ""
        return
    except Exception as e:
        direct_err = str(e)

    # ── Strategy 2: subprocess probe (Anaconda fallback) ───────────────────
    if os.environ.get("FINRL_ENABLE", "").lower() not in ("1", "true", "yes"):
        _import_error = (
            f"Direct FinRL import failed ({direct_err}). "
            "Set FINRL_ENABLE=1 to try subprocess probe, "
            "or activate the project .venv which has finrl installed."
        )
        return

    probe_cmd = (
        "import sys; from unittest.mock import MagicMock; "
        "[sys.modules.__setitem__(m, MagicMock()) for m in ('wrds','pyfolio','alpaca_trade_api') "
        "if m not in sys.modules]; "
        "from finrl.meta.env_stock_trading.env_stocktrading import StockTradingEnv; "
        "from stable_baselines3 import PPO; print('ok')"
    )
    try:
        proc = subprocess.run(
            [sys.executable, "-c", probe_cmd],
            capture_output=True, text=True, timeout=60,
        )
        if proc.returncode == 0:
            FINRL_AVAILABLE = True
            _import_error = ""
        else:
            err = (proc.stderr or proc.stdout or "").strip()
            _import_error = err or f"finrl probe exited {proc.returncode}"
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
        "name": "Yahoo Finance (US)",
        "description": "Free, no API key required.",
        "requires_key": False,
    },
    "yahoo_egx": {
        "name": "Yahoo Finance (EGX)",
        "description": "Egyptian stocks via Yahoo (.CA suffix).",
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


def get_tickers_by_source() -> Dict[str, List[str]]:
    return _catalog_tickers_by_source()


def get_ticker_catalogs() -> Dict[str, Any]:
    return get_all_catalogs()


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


# ── Auto-probe at module load ──────────────────────────────────────────────────
# Safe: strategy 1 (direct import) never segfaults — it only raises Python
# exceptions.  This sets FINRL_AVAILABLE correctly for train_service.py's
# `if FINRL_AVAILABLE:` guard without requiring a manual env-var.
_probe_finrl()
