"""Tests for the deterministic analysis engine (ml/analysis)."""
import math
from pathlib import Path

import numpy as np
import pytest

from ml.analysis import data as D
from ml.analysis import market, stock
from ml.analysis import technicals as T

DEPLOY = Path("deploy_data")
needs_data = pytest.mark.skipif(not (DEPLOY / "processed" / "NABIL_features.csv").exists(),
                                reason="deploy_data snapshot not present")


# ----------------------------------------------------------------- pure functions
def test_period_returns_counts_sessions():
    close = np.arange(1, 301, dtype=float)          # 1..300
    r = T.period_returns(close)
    assert r["1D"] == round((300 / 299 - 1) * 100, 2)
    assert r["1W"] == round((300 / 295 - 1) * 100, 2)
    assert r["1M"] == round((300 / 279 - 1) * 100, 2)
    assert r["1Y"] == round((300 / 55 - 1) * 100, 2)
    assert T.period_returns(close[:10])["1M"] is None


def test_volatility_matches_hand_calculation():
    rng = np.random.default_rng(0)
    close = 100 * np.cumprod(1 + rng.normal(0, 0.02, 100))
    r = close[1:] / close[:-1] - 1
    expected = round(np.std(r[-20:], ddof=1) * math.sqrt(245) * 100, 2)
    assert T.volatility(close, 20) == expected
    assert T.volatility(close[:5], 20) is None


def test_relative_volume_uses_previous_20_sessions():
    vol = np.array([100.0] * 20 + [350.0])
    assert T.relative_volume(vol) == 3.5
    assert T.relative_volume(vol[:10]) is None


def test_max_drawdown():
    close = np.array([100, 120, 90, 110, 60, 80], dtype=float)
    assert T.max_drawdown(close) == -50.0


def test_range_position():
    high = np.array([10, 12, 11, 15, 13], dtype=float)
    low = np.array([9, 10, 8, 12, 11], dtype=float)
    close = np.array([9.5, 11, 9, 14, 11.5])
    rp = T.range_position(high, low, close)
    assert rp["high"] == 15 and rp["low"] == 8
    assert rp["position_pct"] == round((11.5 - 8) / 7 * 100, 2)


def test_crossed_detects_latest_crossing():
    a = np.array([1, 1, 1, 3, 3, 3], dtype=float)
    b = np.array([2] * 6, dtype=float)
    assert T.crossed(a, b, 5) == {"direction": "up", "sessions_ago": 2}
    assert T.crossed(-a, -b, 5)["direction"] == "down"
    assert T.crossed(a, b, 1) is None          # crossing is older than the lookback


def test_support_resistance_on_zigzag():
    # price oscillates between ~90 and ~110, last close 100
    base = np.array([100, 105, 110, 105, 100, 95, 90, 95] * 10, dtype=float)
    close = np.append(base, 100.0)
    high, low = close + 0.5, close - 0.5
    dates = [f"d{i}" for i in range(len(close))]
    sr = T.support_resistance(high, low, close, dates, lookback=80)
    assert sr["support"] and sr["resistance"]
    assert all(x["level"] < 100 for x in sr["support"])
    assert all(x["level"] > 100 for x in sr["resistance"])
    assert abs(sr["support"][0]["level"] - 89.5) < 1 and sr["support"][0]["touches"] >= 5
    assert abs(sr["resistance"][0]["level"] - 110.5) < 1


def test_trend_rule():
    up = np.linspace(100, 200, 80)
    sma21 = np.array([np.mean(up[max(0, i - 20):i + 1]) for i in range(80)])
    sma50 = np.array([np.mean(up[max(0, i - 49):i + 1]) for i in range(80)])
    assert T.trend(up, sma21, sma50)["direction"] == "up"
    down = up[::-1]
    d21 = np.array([np.mean(down[max(0, i - 20):i + 1]) for i in range(80)])
    d50 = np.array([np.mean(down[max(0, i - 49):i + 1]) for i in range(80)])
    assert T.trend(down, d21, d50)["direction"] == "down"
    flat = np.full(80, 100.0)
    assert T.trend(flat, flat, flat)["direction"] == "sideways"
    assert T.trend(up, sma21 * np.nan, sma50)["direction"] == "unknown"


def test_parse_handles_blanks_inf_and_order():
    rows = [
        {"Date": "2026-01-03", "Close": "12", "Volume": "inf", "Sector": "Finance"},
        {"Date": "2026-01-01", "Close": "10", "Volume": "5"},
        {"Date": "2026-01-02", "Close": "", "Volume": "6"},
    ]
    h = D.parse_rows("XYZ", rows)
    assert h.dates == ["2026-01-01", "2026-01-03"]
    assert list(h["Close"]) == [10.0, 12.0]
    assert np.isnan(h["Volume"][1]) and np.isnan(h["RSI_14"]).all()
    assert h.sector == "Finance"


# ----------------------------------------------------------------- real data
@needs_data
def test_snapshot_matches_file():
    import csv
    rows = list(csv.DictReader(open(DEPLOY / "processed" / "NABIL_features.csv", encoding="utf-8")))
    closes = [float(r["Close"]) for r in rows if r["Close"]]
    snap = stock.snapshot("NABIL", path=DEPLOY)
    assert snap["as_of"] == rows[-1]["Date"][:10]
    assert snap["price"]["close"] == round(closes[-1], 2)
    assert snap["returns_pct"]["1W"] == round((closes[-1] / closes[-6] - 1) * 100, 2)
    assert snap["indicators"]["rsi_14"] == round(float(rows[-1]["RSI_14"]), 1)
    assert snap["sector"] == "Commercial Banks"
    for lv in snap["levels"]["support"]:
        assert lv["level"] < snap["price"]["close"]
    for lv in snap["levels"]["resistance"]:
        assert lv["level"] > snap["price"]["close"]
    assert all(o["side"] in ("bullish", "bearish", "caution", "neutral") and o["rule"] for o in snap["observations"])


@needs_data
def test_unknown_ticker_returns_none():
    assert stock.snapshot("NOT_A_TICKER", path=DEPLOY) is None


@needs_data
def test_market_summary_is_consistent():
    s = market.summary(path=DEPLOY)
    b = s["breadth"]
    assert b["advancing"] + b["declining"] + b["unchanged"] <= b["traded"] <= b["tracked"]
    assert sum(x["stocks"] for x in s["sectors"]) == b["tracked"]
    assert sum(x["traded"] for x in s["sectors"]) == b["traded"]
    g = [x["change_pct"] for x in s["gainers"]]
    assert g == sorted(g, reverse=True)
    assert all(x["date"] == s["as_of"] for x in s["gainers"] + s["losers"] + s["unusual_volume"])
    assert all(x["relative_volume"] >= market.UNUSUAL_RELVOL for x in s["unusual_volume"])
    assert len(b) and "official" in s["scope"].lower()
    shares = [x["turnover_share_pct"] for x in s["sectors"] if x["turnover_share_pct"] is not None]
    assert abs(sum(shares) - 100) < 0.1


# ----------------------------------------------------------------- report + API
@needs_data
def test_report_sections_are_labelled_and_traceable():
    from ml.analysis import report
    date, rows = market.stock_table(DEPLOY)
    sec = market.sector_medians(market.sector_performance(rows, date))
    snap = stock.snapshot("NABIL", path=DEPLOY, sector_returns=sec, market_date=date)
    rep = report.build(snap, rows)
    S = rep["sections"]
    assert set(S) == {"overview", "technical", "trend", "signals", "levels", "risk", "summary"}
    assert all(s["basis"] in ("data", "calculated", "rules") for s in S.values())
    # numbers in the text come from the snapshot
    assert f"{snap['price']['close']:,.2f}" in S["overview"]["lines"][0]
    rsi_row = next(r for r in S["technical"]["rows"] if r["indicator"].startswith("RSI"))
    assert rsi_row["value"] == str(snap["indicators"]["rsi_14"])
    assert "not a forecast" in S["summary"]["disclaimer"]
    counts = S["summary"]["counts"]
    assert counts["positive"] == len(S["signals"]["bullish"])
    assert counts["negative"] == len(S["signals"]["bearish"])
    assert counts["watch"] == len(S["signals"]["caution"])


def test_percentile_and_money_format():
    from ml.analysis import report
    assert report.percentile(5, [1, 5, 10, None]) == 67
    assert report.percentile(None, [1]) is None
    assert report._rs_big(61120456.7) == "Rs 6.11 crore"
    assert report._rs_big(8.5e9) == "Rs 8.50 arba"
    assert report._rs_big(250000) == "Rs 2.50 lakh"


@needs_data
def test_analysis_endpoint(monkeypatch):
    import app.backend.api as api_mod
    from flask import Flask
    monkeypatch.setattr(api_mod, "DATA_DIR", DEPLOY)
    monkeypatch.setattr(api_mod, "MODELS_DIR", DEPLOY / "models")
    app = Flask(__name__)
    app.register_blueprint(api_mod.api, url_prefix="/api")
    c = app.test_client()
    r = c.get("/api/analysis/nabil")
    assert r.status_code == 200
    d = r.get_json()
    assert d["snapshot"]["ticker"] == "NABIL"
    assert d["report"]["model"]["type"] == "LSTM"
    assert d["report"]["model"]["data_up_to"] == d["snapshot"]["as_of"]
    assert c.get("/api/analysis/NOPE123").status_code == 404


def test_load_history_rejects_non_ticker_text():
    for bad in ("../secret", "..", "A/B", "nabil; rm", "", "X" * 40):
        assert D.load_history(bad, DEPLOY) is None
