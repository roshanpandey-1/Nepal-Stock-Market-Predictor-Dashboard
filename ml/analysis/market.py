"""Market-wide views built from every tracked stock's daily file.

Important scope note: these are totals and medians over the stocks this
project tracks (about 270 listed equities), computed from completed daily
sessions. They are NOT the official NEPSE index or NEPSE's published market
totals, and are labelled that way wherever they are shown.
"""
import threading
import time

import numpy as np

from . import data as D
from . import technicals as T

UNUSUAL_RELVOL = 3.0          # volume >= 3x its 20-session average
UNUSUAL_MIN_TURNOVER = 1e6    # and at least Rs 10 lakh traded that day (filters illiquid noise)
SCOPE = "Tracked stocks only (not the official NEPSE index or NEPSE market totals)"


def stock_row(h, names):
    """Compact metrics for one stock (used by the market views and the screener)."""
    close, vol = h["Close"], h["Volume"]
    c = T._last(close)
    prev = float(close[-2]) if len(close) > 1 else None
    rets = T.period_returns(close)
    rng = T.range_position(h["High"], h["Low"], close)
    rsi = T._last(h["RSI_14"])
    sr = T.support_resistance(h["High"], h["Low"], close, h.dates, max_levels=1)
    return {
        "ticker": h.ticker,
        "name": names.get(h.ticker, h.ticker),
        "sector": h.sector,
        "date": h.last_date,
        "close": T._r(c),
        "change_pct": rets["1D"],
        "change": T._r(c - prev) if prev else None,
        "ret_1w": rets["1W"], "ret_1m": rets["1M"], "ret_3m": rets["3M"],
        "ret_6m": rets["6M"], "ret_1y": rets["1Y"],
        "volume": T._r(T._last(vol), 0),
        "turnover": T._r(T._last(h["Turnover"])),
        "relative_volume": T.relative_volume(vol),
        "avg_turnover_20d": T._r(float(np.nanmean(h["Turnover"][-21:-1]))) if len(vol) > 21 and np.isfinite(h["Turnover"][-21:-1]).any() else None,
        "rsi_14": T._r(rsi, 1),
        "volatility_20d": T.volatility(close, 20),
        "from_high_pct": rng["from_high_pct"] if rng else None,
        "from_low_pct": rng["from_low_pct"] if rng else None,
        "price_vs_sma_50_pct": T._r((c / T._last(h["SMA_50"]) - 1) * 100) if c and T._last(h["SMA_50"]) else None,
        "trend": T.trend(close, h["SMA_21"], h["SMA_50"])["direction"],
        "support_pct": sr["support"][0]["distance_pct"] if sr["support"] else None,
        "support": sr["support"][0]["level"] if sr["support"] else None,
        "resistance_pct": sr["resistance"][0]["distance_pct"] if sr["resistance"] else None,
        "resistance": sr["resistance"][0]["level"] if sr["resistance"] else None,
        "support_touches": sr["support"][0]["touches"] if sr["support"] else None,
        "resistance_touches": sr["resistance"][0]["touches"] if sr["resistance"] else None,
        "cross_price_sma50": (T.crossed(close, h["SMA_50"], 5) or {}).get("direction"),
        "cross_macd": (T.crossed(h["MACD"], h["MACD_Signal"], 5) or {}).get("direction"),
        "macd_above_signal": (None if T._last(h["MACD"]) is None or T._last(h["MACD_Signal"]) is None
                              else T._last(h["MACD"]) > T._last(h["MACD_Signal"])),
    }


_TABLE = {"key": None, "rows": None, "date": None, "checked": 0.0, "path": None}
RECHECK_SECONDS = 60   # data changes once a day; don't stat 270 files on every request


_TABLE_LOCK = threading.Lock()


def stock_table(path=None):
    """(market_date, [stock_row, ...]) for every tracked stock. Cached until any file changes
    (files are re-checked at most once a minute). A lock makes concurrent first requests wait
    for one build instead of each reading all the files."""
    now = time.monotonic()
    if _TABLE["rows"] is not None and _TABLE["path"] == str(path) and now - _TABLE["checked"] < RECHECK_SECONDS:
        return _TABLE["date"], _TABLE["rows"]
    with _TABLE_LOCK:
        now = time.monotonic()
        if _TABLE["rows"] is not None and _TABLE["path"] == str(path) and now - _TABLE["checked"] < RECHECK_SECONDS:
            return _TABLE["date"], _TABLE["rows"]
        hists = D.universe(path)
        key = tuple((t, h.last_date, len(h)) for t, h in sorted(hists.items()))
        if _TABLE["key"] != key or _TABLE["path"] != str(path):
            names = D.company_names(path)
            _TABLE.update(key=key, rows=[stock_row(h, names) for h in hists.values()],
                          date=D.market_date(hists))
        _TABLE.update(checked=time.monotonic(), path=str(path))
        return _TABLE["date"], _TABLE["rows"]


def _median(values):
    v = [x for x in values if x is not None]
    return T._r(float(np.median(v))) if v else None


def sector_performance(rows, market_date):
    """Per sector: median returns, today's breadth and turnover."""
    out = {}
    for r in rows:
        if not r["sector"]:
            continue
        out.setdefault(r["sector"], []).append(r)
    result = []
    total_turnover = sum(r["turnover"] or 0 for r in rows if r["date"] == market_date)
    for sector, rs in out.items():
        today = [r for r in rs if r["date"] == market_date]
        turnover = sum(r["turnover"] or 0 for r in today)
        result.append({
            "sector": sector,
            "stocks": len(rs),
            "traded": len(today),
            "advancing": sum(1 for r in today if (r["change_pct"] or 0) > 0),
            "declining": sum(1 for r in today if (r["change_pct"] or 0) < 0),
            "median_1d_pct": _median([r["change_pct"] for r in today]),
            "median_1w_pct": _median([r["ret_1w"] for r in rs]),
            "median_1m_pct": _median([r["ret_1m"] for r in rs]),
            "median_3m_pct": _median([r["ret_3m"] for r in rs]),
            "turnover": T._r(turnover),
            "turnover_share_pct": T._r(turnover / total_turnover * 100) if total_turnover else None,
            "uptrend": sum(1 for r in rs if r["trend"] == "up"),
            "downtrend": sum(1 for r in rs if r["trend"] == "down"),
        })
    result.sort(key=lambda s: -(s["median_1m_pct"] if s["median_1m_pct"] is not None else -1e9))
    return result


def sector_medians(sectors):
    """{sector: {'1W': ..., '1M': ..., '3M': ...}} for stock.snapshot(sector_returns=...)."""
    return {s["sector"]: {"1W": s["median_1w_pct"], "1M": s["median_1m_pct"], "3M": s["median_3m_pct"]}
            for s in sectors}


def unusual_volume(rows, market_date, limit=15):
    hits = [r for r in rows if r["date"] == market_date and r["relative_volume"] is not None
            and r["relative_volume"] >= UNUSUAL_RELVOL and (r["turnover"] or 0) >= UNUSUAL_MIN_TURNOVER]
    return sorted(hits, key=lambda r: -r["relative_volume"])[:limit]


def summary(path=None, top=5):
    """Market summary for the latest completed session in the data."""
    market_date, rows = stock_table(path)
    today = [r for r in rows if r["date"] == market_date]
    chg = [r for r in today if r["change_pct"] is not None]
    sectors = sector_performance(rows, market_date)
    pick = lambda key, rev, n: sorted([r for r in today if r[key] is not None], key=lambda r: r[key], reverse=rev)[:n]
    return {
        "as_of": market_date,
        "source": D.SOURCE,
        "scope": SCOPE,
        "breadth": {
            "tracked": len(rows),
            "traded": len(today),
            "advancing": sum(1 for r in chg if r["change_pct"] > 0),
            "declining": sum(1 for r in chg if r["change_pct"] < 0),
            "unchanged": sum(1 for r in chg if r["change_pct"] == 0),
            "median_change_pct": _median([r["change_pct"] for r in chg]),
            "average_change_pct": T._r(float(np.mean([r["change_pct"] for r in chg]))) if chg else None,
            "near_1y_high": sum(1 for r in today if r["from_high_pct"] is not None and r["from_high_pct"] >= -2),
            "near_1y_low": sum(1 for r in today if r["from_low_pct"] is not None and r["from_low_pct"] <= 2),
            "above_sma_50": sum(1 for r in today if (r["price_vs_sma_50_pct"] or 0) > 0),
        },
        "totals": {
            "turnover": T._r(sum(r["turnover"] or 0 for r in today)),
            "volume": T._r(sum(r["volume"] or 0 for r in today), 0),
        },
        "gainers": pick("change_pct", True, top),
        "losers": pick("change_pct", False, top),
        "top_turnover": pick("turnover", True, 10),
        "top_volume": pick("volume", True, 10),
        "unusual_volume": unusual_volume(rows, market_date),
        "sectors": sectors,
        "not_traded": sorted(r["ticker"] for r in rows if r["date"] != market_date),
    }
