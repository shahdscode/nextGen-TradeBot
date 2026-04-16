"""
Run this once before a demo to pre-populate the database with
two trained agents (PPO + A2C) and their backtest results.

Usage:
    cd backend
    python scripts/demo_seed.py
    python scripts/demo_seed.py --reset-demo
"""
import argparse
import shutil
import sys, os, uuid
from pathlib import Path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.database import create_tables, SessionLocal, Job, Run, Backtest
from app.services.data_service import download_data
from app.services.train_service import train_agent
from app.services.backtest_service import run_backtest
from app.config import settings
from datetime import datetime

TICKERS = ["AAPL", "MSFT", "GOOGL", "AMZN", "META"]
TRAIN_START = "2020-01-01"
TRAIN_END   = "2022-12-31"
TEST_START  = "2023-01-01"
TEST_END    = "2023-12-31"
ALGOS       = ["ppo", "a2c"]
SEED_TAG    = "demo_seed_v1"

def log(msg):
    print(f"[seed] {msg}")

def _reset_demo_state(db):
    log("Resetting existing demo state...")

    # Clear database records in dependency-safe order.
    db.query(Backtest).delete()
    db.query(Run).delete()
    db.query(Job).delete()
    db.commit()

    # Clear generated artifacts so dashboard shows only fresh demo outputs.
    for root in [settings.data_dir, settings.models_dir, settings.results_dir]:
        root_path = Path(root)
        root_path.mkdir(parents=True, exist_ok=True)
        for child in root_path.iterdir():
            if child.is_dir():
                shutil.rmtree(child, ignore_errors=True)
            elif child.is_file() and child.suffix in {".csv", ".json", ".zip"}:
                try:
                    child.unlink()
                except OSError:
                    pass

    log("Reset complete")


def main(reset_demo: bool = False, timesteps: int = 30000):
    create_tables()
    db = SessionLocal()

    if reset_demo:
        _reset_demo_state(db)

    log("Downloading data...")
    job_id = str(uuid.uuid4())
    job = Job(
        id=job_id,
        type="data",
        status="running",
        created_at=datetime.utcnow(),
        meta={
            "tickers": TICKERS,
            "start_date": TRAIN_START,
            "end_date": TEST_END,
            "source": "yahoo",
            "seed_tag": SEED_TAG,
        },
    )
    db.add(job); db.commit()

    result_path = download_data(job_id, TICKERS, TRAIN_START, TEST_END, "yahoo")
    job.status = "done"; job.result_path = result_path; db.commit()
    log(f"Data saved to {result_path}")

    run_ids = []
    for algo in ALGOS:
        log(f"Training {algo.upper()}...")
        run_id = str(uuid.uuid4())
        run = Run(
            id=run_id,
            data_job_id=job_id,
            algorithm=algo,
            status="running",
            created_at=datetime.utcnow(),
            hyperparams={"total_timesteps": timesteps, "seed_tag": SEED_TAG},
        )
        db.add(run); db.commit()

        result = train_agent(run_id, job_id, algo, {"total_timesteps": timesteps})
        run.status = "done"
        run.model_path = result["model_path"]
        run.metrics_json = result["metrics"]
        db.commit()
        run_ids.append(run_id)
        log(f"{algo.upper()} trained — model at {result['model_path']}")

    for run_id in run_ids:
        run = db.query(Run).filter(Run.id == run_id).first()
        log(f"Backtesting {run.algorithm.upper()}...")
        bt_id = str(uuid.uuid4())
        bt = Backtest(id=bt_id, run_id=run_id, status="running", created_at=datetime.utcnow(),
                      test_start=TEST_START, test_end=TEST_END)
        db.add(bt); db.commit()

        result = run_backtest(bt_id, run_id, TEST_START, TEST_END)
        result["seed_tag"] = SEED_TAG
        bt.status = "done"; bt.result_json = result; db.commit()
        metrics = result.get("metrics", {})
        log(f"{run.algorithm.upper()} backtest done — Sharpe: {metrics.get('sharpe')}, CAGR: {metrics.get('cagr')}")

    if reset_demo:
        total_runs = db.query(Run).count()
        total_backtests = db.query(Backtest).count()
        if total_runs != 2 or total_backtests != 2:
            raise RuntimeError(
                f"Reset demo expected exactly 2 runs and 2 backtests, got runs={total_runs}, backtests={total_backtests}"
            )

    db.close()
    log("Seed complete. Open http://localhost:5173 to view the dashboard.")

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Seed demo data for FinRL dashboard")
    parser.add_argument(
        "--reset-demo",
        action="store_true",
        help="Clear existing jobs/runs/backtests and generated artifacts before seeding",
    )
    parser.add_argument(
        "--timesteps",
        type=int,
        default=30000,
        help="Training timesteps per algorithm (default: 30000)",
    )
    args = parser.parse_args()

    main(reset_demo=args.reset_demo, timesteps=args.timesteps)
