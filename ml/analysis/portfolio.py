"""Portfolio and watchlist checks built from end-of-day data.

Everything here is a fixed rule or plain arithmetic on the user's own holdings; nothing
is predicted. Each flag carries the rule that produced it so the page can show it.

What it is not: it does not compare with the official NEPSE index (we do not keep an
index history), and the "history" of a portfolio is hypothetical: today's quantities
priced at past closes, not the user's actual past balance.
"""
import math
from datetime import date, timedelta

import numpy as np

from . import data as D
from . import external
from . import market
from . import technicals as T

# ---- rule thresholds (shown to the user alongside each flag) ---------------------
MAX_SINGLE_PCT = 25.0        # one stock above this share of the portfolio
MAX_TOP3_PCT = 60.0          # three biggest above this share (only with 5+ holdings)
MAX_SECTOR_PCT = 40.0        # one sector above this share
MIN_HOLDINGS = 5             # fewer than this = "few holdings"
LIQUIDITY_RATIO = 1.0        # position worth more than a day of the stock's average turnover
RSI_HIGH, RSI_LOW = 70.0, 30.0
UNUSUAL_RELVOL, UNUSUAL_MIN_TURNOVER = market.UNUSUAL_RELVOL, market.UNUSUAL_MIN_TURNOVER
BIG_MOVE_PCT = 5.0
NEAR_LEVEL_PCT, MIN_TOUCHES = 2.0, 3
MIN_SESSIONS = 60            # least history needed to quote volatility / drawdown
WINDOW = T.SESSIONS_PER_YEAR


def _f(text, rule, level="watch"):
    return {"text": text, "rule": rule, "level": level}


def stock_flags(r):
    """Rule-based things worth a look for one stock row (market.stock_row)."""
    out = []
    rsi = r.get("rsi_14")
    if rsi is not None and rsi >= RSI_HIGH:
        out.append(_f(f"RSI is {rsi:g}, above {RSI_HIGH:g}: the price has risen fast lately.",
                      f"RSI(14) at or above {RSI_HIGH:g}"))
    if rsi is not None and rsi <= RSI_LOW:
        out.append(_f(f"RSI is {rsi:g}, below {RSI_LOW:g}: the price has fallen fast lately.",
                      f"RSI(14) at or below {RSI_LOW:g}"))
    if r.get("trend") == "down" and (r.get("price_vs_sma_50_pct") or 0) < 0:
        out.append(_f("In a downtrend and trading below its 50-day average.",
                      "Close below SMA 50, SMA 21 below SMA 50, SMA 50 falling"))
    if r.get("trend") == "up":
        out.append(_f("In an uptrend (price above a rising 50-day average).",
                      "Close above SMA 50, SMA 21 above SMA 50, SMA 50 rising", "info"))
    rv, to = r.get("relative_volume"), r.get("turnover") or 0
    if rv is not None and rv >= UNUSUAL_RELVOL and to >= UNUSUAL_MIN_TURNOVER:
        out.append(_f(f"Volume was {rv:g}x its 20-session average.",
                      f"Volume at least {UNUSUAL_RELVOL:g}x average and turnover at least Rs 10 lakh"))
    chg = r.get("change_pct")
    if chg is not None and abs(chg) >= BIG_MOVE_PCT:
        out.append(_f(f"Moved {chg:+.1f}% in the latest session.", f"Daily move of {BIG_MOVE_PCT:g}% or more"))
    sp, st = r.get("support_pct"), r.get("support_touches")
    if sp is not None and abs(sp) <= NEAR_LEVEL_PCT and (st or 0) >= MIN_TOUCHES:
        out.append(_f(f"Within {abs(sp):.1f}% of a support level (price {r.get('support'):g}) tested {st} times.",
                      f"Support within {NEAR_LEVEL_PCT:g}% with at least {MIN_TOUCHES} touches"))
    rp, rt = r.get("resistance_pct"), r.get("resistance_touches")
    if rp is not None and abs(rp) <= NEAR_LEVEL_PCT and (rt or 0) >= MIN_TOUCHES:
        out.append(_f(f"Within {abs(rp):.1f}% of a resistance level (price {r.get('resistance'):g}) tested {rt} times.",
                      f"Resistance within {NEAR_LEVEL_PCT:g}% with at least {MIN_TOUCHES} touches"))
    if r.get("cross_price_sma50"):
        up = r["cross_price_sma50"] == "up"
        out.append(_f(f"Closed {'above' if up else 'below'} its 50-day average within the last 5 sessions.",
                      "Close crossed SMA 50 in the last 5 sessions"))
    if r.get("cross_macd"):
        up = r["cross_macd"] == "up"
        out.append(_f(f"MACD crossed {'above' if up else 'below'} its signal line within the last 5 sessions.",
                      "MACD crossed its signal line in the last 5 sessions"))
    fh = r.get("from_high_pct")
    if fh is not None and fh >= -3:
        out.append(_f("Within 3% of its 52-week high.", "Close within 3% of the highest high in 245 sessions", "info"))
    fl = r.get("from_low_pct")
    if fl is not None and fl <= 3:
        out.append(_f("Within 3% of its 52-week low.", "Close within 3% of the lowest low in 245 sessions"))
    return out


# ---- portfolio -------------------------------------------------------------------
def concentration(rows):
    """How spread out the holdings are, from valued rows (portfolio_utils.value_holdings)."""
    priced = [r for r in rows if r.get("value_ltp")]
    total = sum(r["value_ltp"] for r in priced)
    if not priced or total <= 0:
        return None
    w = sorted(((r["value_ltp"] / total * 100, r) for r in priced), key=lambda x: -x[0])
    weights = [x[0] for x in w]
    hhi = sum((x / 100) ** 2 for x in weights)
    sectors = {}
    for pct, r in w:
        sectors[r.get("sector") or "No sector"] = sectors.get(r.get("sector") or "No sector", 0) + pct
    sector_list = sorted(({"sector": s, "share_pct": round(v, 1)} for s, v in sectors.items()),
                         key=lambda x: -x["share_pct"])
    flags = []
    if len(priced) < MIN_HOLDINGS:
        flags.append(_f(f"You hold {len(priced)} stock{'s' if len(priced) != 1 else ''}; with so few, "
                        "one company's bad news moves the whole portfolio.",
                        f"Fewer than {MIN_HOLDINGS} priced holdings"))
    if weights[0] > MAX_SINGLE_PCT and len(priced) > 1:
        flags.append(_f(f"{w[0][1]['ticker']} is {weights[0]:.0f}% of the portfolio.",
                        f"One holding above {MAX_SINGLE_PCT:g}% of portfolio value"))
    if len(priced) >= MIN_HOLDINGS and sum(weights[:3]) > MAX_TOP3_PCT:
        flags.append(_f(f"Your three largest holdings are {sum(weights[:3]):.0f}% of the portfolio.",
                        f"Top three above {MAX_TOP3_PCT:g}% (with {MIN_HOLDINGS}+ holdings)"))
    if sector_list[0]["share_pct"] > MAX_SECTOR_PCT and sector_list[0]["sector"] != "No sector":
        flags.append(_f(f"{sector_list[0]['share_pct']:.0f}% of the portfolio is in {sector_list[0]['sector']}, "
                        "so a bad stretch for that sector would hit most of your money.",
                        f"One sector above {MAX_SECTOR_PCT:g}% of portfolio value"))
    return {
        "holdings": len(priced),
        "largest": {"ticker": w[0][1]["ticker"], "share_pct": round(weights[0], 1)},
        "top3_pct": round(sum(weights[:3]), 1),
        "effective_holdings": round(1 / hhi, 1) if hhi else None,
        "sectors": sector_list,
        "weights": [{"ticker": r["ticker"], "share_pct": round(p, 1)} for p, r in w],
        "flags": flags,
        "note": ("Effective holdings is the number of equal-sized positions that would be as concentrated "
                 "as yours; ten stocks where one is half the portfolio behave more like two or three."),
    }


def _series(h):
    out = {}
    for d, c in zip(h.dates, h["Close"]):
        c = float(c)
        if math.isfinite(c) and c > 0:
            out[d] = c
    return out


def basket(quantities, path=None):
    """Value of today's quantities at each past close, forward-filling days a stock did not trade.

    Returns (dates, values, per-ticker matrix of closes, tickers used, tickers missing) or None.
    """
    hs = {t: D.load_history(t, path) for t in quantities}
    used = [t for t, h in sorted(hs.items()) if h is not None and len(h)]
    missing = [t for t in sorted(hs) if t not in used]
    if not used:
        return None
    series = {t: _series(hs[t]) for t in used}
    start = max(min(s) for s in series.values())
    dates = sorted({d for s in series.values() for d in s if d >= start})
    if len(dates) < MIN_SESSIONS + 1:
        return None
    dates = dates[-(WINDOW + 1):]
    mat = np.full((len(dates), len(used)), np.nan)
    for j, t in enumerate(used):
        last = None
        # seed with the latest close at or before the first date
        before = [d for d in series[t] if d <= dates[0]]
        if before:
            last = series[t][max(before)]
        for i, d in enumerate(dates):
            last = series[t].get(d, last)
            mat[i, j] = last if last is not None else np.nan
    if np.isnan(mat).any():
        return None
    return dates, mat, used, missing


def risk(quantities, path=None, table_rows=None):
    """Volatility, worst fall and recent returns of today's holdings, plus each holding's
    share of the day-to-day variation. Hypothetical: today's quantities at past closes."""
    b = basket({t: q for t, q in quantities.items() if q}, path)
    if b is None:
        return None
    dates, mat, used, missing = b
    qty = np.array([quantities[t] for t in used], dtype=float)
    values = mat @ qty
    rets = values[1:] / values[:-1] - 1
    if len(rets) < MIN_SESSIONS:
        return None
    out = {
        "sessions": len(rets),
        "from": dates[0], "to": dates[-1],
        "volatility_pct": T._r(float(np.std(rets, ddof=1)) * math.sqrt(T.SESSIONS_PER_YEAR) * 100),
        "max_drawdown_pct": T.max_drawdown(values),
        "ret_1m": T._r((values[-1] / values[-22] - 1) * 100) if len(values) > 22 else None,
        "ret_3m": T._r((values[-1] / values[-64] - 1) * 100) if len(values) > 64 else None,
        "missing": missing,
    }
    if table_rows:
        med = lambda k: market._median([r[k] for r in table_rows])
        out["median_stock_1m"], out["median_stock_3m"] = med("ret_1m"), med("ret_3m")
    stock_rets = mat[1:] / mat[:-1] - 1
    w = (mat[-1] * qty) / float((mat[-1] * qty).sum())
    if len(used) >= 2:
        cov = np.cov(stock_rets, rowvar=False)
        var = float(w @ cov @ w)
        if var > 0:
            share = w * (cov @ w) / var * 100
            out["variance_share"] = sorted(
                ({"ticker": t, "weight_pct": round(float(w[i] * 100), 1), "risk_share_pct": round(float(share[i]), 1)}
                 for i, t in enumerate(used)), key=lambda x: -x["risk_share_pct"])
    out["note"] = ("Worked out from today's quantities priced at past closes, so it shows how this mix "
                   "would have behaved, not what you actually earned. It is not compared with the NEPSE index "
                   "because we do not keep an index history; the comparison is with the median tracked stock.")
    return out


def holdings_view(valued_rows, by_ticker):
    """One entry per holding: its latest metrics, rule flags, and how big the position is
    compared with what the stock normally trades."""
    out = []
    for r in valued_rows:
        row = by_ticker.get(r["ticker"])
        entry = {"ticker": r["ticker"], "name": r.get("name"), "sector": r.get("sector"),
                 "value": r.get("value_ltp"), "flags": []}
        if row:
            entry.update({k: row.get(k) for k in ("trend", "rsi_14", "ret_1m", "relative_volume", "change_pct")})
            entry["flags"] = stock_flags(row)
            avg = row.get("avg_turnover_20d")
            if avg and r.get("value_ltp") and r["value_ltp"] / avg >= LIQUIDITY_RATIO:
                entry["flags"].append(_f(
                    f"Your position (Rs {r['value_ltp']:,.0f}) is {r['value_ltp'] / avg:.1f}x what this stock "
                    f"trades on an average day (Rs {avg:,.0f}); selling it all may take several sessions "
                    "or move the price.",
                    f"Position value at least {LIQUIDITY_RATIO:g}x the 20-session average daily turnover"))
        out.append(entry)
    return out


def intelligence(valued_rows, quantities, path=None):
    """Everything for the portfolio check page."""
    market_date, table = market.stock_table(path)
    by_ticker = {r["ticker"]: r for r in table}
    return {
        "as_of": market_date,
        "basis": "End-of-day data for the latest completed session.",
        "concentration": concentration(valued_rows),
        "risk": risk(quantities, path, table),
        "holdings": holdings_view(valued_rows, by_ticker),
        "disclaimer": "Checks from fixed rules on your holdings, for research. Not a recommendation to buy, sell or hold.",
    }


# ---- watchlist -------------------------------------------------------------------
def watchlist_view(tickers, path=None, news_days=14):
    market_date, table = market.stock_table(path)
    by = {r["ticker"]: r for r in table}
    since = (date.today() - timedelta(days=news_days)).isoformat()
    rows = []
    for t in tickers:
        r = by.get(t)
        if not r:
            rows.append({"ticker": t, "missing": True})
            continue
        ann = external.announcements(path, ticker=t, since=since, limit=3)["items"]
        rows.append({
            **{k: r.get(k) for k in ("ticker", "name", "sector", "date", "close", "change_pct", "ret_1w", "ret_1m",
                                     "rsi_14", "trend", "relative_volume", "support", "support_pct",
                                     "resistance", "resistance_pct")},
            "traded_on_market_date": r["date"] == market_date,
            "flags": [f for f in stock_flags(r) if f["level"] != "info" or f["text"].startswith("In an uptrend")],
            "recent_news": [{k: a[k] for k in ("title", "url", "date", "category_label")} for a in ann],
        })
    movers = [r for r in rows if not r.get("missing") and r.get("change_pct") is not None]
    movers.sort(key=lambda r: r["change_pct"])
    return {
        "as_of": market_date,
        "basis": "End-of-day data for the latest completed session.",
        "rows": rows,
        "summary": {
            "count": len(rows),
            "with_flags": sum(1 for r in rows if any(f["level"] == "watch" for f in r.get("flags", []))),
            "biggest_gain": {"ticker": movers[-1]["ticker"], "change_pct": movers[-1]["change_pct"]} if movers else None,
            "biggest_fall": {"ticker": movers[0]["ticker"], "change_pct": movers[0]["change_pct"]} if movers else None,
        },
    }
