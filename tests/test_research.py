"""Tests for the screener and the comparison engine (ml/analysis)."""
from pathlib import Path

import pytest

from ml.analysis import compare, market, screener

DEPLOY = Path("deploy_data")
needs_data = pytest.mark.skipif(not (DEPLOY / "processed" / "NABIL_features.csv").exists(),
                                reason="deploy_data snapshot not present")


@needs_data
@pytest.mark.parametrize("preset", list(screener.PRESETS))
def test_every_preset_only_returns_matching_rows(preset):
    res = screener.run(DEPLOY, preset=preset)
    pred = screener.PRESETS[preset][2]
    assert res["count"] == len(res["rows"]) or res["count"] > len(res["rows"])
    for r in res["rows"]:
        assert pred(r), (preset, r["ticker"])
        assert r["traded_on_market_date"]
    assert "not a recommendation" in res["note"]


@needs_data
def test_filters_and_sorting():
    res = screener.run(DEPLOY, sector="Hydro Power", min_price=200, max_price=600, min_avg_turnover=1e6,
                       min_rsi=40, max_rsi=70, trend="up", sort="ret_1m", descending=True)
    for r in res["rows"]:
        assert r["sector"] == "Hydro Power" and 200 <= r["close"] <= 600
        assert r["avg_turnover_20d"] >= 1e6 and 40 <= r["rsi_14"] <= 70 and r["trend"] == "up"
    vals = [r["ret_1m"] for r in res["rows"] if r["ret_1m"] is not None]
    assert vals == sorted(vals, reverse=True)
    assert len(res["applied"]) >= 7


@needs_data
def test_not_traded_excluded_by_default():
    date, rows = market.stock_table(DEPLOY)
    stale = {r["ticker"] for r in rows if r["date"] != date}
    assert stale, "snapshot has no non-traded stocks to test with"
    assert not stale & {r["ticker"] for r in screener.run(DEPLOY, limit=1000)["rows"]}
    assert stale <= {r["ticker"] for r in screener.run(DEPLOY, include_not_traded=True, limit=1000)["rows"]}


def test_unknown_preset_rejected():
    with pytest.raises(ValueError):
        screener.run(DEPLOY, preset="does_not_exist")


def test_parse_tickers():
    assert compare.parse_tickers(" nabil, NICA nabil,,gbime,a,b,c ") == ["NABIL", "NICA", "GBIME", "A", "B"]


@needs_data
def test_compare_is_relative_and_consistent():
    c = compare.compare("NABIL,NICA,GBIME,NOPE", path=DEPLOY, period="3M")
    assert c["tickers"] == ["NABIL", "NICA", "GBIME"] and c["missing"] == ["NOPE"]
    # rebased series start at 100 and share dates
    assert all(s[0] == 100 for s in c["chart"]["series"].values())
    assert len(c["chart"]["dates"]) == compare.PERIODS["3M"] + 1
    row = next(r for r in c["table"] if r["key"] == "ret_1m")
    best = max(row["values"], key=row["values"].get)
    assert "strongest 1-month return in this group" in c["relative"][best]["strengths"]
    assert "not investment advice" in c["note"]
    # no "best investment" style wording anywhere
    text = str(c["relative"]).lower()
    assert "buy" not in text and "best investment" not in text
