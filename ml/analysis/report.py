"""Turns a stock snapshot into a readable report.

The wording comes from fixed rules applied to the calculated values -- there
is no language model involved -- so every sentence can be traced to a number
in the snapshot. Each section says what kind of content it holds:

* "data"        -- read straight from the daily price files
* "calculated"  -- computed from that data by a stated formula
* "rules"       -- an interpretation produced by fixed, documented rules
"""
from . import technicals as T

DISCLAIMER = ("Generated automatically by fixed rules from end-of-day data. It describes what the "
              "indicators show; it is not a forecast, a recommendation, or investment advice.")


def _fmt_pct(x, signed=True):
    if x is None:
        return "n/a"
    return f"{x:+.2f}%" if signed else f"{x:.2f}%"


def _rs(x):
    return "n/a" if x is None else f"Rs {x:,.2f}"


def _rs_big(x):
    """Large rupee amounts in the Nepali units people use (lakh, crore, arba)."""
    if x is None:
        return "n/a"
    for div, unit in ((1e9, "arba"), (1e7, "crore"), (1e5, "lakh")):
        if abs(x) >= div:
            return f"Rs {x / div:,.2f} {unit}"
    return _rs(x)


def _num(x, nd=0):
    if x is None:
        return "n/a"
    return f"{x:,.{nd}f}"


def percentile(value, population):
    """Share (%) of the population at or below value; None if not computable."""
    pop = [p for p in population if p is not None]
    if value is None or not pop:
        return None
    return round(sum(1 for p in pop if p <= value) / len(pop) * 100)


def overview(s):
    p, r, v = s["price"], s["returns_pct"], s["volume"]
    lines = [
        f"{s['name']} ({s['ticker']}, {s['sector'] or 'sector unknown'}) closed at {_rs(p['close'])} on "
        f"{s['as_of']}, {_fmt_pct(p['change_pct'])} ({p['change']:+,.2f}) from the previous session."
        if p["change"] is not None else f"{s['name']} ({s['ticker']}) closed at {_rs(p['close'])} on {s['as_of']}.",
        "Returns: " + ", ".join(f"{k} {_fmt_pct(r[k])}" for k in ("1W", "1M", "3M", "6M", "1Y") if r.get(k) is not None) + ".",
        f"Volume {_num(v['volume'])} shares, turnover {_rs_big(v['turnover'])}"
        + (f", {v['relative_volume']}x its 20-session average volume." if v["relative_volume"] is not None else "."),
    ]
    if s.get("traded_on_market_date") is False:
        lines.insert(0, f"Note: {s['ticker']} did not trade in the latest market session ({s['market_date']}); "
                        f"these figures are from its last trade on {s['as_of']}.")
    return {"title": "Overview", "basis": "data", "lines": lines}


def technical(s):
    i = s["indicators"]
    rows = []

    def row(name, value, reading):
        rows.append({"indicator": name, "value": value, "reading": reading})

    if i["rsi_14"] is not None:
        rsi = i["rsi_14"]
        reading = ("overbought zone (70 or more): strong recent buying" if rsi >= 70 else
                   "oversold zone (30 or less): heavy recent selling" if rsi <= 30 else
                   "above 50: buyers slightly stronger recently" if rsi > 50 else
                   "below 50: sellers slightly stronger recently")
        row("RSI (14)", f"{rsi}", reading)
    if i["macd"] is not None and i["macd_signal"] is not None:
        above = i["macd"] > i["macd_signal"]
        ch = i["macd_histogram_5d_change"]
        reading = (f"MACD {'above' if above else 'below'} its signal line"
                   + ("" if ch is None else f"; gap {'widening' if (ch > 0) == above else 'narrowing'} over 5 sessions"))
        row("MACD (12, 26, 9)", f"{i['macd']} vs signal {i['macd_signal']}", reading)
    for key, label in (("sma_50", "50-day average"), ("sma_200", "200-day average")):
        if i[key] is not None:
            diff = i[f"price_vs_{key}_pct"]
            row(f"SMA {key.split('_')[1]}", _rs(i[key]),
                "n/a" if diff is None else f"price {abs(diff):.2f}% {'above' if diff >= 0 else 'below'} the {label}")
    if i["sma_21"] is not None and i["sma_50"] is not None:
        row("SMA 21 vs SMA 50", f"{_rs(i['sma_21'])} vs {_rs(i['sma_50'])}",
            "short-term average above the medium-term one" if i["sma_21"] > i["sma_50"]
            else "short-term average below the medium-term one")
    if i["bb_percent_b"] is not None:
        b = i["bb_percent_b"]
        row("Bollinger Bands (20, 2)", f"{_rs(i['bb_low'])} - {_rs(i['bb_high'])}",
            f"close at {b}% of the band" + (" (above the upper band)" if b > 100 else
                                            " (below the lower band)" if b < 0 else
                                            " (upper half)" if b >= 50 else " (lower half)"))
    if i["stochastic"] is not None:
        st = i["stochastic"]
        row("Stochastic %K (14)", f"{st}", "near the top of its recent range" if st >= 80 else
            "near the bottom of its recent range" if st <= 20 else "mid-range")
    if i["atr_14"] is not None:
        row("ATR (14)", _rs(i["atr_14"]), f"typical daily range is about {_fmt_pct(i['atr_pct'], False)} of the price")
    return {"title": "Technical indicators", "basis": "calculated", "rows": rows}


TREND_TEXT = {
    "up": "Uptrend: the close and the 21-day average are above the 50-day average, and the 50-day average is rising.",
    "down": "Downtrend: the close and the 21-day average are below the 50-day average, and the 50-day average is falling.",
    "sideways": "Sideways or mixed: price and its averages do not line up in one direction.",
    "unknown": "Not enough data to judge the trend.",
}


def trend(s):
    t = s["trend"]
    lines = [TREND_TEXT[t["direction"]]]
    if t["sma50_slope_10d_pct"] is not None:
        lines.append(f"The 50-day average changed {_fmt_pct(t['sma50_slope_10d_pct'])} over the last 10 sessions.")
    vs = s.get("vs_sector") or {}
    for k in ("1M", "3M"):
        d = vs.get(k)
        if d and d["difference_pct_points"] is not None:
            lines.append(f"{k}: stock {_fmt_pct(d['stock_pct'])} vs sector median {_fmt_pct(d['sector_median_pct'])} "
                         f"({d['difference_pct_points']:+.2f} points).")
    return {"title": "Trend", "basis": "rules", "direction": t["direction"], "lines": lines,
            "rule": "Up: close > SMA50, SMA21 > SMA50 and SMA50 rising over 10 sessions; down: the reverse; otherwise sideways."}


def levels(s):
    lv, rg, i = s["levels"], s["range_1y"], s["indicators"]
    ref = []
    if rg:
        ref.append({"label": f"{rg['sessions']}-session high", "level": rg["high"], "distance_pct": rg["from_high_pct"]})
        ref.append({"label": f"{rg['sessions']}-session low", "level": rg["low"], "distance_pct": rg["from_low_pct"]})
    c = s["price"]["close"]
    for key, label in (("sma_50", "50-day average"), ("sma_200", "200-day average")):
        if i[key]:
            ref.append({"label": label, "level": i[key], "distance_pct": T._r((i[key] / c - 1) * 100)})
    return {"title": "Important price levels", "basis": "calculated", "support": lv["support"],
            "resistance": lv["resistance"], "reference": ref, "method": lv["method"]}


def risk(s, table):
    v, rk = s["volume"], s["risk"]
    vol_pct = percentile(rk["volatility_20d_pct"], [r["volatility_20d"] for r in table])
    liq_pct = percentile(v["avg_turnover_20d"], [r.get("avg_turnover_20d") for r in table])
    level = None if vol_pct is None else "higher" if vol_pct >= 67 else "lower" if vol_pct <= 33 else "average"
    lines = []
    if rk["volatility_20d_pct"] is not None:
        lines.append(f"20-session volatility {rk['volatility_20d_pct']}% a year (60-session: {rk['volatility_60d_pct']}%), "
                     f"at or above {vol_pct}% of tracked stocks." if vol_pct is not None else
                     f"20-session volatility {rk['volatility_20d_pct']}% a year.")
    if rk["max_drawdown_1y_pct"] is not None:
        lines.append(f"Largest fall from a peak in the last year: {rk['max_drawdown_1y_pct']}%.")
    if v["avg_turnover_20d"] is not None:
        thin = liq_pct is not None and liq_pct <= 25
        lines.append(f"Average daily turnover over 20 sessions: {_rs_big(v['avg_turnover_20d'])}"
                     + (f" (at or above {liq_pct}% of tracked stocks)" if liq_pct is not None else "")
                     + (". Thin trading: prices can jump on small orders and exits can be slow." if thin else "."))
    rsi = s["indicators"]["rsi_14"]
    if rsi is not None and (rsi >= 70 or rsi <= 30):
        lines.append(f"RSI {rsi} is at an extreme, which often comes with sharp moves either way.")
    if s.get("traded_on_market_date") is False:
        lines.append("It did not trade in the latest session (possible suspension or very low liquidity).")
    lines.append("Not assessed here: company financials, dividends, news and regulatory events.")
    return {"title": "Risk assessment", "basis": "calculated", "volatility_level": level,
            "volatility_percentile": vol_pct, "liquidity_percentile": liq_pct, "lines": lines}


def summary(s, risk_section):
    obs = s["observations"]
    bull = sum(1 for o in obs if o["side"] == "bullish")
    bear = sum(1 for o in obs if o["side"] == "bearish")
    caution = sum(1 for o in obs if o["side"] in ("caution", "neutral"))
    tone = ("mostly positive" if bull >= bear + 2 else "mostly negative" if bear >= bull + 2 else "mixed")
    lv = s["levels"]
    parts = [f"Technical picture: {tone} ({bull} positive, {bear} negative, {caution} to watch)."]
    parts.append(f"Trend: {s['trend']['direction']}.")
    if lv["support"]:
        parts.append(f"Nearest support {_rs(lv['support'][0]['level'])} ({_fmt_pct(lv['support'][0]['distance_pct'])}).")
    if lv["resistance"]:
        parts.append(f"Nearest resistance {_rs(lv['resistance'][0]['level'])} ({_fmt_pct(lv['resistance'][0]['distance_pct'])}).")
    if risk_section["volatility_level"]:
        parts.append(f"Volatility is {risk_section['volatility_level']} than most tracked stocks."
                     if risk_section["volatility_level"] != "average" else "Volatility is about average for tracked stocks.")
    return {"title": "Summary", "basis": "rules", "tone": tone, "counts": {"positive": bull, "negative": bear, "watch": caution},
            "text": " ".join(parts), "disclaimer": DISCLAIMER}


def build(s, table):
    """Report dict for a stock snapshot `s`; `table` is market.stock_table()'s rows."""
    rsk = risk(s, table)
    obs = s["observations"]
    return {
        "ticker": s["ticker"], "name": s["name"], "sector": s["sector"],
        "as_of": s["as_of"], "market_date": s["market_date"], "source": s["source"],
        "sections": {
            "overview": overview(s),
            "technical": technical(s),
            "trend": trend(s),
            "signals": {"title": "Bullish and bearish signals", "basis": "rules",
                        "bullish": [o for o in obs if o["side"] == "bullish"],
                        "bearish": [o for o in obs if o["side"] == "bearish"],
                        "caution": [o for o in obs if o["side"] in ("caution", "neutral")]},
            "levels": levels(s),
            "risk": rsk,
            "summary": summary(s, rsk),
        },
    }
