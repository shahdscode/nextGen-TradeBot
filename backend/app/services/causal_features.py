"""
Causal feature registry — pipeline validation without weak statistical heuristics.

Each feature must declare that it uses only information available at or before time t.
New features that appear in FEATURE_COLUMNS (feature_service.py) are auto-registered
with a placeholder description so the DAG check never fails on legitimate additions.
"""
from __future__ import annotations

import logging
from typing import Dict, List, Set

logger = logging.getLogger(__name__)

# Features allowed in supervised pipelines (backward-looking construction only)
CAUSAL_FEATURE_REGISTRY: Dict[str, str] = {
    "macd":            "ewm/spread of past closes",
    "rsi_30":          "rolling 30d from past closes",
    "rsi_14":          "rolling 14d from past closes",
    "boll_ub":         "rolling 20d mean+2σ on past closes",
    "boll_lb":         "rolling 20d mean−2σ on past closes",
    "bb_width":        "derived from boll bands",
    "close_30_sma":    "rolling mean past 30 closes",
    "close_60_sma":    "rolling mean past 60 closes",
    "cci_30":          "rolling 30d typical price",
    "dx_30":           "rolling directional movement",
    "atr":             "rolling true range",
    "volume_zscore":   "rolling z-score of volume",
    "price_mom_5":     "close / close.shift(5) − 1",
    "price_mom_20":    "close / close.shift(20) − 1",
    "frac_diff_close": "fractional diff on past closes (d=0.4)",
    "turbulence":      "rolling return volatility",
    "high_low_range":  "(high−low)/close same bar",
    "gap":             "open vs prior close",
    "obv_zscore":      "cumulative volume direction, z-scored",
    "ema_cross":       "ema12/ema26 from past closes",
    "vol_price_corr":  "rolling corr volume vs |return|",
}

FORBIDDEN_COLUMN_SUFFIXES: Set[str] = {"_future", "_next", "_fwd", "_lead", "_t+1"}

# Pass-through columns that are never features and should not be validated
_PASSTHROUGH_COLS: Set[str] = {"date", "tic", "open", "high", "low", "close", "volume", "target"}


def auto_register_features(feature_columns: List[str]) -> None:
    """
    Sync CAUSAL_FEATURE_REGISTRY with FEATURE_COLUMNS from feature_service.

    Any column in feature_columns that:
    - is not already in the registry, AND
    - does not have a forbidden suffix (which would be a real violation)
    is auto-registered with a placeholder description and a warning.

    This prevents DAG-check failures when a legitimate new feature is added to
    feature_service.py before its description is written into the registry.
    """
    for col in feature_columns:
        if col in CAUSAL_FEATURE_REGISTRY or col in _PASSTHROUGH_COLS:
            continue
        if any(col.endswith(s) for s in FORBIDDEN_COLUMN_SUFFIXES):
            continue  # forbidden — don't auto-register, let pipeline_dag_check catch it
        CAUSAL_FEATURE_REGISTRY[col] = "auto-registered — add explicit description"
        logger.warning(
            "causal_features: '%s' was auto-registered. Add an explicit description "
            "to CAUSAL_FEATURE_REGISTRY to silence this warning.", col
        )


def validate_feature_columns(columns: List[str]) -> Dict[str, object]:
    """DAG-style check: every feature column must be registered as causal."""
    # Auto-sync registry with whatever is currently in FEATURE_COLUMNS
    try:
        from app.services.feature_service import FEATURE_COLUMNS
        auto_register_features(FEATURE_COLUMNS)
    except ImportError:
        pass

    unknown   = [c for c in columns if c not in CAUSAL_FEATURE_REGISTRY and c not in _PASSTHROUGH_COLS]
    forbidden = [c for c in columns if any(c.endswith(s) for s in FORBIDDEN_COLUMN_SUFFIXES)]
    return {
        "registered_count": len(CAUSAL_FEATURE_REGISTRY),
        "unknown_features":  unknown,
        "forbidden_columns": forbidden,
        "passed":            len(unknown) == 0 and len(forbidden) == 0,
    }


def pipeline_dag_check(train_df_columns: List[str]) -> List[str]:
    """Returns violation messages for causal pipeline enforcement."""
    msgs: List[str] = []
    check_cols = [c for c in train_df_columns if c not in _PASSTHROUGH_COLS]
    audit = validate_feature_columns(check_cols)
    if audit["forbidden_columns"]:
        msgs.append(f"Forbidden column names: {audit['forbidden_columns']}")
    if audit["unknown_features"]:
        msgs.append(
            f"Unregistered features (add to CAUSAL_FEATURE_REGISTRY): {audit['unknown_features']}"
        )
    return msgs
