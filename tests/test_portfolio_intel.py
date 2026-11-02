"""Tests for portfolio and watchlist checks (ml/analysis/portfolio.py)."""
import csv
import math
from datetime import date, timedelta

import numpy as np
import pytest

from ml.analysis import data as D
from ml.analysis import portfolio as P


def _write(root, ticker, closes, dates, sector="Finance", skip=()):
    proc = root / "processed"
    proc.mkdir(parents=True, exist_ok=True)
    with open(proc / f"{ticker}_features.csv", "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["Date", "Open", "High", "Low", "Close", "Volume", "Turnover", "Sector"])
        for i, (d, c) in enumerate(zip(dates, closes)):
            if i in skip:
                continue
            w.writerow([d, c, c * 1.01, c * 0.99, c, 1000, c * 1000, sector])


def _dates(n, end="2026-10-30"):
    e = date.fromisoformat(end)
    return [(e - timedelta(days=n - 1 - i)).isoformat() for i in range(n)]


@pytest.fixture
def root(tmp_path):
    rng = np.random.default_rng(1)
    dates = _dates(130)
    a = 100 * np.cumprod(1 + rng.normal(0.001, 0.01, 130))
    b = 50 * np.cumprod(1 + rng.normal(0.000, 0.03, 130))
    _write(tmp_path, "AAA", a, dates, "Finance")
    _write(tmp_path, "BBB", b, dates, "Hydro Power", skip=set(range(10, 130, 2)))   # BBB trades every other day after 10
    D._CACHE.clear()
    return tmp_path, dates, a, b


# ---------------------------------------------------------------- concentration
def _row(t, v, sector="Finance"):
    return {"ticker": t, "value_ltp": v, "sector": sector}


def test_concentration_flags_and_numbers():
    c = P.concentration([_row("A", 600, "Finance"), _row("B", 200, "Hydro Power"), _row("C", 200, "Finance")])
    assert c["largest"] == {"ticker": "A", "share_pct": 60.0}
    assert c["top3_pct"] == 100.0 and c["effective_holdings"] == round(1 / (0.36 + 0.04 + 0.04), 1)
    texts = " | ".join(f["text"] for f in c["flags"])
    assert "A is 60%" in texts and "3 stocks" in texts and "Finance" in texts
    assert all(f["rule"] for f in c["flags"])                      # every flag states its rule


def test_concentration_quiet_for_balanced_portfolio():
    rows = [_row(f"S{i}", 100, f"Sector{i % 4}") for i in range(10)]
    assert P.concentration(rows)["flags"] == []
    assert P.concentration([]) is None


def test_single_holding_is_not_flagged_as_dominant():
    flags = [f["text"] for f in P.concentration([_row("A", 100)])["flags"]]
    assert not any("is 100%" in t for t in flags)                   # obvious, so not repeated


# ---------------------------------------------------------------- stock flags
def test_stock_flags_fire_only_when_their_rule_is_met():
    base = {"rsi_14": 50, "trend": "sideways", "relative_volume": 1.0, "turnover": 5e6, "change_pct": 1.0,
            "support_pct": None, "resistance_pct": None, "cross_price_sma50": None, "cross_macd": None,
            "from_high_pct": -20, "from_low_pct": 25, "price_vs_sma_50_pct": 1}
    assert P.stock_flags(base) == []
    hot = dict(base, rsi_14=78, relative_volume=4.2, change_pct=-6.5, support_pct=-1.2, support=480.0,
               support_touches=4, cross_macd="down", from_low_pct=2)
    texts = [f["text"] for f in P.stock_flags(hot)]
    assert any("RSI is 78" in t for t in texts) and any("4.2x" in t for t in texts)
    assert any("-6.5%" in t for t in texts) and any("support level (price 480" in t for t in texts)
    assert any("MACD crossed below" in t for t in texts) and any("52-week low" in t for t in texts)
    thin = dict(hot, turnover=1e5)                                  # illiquid: volume spike ignored
    assert not any("4.2x" in f["text"] for f in P.stock_flags(thin))


# ---------------------------------------------------------------- portfolio risk
def test_basket_forward_fills_days_a_stock_did_not_trade(root):
    tmp, dates, a, b = root
    dts, mat, used, missing = P.basket({"AAA": 10, "BBB": 20, "ZZZ": 5}, tmp)
    assert used == ["AAA", "BBB"] and missing == ["ZZZ"]
    j = dts.index(dates[12])                       # BBB did not trade on this day
    assert mat[j, 1] == pytest.approx(b[11])       # carries the previous close
    assert not np.isnan(mat).any()


def test_risk_matches_hand_calculation(root):
    tmp, dates, a, b = root
    r = P.risk({"AAA": 10, "BBB": 20}, tmp)
    dts, mat, used, _ = P.basket({"AAA": 10, "BBB": 20}, tmp)
    values = mat @ np.array([10.0, 20.0])
    rets = values[1:] / values[:-1] - 1
    assert r["volatility_pct"] == round(float(np.std(rets, ddof=1)) * math.sqrt(245) * 100, 2)
    assert r["max_drawdown_pct"] <= 0
    assert r["ret_1m"] == round((values[-1] / values[-22] - 1) * 100, 2)
    shares = r["variance_share"]
    assert sum(s["risk_share_pct"] for s in shares) == pytest.approx(100, abs=0.5)
    assert shares[0]["ticker"] == "BBB"            # the more volatile stock drives the risk
    assert "NEPSE index" in r["note"]


def test_risk_unavailable_with_too_little_history(tmp_path):
    _write(tmp_path, "AAA", [100 + i for i in range(30)], _dates(30))
    D._CACHE.clear()
    assert P.risk({"AAA": 10}, tmp_path) is None
    assert P.risk({"NOPE": 10}, tmp_path) is None


# ---------------------------------------------------------------- watchlist
def test_watchlist_view_order_missing_and_summary(root):
    tmp, dates, a, b = root
    v = P.watchlist_view(["BBB", "NOPE", "AAA"], tmp)
    assert [r["ticker"] for r in v["rows"]] == ["BBB", "NOPE", "AAA"]
    assert v["rows"][1]["missing"] is True
    s = v["summary"]
    assert s["count"] == 3 and s["biggest_gain"]["change_pct"] >= s["biggest_fall"]["change_pct"]
    assert "End-of-day" in v["basis"]


def test_market_table_is_built_once_for_concurrent_first_requests(root, monkeypatch):
    import threading
    from ml.analysis import market
    tmp, *_ = root
    calls = []
    real = D.universe
    monkeypatch.setattr(D, "universe", lambda p=None: (calls.append(1), real(p))[1])
    market._TABLE.update(rows=None, key=None, path=None, checked=0.0)
    out = []
    threads = [threading.Thread(target=lambda: out.append(market.stock_table(tmp))) for _ in range(5)]
    [t.start() for t in threads]
    [t.join() for t in threads]
    assert len(calls) == 1 and len({id(o[1]) for o in out}) == 1
