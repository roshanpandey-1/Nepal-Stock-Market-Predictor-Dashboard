"""Side-by-side comparison of 2-5 stocks.

Relative strengths and weaknesses are stated only within the compared group
(e.g. "highest 1-month return of the group") and never as a verdict on which
stock is the better investment.
"""
from . import data as D
from . import market as M
from . import stock as S
from . import technicals as T

MAX_STOCKS = 5
PERIODS = {"1M": 21, "3M": 63, "6M": 126, "1Y": 245}

METRICS = [
    # key, label, getter, better ("high"/"low"/None), kind
    ("close", "Last close (Rs)", lambda s: s["price"]["close"], None, "data"),
    ("change_pct", "Day change %", lambda s: s["price"]["change_pct"], None, "data"),
    ("ret_1w", "1-week return %", lambda s: s["returns_pct"]["1W"], None, "calculated"),
    ("ret_1m", "1-month return %", lambda s: s["returns_pct"]["1M"], "high", "calculated"),
    ("ret_3m", "3-month return %", lambda s: s["returns_pct"]["3M"], "high", "calculated"),
    ("ret_1y", "1-year return %", lambda s: s["returns_pct"]["1Y"], "high", "calculated"),
    ("vs_sector_1m", "1M vs sector median (pts)", lambda s: ((s.get("vs_sector") or {}).get("1M") or {}).get("difference_pct_points"), "high", "calculated"),
    ("volatility_20d", "Volatility, 20 sessions (% a year)", lambda s: s["risk"]["volatility_20d_pct"], "low", "calculated"),
    ("max_drawdown_1y", "Largest fall in 1 year %", lambda s: s["risk"]["max_drawdown_1y_pct"], "high", "calculated"),
    ("avg_turnover_20d", "Avg daily turnover, 20 sessions (Rs)", lambda s: s["volume"]["avg_turnover_20d"], "high", "calculated"),
    ("relative_volume", "Volume vs 20-session average (x)", lambda s: s["volume"]["relative_volume"], None, "calculated"),
    ("rsi_14", "RSI (14)", lambda s: s["indicators"]["rsi_14"], None, "calculated"),
    ("price_vs_sma_50", "Price vs 50-day average %", lambda s: s["indicators"]["price_vs_sma_50_pct"], None, "calculated"),
    ("price_vs_sma_200", "Price vs 200-day average %", lambda s: s["indicators"]["price_vs_sma_200_pct"], None, "calculated"),
    ("from_high", "From 1-year high %", lambda s: (s["range_1y"] or {}).get("from_high_pct"), None, "calculated"),
    ("trend", "Trend (rule)", lambda s: s["trend"]["direction"], None, "rules"),
    ("support", "Nearest support (Rs)", lambda s: s["levels"]["support"][0]["level"] if s["levels"]["support"] else None, None, "calculated"),
    ("resistance", "Nearest resistance (Rs)", lambda s: s["levels"]["resistance"][0]["level"] if s["levels"]["resistance"] else None, None, "calculated"),
]

PHRASES = {
    "ret_1m": ("strongest 1-month return in this group", "weakest 1-month return in this group"),
    "ret_3m": ("strongest 3-month return in this group", "weakest 3-month return in this group"),
    "ret_1y": ("strongest 1-year return in this group", "weakest 1-year return in this group"),
    "vs_sector_1m": ("did best against its own sector over 1 month", "did worst against its own sector over 1 month"),
    "volatility_20d": ("least volatile over the last 20 sessions", "most volatile over the last 20 sessions"),
    "max_drawdown_1y": ("smallest fall from a peak in the last year", "largest fall from a peak in the last year"),
    "avg_turnover_20d": ("highest average daily turnover in this group", "lowest average daily turnover in this group"),
}


def parse_tickers(raw):
    seen = []
    for t in (raw or "").replace(" ", ",").split(","):
        t = t.strip().upper()
        if t and t not in seen:
            seen.append(t)
    return seen[:MAX_STOCKS]


def normalised_series(path, tickers, sessions):
    """Each stock's closes rebased to 100 on the first common date of the window."""
    hists = {t: D.load_history(t, path) for t in tickers}
    hists = {t: h for t, h in hists.items() if h is not None and len(h)}
    if not hists:
        return {"dates": [], "series": {}}
    common = set.intersection(*(set(h.dates) for h in hists.values()))
    dates = sorted(common)[-(sessions + 1):]
    series = {}
    for t, h in hists.items():
        idx = {d: i for i, d in enumerate(h.dates)}
        base = h["Close"][idx[dates[0]]] if dates else None
        series[t] = [T._r(h["Close"][idx[d]] / base * 100) if base else None for d in dates]
    return {"dates": dates, "series": series}


def compare(tickers, path=None, period="6M"):
    tickers = parse_tickers(",".join(tickers) if isinstance(tickers, (list, tuple)) else tickers)
    date, rows = M.stock_table(path)
    sec = M.sector_medians(M.sector_performance(rows, date))
    names = D.company_names(path)
    snaps, missing = {}, []
    for t in tickers:
        s = S.snapshot(t, path=path, sector_returns=sec, market_date=date, names=names)
        if s is None:
            missing.append(t)
        else:
            snaps[t] = s
    table = []
    for key, label, get, better, kind in METRICS:
        table.append({"key": key, "label": label, "basis": kind, "better": better,
                      "values": {t: get(s) for t, s in snaps.items()}})
    from . import external
    fmap = external.fundamentals_map(path)
    for key, label, field in (("eps", "EPS, reported (Rs)", "eps"), ("pe", "P/E, as listed", "pe"),
                              ("pbv", "Price to book, as listed", "pbv"), ("book_value", "Book value per share (Rs)", "book_value"),
                              ("cash_dividend", "Latest cash dividend (% of face value)", "cash_dividend_pct")):
        vals = {t: (fmap.get(t) or {}).get(field) for t in snaps}
        if any(v is not None for v in vals.values()):
            table.append({"key": key, "label": label, "basis": "reported", "better": None, "values": vals})
    notes = {t: {"strengths": [], "weaknesses": []} for t in snaps}
    if len(snaps) >= 2:
        for row in table:
            if row["key"] not in PHRASES:
                continue
            vals = {t: v for t, v in row["values"].items() if v is not None}
            if len(vals) < 2 or len(set(vals.values())) == 1:
                continue
            hi, lo = max(vals, key=vals.get), min(vals, key=vals.get)
            best, worst = (hi, lo) if row["better"] == "high" else (lo, hi)
            good, bad = PHRASES[row["key"]]
            notes[best]["strengths"].append(good)
            notes[worst]["weaknesses"].append(bad)
    sessions = PERIODS.get(period, PERIODS["6M"])
    return {
        "as_of": date, "tickers": list(snaps), "missing": missing, "period": period if period in PERIODS else "6M",
        "stocks": {t: {"name": s["name"], "sector": s["sector"], "as_of": s["as_of"],
                       "traded_on_market_date": s["traded_on_market_date"],
                       "observations": s["observations"]} for t, s in snaps.items()},
        "table": table,
        "relative": notes,
        "chart": normalised_series(path, list(snaps), sessions),
        "source": D.SOURCE,
        "note": ("Strengths and weaknesses are relative to the other stocks in this comparison only. "
                 "Past returns and indicators do not say which stock will do better, and this is not investment advice."),
    }
