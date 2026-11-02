"""Stock discovery: research filters over market.stock_table() rows.

Every preset is a fixed, documented rule. Results are lists of stocks that
match a rule today -- starting points for research, not buy or sell calls.
"""
from . import market as M

MIN_TURNOVER_DEFAULT = 0


def _ge(x, v):
    return x is not None and x >= v


def _le(x, v):
    return x is not None and x <= v


PRESETS = {
    "momentum_up": ("Strong positive momentum",
                    "Up 10% or more over 1 month and in an uptrend (close and 21-day average above a rising 50-day average).",
                    lambda r: _ge(r["ret_1m"], 10) and r["trend"] == "up"),
    "momentum_down": ("Strong negative momentum",
                      "Down 10% or more over 1 month and in a downtrend.",
                      lambda r: _le(r["ret_1m"], -10) and r["trend"] == "down"),
    "unusual_volume": ("Unusual volume",
                       f"Latest session volume at least {M.UNUSUAL_RELVOL:g}x the 20-session average, with at least Rs 10 lakh traded.",
                       lambda r: _ge(r["relative_volume"], M.UNUSUAL_RELVOL) and _ge(r["turnover"], M.UNUSUAL_MIN_TURNOVER)),
    "near_support": ("Approaching support",
                     "Close within 2% above the nearest support level that price has turned at 3 or more times "
                     "(swing highs/lows over the last 120 sessions).",
                     lambda r: r["support_pct"] is not None and r["support_pct"] >= -2 and _ge(r["support_touches"], 3)),
    "near_resistance": ("Approaching resistance",
                        "Close within 2% below the nearest resistance level that price has turned at 3 or more times.",
                        lambda r: r["resistance_pct"] is not None and r["resistance_pct"] <= 2 and _ge(r["resistance_touches"], 3)),
    "rsi_oversold": ("RSI oversold", "RSI (14) at 30 or below.", lambda r: _le(r["rsi_14"], 30)),
    "rsi_overbought": ("RSI overbought", "RSI (14) at 70 or above.", lambda r: _ge(r["rsi_14"], 70)),
    "improving": ("Improving technicals",
                  "In the last 5 sessions the price crossed above its 50-day average or MACD crossed above its signal line, "
                  "and now both the price is above the 50-day average and MACD is above its signal line.",
                  lambda r: "up" in (r["cross_price_sma50"], r["cross_macd"]) and _ge(r["price_vs_sma_50_pct"], 0)
                  and r["macd_above_signal"] is True),
    "weakening": ("Weakening technicals",
                  "In the last 5 sessions the price crossed below its 50-day average or MACD crossed below its signal line, "
                  "and now both the price is below the 50-day average and MACD is below its signal line.",
                  lambda r: "down" in (r["cross_price_sma50"], r["cross_macd"]) and _le(r["price_vs_sma_50_pct"], 0)
                  and r["macd_above_signal"] is False),
    "outperform_sector": ("Outperforming its sector",
                          "1-month return at least 5 points above its sector's median 1-month return.",
                          lambda r: _ge(r.get("vs_sector_1m"), 5)),
    "underperform_sector": ("Underperforming its sector",
                            "1-month return at least 5 points below its sector's median 1-month return.",
                            lambda r: _le(r.get("vs_sector_1m"), -5)),
    "near_high": ("Near 1-year high", "Close within 5% of its 1-year high.", lambda r: _ge(r["from_high_pct"], -5)),
    "near_low": ("Near 1-year low", "Close within 5% of its 1-year low.", lambda r: _le(r["from_low_pct"], 5)),
}

SORTABLE = {"ticker", "close", "change_pct", "ret_1w", "ret_1m", "ret_3m", "ret_1y", "turnover", "avg_turnover_20d",
            "relative_volume", "rsi_14", "volatility_20d", "from_high_pct", "support_pct", "resistance_pct", "vs_sector_1m",
            "pe", "pbv"}
DEFAULT_SORT = {"momentum_up": "ret_1m", "momentum_down": "ret_1m", "unusual_volume": "relative_volume",
                "near_support": "support_pct", "near_resistance": "resistance_pct", "rsi_oversold": "rsi_14",
                "rsi_overbought": "rsi_14", "outperform_sector": "vs_sector_1m", "underperform_sector": "vs_sector_1m",
                "near_high": "from_high_pct", "near_low": "from_low_pct"}
ASCENDING_DEFAULT = {"momentum_down", "rsi_oversold", "near_resistance", "underperform_sector", "near_low"}


def _f(v):
    try:
        return None if v in (None, "") else float(v)
    except (TypeError, ValueError):
        return None


def presets():
    return [{"key": k, "label": v[0], "rule": v[1]} for k, v in PRESETS.items()]


def run(path=None, preset=None, sector=None, min_price=None, max_price=None, min_avg_turnover=None,
        max_pe=None, max_pbv=None,
        min_rsi=None, max_rsi=None, min_ret_1m=None, max_ret_1m=None, trend=None,
        include_not_traded=False, sort=None, descending=None, limit=200):
    """Filtered, sorted rows plus the rules that were applied."""
    from . import external
    date, rows = M.stock_table(path)
    sectors = M.sector_medians(M.sector_performance(rows, date))
    fmap = external.fundamentals_map(path)
    out = []
    for r in rows:
        med = (sectors.get(r["sector"]) or {}).get("1M")
        f = fmap.get(r["ticker"]) or {}
        eps, bv = f.get("eps"), f.get("book_value")
        r = dict(r, vs_sector_1m=round(r["ret_1m"] - med, 2) if r["ret_1m"] is not None and med is not None else None,
                 traded_on_market_date=r["date"] == date,
                 eps=eps, pe=round(r["close"] / eps, 2) if eps and eps > 0 and r["close"] else None,
                 pbv=round(r["close"] / bv, 2) if bv and bv > 0 and r["close"] else None)
        out.append(r)

    applied = []
    if preset:
        if preset not in PRESETS:
            raise ValueError(f"unknown preset {preset!r}")
        label, rule, pred = PRESETS[preset]
        out = [r for r in out if pred(r)]
        applied.append(f"{label}: {rule}")
    if not include_not_traded:
        out = [r for r in out if r["traded_on_market_date"]]
        applied.append(f"Traded in the latest session ({date}).")
    checks = [
        (sector, lambda r, v: r["sector"] == v, "Sector: {}"),
        (_f(min_price), lambda r, v: _ge(r["close"], v), "Price at least Rs {:,.0f}"),
        (_f(max_price), lambda r, v: _le(r["close"], v), "Price at most Rs {:,.0f}"),
        (_f(min_avg_turnover), lambda r, v: _ge(r["avg_turnover_20d"], v), "Average daily turnover at least Rs {:,.0f}"),
        (_f(min_rsi), lambda r, v: _ge(r["rsi_14"], v), "RSI at least {:g}"),
        (_f(max_rsi), lambda r, v: _le(r["rsi_14"], v), "RSI at most {:g}"),
        (_f(min_ret_1m), lambda r, v: _ge(r["ret_1m"], v), "1-month return at least {:g}%"),
        (_f(max_ret_1m), lambda r, v: _le(r["ret_1m"], v), "1-month return at most {:g}%"),
        (_f(max_pe), lambda r, v: r["pe"] is not None and r["pe"] <= v, "P/E (latest close / reported EPS) at most {:g}, positive EPS only"),
        (_f(max_pbv), lambda r, v: _le(r["pbv"], v), "Price to book at most {:g}"),
        (trend if trend in ("up", "down", "sideways") else None, lambda r, v: r["trend"] == v, "Trend: {}"),
    ]
    for value, pred, text in checks:
        if value is None or value == "":
            continue
        out = [r for r in out if pred(r, value)]
        applied.append(text.format(value))

    key = sort if sort in SORTABLE else DEFAULT_SORT.get(preset, "turnover")
    if descending is None:
        descending = preset not in ASCENDING_DEFAULT
        if key in ("support_pct",):
            descending = True     # closest to support first (least negative)
    out.sort(key=lambda r: (r[key] is None, r[key] if not descending or r[key] is None
                            else (-r[key] if isinstance(r[key], (int, float)) else r[key])))
    if descending and key == "ticker":
        out.reverse()
    return {"as_of": date, "preset": preset, "applied": applied, "count": len(out),
            "sort": key, "descending": descending, "rows": out[:limit],
            "note": "Research filters only: a stock appearing here is not a recommendation to buy or sell."}
