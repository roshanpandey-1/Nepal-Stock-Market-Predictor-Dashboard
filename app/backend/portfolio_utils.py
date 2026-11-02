"""Pure portfolio maths (no Flask / database imports, so it is easy to test).

A portfolio is just the user's balance per scrip, valued like Meroshare does:
value at last closing price (LCP) and value at last traded price (LTP).
"""
from collections import defaultdict


class PortfolioError(ValueError):
    """Invalid user input for a holding."""


def value_holdings(quantities, prices, costs=None):
    """quantities: {ticker: shares}.  prices: {ticker: {"lcp","ltp","name","sector"}}.

    costs: optional {ticker: average cost per share} typed in by the user. Profit/loss is
    only worked out for holdings that have a cost, and is before brokerage, SEBON and DP
    charges and capital gains tax. A ticker with no price is valued at 0 and flagged
    `priced: False`. Returns (rows, totals).
    """
    costs = costs or {}
    rows = []
    tot = {"value_lcp": 0.0, "value_ltp": 0.0, "day_pl": 0.0, "cost": 0.0, "cost_value": 0.0, "cost_count": 0}
    for ticker in sorted(quantities):
        qty = quantities[ticker]
        p = prices.get(ticker) or {}
        ltp = p.get("ltp")
        lcp = p.get("lcp") if p.get("lcp") is not None else ltp
        v_ltp = qty * ltp if ltp is not None else 0.0
        v_lcp = qty * lcp if lcp is not None else 0.0
        # Today's gain/loss = shares x (LTP - previous close). This keeps the
        # session's move visible after the close too, when Meroshare-style
        # LCP and LTP are the same number. Without a change figure, fall
        # back to LTP vs LCP.
        change = p.get("change")
        day_pl = qty * change if change is not None and ltp is not None else v_ltp - v_lcp
        avg_cost = costs.get(ticker)
        has_cost = avg_cost is not None and avg_cost > 0 and ltp is not None
        cost = qty * avg_cost if has_cost else None
        pl = v_ltp - cost if has_cost else None
        rows.append({
            "avg_cost": avg_cost if avg_cost else None,
            "cost": None if cost is None else round(cost, 2),
            "pl": None if pl is None else round(pl, 2),
            "pl_pct": round(pl / cost * 100, 2) if has_cost else None,
            "ticker": ticker,
            "name": p.get("name") or ticker,
            "sector": p.get("sector"),
            "quantity": qty,
            "lcp": None if lcp is None else round(lcp, 2),
            "value_lcp": round(v_lcp, 2),
            "ltp": None if ltp is None else round(ltp, 2),
            "value_ltp": round(v_ltp, 2),
            "day_pl": round(day_pl, 2),
            "change": change,
            "change_pct": p.get("change_pct"),
            "priced": ltp is not None,
        })
        tot["value_lcp"] += v_lcp
        tot["value_ltp"] += v_ltp
        tot["day_pl"] += day_pl
        if has_cost:
            tot["cost"] += cost
            tot["cost_value"] += v_ltp
            tot["cost_count"] += 1
    totals = {
        "cost": round(tot["cost"], 2) if tot["cost_count"] else None,
        "pl": round(tot["cost_value"] - tot["cost"], 2) if tot["cost_count"] else None,
        "pl_pct": round((tot["cost_value"] - tot["cost"]) / tot["cost"] * 100, 2) if tot["cost_count"] else None,
        "cost_count": tot["cost_count"],
        "value_lcp": round(tot["value_lcp"], 2),
        "value_ltp": round(tot["value_ltp"], 2),
        "day_pl": round(tot["day_pl"], 2),
        # % of the value at the previous close
        "day_pct": (round(tot["day_pl"] / (tot["value_ltp"] - tot["day_pl"]) * 100, 2)
                    if tot["value_ltp"] - tot["day_pl"] > 0 else None),
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
