"""Tests for the Advancing / Declining / Unchanged lists behind the dashboard's
breadth pills (ml/scraper/live_market.py + /api/live/breadth/<bucket>)."""
import sys
from pathlib import Path
sys.path.append(str(Path(__file__).resolve().parents[1]))
from unittest.mock import patch

from ml.scraper import live_market as lm

LIVE_ROWS = [
    {"symbol": "AAA", "lastTradedPrice": 110, "previousClose": 100, "percentageChange": 10.0},  # duplicate row
    {"symbol": "AAA", "lastTradedPrice": 110, "previousClose": 100, "percentageChange": 10.0,
     "totalTradeQuantity": 500, "totalTradeValue": 55000, "openPrice": 101, "highPrice": 111, "lowPrice": 100},
    {"symbol": "BBB", "lastTradedPrice": 52, "previousClose": 50, "percentageChange": 4.0,
     "totalTradeQuantity": 900, "totalTradeValue": 46800},
    {"symbol": "CCC", "lastTradedPrice": 90, "previousClose": 100, "percentageChange": -10.0,
     "totalTradeQuantity": 100, "totalTradeValue": 9000},
    {"symbol": "DDD", "lastTradedPrice": 95, "previousClose": 100, "percentageChange": -5.0,
     "totalTradeQuantity": 100, "totalTradeValue": 9500},
    {"symbol": "EEE", "lastTradedPrice": 20, "previousClose": 20, "percentageChange": 0,
     "totalTradeQuantity": 10, "totalTradeValue": 200},
    {"symbol": "FFF", "lastTradedPrice": 30, "previousClose": 30, "percentageChange": 0,
     "totalTradeQuantity": 700, "totalTradeValue": 21000},
    {"symbol": "NOPCT", "lastTradedPrice": 5},                                                   # no % change
]


def test_bucket_lengths_match_breadth_counts():
    breadth = lm._live_breadth(LIVE_ROWS)
    buckets = lm._breadth_symbols(LIVE_ROWS)
    assert len(buckets["advancing"]) == breadth["advancing"] - 1   # breadth counts the duplicate row
    assert buckets["advancing"] == ["AAA", "BBB"]
    assert buckets["declining"] == ["CCC", "DDD"]
    assert buckets["unchanged"] == ["EEE", "FFF"]
    assert "NOPCT" not in sum(buckets.values(), [])


def test_sorting_puts_biggest_movers_first():
    quotes = lm._live_quotes_by_symbol(LIVE_ROWS)
    adv = lm._sort_breadth_rows("advancing", [quotes["BBB"], quotes["AAA"]])
    dec = lm._sort_breadth_rows("declining", [quotes["DDD"], quotes["CCC"]])
    unc = lm._sort_breadth_rows("unchanged", [quotes["EEE"], quotes["FFF"]])
    assert [q["ticker"] for q in adv] == ["AAA", "BBB"]
    assert [q["ticker"] for q in dec] == ["CCC", "DDD"]
    assert [q["ticker"] for q in unc] == ["FFF", "EEE"]   # by volume


def _fake_results(live):
    return {"getMarketStatus": {"isOpen": "OPEN"}, "getNepseIndex": None, "getTopGainers": [],
            "getTopLosers": [], "getLiveMarket": live, "getPriceVolume": [],
            "getDailyNepseIndexGraph": [], "getNepseSubIndices": []}


def test_breadth_list_comes_from_the_same_snapshot():
    lm.reset_state()
    with patch.object(lm, "_call_all", return_value=_fake_results(LIVE_ROWS)):
        result = lm.get_breadth_list("advancing")
    lm.reset_state()
    assert result["available"] and result["bucket"] == "advancing"
    assert [r["ticker"] for r in result["rows"]] == ["AAA", "BBB"]
    assert result["count"] == 2
    assert result["rows"][0]["open"] == 101 and result["rows"][0]["prev_close"] == 100


def test_unknown_bucket_is_rejected():
    assert lm.get_breadth_list("sideways") is None


def test_api_route_and_private_field_not_leaked():
    from app import create_app
    lm.reset_state()
    app = create_app()
    with patch.object(lm, "_call_all", return_value=_fake_results(LIVE_ROWS)):
        client = app.test_client()
        ok = client.get("/api/live/breadth/declining").get_json()
        live = client.get("/api/live").get_json()
        bad = client.get("/api/live/breadth/sideways")
    lm.reset_state()
    assert [r["ticker"] for r in ok["rows"]] == ["CCC", "DDD"]
    assert "_breadth_quotes" not in live and "_quotes" not in live
    assert bad.status_code == 404


def test_nepse_time_with_fractional_seconds_is_parsed():
    """NEPSE's "asOf" gained microseconds; the library's parser failed on them every new day,
    which stopped the intraday index chart (getDailyNepseIndexGraph) from loading."""
    from datetime import datetime
    assert lm._parse_nepse_time("2026-10-26T14:32:20.500719") == datetime(2026, 10, 26, 14, 32, 20, 500719)
    assert lm._parse_nepse_time("2023-09-27T10:45:00") == datetime(2023, 9, 27, 10, 45)

    class LibraryManager:  # stands in for nepse.DummyIDUtils._DummyIDManager
        def convertToDateTime(self, date_time_str):
            return datetime.strptime(date_time_str, "%Y-%m-%dT%H:%M:%S")

    lm._patch_nepse_time_parsing(LibraryManager)
    assert LibraryManager().convertToDateTime("2026-10-26T14:32:20.5").date().isoformat() == "2026-10-26"
