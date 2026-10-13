"""Pure portfolio maths (no Flask / database imports, so it is easy to test).

A portfolio is just the user's balance per scrip, valued like Meroshare does:
value at last closing price (LCP) and value at last traded price (LTP).
"""
from collections import defaultdict


class PortfolioError(ValueError):
    """Invalid user input for a holding."""


def value_holdings(quantities, prices):
    """quantities: {ticker: shares}.  prices: {ticker: {"lcp","ltp","name","sector"}}.

    A ticker with no price is valued at 0 and flagged `priced: False`.
    Returns (rows, totals).
    """
    rows = []
    tot = {"value_lcp": 0.0, "value_ltp": 0.0}
    for ticker in sorted(quantities):
        qty = quantities[ticker]
        p = prices.get(ticker) or {}
        ltp = p.get("ltp")
        lcp = p.get("lcp") if p.get("lcp") is not None else ltp
        v_ltp = qty * ltp if ltp is not None else 0.0
        v_lcp = qty * lcp if lcp is not None else 0.0
        rows.append({
            "ticker": ticker,
            "name": p.get("name") or ticker,
            "sector": p.get("sector"),
            "quantity": qty,
            "lcp": None if lcp is None else round(lcp, 2),
            "value_lcp": round(v_lcp, 2),
            "ltp": None if ltp is None else round(ltp, 2),
            "value_ltp": round(v_ltp, 2),
            "day_pl": round(v_ltp - v_lcp, 2),
            "priced": ltp is not None,
        })
        tot["value_lcp"] += v_lcp
        tot["value_ltp"] += v_ltp
    totals = {
        "value_lcp": round(tot["value_lcp"], 2),
        "value_ltp": round(tot["value_ltp"], 2),
        "day_pl": round(tot["value_ltp"] - tot["value_lcp"], 2),
        "count": len(rows),
    }
    return rows, totals


def sector_breakdown(rows):
    """Share of the portfolio (by value at LTP) per sector, largest first."""
    by_sector = defaultdict(float)
    for r in rows:
        by_sector[r["sector"] or "Other (no sector model)"] += r["value_ltp"]
    total = sum(by_sector.values())
    out = [
        {"sector": s, "value": round(v, 2), "share_pct": round(v / total * 100, 2) if total else 0.0}
        for s, v in by_sector.items()
    ]
    return sorted(out, key=lambda x: -x["value"])
