"""Tests for stock ideas, holdings forecasts and search history."""
import sys
from pathlib import Path

sys.path.append(str(Path(__file__).resolve().parents[1]))

import pytest

from app import insights
from tests.test_accounts import _signup, _token, client  # noqa: F401  (fixture reuse)

STATS = {
    "NABIL": {"sector": "Commercial Banks", "close": 500, "mom20": 2.0, "turnover20": 9e7},
    "SCB":   {"sector": "Commercial Banks", "close": 600, "mom20": 6.0, "turnover20": 8e7},
    "NICA":  {"sector": "Commercial Banks", "close": 400, "mom20": 1.0, "turnover20": 7e7},
    "ADBL":  {"sector": "Commercial Banks", "close": 300, "mom20": -9.0, "turnover20": 6e7},
    "TINY":  {"sector": "Commercial Banks", "close": 100, "mom20": 30.0, "turnover20": 1e3},
    "UPPER": {"sector": "Hydro Power", "close": 200, "mom20": 12.0, "turnover20": 9e7},
    "NLIC":  {"sector": "Life Insurance", "close": 700, "mom20": 3.0, "turnover20": 5e7},
}
FC = {t: {"change_pct": c, "forecast_price": 1, "lower_bound": 1, "upper_bound": 1,
          "current_price": 1, "horizon_days": 30, "generated_at": "2026-10-12"}
      for t, c in {"NABIL": 1, "SCB": 5, "NICA": 2, "ADBL": -4, "TINY": 9, "UPPER": 8, "NLIC": 1}.items()}


def test_ideas_stay_in_users_sectors_and_skip_held():
    ideas = insights.recommend(["NABIL"], [], STATS, FC, limit=5)
    tickers = [i["ticker"] for i in ideas]
    assert "NABIL" not in tickers                     # already held
    assert "UPPER" not in tickers                     # other sector
    assert "TINY" not in tickers                      # too illiquid
    assert "ADBL" not in tickers                      # negative score
    assert tickers[0] == "SCB"                        # best forecast + momentum
    assert ideas[0]["reasons"][0] == "Same sector as NABIL (you hold it)"
    assert all(i["basis"] == "personal" for i in ideas)


def test_searched_sector_counts_and_watched_excluded():
    ideas = insights.recommend([], ["UPPER"], STATS, FC, exclude=["SCB"])
    assert [i["ticker"] for i in ideas] == []         # only UPPER in Hydro, and it was searched
    ideas = insights.recommend(["NICA"], ["UPPER"], STATS, FC, exclude=["SCB"])
    assert "SCB" not in [i["ticker"] for i in ideas]


def test_no_history_falls_back_to_market_and_caps_per_sector():
    ideas = insights.recommend([], [], STATS, FC, limit=10)
    assert ideas and all(i["basis"] == "market" for i in ideas)
    from collections import Counter
    assert max(Counter(i["sector"] for i in ideas).values()) <= 2


def test_holdings_forecast_values_and_missing():
    summary = {"NABIL": {"forecast_price": 110.0, "lower_bound": 90.0, "upper_bound": 130.0, "generated_at": "2026-10-12"}}
    rows = [{"ticker": "NABIL", "quantity": 10, "ltp": 100.0, "name": "Nabil"},
            {"ticker": "XYZ", "quantity": 5, "ltp": 50.0}]
    out = insights.holdings_forecast(rows, summary, {"NABIL": [{"d": 1, "date": "2026-10-13", "p": 101, "lo": 99, "hi": 103}]})
    item = out["items"][0]
    assert (item["change_pct"], item["lower_pct"], item["upper_pct"]) == (10.0, -10.0, 30.0)
    assert (item["value_now"], item["value_forecast"], item["value_change"]) == (1000, 1100, 100)
    assert out["totals"]["change_pct"] == 10.0 and out["totals"]["value_low"] == 900
    assert out["missing"] == ["XYZ"] and len(item["path"]) == 1
    assert item["rescaled"] is False


def test_holdings_forecast_rescales_when_price_moved_a_lot():
    summary = {"A": {"current_price": 200.0, "forecast_price": 220.0, "lower_bound": 180.0,
                     "upper_bound": 260.0, "generated_at": "2026-10-12"}}
    out = insights.holdings_forecast([{"ticker": "A", "quantity": 1, "ltp": 100.0}], summary, {})
    item = out["items"][0]   # price halved since the batch: keep the +10% move, not +120%
    assert item["rescaled"] is True and item["forecast_price"] == 110.0 and item["change_pct"] == 10.0


def test_ideas_need_a_positive_forecast():
    fc = dict(FC, SCB=dict(FC["SCB"], change_pct=-1.0))
    assert "SCB" not in [i["ticker"] for i in insights.recommend(["NABIL"], [], STATS, fc)]


# ---------------- API ----------------
def _api(c, method, path, **kw):
    return c.open(path, method=method, headers={"X-CSRF-Token": _token(c)}, **kw)


def test_search_history_latest_five_newest_first(client):
    _signup(client)
    for t in ["NABIL", "SCB", "NLIC"]:
        assert _api(client, "POST", "/api/me/search-history", json={"ticker": t}).status_code == 200
    _api(client, "POST", "/api/me/search-history", json={"ticker": "NABIL"})   # repeat moves to top
    items = client.get("/api/me/search-history").get_json()["items"]
    assert [i["t"] for i in items] == ["NABIL", "NLIC", "SCB"]
    assert items[0]["n"] == "Nabil Bank"
    assert _api(client, "POST", "/api/me/search-history", json={"ticker": "NOPE1"}).status_code == 400
    _api(client, "DELETE", "/api/me/search-history")
    assert client.get("/api/me/search-history").get_json()["items"] == []


def test_search_history_needs_login_and_csrf(client):
    assert client.get("/api/me/search-history").status_code == 401
    _signup(client)
    assert client.post("/api/me/search-history", json={"ticker": "NABIL"}).status_code in (400, 403)


def test_search_history_caps_at_five_shown(client, monkeypatch):
    from app import routes
    names = [f"T{i}" for i in range(8)]
    monkeypatch.setattr(routes, "_ticker_list", lambda: names)
    _signup(client)
    for t in names:
        _api(client, "POST", "/api/me/search-history", json={"ticker": t})
    items = client.get("/api/me/search-history").get_json()["items"]
    assert len(items) == 5 and items[0]["t"] == "T7"


def test_portfolio_forecast_and_ideas_endpoints(client, monkeypatch):
    monkeypatch.setattr(insights, "load_forecasts", lambda: (
        {"NABIL": {"forecast_price": 1100.0, "lower_bound": 900.0, "upper_bound": 1300.0,
                   "change_pct": 5.0, "generated_at": "2026-10-12"},
         "SCB": {"forecast_price": 1, "lower_bound": 1, "upper_bound": 1, "change_pct": 5.0, "generated_at": "x"}}, {}))
    monkeypatch.setattr(insights, "market_stats", lambda tickers: {
        "NABIL": {"sector": "Commercial Banks", "close": 1000, "mom20": 1.0, "turnover20": 5e7},
        "SCB": {"sector": "Commercial Banks", "close": 1000, "mom20": 4.0, "turnover20": 5e7}})
    _signup(client)
    _api(client, "POST", "/api/me/holdings", json={"ticker": "NABIL", "quantity": 10})
    d = client.get("/api/me/portfolio/forecast").get_json()
    assert d["ok"] and d["items"][0]["change_pct"] == 10.0 and d["totals"]["value_forecast"] == 11000
    r = client.get("/api/me/recommendations").get_json()
    assert r["basis"] == "personal" and [i["ticker"] for i in r["items"]] == ["SCB"]
