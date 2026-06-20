#!/usr/bin/env python3
"""
FinCast contextual-bandit backtest across several US tickers (for the thesis).
Reuses the cached model across tickers. Writes data/results/fincast_eval.json.
"""
import sys, os, json, time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "backend"))
os.chdir(ROOT / "backend")

import logging
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s", datefmt="%H:%M:%S")
log = logging.getLogger("fincast_eval")

from app.tasks.fincast_tasks import _fetch_closes_max
from app.services.fincast_backtest_service import run_fincast_backtest

TICKERS = os.environ.get("TICKERS", "AAPL,MSFT,NVDA,JPM,KO").split(",")
WINDOWS = int(os.environ.get("WINDOWS", "2000"))
OUT = ROOT / "data" / "results" / os.environ.get("OUT_NAME", "fincast_eval.json")

results = []
for t in TICKERS:
    t0 = time.time()
    log.info("=== %s (windows=%d) ===", t, WINDOWS)
    closes = _fetch_closes_max(t)
    if len(closes) < 200:
        log.warning("  %s: only %d 5m bars — skipping", t, len(closes))
        results.append({"ticker": t, "ok": False, "message": f"{len(closes)} bars"})
        continue
    r = run_fincast_backtest(closes, test_windows=WINDOWS)
    r["ticker"] = t
    r["minutes"] = round((time.time() - t0) / 60, 1)
    results.append(r)
    if r.get("ok"):
        log.info("  %s: OOS %.2f%% | Sharpe %.2f | MaxDD %.2f%% | edge %.2f%% | %d trades | %.1fmin",
                 t, r["oos_return"]*100, r["sharpe_ratio"], r["max_drawdown"]*100,
                 r["edge_vs_buyhold"]*100, r["test_trades"], r["minutes"])
    OUT.write_text(json.dumps(results, indent=2))   # checkpoint after each

OUT.write_text(json.dumps(results, indent=2))
log.info("Saved -> %s", OUT)
ok = [r for r in results if r.get("ok")]
if ok:
    import numpy as np
    print("\n=== FinCast bandit — summary ===")
    print("%-6s %10s %8s %10s %12s %8s" % ("ticker","OOS","Sharpe","MaxDD","edgeVsB&H","trades"))
    for r in ok:
        print("%-6s %9.2f%% %8.2f %9.2f%% %11.2f%% %8d" %
              (r["ticker"], r["oos_return"]*100, r["sharpe_ratio"], r["max_drawdown"]*100,
               r["edge_vs_buyhold"]*100, r["test_trades"]))
    print("mean OOS %.2f%% | mean Sharpe %.2f | beat B&H %d/%d" % (
        np.mean([r["oos_return"] for r in ok])*100, np.mean([r["sharpe_ratio"] for r in ok]),
        sum(r["edge_vs_buyhold"]>0 for r in ok), len(ok)))
