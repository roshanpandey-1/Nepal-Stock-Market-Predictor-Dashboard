"""Alert rules: what can be set, whether a rule is met, and what the message says.

Pure functions on plain dicts, with no Flask or database imports, so they are easy to test
and the daily runner (scripts/run_alerts.py) and the web app share exactly one definition.

Alerts use end-of-day data and are checked once a day, after the price refresh. A rule fires
when its condition turns from false to true, not on every day it stays true.
"""
import json

MAX_RULES_PER_USER = 25
MAX_SEEN = 60
UNUSUAL_MIN_TURNOVER = 1e6            # Rs 10 lakh, same floor as the volume flags elsewhere

# kind -> (label, unit, default, low, high)
KINDS = {
    "price_above":      ("Closes at or above a price", "Rs", None, 0.01, 1_000_000),
    "price_below":      ("Closes at or below a price", "Rs", None, 0.01, 1_000_000),
    "move_up":          ("Rises by at least X% in a session", "%", 5, 0.5, 10),
    "move_down":        ("Falls by at least X% in a session", "%", 5, 0.5, 10),
    "volume_spike":     ("Volume at least X times its 20-session average", "x", 3, 1.5, 50),
    "rsi_above":        ("RSI(14) at or above a level", "", 70, 50, 99),
    "rsi_below":        ("RSI(14) at or below a level", "", 30, 1, 50),
    "cross_sma50_up":   ("Closes above its 50-day average (crossed in the last 5 sessions)", None, None, None, None),
    "cross_sma50_down": ("Closes below its 50-day average (crossed in the last 5 sessions)", None, None, None, None),
    "macd_cross_up":    ("MACD crosses above its signal line (last 5 sessions)", None, None, None, None),
    "macd_cross_down":  ("MACD crosses below its signal line (last 5 sessions)", None, None, None, None),
    "announcement":     ("A new announcement or news headline is posted", None, None, None, None),
}
CATEGORIES = ("quarterly_result", "book_closure", "listing", "dividend", "right_share", "agm", "merger",
              "ipo", "nav", "regulation", "market", "other")


def kinds_for_ui():
    return [{"kind": k, "label": v[0], "unit": v[1], "default": v[2], "needs_value": v[1] is not None}
            for k, v in KINDS.items()]


def validate(kind, threshold=None, category=None):
    """(threshold, category) cleaned, or ValueError with a message safe to show the user."""
    if kind not in KINDS:
        raise ValueError("Choose one of the alert types in the list.")
    label, unit, default, low, high = KINDS[kind]
    if unit is None:
        threshold = None
    else:
        try:
            threshold = float(str(threshold).replace(",", "").strip())
        except (TypeError, ValueError):
            raise ValueError("Enter a number for the alert level.")
        if not low <= threshold <= high:
            raise ValueError(f"The level must be between {low:g} and {high:g}.")
        threshold = round(threshold, 2)
    category = (category or "").strip() or None
    if kind != "announcement":
        category = None
    elif category is not None and category not in CATEGORIES:
        raise ValueError("Unknown announcement category.")
    return threshold, category


def describe(kind, threshold=None, category=None):
    """Short human text for a rule, e.g. 'closes at or above Rs 1,100'."""
    t = threshold
    return {
        "price_above": f"closes at or above Rs {t:,.2f}" if t is not None else "",
        "price_below": f"closes at or below Rs {t:,.2f}" if t is not None else "",
        "move_up": f"rises {t:g}% or more in a session" if t is not None else "",
        "move_down": f"falls {t:g}% or more in a session" if t is not None else "",
        "volume_spike": f"volume is {t:g}x its 20-session average or more" if t is not None else "",
        "rsi_above": f"RSI(14) is {t:g} or higher" if t is not None else "",
        "rsi_below": f"RSI(14) is {t:g} or lower" if t is not None else "",
        "cross_sma50_up": "closes above its 50-day average",
        "cross_sma50_down": "closes below its 50-day average",
        "macd_cross_up": "MACD crosses above its signal line",
        "macd_cross_down": "MACD crosses below its signal line",
        "announcement": "a new announcement or headline appears" + (f" ({category.replace('_', ' ')})" if category else ""),
    }[kind]


def condition(kind, threshold, row):
    """(met, message) for the state-type rules. `row` is market.stock_row for the stock."""
    t = row["ticker"]
    close, chg, rv = row.get("close"), row.get("change_pct"), row.get("relative_volume")
    rsi = row.get("rsi_14")
    if kind == "price_above":
        return (close is not None and close >= threshold,
                f"{t} closed at Rs {close:,.2f}, at or above your level of Rs {threshold:,.2f}." if close is not None else "")
    if kind == "price_below":
        return (close is not None and close <= threshold,
                f"{t} closed at Rs {close:,.2f}, at or below your level of Rs {threshold:,.2f}." if close is not None else "")
    if kind == "move_up":
        return (chg is not None and chg >= threshold, f"{t} rose {chg:+.2f}% in the latest session (your level: {threshold:g}%)." if chg is not None else "")
    if kind == "move_down":
        return (chg is not None and chg <= -threshold, f"{t} fell {chg:+.2f}% in the latest session (your level: {threshold:g}%)." if chg is not None else "")
    if kind == "volume_spike":
        met = rv is not None and rv >= threshold and (row.get("turnover") or 0) >= UNUSUAL_MIN_TURNOVER
        return met, f"{t} volume was {rv:g}x its 20-session average (your level: {threshold:g}x)." if rv is not None else ""
    if kind == "rsi_above":
        return rsi is not None and rsi >= threshold, f"{t} RSI(14) is {rsi:g} (your level: {threshold:g} or higher)." if rsi is not None else ""
    if kind == "rsi_below":
        return rsi is not None and rsi <= threshold, f"{t} RSI(14) is {rsi:g} (your level: {threshold:g} or lower)." if rsi is not None else ""
    if kind in ("cross_sma50_up", "cross_sma50_down"):
        want = "up" if kind.endswith("up") else "down"
        return (row.get("cross_price_sma50") == want,
                f"{t} closed {'above' if want == 'up' else 'below'} its 50-day average within the last 5 sessions.")
    if kind in ("macd_cross_up", "macd_cross_down"):
        want = "up" if kind.endswith("up") else "down"
        return (row.get("cross_macd") == want,
                f"{t} MACD crossed {'above' if want == 'up' else 'below'} its signal line within the last 5 sessions.")
    raise ValueError(kind)


def parse_seen(text):
    try:
        v = json.loads(text or "[]")
        return [str(x) for x in v] if isinstance(v, list) else []
    except ValueError:
        return []


def evaluate(rule, row, session_date, items=()):
    """Decide what to do with one rule for the latest session.

    rule: {"kind","threshold","category","state","seen","created"}  (created = YYYY-MM-DD)
    row: market.stock_row for the stock, or None
    items: ShareSansar items for the stock (dicts with url, date, title, category, category_label)

    Returns {"skip": bool, "state": bool, "fire": bool, "messages": [str], "seen": [url]}.
    A stock that did not trade in the latest session is skipped: its numbers are old news.
    """
    kind = rule["kind"]
    if kind == "announcement":
        seen = parse_seen(rule.get("seen")) if isinstance(rule.get("seen"), str) else list(rule.get("seen") or [])
        new = [i for i in items if i["url"] not in seen and (i.get("date") or "") >= rule["created"]
               and (not rule.get("category") or i.get("category") == rule["category"])]
        msgs = [f"{i.get('ticker') or rule.get('ticker', '')}: {i['title']} ({i.get('date')}, {i.get('category_label') or 'Other'})" for i in new[:5]]
        if len(new) > 5:
            msgs.append(f"...and {len(new) - 5} more.")
        handled = [i["url"] for i in new]
        return {"skip": False, "state": False, "fire": bool(new), "messages": msgs,
                "links": [i["url"] for i in new[:5]], "seen": (handled + seen)[:MAX_SEEN]}
    if row is None or row.get("date") != session_date:
        return {"skip": True, "state": bool(rule.get("state")), "fire": False, "messages": [], "links": []}
    met, msg = condition(kind, rule["threshold"], row)
    met = bool(met)
    return {"skip": False, "state": met, "fire": met and not rule.get("state"),
            "messages": [msg] if met and not rule.get("state") else [], "links": []}
