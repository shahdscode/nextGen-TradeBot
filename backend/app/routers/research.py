from fastapi import APIRouter

from typing import List, Optional

from pydantic import BaseModel

from app.services.trading_config import transaction_costs_summary
from app.services.walk_forward import RECOMMENDED_TICKERS, list_presets
from app.services.rl_training import RLTrainingConfig
from app.services import pipeline_service
from app import finrl_wrapper

router = APIRouter(prefix="/research", tags=["research"])


@router.get("/walk-forward-presets")
def walk_forward_presets():
    return {"presets": list_presets(), "recommended_tickers": RECOMMENDED_TICKERS}


@router.get("/trading-costs")
def trading_costs():
    return transaction_costs_summary()


class PipelineValidateRequest(BaseModel):
    data_job_id: str


class XgbBatchRequest(BaseModel):
    data_job_id: str
    tickers: Optional[List[str]] = None
    n_trials: int = 25


@router.post("/alpha-pipeline/validate")
def alpha_pipeline_validate(req: PipelineValidateRequest):
    return pipeline_service.validate_data_job(req.data_job_id)


@router.get("/alpha-pipeline/status/{data_job_id}")
def alpha_pipeline_status(data_job_id: str):
    return pipeline_service.pipeline_status(data_job_id)


@router.post("/alpha-pipeline/xgb-batch")
def alpha_pipeline_xgb_batch(req: XgbBatchRequest):
    return pipeline_service.queue_xgb_batch(req.data_job_id, req.tickers, req.n_trials)


@router.get("/ppo-training-guide")
def ppo_training_guide():
    """Document PPO alpha stack for UI / operators."""
    from app.services.rl_features import RL_ALPHA_FEATURES

    ppo = finrl_wrapper.SUPPORTED_AGENTS.get("ppo", {})
    return {
        "summary": (
            "Alpha-first PPO: reward = return − S&P500 − underperform_best_baseline; "
            "28+ state features; ML confidence; 400k timesteps; optional curriculum phases."
        ),
        "default_hyperparams": ppo.get("default_hyperparams", {}),
        "rl_wrappers": RLTrainingConfig().__dict__,
        "alpha_features": RL_ALPHA_FEATURES,
        "hybrid_flow": [
            "1. Download Yahoo data (multi-ticker recommended)",
            "2. Train XGBoost per ticker on /ml-train",
            "3. Train PPO with xgb_run_id (+ optional lstm_run_id) in hyperparams",
            "4. Backtest — uses same alpha columns saved in run metrics",
        ],
        "retrain_required": "Re-train PPO after feature/reward changes; old .zip lacks new state dims.",
    }
