"""Walk-forward date presets for research-grade train/val/test splits."""

WALK_FORWARD_PRESETS = {
    "research_v1": {
        "label": "Research (train 2020–22, val 2023, test 2024–25)",
        "data_download": {"start_date": "2020-01-01", "end_date": "2025-12-31"},
        "train": {"start": "2020-01-01", "end": "2022-12-31"},
        "validate": {"start": "2023-01-01", "end": "2023-12-31"},
        "test": {"start": "2024-01-01", "end": "2025-12-31"},
    },
    "bear_stress": {
        "label": "Bear stress (train incl. 2022, test 2022)",
        "data_download": {"start_date": "2019-01-01", "end_date": "2024-12-31"},
        "train": {"start": "2019-01-01", "end": "2021-12-31"},
        "validate": {"start": "2022-01-01", "end": "2022-12-31"},
        "test": {"start": "2023-01-01", "end": "2024-12-31"},
    },
}

RECOMMENDED_TICKERS = [
    "AAPL", "MSFT", "GOOGL", "AMZN", "NVDA", "META",
    "SPY", "QQQ", "XLF", "XLE", "JPM", "JNJ",
]


def list_presets():
    return WALK_FORWARD_PRESETS
