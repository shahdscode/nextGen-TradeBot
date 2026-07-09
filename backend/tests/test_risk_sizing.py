"""Unit tests for volatility-based position sizing + risk limits."""
from app.services.risk_sizing_service import (
    RiskConfig, size_positions, volatility_regime, DOW30_SECTORS,
)


def test_one_percent_risk_per_trade():
    # A 2*ATR stop-out should lose ~risk_per_trade_pct of equity.
    eq = 100_000.0
    prices = {"AAA": 100.0}
    atr = {"AAA": 2.0}   # stop distance = 2*ATR = 4 -> 4% stop
    r = size_positions(["AAA"], prices, atr, eq,
                       config=RiskConfig(risk_per_trade_pct=0.01, max_position_pct=1.0))
    p = r["positions"]["AAA"]
    risk_at_stop = (p["entry"] - p["stop_price"]) * p["shares"]
    assert abs(risk_at_stop - eq * 0.01) < 1.0   # ~$1000 risked


def test_low_vol_gets_bigger_position_than_high_vol():
    eq = 100_000.0
    prices = {"LOW": 100.0, "HIGH": 100.0}
    atr = {"LOW": 1.0, "HIGH": 5.0}   # same price, HIGH is 5x more volatile
    r = size_positions(["LOW", "HIGH"], prices, atr, eq,
                       config=RiskConfig(max_position_pct=1.0, max_gross_exposure=10.0))
    assert r["positions"]["LOW"]["dollars"] > r["positions"]["HIGH"]["dollars"]


def test_per_position_cap_enforced():
    eq = 100_000.0
    prices = {"X": 100.0}
    atr = {"X": 0.1}   # tiny ATR -> huge raw size, must be capped
    r = size_positions(["X"], prices, atr, eq,
                       config=RiskConfig(max_position_pct=0.20, max_gross_exposure=10.0))
    assert r["positions"]["X"]["weight"] <= 0.20 + 1e-6


def test_gross_exposure_cap_no_leverage():
    eq = 100_000.0
    prices = {a: 100.0 for a in ["A", "B", "C", "D", "E", "F"]}
    atr = {a: 0.1 for a in prices}   # each wants a huge position
    r = size_positions(list(prices), prices, atr, eq,
                       config=RiskConfig(max_position_pct=0.30, max_gross_exposure=1.0))
    assert r["gross_exposure"] <= 1.0 + 1e-6


def test_sector_cap_enforced():
    eq = 100_000.0
    tech = ["AAPL", "MSFT", "NVDA", "CSCO"]   # all Technology in DOW30_SECTORS
    prices = {t: 100.0 for t in tech}
    atr = {t: 1.0 for t in tech}
    r = size_positions(tech, prices, atr, eq, sectors=DOW30_SECTORS,
                       config=RiskConfig(max_position_pct=0.30, max_sector_pct=0.40,
                                         max_gross_exposure=10.0))
    tech_weight = sum(p["weight"] for p in r["positions"].values())
    assert tech_weight <= 0.40 + 1e-6


def test_target_weights_mode_normalizes_to_gross():
    eq = 100_000.0
    prices = {"A": 100.0, "B": 100.0}
    atr = {"A": 1.0, "B": 1.0}
    weights = {"A": 3.0, "B": 1.0}   # unnormalized 3:1
    r = size_positions(["A", "B"], prices, atr, eq, target_weights=weights,
                       config=RiskConfig(max_position_pct=1.0, max_gross_exposure=1.0))
    wa, wb = r["positions"]["A"]["weight"], r["positions"]["B"]["weight"]
    assert abs(wa / wb - 3.0) < 0.05        # 3:1 ratio preserved
    assert r["gross_exposure"] <= 1.0 + 1e-6


def test_stop_and_target_present():
    r = size_positions(["A"], {"A": 100.0}, {"A": 2.0}, 100_000.0,
                       config=RiskConfig(atr_stop_mult=2.0, take_profit_mult=3.0))
    p = r["positions"]["A"]
    assert p["stop_price"] == 96.0          # 100 - 2*2
    assert p["take_profit"] == 106.0        # 100 + 3*2


def test_missing_atr_uses_fallback_stop():
    r = size_positions(["A"], {"A": 100.0}, {"A": 0.0}, 100_000.0)
    # fallback stop is a fixed % below entry (no crash, valid stop)
    p = r["positions"]["A"]
    assert 0 < p["stop_price"] < 100.0


def test_volatility_regime_high_low_normal():
    calm = [1.0 + 0.01 * i for i in range(60)]
    assert volatility_regime(calm + [99.0])["vol_regime"] == "HIGH"   # spike at top pct
    assert volatility_regime(calm + [0.001])["vol_regime"] == "LOW"
    assert volatility_regime(calm + [1.3])["vol_regime"] == "NORMAL"


def test_volatility_regime_vix_forces_high():
    calm = [1.0 for _ in range(60)]
    r = volatility_regime(calm + [1.0], vix_zscore=2.0)
    assert r["vol_regime"] == "HIGH"
    assert r["risk_scale"] == 0.5


def test_empty_candidates_safe():
    r = size_positions([], {}, {}, 100_000.0)
    assert r["positions"] == {}
    assert r["gross_exposure"] == 0.0
