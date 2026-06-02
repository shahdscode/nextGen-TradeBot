"""Per-source ticker catalogs and validation for the Data download UI."""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, List, Set

from app.services.walk_forward import RECOMMENDED_TICKERS

DATA_SOURCES = ("yahoo", "yahoo_egx", "alpaca", "mt5")

DOW_30_TICKER = [
    "AXP", "AMGN", "AAPL", "BA", "CAT", "CSCO", "CVX", "GS",
    "HD", "HON", "IBM", "INTC", "JNJ", "JPM", "KO", "MCD",
    "MMM", "MRK", "MSFT", "NKE", "PG", "TRV", "UNH", "CRM",
    "VZ", "V", "WBA", "WMT", "DIS", "DOW",
]

EGX_30_TICKERS = [
    # Full EGX 30 constituents supported by Yahoo Finance (.CA suffix)
    "COMI.CA",  # CIB — Commercial International Bank
    "HRHO.CA",  # EFG Hermes
    "ETEL.CA",  # Telecom Egypt
    "TMGH.CA",  # TMG Holding
    "EFIH.CA",  # EFG Hermes International Holdings
    "AMOC.CA",  # Alexandria Mineral Oils Company
    "ABUK.CA",  # Abu Kir Fertilizers
    "PHDC.CA",  # Palm Hills Developments
    "SWDY.CA",  # El Sewedy Electric
    "ORWE.CA",  # Oriental Weavers
    "CLHO.CA",  # Cleopatra Hospital Group
    "ESRS.CA",  # Ezz Steel
    "MNHD.CA",  # Medinet Nasr Housing
    "FWRY.CA",  # Fawry
    "EGTS.CA",  # Egyptian Gas
    "EAST.CA",  # Eastern Company
    "OCDI.CA",  # Orascom Development Egypt
    "ACGC.CA",  # Arab Cotton Ginning
    "ISPH.CA",  # Integrated Diagnostics Holdings
    "GBCO.CA",  # GB Auto
    "MFPC.CA",  # Misr Fertilizers Production Company
    "BTFH.CA",  # Biotechnology
    # Removed: GTHE.CA, ABIS.CA, BICO.CA, MNHD.CA — delisted (no data on Yahoo Finance)
]

EGX_30_BENCHMARK = "^CASE30"

YAHOO_ETFS = [
    "SPY", "QQQ", "DIA", "IWM", "VTI", "VOO", "VUG", "VTV", "VB", "VO",
    "VEA", "VWO", "EEM", "EFA", "XLF", "XLE", "XLK", "XLV", "XLI", "XLY",
    "XLP", "XLU", "XLB", "XLRE", "XLC", "GLD", "SLV", "TLT", "IEF", "SHY",
    "HYG", "LQD", "VNQ", "ARKK", "SMH", "SOXX", "IBB", "KRE", "XBI", "USO",
    "UNG", "GDX", "GDXJ", "EWJ", "FXI", "EWZ",
]

YAHOO_INDICES = [
    "^GSPC",   # S&P 500
    "^DJI",    # Dow Jones
    "^IXIC",   # Nasdaq Composite
    "^RUT",    # Russell 2000
    "^VIX",    # Volatility
    "^NYA",    # NYSE Composite
]

_DATA_DIR = Path(__file__).resolve().parent / "data"
_SP500_PATH = _DATA_DIR / "sp500_tickers.json"


def _load_sp500() -> List[str]:
    if not _SP500_PATH.exists():
        return []
    try:
        data = json.loads(_SP500_PATH.read_text(encoding="utf-8"))
        if isinstance(data, list):
            return sorted({str(t).strip().upper() for t in data if t})
    except (json.JSONDecodeError, OSError):
        pass
    return []


def get_yahoo_us_tickers() -> List[str]:
    """US equities, ETFs, and indices fetchable via yfinance (Yahoo Finance)."""
    sp500 = _load_sp500()
    merged = (
        RECOMMENDED_TICKERS
        + DOW_30_TICKER
        + YAHOO_ETFS
        + YAHOO_INDICES
        + sp500
    )
    return sorted(dict.fromkeys(t.strip().upper() for t in merged if t))


def get_yahoo_egx_tickers() -> List[str]:
    return list(EGX_30_TICKERS)


def get_yahoo_catalog() -> Dict[str, Any]:
    """Grouped catalog for the Data page (US Yahoo / yfinance)."""
    sp500 = _load_sp500()
    sp500_only = [t for t in sp500 if t not in DOW_30_TICKER and t not in RECOMMENDED_TICKERS]

    groups = [
        {
            "id": "recommended",
            "label": "Research preset (recommended)",
            "tickers": [t for t in RECOMMENDED_TICKERS if t in get_yahoo_us_tickers()],
        },
        {
            "id": "dow30",
            "label": "Dow Jones 30",
            "tickers": DOW_30_TICKER,
        },
        {
            "id": "etfs",
            "label": "ETFs & funds",
            "tickers": YAHOO_ETFS,
        },
        {
            "id": "indices",
            "label": "Indices (^ prefix)",
            "tickers": YAHOO_INDICES,
        },
    ]
    if sp500_only:
        groups.append({
            "id": "sp500",
            "label": f"S&P 500 ({len(sp500)} symbols)",
            "tickers": sp500_only,
        })

    tickers = get_yahoo_us_tickers()
    return {
        "tickers": tickers,
        "count": len(tickers),
        "groups": groups,
        "custom_allowed": False,
        "note": (
            "US symbols from S&P 500, ETFs, and indices (Yahoo Finance / yfinance). "
            "Only listed symbols can be downloaded for this source."
        ),
    }


def get_yahoo_egx_catalog() -> Dict[str, Any]:
    tickers = get_yahoo_egx_tickers()
    return {
        "tickers": tickers,
        "count": len(tickers),
        "groups": [{"id": "egx", "label": "EGX (Egypt)", "tickers": tickers}],
        "custom_allowed": False,
        "note": "Egyptian exchange symbols use the .CA suffix on Yahoo Finance.",
    }


# ── Alpaca (US equities supported by this project's Alpaca/Yahoo path) ────────

def get_alpaca_tickers() -> List[str]:
    return sorted(dict.fromkeys(DOW_30_TICKER + RECOMMENDED_TICKERS))


def get_alpaca_catalog() -> Dict[str, Any]:
    dow = [t for t in DOW_30_TICKER]
    extra = [t for t in RECOMMENDED_TICKERS if t not in dow]
    tickers = get_alpaca_tickers()
    return {
        "tickers": tickers,
        "count": len(tickers),
        "groups": [
            {"id": "dow30", "label": "Dow Jones 30", "tickers": dow},
            {"id": "research", "label": "Research preset (also on Dow)", "tickers": extra},
        ],
        "custom_allowed": False,
        "note": "US symbols tradeable via Alpaca in this app (Dow 30 + research preset).",
    }


# ── MT5 gateway symbols ───────────────────────────────────────────────────────

MT5_FOREX = [
    "EURUSD", "GBPUSD", "USDJPY", "AUDUSD", "USDCAD", "NZDUSD",
    "EURJPY", "GBPJPY", "EURGBP", "EURCAD", "AUDNZD", "AUDCAD",
    "AUDJPY", "CADJPY", "EURAUD", "EURCHF", "GBPAUD", "GBPCAD",
    "GBPCHF", "NZDJPY", "USDCHF",
]

MT5_METALS_ENERGY = [
    "XAUUSD", "XAGUSD", "XPTUSD", "XPDUSD", "BRENT", "WTIUSD",
]

MT5_INDICES = [
    "SP500", "USTEC", "DAX", "FTSE100", "CAC40", "NIKKEI", "HSI", "ASX200",
]

MT5_CRYPTO = [
    "BTCUSD", "ETHUSD", "LTCUSD", "XRPUSD", "ADAUSD", "DOGEUSD",
    "BTCUSDm", "ETHUSDm",
]

MT5_US_CFD_STOCKS = [
    "AAPL", "MSFT", "GOOGL", "AMZN", "TSLA", "NVDA", "META", "NFLX",
]


def get_mt5_tickers() -> List[str]:
    merged = MT5_FOREX + MT5_METALS_ENERGY + MT5_INDICES + MT5_CRYPTO + MT5_US_CFD_STOCKS
    return sorted(dict.fromkeys(merged))


def get_mt5_catalog() -> Dict[str, Any]:
    return {
        "tickers": get_mt5_tickers(),
        "count": len(get_mt5_tickers()),
        "groups": [
            {"id": "forex", "label": "Forex", "tickers": MT5_FOREX},
            {"id": "metals", "label": "Metals & energy", "tickers": MT5_METALS_ENERGY},
            {"id": "indices", "label": "Indices", "tickers": MT5_INDICES},
            {"id": "crypto", "label": "Crypto", "tickers": MT5_CRYPTO},
            {"id": "stocks", "label": "US CFD stocks", "tickers": MT5_US_CFD_STOCKS},
        ],
        "custom_allowed": False,
        "note": "Symbols must match your MT5 gateway (suffix m may be added automatically).",
    }


def _catalog_for_source(source: str) -> Dict[str, Any]:
    key = (source or "yahoo").lower().strip()
    if key == "yahoo":
        return get_yahoo_catalog()
    if key == "yahoo_egx":
        return get_yahoo_egx_catalog()
    if key == "alpaca":
        return get_alpaca_catalog()
    if key == "mt5":
        return get_mt5_catalog()
    return {"tickers": [], "count": 0, "groups": [], "custom_allowed": False, "note": ""}


def get_allowed_tickers(source: str) -> List[str]:
    return _catalog_for_source(source).get("tickers") or []


def get_allowed_ticker_set(source: str) -> Set[str]:
    return set(get_allowed_tickers(source))


def normalize_ticker(source: str, ticker: str) -> str:
    t = (ticker or "").strip()
    if not t:
        return ""
    if (source or "").lower() == "yahoo_egx":
        return t.upper()
    return t.upper()


def validate_tickers_for_source(source: str, tickers: List[str]) -> Dict[str, Any]:
    """
    Return validation result for a data-source + ticker list.
    Invalid = not in that source's catalog (strict whitelist per source).
    """
    key = (source or "yahoo").lower().strip()
    if key not in DATA_SOURCES:
        return {
            "valid": False,
            "source": key,
            "invalid": list(tickers),
            "allowed_count": 0,
            "message": f"Unknown data source '{source}'. Use: {', '.join(DATA_SOURCES)}.",
        }

    allowed = get_allowed_ticker_set(key)
    normalized: List[str] = []
    invalid: List[str] = []
    seen: Set[str] = set()

    for raw in tickers:
        t = normalize_ticker(key, raw)
        if not t or t in seen:
            continue
        seen.add(t)
        normalized.append(t)
        if t not in allowed:
            invalid.append(t)

    source_label = {
        "yahoo": "Yahoo Finance (US)",
        "yahoo_egx": "Yahoo Finance (EGX)",
        "alpaca": "Alpaca Markets",
        "mt5": "MT5 Demo Gateway",
    }.get(key, key)

    if invalid:
        message = (
            f"Not available for {source_label}: {', '.join(invalid)}. "
            f"Choose symbols from this source's ticker list only."
        )
    else:
        message = ""

    return {
        "valid": len(invalid) == 0 and len(normalized) > 0,
        "source": key,
        "tickers": normalized,
        "invalid": invalid,
        "allowed_count": len(allowed),
        "message": message,
    }


def get_all_catalogs() -> Dict[str, Any]:
    return {
        "yahoo": get_yahoo_catalog(),
        "yahoo_egx": get_yahoo_egx_catalog(),
        "alpaca": get_alpaca_catalog(),
        "mt5": get_mt5_catalog(),
    }


def get_tickers_by_source() -> Dict[str, List[str]]:
    return {src: get_allowed_tickers(src) for src in DATA_SOURCES}
