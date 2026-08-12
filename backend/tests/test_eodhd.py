"""Unit tests for the EODHD (EGX) data adapter — symbology + response parsing."""
from unittest.mock import patch

import pandas as pd

from app.services import eodhd_service


def test_symbol_mapping_ca_to_egx():
    assert eodhd_service._to_eodhd_symbol("COMI.CA") == "COMI.EGX"
    assert eodhd_service._to_eodhd_symbol("HRHO.CA") == "HRHO.EGX"
    assert eodhd_service._to_eodhd_symbol("SWDY") == "SWDY.EGX"   # no suffix


def test_not_configured_raises(monkeypatch):
    monkeypatch.setattr(eodhd_service.settings, "eodhd_api_key", "")
    assert eodhd_service.configured() is False
    try:
        eodhd_service.get_daily_bars(["COMI.CA"], "2024-01-01", "2024-02-01")
        assert False, "should raise when not configured"
    except RuntimeError:
        pass


class _FakeResp:
    status_code = 200
    def __init__(self, payload):
        self._p = payload
    def json(self):
        return self._p


def test_get_daily_bars_parses_and_adjusts(monkeypatch):
    monkeypatch.setattr(eodhd_service.settings, "eodhd_api_key", "TESTKEY")
    payload = [
        {"date": "2024-01-02", "open": 100.0, "high": 110.0, "low": 95.0,
         "close": 100.0, "adjusted_close": 50.0, "volume": 1000},   # 2:1 split -> factor 0.5
        {"date": "2024-01-03", "open": 52.0, "high": 54.0, "low": 50.0,
         "close": 52.0, "adjusted_close": 52.0, "volume": 1200},     # factor 1.0
    ]
    with patch.object(eodhd_service.requests, "get", return_value=_FakeResp(payload)):
        df = eodhd_service.get_daily_bars(["COMI.CA"], "2024-01-01", "2024-01-05")
    assert list(df.columns) == ["date", "tic", "open", "high", "low", "close", "volume"]
    assert (df["tic"] == "COMI.CA").all()          # original .CA ticker preserved
    row0 = df.iloc[0]
    assert row0["close"] == 50.0                    # adjusted_close used as close
    assert abs(row0["open"] - 50.0) < 1e-9          # OHLC scaled by 0.5 factor
    assert abs(row0["high"] - 55.0) < 1e-9
    row1 = df.iloc[1]
    assert abs(row1["close"] - 52.0) < 1e-9         # factor 1.0 unchanged


def test_get_daily_bars_empty_raises(monkeypatch):
    monkeypatch.setattr(eodhd_service.settings, "eodhd_api_key", "TESTKEY")
    with patch.object(eodhd_service.requests, "get", return_value=_FakeResp([])):
        try:
            eodhd_service.get_daily_bars(["COMI.CA"], "2024-01-01", "2024-02-01")
            assert False, "should raise when no data"
        except RuntimeError:
            pass


def test_latest_price_parses(monkeypatch):
    monkeypatch.setattr(eodhd_service.settings, "eodhd_api_key", "TESTKEY")
    with patch.object(eodhd_service.requests, "get", return_value=_FakeResp({"code": "COMI.EGX", "close": 136.9})):
        assert eodhd_service.get_latest_price("COMI.CA") == 136.9


def test_latest_price_handles_NA(monkeypatch):
    monkeypatch.setattr(eodhd_service.settings, "eodhd_api_key", "TESTKEY")
    with patch.object(eodhd_service.requests, "get", return_value=_FakeResp({"close": "NA"})):
        assert eodhd_service.get_latest_price("COMI.CA") is None
