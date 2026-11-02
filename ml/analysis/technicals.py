"""Calculated measures for one stock. Pure functions over numpy arrays.

Conventions (stated so every number can be checked by hand):
* Periods are counted in trading sessions, not calendar days:
  1W = 5, 1M = 21, 3M = 63, 6M = 126, 1Y = 245 sessions (NEPSE trades
  about 240-250 days a year).
* Returns are simple close-to-close returns in percent.
* Volatility is the standard deviation of daily close-to-close returns,
  annualised with sqrt(245), in percent.
* Relative volume = latest session volume / mean volume of the 20 sessions
  before it.
"""
import math

import numpy as np

PERIODS = {"1D": 1, "1W": 5, "1M": 21, "3M": 63, "6M": 126, "1Y": 245}
SESSIONS_PER_YEAR = 245


def _last(a):
    a = np.asarray(a, dtype=float)
    return float(a[-1]) if len(a) and np.isfinite(a[-1]) else None


def _r(x, nd=2):
    return None if x is None or not math.isfinite(x) else round(float(x), nd)


def period_returns(close):
    """{'1D': pct, ...}; None when the history is too short."""
    close = np.asarray(close, dtype=float)
    out = {}
    for name, n in PERIODS.items():
        if len(close) > n and close[-1 - n] > 0:
            out[name] = _r((close[-1] / close[-1 - n] - 1) * 100)
        else:
            out[name] = None
    return out


def daily_returns(close):
    close = np.asarray(close, dtype=float)
    if len(close) < 2:
        return np.array([])
    prev = close[:-1]
    with np.errstate(divide="ignore", invalid="ignore"):
        r = close[1:] / prev - 1
    return r[np.isfinite(r)]


def volatility(close, window):
    """Annualised volatility (%) over the last `window` daily returns."""
    r = daily_returns(close)[-window:]
    if len(r) < max(5, window // 2):
        return None
    return _r(np.std(r, ddof=1) * math.sqrt(SESSIONS_PER_YEAR) * 100)


def max_drawdown(close, window=SESSIONS_PER_YEAR):
    """Largest peak-to-trough fall (%) within the last `window` sessions."""
    c = np.asarray(close, dtype=float)[-window:]
    c = c[np.isfinite(c)]
    if len(c) < 2:
        return None
    peak = np.maximum.accumulate(c)
    return _r(((c / peak) - 1).min() * 100)


def relative_volume(volume, window=20):
    v = np.asarray(volume, dtype=float)
    if len(v) < window + 1:
        return None
    base = v[-window - 1:-1]
    base = base[np.isfinite(base)]
    if not len(base) or base.mean() <= 0 or not np.isfinite(v[-1]):
        return None
    return _r(v[-1] / base.mean())


def range_position(high, low, close, window=SESSIONS_PER_YEAR):
    """52-week style high/low and where the close sits (0% = low, 100% = high)."""
    h = np.asarray(high, dtype=float)[-window:]
    l = np.asarray(low, dtype=float)[-window:]
    c = _last(close)
    if c is None or not len(h):
        return None
    hi, lo = np.nanmax(h), np.nanmin(l)
    return {
        "sessions": int(len(h)),
        "high": _r(hi), "low": _r(lo),
        "from_high_pct": _r((c / hi - 1) * 100) if hi > 0 else None,
        "from_low_pct": _r((c / lo - 1) * 100) if lo > 0 else None,
        "position_pct": _r((c - lo) / (hi - lo) * 100) if hi > lo else None,
    }


def sma(values, n):
    v = np.asarray(values, dtype=float)
    if len(v) < n:
        return None
    w = v[-n:]
    return _r(w.mean()) if np.all(np.isfinite(w)) else None


def crossed(a, b, lookback=5):
    """'up' if series a moved from below b to above it within the last
    `lookback` sessions, 'down' for the reverse, else None. Uses the most
    recent crossing."""
    a, b = np.asarray(a, dtype=float), np.asarray(b, dtype=float)
    n = min(len(a), len(b))
    if n < 2:
        return None
    d = (a - b)[-(lookback + 1):]
    for i in range(len(d) - 1, 0, -1):
        if not (np.isfinite(d[i]) and np.isfinite(d[i - 1])):
            continue
        if d[i - 1] <= 0 < d[i]:
            return {"direction": "up", "sessions_ago": len(d) - 1 - i}
        if d[i - 1] >= 0 > d[i]:
            return {"direction": "down", "sessions_ago": len(d) - 1 - i}
    return None


def slope_pct(values, n=10):
    """Change of a series over the last n sessions, in % of its earlier value."""
    v = np.asarray(values, dtype=float)
    if len(v) <= n or not np.isfinite(v[-1]) or not np.isfinite(v[-1 - n]) or v[-1 - n] == 0:
        return None
    return _r((v[-1] / v[-1 - n] - 1) * 100)


def swing_points(high, low, k=3):
    """Indices of swing highs/lows: a bar whose high (low) is the strict
    maximum (minimum) of the k bars on each side."""
    h, l = np.asarray(high, dtype=float), np.asarray(low, dtype=float)
    highs, lows = [], []
    for i in range(k, len(h) - k):
        win_h, win_l = h[i - k:i + k + 1], l[i - k:i + k + 1]
        if np.isfinite(h[i]) and h[i] == np.nanmax(win_h) and np.sum(win_h == h[i]) == 1:
            highs.append(i)
        if np.isfinite(l[i]) and l[i] == np.nanmin(win_l) and np.sum(win_l == l[i]) == 1:
            lows.append(i)
    return highs, lows


def support_resistance(high, low, close, dates, lookback=120, k=3, tolerance_pct=2.0, max_levels=3):
    """Support and resistance zones from swing points.

    Method: take swing highs and lows (see swing_points) from the last
    `lookback` sessions, group prices that lie within `tolerance_pct` of each
    other, and report each group as a level (its average price) with the number
    of swings in it ("touches") and the date of the latest one. Levels below
    the last close are support, above it resistance; nearest first.
    """
    n = len(close)
    start = max(0, n - lookback)
    h, l = np.asarray(high, dtype=float)[start:], np.asarray(low, dtype=float)[start:]
    c = _last(close)
    if c is None or len(h) < 2 * k + 1:
        return {"support": [], "resistance": [], "method": None}
    sh, sl = swing_points(h, l, k)
    pts = sorted([(float(h[i]), start + i) for i in sh] + [(float(l[i]), start + i) for i in sl])
    groups = []
    for price, idx in pts:
        if groups and price <= groups[-1]["base"] * (1 + tolerance_pct / 100):
            groups[-1]["prices"].append(price)
            groups[-1]["idx"].append(idx)
        else:
            groups.append({"base": price, "prices": [price], "idx": [idx]})
    levels = []
    for g in groups:
        lvl = float(np.mean(g["prices"]))
        levels.append({
            "level": _r(lvl),
            "touches": len(g["prices"]),
            "last_touch": dates[max(g["idx"])],
            "distance_pct": _r((lvl / c - 1) * 100),
        })
    support = sorted([x for x in levels if x["level"] < c], key=lambda x: -x["level"])[:max_levels]
    resistance = sorted([x for x in levels if x["level"] > c], key=lambda x: x["level"])[:max_levels]
    return {
        "support": support,
        "resistance": resistance,
        "method": (f"Swing highs/lows ({k} sessions each side) over the last {min(lookback, n)} "
                   f"sessions, grouped within {tolerance_pct:g}%"),
    }


def trend(close, sma21, sma50):
    """Trend from price vs SMA 50, SMA 21 vs SMA 50 and the SMA 50 slope.

    up: close > SMA50, SMA21 > SMA50 and SMA50 rising over 10 sessions
    down: close < SMA50, SMA21 < SMA50 and SMA50 falling
    otherwise sideways/mixed.
    """
    c, s21, s50 = _last(close), _last(sma21), _last(sma50)
    sl = slope_pct(sma50, 10)
    if None in (c, s21, s50) or sl is None:
        return {"direction": "unknown", "sma50_slope_10d_pct": sl}
    if c > s50 and s21 > s50 and sl > 0:
        d = "up"
    elif c < s50 and s21 < s50 and sl < 0:
        d = "down"
    else:
        d = "sideways"
    return {"direction": d, "sma50_slope_10d_pct": sl}
