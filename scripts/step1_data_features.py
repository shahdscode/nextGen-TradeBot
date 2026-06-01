#!/usr/bin/env python3
"""
Step 1 — Data Download + Feature Engineering (CLAUDE.md training sequence)

Usage:
    cd /Users/shaahdmaansour/Downloads/nextGen-TradeBot
    source .venv/bin/activate
    python scripts/step1_data_features.py

Outputs:
    data/oof/features_us.csv          — US tickers, 26-feature matrix
    data/oof/features_egx.csv         — EGX tickers, 26-feature matrix
    data/models/fold_definitions.json — shared fold boundaries (ALL models use this)

All models (XGBoost, LSTM, RL) MUST use the fold_definitions.json produced here.
"""

import sys
import json
import logging
import os
from pathlib import Path

# ── Add backend to path ────────────────────────────────────────────────────────
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "backend"))
os.chdir(ROOT / "backend")

import numpy as np
import pandas as pd
import yfinance as yf

from app.services.feature_service import (
    build_features,
    download_vix,
    add_mahalanobis_turbulence,
    add_cross_sectional_rank,
    generate_walk_forward_folds,
    save_fold_definitions,
    verify_no_leakage,
    FEATURE_COLUMNS,
)
from app.ticker_catalog import DOW_30_TICKER, EGX_30_TICKERS

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-8s  %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger("step1")

# ── Config ─────────────────────────────────────────────────────────────────────
START_DATE  = "2019-01-01"   # 1 year warmup before 2020-01-01 for turbulence lookback
END_DATE    = "2024-12-31"
TRAIN_MONTHS = 12
TEST_MONTHS  = 1

OUTPUT_DIR   = ROOT / "data" / "oof"
MODELS_DIR   = ROOT / "data" / "models"
FOLD_PATH    = MODELS_DIR / "fold_definitions.json"

OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
MODELS_DIR.mkdir(parents=True, exist_ok=True)


def download_ohlcv(tickers: list, start: str, end: str, market: str) -> pd.DataFrame:
    """Download OHLCV for a list of tickers, return long-format DataFrame."""
    logger.info("Downloading %d %s tickers (%s → %s)…", len(tickers), market, start, end)
    frames = []
    for tic in tickers:
        try:
            raw = yf.download(tic, start=start, end=end, progress=False, auto_adjust=True)
            if raw.empty:
                logger.warning("  %-12s  no data — skipping", tic)
                continue
            # Flatten MultiIndex columns from yfinance ≥ 0.2.x
            if isinstance(raw.columns, pd.MultiIndex):
                raw.columns = raw.columns.get_level_values(0)
            raw = raw.rename(columns=str.lower).reset_index()
            raw = raw.rename(columns={"index": "date", "Datetime": "date", "Date": "date"})
            raw["tic"] = tic
            # Normalise column names
            for col in ("open", "high", "low", "close", "volume"):
                if col not in raw.columns:
                    raw[col] = 0.0
            frames.append(raw[["date", "tic", "open", "high", "low", "close", "volume"]])
            logger.info("  %-12s  %d rows", tic, len(raw))
        except Exception as exc:
            logger.warning("  %-12s  download error: %s", tic, exc)

    if not frames:
        raise RuntimeError(f"No data downloaded for {market} tickers")

    df = pd.concat(frames, ignore_index=True)
    df["date"] = pd.to_datetime(df["date"]).dt.normalize()
    # Forward-fill zeros within each ticker (exchange holidays)
    df = df.sort_values(["tic", "date"])
    df["close"] = df.groupby("tic")["close"].transform(lambda s: s.replace(0, np.nan).ffill().bfill())
    logger.info("Combined %s DataFrame: %d rows, %d tickers", market, len(df), df["tic"].nunique())
    return df


def build_feature_matrix(raw_df: pd.DataFrame, vix_df: pd.DataFrame | None, market: str) -> pd.DataFrame:
    """Run cross-sectional rank + turbulence + per-ticker build_features, return stacked matrix."""
    logger.info("[%s] Adding cross-sectional momentum rank…", market)
    raw_df = add_cross_sectional_rank(raw_df)

    logger.info("[%s] Computing Mahalanobis turbulence (lookback=252)…", market)
    raw_df = add_mahalanobis_turbulence(raw_df, lookback=252, training_start="2020-01-01")

    tickers = raw_df["tic"].unique().tolist()
    logger.info("[%s] Building per-ticker feature matrices (%d tickers)…", market, len(tickers))

    feat_frames = []
    failed = []
    for tic in tickers:
        try:
            feat = build_features(raw_df, ticker=tic, vix_df=vix_df if market == "us" else None)
            if feat.empty or len(feat) < 60:
                logger.warning("  %-12s  too few rows (%d) — skipping", tic, len(feat))
                continue
            feat_frames.append(feat)
            logger.debug("  %-12s  %d feature rows", tic, len(feat))
        except Exception as exc:
            logger.warning("  %-12s  feature error: %s", tic, exc)
            failed.append(tic)

    if failed:
        logger.warning("[%s] Failed tickers: %s", market, failed)

    stacked = pd.concat(feat_frames, ignore_index=True)
    logger.info("[%s] Feature matrix: %d rows, %d tickers, %d features",
                market, len(stacked), stacked["tic"].nunique(), len(FEATURE_COLUMNS))
    return stacked


def run_leakage_check(feat_df: pd.DataFrame, market: str) -> None:
    """Generate one fold and run verify_no_leakage on it."""
    logger.info("[%s] Running leakage verification…", market)
    folds = generate_walk_forward_folds(feat_df, train_months=TRAIN_MONTHS, test_months=TEST_MONTHS)
    if not folds:
        logger.error("[%s] No folds generated — check data range", market)
        return
    train_df, test_df = folds[0]
    result = verify_no_leakage(train_df, test_df)
    for msg in result["checks"]:
        logger.info("  ✓ %s", msg)
    for msg in result["warnings"]:
        logger.warning("  ⚠ %s", msg)
    for msg in result["violations"]:
        logger.error("  ✗ %s", msg)
    if not result["passed"]:
        raise RuntimeError(f"[{market}] Leakage check FAILED: {result['violations']}")
    logger.info("[%s] %s", market, result["summary"])


def main():
    logger.info("=" * 60)
    logger.info("Step 1 — Data Download + Feature Engineering")
    logger.info("=" * 60)

    # ── 1. Download US data ────────────────────────────────────────────────────
    us_raw = download_ohlcv(DOW_30_TICKER, START_DATE, END_DATE, "us")

    # ── 2. Download VIX ────────────────────────────────────────────────────────
    logger.info("Downloading VIX index…")
    vix_df = download_vix(START_DATE, END_DATE)
    if vix_df.empty:
        logger.warning("VIX unavailable — US tickers will have vix_level=0, vix_zscore=0")

    # ── 3. Build US features ───────────────────────────────────────────────────
    us_features = build_feature_matrix(us_raw, vix_df, "us")
    us_out = OUTPUT_DIR / "features_us.csv"
    us_features.to_csv(us_out, index=False)
    logger.info("US features saved → %s  (%d rows)", us_out, len(us_features))

    # ── 4. Download EGX data ───────────────────────────────────────────────────
    egx_raw = download_ohlcv(EGX_30_TICKERS, START_DATE, END_DATE, "egx")

    # ── 5. Build EGX features (vix=None → 0.0 for both vix columns) ───────────
    egx_features = build_feature_matrix(egx_raw, None, "egx")
    egx_out = OUTPUT_DIR / "features_egx.csv"
    egx_features.to_csv(egx_out, index=False)
    logger.info("EGX features saved → %s  (%d rows)", egx_out, len(egx_features))

    # ── 6. Generate and save shared fold definitions (use US for calendar) ─────
    logger.info("Generating fold definitions from US feature matrix…")
    # Use only training-window rows (2020-2024) to define folds
    fold_df = us_features[us_features["date"] >= "2020-01-01"].copy() if "date" in us_features.columns else us_features.copy()
    folds = generate_walk_forward_folds(fold_df, train_months=TRAIN_MONTHS, test_months=TEST_MONTHS)
    save_fold_definitions(folds, str(FOLD_PATH), train_months=TRAIN_MONTHS, test_months=TEST_MONTHS)
    logger.info("Fold definitions → %s  (%d folds)", FOLD_PATH, len(folds))

    # ── 7. Verify no leakage on each market ───────────────────────────────────
    run_leakage_check(us_features, "us")
    run_leakage_check(egx_features, "egx")

    # ── 8. Summary ─────────────────────────────────────────────────────────────
    logger.info("=" * 60)
    logger.info("Step 1 complete.")
    logger.info("  US features:         %s  (%d rows, %d tickers)",
                us_out, len(us_features), us_features["tic"].nunique() if "tic" in us_features.columns else "?")
    logger.info("  EGX features:        %s  (%d rows, %d tickers)",
                egx_out, len(egx_features), egx_features["tic"].nunique() if "tic" in egx_features.columns else "?")
    logger.info("  Fold definitions:    %s  (%d folds)", FOLD_PATH, len(folds))
    logger.info("Next: run Step 2 (XGBoost OOF) — use fold_definitions.json above")
    logger.info("=" * 60)


if __name__ == "__main__":
    main()
