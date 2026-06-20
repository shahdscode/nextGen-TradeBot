"""
Celery task for FinCast forecasts.

The 3.7 GB model is loaded once per worker (cached in fincast_service) on the
first forecast, then reused — so the API never blocks on the load and repeat
forecasts are sub-second.
"""
from datetime import datetime

from app.celery_app import celery_app
from app.database import SessionLocal, Job

CONTEXT_MIN = 128


def _fetch_closes(ticker: str, market: str) -> list:
    """Recent 5-MINUTE closes for a ticker (>= CONTEXT_MIN). The bundled adapter
    is finetuned on 5-min bars, so the feed is intraday. Yahoo caps 5m history at
    60 days; we try widening windows. Returns [] if intraday data is unavailable
    (common for EGX .CA on Yahoo) — the caller then errors clearly."""
    ticker = ticker.strip().upper()
    try:
        import yfinance as yf
        for period in ("5d", "1mo", "3mo"):
            h = yf.download(ticker, period=period, interval="5m",
                            progress=False, auto_adjust=True)
            if h is not None and not h.empty:
                col = h["Close"]
                closes = (col.iloc[:, 0] if hasattr(col, "columns") else col).dropna().tolist()
                if len(closes) >= CONTEXT_MIN:
                    return closes
    except Exception:
        pass
    return []


def _fetch_closes_max(ticker: str) -> list:
    """Longest available 5-minute close series (Yahoo caps 5m at ~60 days).
    Used for backtests, which want as many windows as possible."""
    ticker = ticker.strip().upper()
    try:
        import yfinance as yf
        h = yf.download(ticker, period="60d", interval="5m",
                        progress=False, auto_adjust=True)
        if h is not None and not h.empty:
            col = h["Close"]
            return (col.iloc[:, 0] if hasattr(col, "columns") else col).dropna().tolist()
    except Exception:
        pass
    return []


@celery_app.task(bind=True, name="fincast_tasks.backtest")
def fincast_backtest_task(self, job_id: str, ticker: str, market: str = "us",
                          test_windows: int = 2000):
    from app.services.fincast_backtest_service import run_fincast_backtest
    db = SessionLocal()
    try:
        job = db.query(Job).filter(Job.id == job_id).first()
        if job:
            job.status = "running"; job.updated_at = datetime.utcnow(); db.commit()

        closes = _fetch_closes_max(ticker)
        if len(closes) < CONTEXT_MIN + 70:
            raise ValueError(
                f"Not enough 5-minute history for {ticker} ({len(closes)} bars). "
                f"Intraday data may be unavailable on Yahoo (common for EGX .CA).")

        result = run_fincast_backtest(closes, test_windows=test_windows)
        result["ticker"] = ticker.upper(); result["market"] = market

        job = db.query(Job).filter(Job.id == job_id).first()
        job.status = "done" if result.get("ok") else "failed"
        job.meta = result
        if not result.get("ok"):
            job.error = result.get("message")
        job.updated_at = datetime.utcnow(); db.commit()
        return {"status": job.status}
    except Exception as e:
        job = db.query(Job).filter(Job.id == job_id).first()
        if job:
            job.status = "failed"; job.error = str(e)
            job.updated_at = datetime.utcnow(); db.commit()
        raise
    finally:
        db.close()


@celery_app.task(bind=True, name="fincast_tasks.forecast")
def fincast_forecast_task(self, job_id: str, ticker: str, market: str = "us"):
    from app.services import fincast_service
    db = SessionLocal()
    try:
        job = db.query(Job).filter(Job.id == job_id).first()
        if job:
            job.status = "running"; job.updated_at = datetime.utcnow(); db.commit()

        closes = _fetch_closes(ticker, market)
        if len(closes) < CONTEXT_MIN:
            raise ValueError(
                f"Not enough 5-minute history for {ticker} ({len(closes)} bars, "
                f"need >= {CONTEXT_MIN}). Intraday data may be unavailable on Yahoo "
                f"for this symbol (common for EGX .CA).")

        result = fincast_service.forecast(closes)
        result["ticker"] = ticker.upper()
        result["market"] = market

        job = db.query(Job).filter(Job.id == job_id).first()
        job.status = "done" if result.get("ok") else "failed"
        job.meta = result
        if not result.get("ok"):
            job.error = result.get("message")
        job.updated_at = datetime.utcnow()
        db.commit()
        return {"status": job.status}
    except Exception as e:
        job = db.query(Job).filter(Job.id == job_id).first()
        if job:
            job.status = "failed"; job.error = str(e)
            job.updated_at = datetime.utcnow(); db.commit()
        raise
    finally:
        db.close()
