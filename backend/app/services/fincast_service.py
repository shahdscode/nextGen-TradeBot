"""
FinCast forecasting service.

Wraps the finetuned FinCast foundation model (TimesFM-derived MoE decoder +
LoRA/DoRA adapter) that lives under backend/models/. The 3.7 GB base model is
loaded ONCE and cached at module level (lazy on first call) — this is designed
to run inside a Celery worker so the API process never blocks on the load.

Pipeline: recent close series → FinCast → 60-step horizon forecast with quantile
band (q10..q90), denormalised back to price space.

The bundled adapter ("5min_adapter_2_continued_best") was finetuned on 5-minute
bars, so the data feed is 5-minute (the Celery task fetches intraday 5m bars).
The model's frequency token is the high-frequency category (0), which covers
sub-daily data. Horizon is 60 steps → 60 x 5min = 5 trading hours ahead.
"""
from __future__ import annotations

import json
import logging
import os
import sys
import tempfile
from pathlib import Path
from types import SimpleNamespace
from typing import Any, Dict, List, Optional

import numpy as np

logger = logging.getLogger(__name__)

# ── Paths ────────────────────────────────────────────────────────────────────
_BACKEND_DIR = Path(__file__).resolve().parents[2]          # .../backend
_FINCAST_SRC = _BACKEND_DIR / "fincast"                     # ported ffm/tools/st_moe_pytorch
_MODELS_DIR  = _BACKEND_DIR / "models"
_BASE_MODEL  = _MODELS_DIR / "v1.pth"                       # symlink → real .pth
_ADAPTER_DIR = _MODELS_DIR / "5min_adapter_2_continued_best"

CONTEXT_LEN = 128
HORIZON_LEN = 60
# DEFAULT_QUANTILES in ffm_base = (0.1..0.9); full_all channels: 0=mean, 1..9=quantiles
_Q10_CH, _Q90_CH = 1, 9

_MODEL_CACHE: Dict[str, Any] = {}   # {"inf": FinCast_Inference} — loaded once


def available() -> Dict[str, Any]:
    """Report whether the FinCast weights + ported code are present."""
    return {
        "code":    _FINCAST_SRC.exists(),
        "base":    _BASE_MODEL.exists(),
        "adapter": (_ADAPTER_DIR / "adapter_config.json").exists(),
        "ready":   _FINCAST_SRC.exists() and _BASE_MODEL.exists()
                   and (_ADAPTER_DIR / "adapter_config.json").exists(),
    }


def _load_model():
    """Lazy-load base model + LoRA adapter once; cache the FinCast_Inference."""
    if "inf" in _MODEL_CACHE:
        return _MODEL_CACHE["inf"]

    av = available()
    if not av["ready"]:
        raise RuntimeError(f"FinCast not available: {av}")

    if str(_FINCAST_SRC) not in sys.path:
        sys.path.insert(0, str(_FINCAST_SRC))

    import torch
    from tools.inference_utils import FinCast_Inference
    from peft import LoraConfig, PeftModel

    # A tiny placeholder CSV just to satisfy the constructor; real data is swapped
    # per request via _set_series().
    tmp = tempfile.NamedTemporaryFile("w", suffix=".csv", delete=False)
    tmp.write("date,close\n")
    for i in range(CONTEXT_LEN + 5):
        tmp.write(f"2024-01-{(i % 28) + 1:02d},{100 + i}\n")
    tmp.close()

    cfg = SimpleNamespace(
        backend="gpu" if torch.cuda.is_available() else "cpu",
        model_path=str(_BASE_MODEL), model_version="v1",
        data_path=tmp.name, data_frequency="5min",   # 5-minute bars (token cat 0)
        context_len=CONTEXT_LEN, horizon_len=HORIZON_LEN,
        columns_target=["close"], batch_size=1, forecast_mode="mean",
        save_output=False, save_output_path="", plt_outputs=False,
        plt_quantiles=[1, 9], series_norm=True, dropna=True,
        all_data=False,   # last window only → one fast forecast per call
    )
    logger.info("FinCast: loading base model (%s)…", _BASE_MODEL)
    inf = FinCast_Inference(cfg)
    base = inf.model_api._model

    full = json.load(open(_ADAPTER_DIR / "adapter_config.json"))
    keep = {"r", "lora_alpha", "target_modules", "lora_dropout", "bias",
            "task_type", "inference_mode", "init_lora_weights", "use_rslora"}
    peft_cfg = LoraConfig(**{k: v for k, v in full.items() if k in keep})
    model = PeftModel.from_pretrained(base, str(_ADAPTER_DIR), config=peft_cfg)
    model.eval()
    inf.model_api._model = model
    logger.info("FinCast: base + adapter ready.")

    _MODEL_CACHE["inf"] = inf
    return inf


def _set_series(inf, closes: List[float], sliding: bool = False):
    """Rebuild the inference dataset for a fresh close series (model stays cached).
    sliding=False → last window only (one forecast); True → all sliding windows."""
    sys.path.insert(0, str(_FINCAST_SRC)) if str(_FINCAST_SRC) not in sys.path else None
    from data_tools.Inference_dataset import TimeSeriesDataset_SingleCSV_Inference

    tmp = tempfile.NamedTemporaryFile("w", suffix=".csv", delete=False)
    tmp.write("date,close\n")
    # 5-minute timestamps to match the data feed (the model uses the freq token,
    # not the literal timestamps, but keep them consistent with the feed).
    base_ts = np.datetime64("2024-01-01T09:30")
    for i, c in enumerate(closes):
        d = (base_ts + np.timedelta64(5 * i, "m")).astype(str)
        tmp.write(f"{d},{float(c)}\n")
    tmp.close()

    inf.config.data_path = tmp.name
    inf.inference_dataset = TimeSeriesDataset_SingleCSV_Inference(
        csv_path=tmp.name, context_length=inf.config.context_len,
        freq_type=inf.inference_freq, columns=inf.config.columns_target,
        first_c_date=True, series_norm=inf.config.series_norm,
        dropna=getattr(inf.config, "dropna", True),
        sliding_windows=sliding, return_meta=True,
    )
    return tmp.name


def forecast_windows(closes: List[float]) -> Dict[str, Any]:
    """
    Sliding-window forecasts over a full close series (for backtesting).

    Mirrors the FinCast notebook's load_forecasts: one forecast per window, where
    the representative value is the forecast at the END of the horizon (last
    step), with q10/q90 from that step — denormalised to price space with the
    global series mean/std. Window i corresponds to context closes[i:i+CONTEXT_LEN].

    Returns {ok, point[N], q10[N], q90[N], n_windows}.
    """
    closes = [float(c) for c in closes if c is not None and np.isfinite(c)]
    if len(closes) < CONTEXT_LEN + 1:
        return {"ok": False, "message": f"Need >= {CONTEXT_LEN + 1} closes, got {len(closes)}"}

    inf = _load_model()
    # all_data=True → sliding windows over the whole series in one batched pass
    inf.config.all_data = True
    _set_series(inf, closes, sliding=True)
    try:
        mean_all, _mapping, full_all = inf.run_inference(num_workers=0)
    finally:
        inf.config.all_data = False   # restore single-window default for forecast()
    mean_all = np.asarray(mean_all)   # [N, H]
    full_all = np.asarray(full_all)   # [N, H, 1+Q]

    mu, sd = float(np.mean(closes)), float(np.std(closes)) or 1.0
    point = mean_all[:, -1] * sd + mu                 # forecast at horizon end
    q10   = full_all[:, -1, _Q10_CH] * sd + mu
    q90   = full_all[:, -1, _Q90_CH] * sd + mu
    return {
        "ok": True, "n_windows": int(len(point)),
        "point": [float(x) for x in point],
        "q10":   [float(x) for x in q10],
        "q90":   [float(x) for x in q90],
    }


def forecast(closes: List[float]) -> Dict[str, Any]:
    """
    Forecast the next HORIZON_LEN steps from a close-price series.

    closes : list of recent closes (>= CONTEXT_LEN). Only the last window is used.
    Returns {ok, horizon, mean[], q10[], q90[], last_close, model}.
    """
    closes = [float(c) for c in closes if c is not None and np.isfinite(c)]
    if len(closes) < CONTEXT_LEN:
        return {"ok": False, "message": f"Need >= {CONTEXT_LEN} closes, got {len(closes)}"}

    inf = _load_model()
    _set_series(inf, closes)
    mean_all, _mapping, full_all = inf.run_inference(num_workers=0)
    mean_all = np.asarray(mean_all)
    full_all = np.asarray(full_all)

    # Horizon-only slice of the last (most recent) window
    H = HORIZON_LEN
    mean_n = mean_all[-1][-H:]
    q10_n  = full_all[-1][-H:, _Q10_CH]
    q90_n  = full_all[-1][-H:, _Q90_CH]

    # Denormalise: series_norm z-scored by the series stats → invert with them.
    mu, sd = float(np.mean(closes)), float(np.std(closes)) or 1.0
    to_price = lambda a: (np.asarray(a) * sd + mu)

    return {
        "ok": True,
        "horizon": H,
        "last_close": round(closes[-1], 4),
        # recent input bars (same 5-min scale as the forecast) for charting
        "history": [round(float(c), 4) for c in closes[-40:]],
        "mean": [round(float(x), 4) for x in to_price(mean_n)],
        "q10":  [round(float(x), 4) for x in to_price(q10_n)],
        "q90":  [round(float(x), 4) for x in to_price(q90_n)],
        "model": "fincast_v1+5min_adapter",
    }
