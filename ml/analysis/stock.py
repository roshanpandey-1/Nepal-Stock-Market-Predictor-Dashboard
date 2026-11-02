"""One stock's analysis snapshot: data, calculated measures and rule-based
observations, each labelled with where it came from."""
import numpy as np

from . import data as D
from . import technicals as T

def _f(a, nd=2):
    return T._r(T._last(a), nd)


def _ratio_state(value, lo, hi, low_label, mid_label, high_label):
    if value is None:
        return None
    return low_label if value <= lo else high_label if value >= hi else mid_label


def indicators(h):
    close = h["Close"]
    c = T._last(close)
    bb_hi, bb_lo, atr = T._last(h["BB_High"]), T._last(h["BB_Low"]), T._last(h["ATR"])
    macd, sig = T._last(h["MACD"]), T._last(h["MACD_Signal"])
    hist = h["MACD"] - h["MACD_Signal"]
    rsi = _f(h["RSI_14"], 1)
    sma200 = T.sma(close, 200)
    pct_b = None
    if None not in (c, bb_hi, bb_lo) and bb_hi > bb_lo:
        pct_b = T._r((c - bb_lo) / (bb_hi - bb_lo) * 100, 1)
    return {
        "sma_7": _f(h["SMA_7"]), "sma_21": _f(h["SMA_21"]), "sma_50": _f(h["SMA_50"]),
        "sma_200": sma200,
        "ema_12": _f(h["EMA_12"]), "ema_26": _f(h["EMA_26"]),
        "macd": T._r(macd, 3), "macd_signal": T._r(sig, 3),
        "macd_histogram": T._r(T._last(hist), 3),
        "macd_histogram_5d_change": T._r(hist[-1] - hist[-6], 3) if len(hist) > 6 and np.isfinite(hist[-6]) and np.isfinite(hist[-1]) else None,
        "rsi_14": rsi,
        "rsi_state": _ratio_state(rsi, 30, 70, "oversold (<=30)", "neutral (30-70)", "overbought (>=70)"),
        "stochastic": _f(h["Stoch"], 1),
        "bb_high": T._r(bb_hi), "bb_low": T._r(bb_lo), "bb_width": _f(h["BB_Width"]),
        "bb_percent_b": pct_b,
        "atr_14": T._r(atr), "atr_pct": T._r(atr / c * 100) if atr and c else None,
        "price_vs_sma_50_pct": T._r((c / T._last(h["SMA_50"]) - 1) * 100) if c and T._last(h["SMA_50"]) else None,
        "price_vs_sma_200_pct": T._r((c / sma200 - 1) * 100) if c and sma200 else None,
    }


def crossovers(h, lookback=5):
    return {
        "price_sma_50": T.crossed(h["Close"], h["SMA_50"], lookback),
        "sma_21_sma_50": T.crossed(h["SMA_21"], h["SMA_50"], lookback),
        "macd_signal": T.crossed(h["MACD"], h["MACD_Signal"], lookback),
        "lookback_sessions": lookback,
    }


def _ago(n):
    return "in the latest session" if n == 0 else f"{n} session{'s' if n > 1 else ''} ago"


def observations(snap):
    """Rule-based observations. Each has a side (bullish / bearish / caution /
    neutral), a sentence and the rule that produced it. These describe the
    indicators; they are not recommendations."""
    out = []

    def add(side, text, rule):
        out.append({"side": side, "text": text, "rule": rule})

    ind, cx, tr = snap["indicators"], snap["crossovers"], snap["trend"]
    p, lv, rel = snap["price"], snap["levels"], snap.get("vs_sector") or {}

    if tr["direction"] == "up":
        add("bullish", "Uptrend: price and the 21-day average are above a rising 50-day average.", "trend rule")
    elif tr["direction"] == "down":
        add("bearish", "Downtrend: price and the 21-day average are below a falling 50-day average.", "trend rule")

    for key, label in (("price_sma_50", "Price"), ("sma_21_sma_50", "21-day average")):
        x = cx.get(key)
        if x:
            word = "above" if x["direction"] == "up" else "below"
            add("bullish" if x["direction"] == "up" else "bearish",
                f"{label} crossed {word} the 50-day average {_ago(x['sessions_ago'])}.", "crossover, last 5 sessions")

    x = cx.get("macd_signal")
    if x:
        add("bullish" if x["direction"] == "up" else "bearish",
            f"MACD crossed {'above' if x['direction'] == 'up' else 'below'} its signal line {_ago(x['sessions_ago'])}.",
            "MACD crossover, last 5 sessions")
    elif ind["macd_histogram"] is not None and ind["macd_histogram_5d_change"] is not None:
        if ind["macd_histogram"] > 0 and ind["macd_histogram_5d_change"] > 0:
            add("bullish", "MACD is above its signal line and the gap is widening.", "MACD histogram > 0 and rising over 5 sessions")
        elif ind["macd_histogram"] < 0 and ind["macd_histogram_5d_change"] < 0:
            add("bearish", "MACD is below its signal line and the gap is widening.", "MACD histogram < 0 and falling over 5 sessions")

    rsi = ind["rsi_14"]
    if rsi is not None:
        if rsi >= 70:
            add("caution", f"RSI {rsi} is in the overbought zone; strong recent buying, higher risk of a pullback.", "RSI >= 70")
        elif rsi <= 30:
            add("caution", f"RSI {rsi} is in the oversold zone; heavy recent selling, can stay low in a downtrend.", "RSI <= 30")

    b = ind["bb_percent_b"]
    if b is not None:
        if b > 100:
            add("caution", "Close is above the upper Bollinger Band (unusually stretched upward).", "%B > 100")
        elif b < 0:
            add("caution", "Close is below the lower Bollinger Band (unusually stretched downward).", "%B < 0")

    rv = snap["volume"]["relative_volume"]
    if rv is not None and rv >= 2 and p["change_pct"] is not None:
        if p["change_pct"] > 0:
            add("bullish", f"Price rose on {rv}x its 20-session average volume.", "relative volume >= 2 on an up day")
        elif p["change_pct"] < 0:
            add("bearish", f"Price fell on {rv}x its 20-session average volume.", "relative volume >= 2 on a down day")
        else:
            add("neutral", f"Volume was {rv}x its 20-session average with no price change.", "relative volume >= 2")

    if lv["support"] and lv["support"][0]["distance_pct"] >= -3:
        add("neutral", f"Trading within 3% above support near Rs {lv['support'][0]['level']}.", "nearest support within 3%")
    if lv["resistance"] and lv["resistance"][0]["distance_pct"] <= 3:
        add("neutral", f"Trading within 3% below resistance near Rs {lv['resistance'][0]['level']}.", "nearest resistance within 3%")

    rg = snap["range_1y"]
    if rg and rg["from_high_pct"] is not None and rg["from_high_pct"] >= -5:
        add("bullish", f"Within 5% of its {rg['sessions']}-session high (Rs {rg['high']}).", "close within 5% of period high")
    if rg and rg["from_low_pct"] is not None and rg["from_low_pct"] <= 5:
        add("bearish", f"Within 5% of its {rg['sessions']}-session low (Rs {rg['low']}).", "close within 5% of period low")

    d = rel.get("1M")
    if d is not None and d["difference_pct_points"] is not None:
        if d["difference_pct_points"] >= 5:
            add("bullish", f"Outperformed its sector median by {d['difference_pct_points']} points over 1 month.", "1M return >= sector median + 5")
        elif d["difference_pct_points"] <= -5:
            add("bearish", f"Underperformed its sector median by {abs(d['difference_pct_points'])} points over 1 month.", "1M return <= sector median - 5")
    return out


def snapshot(ticker, path=None, sector_returns=None, market_date=None, names=None):
    """Full analysis for one ticker, or None if there is no data.

    sector_returns: optional {sector: {'1W': median, ...}} from market.sector_performance,
    used for the relative-strength comparison.
    """
    h = D.load_history(ticker, path)
    if h is None or len(h) < 2:
        return None
    close, vol = h["Close"], h["Volume"]
    c, prev = float(close[-1]), float(close[-2])
    names = names if names is not None else D.company_names(path)
    rets = T.period_returns(close)
    snap = {
        "ticker": h.ticker,
        "name": names.get(h.ticker, h.ticker),
        "sector": h.sector,
        "as_of": h.last_date,
        "market_date": market_date,
        "sessions_available": len(h),
        "source": D.SOURCE,
        "price": {
            "close": T._r(c), "prev_close": T._r(prev),
            "change": T._r(c - prev), "change_pct": T._r((c / prev - 1) * 100) if prev > 0 else None,
            "open": _f(h["Open"]), "high": _f(h["High"]), "low": _f(h["Low"]),
        },
        "returns_pct": rets,
        "risk": {
            "volatility_20d_pct": T.volatility(close, 20),
            "volatility_60d_pct": T.volatility(close, 60),
            "max_drawdown_1y_pct": T.max_drawdown(close),
        },
        "volume": {
            "volume": T._r(T._last(vol), 0),
            "turnover": _f(h["Turnover"]),
            "avg_volume_20d": T._r(np.nanmean(vol[-21:-1]), 0) if len(vol) > 21 else None,
            "avg_turnover_20d": T._r(np.nanmean(h["Turnover"][-21:-1])) if len(vol) > 21 else None,
            "relative_volume": T.relative_volume(vol),
        },
        "range_1y": T.range_position(h["High"], h["Low"], close),
        "indicators": indicators(h),
        "crossovers": crossovers(h),
        "trend": T.trend(close, h["SMA_21"], h["SMA_50"]),
        "levels": T.support_resistance(h["High"], h["Low"], close, h.dates),
    }
    # False when the stock did not trade in the latest market session (suspended,
    # illiquid or delisted): its "latest" values are then older than the market's.
    snap["traded_on_market_date"] = None if not market_date else h.last_date == market_date
    sec = (sector_returns or {}).get(h.sector) if h.sector else None
    if sec:
        snap["vs_sector"] = {
            k: {"stock_pct": rets.get(k), "sector_median_pct": sec.get(k),
                "difference_pct_points": T._r(rets[k] - sec[k]) if rets.get(k) is not None and sec.get(k) is not None else None}
            for k in ("1W", "1M", "3M")
        }
    snap["observations"] = observations(snap)
    return snap
