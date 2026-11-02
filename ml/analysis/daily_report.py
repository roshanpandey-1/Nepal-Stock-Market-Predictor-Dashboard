"""Daily market report, written by fixed rules from the tracked stocks' data.

Built once a day by scripts/build_daily_report.py (GitHub Actions, after the
price refresh) and served as a static JSON file, so visitors never trigger the
calculation. Every sentence is produced from a number in the same report.

Scope: market totals here are sums over the ~270 stocks this project tracks,
not NEPSE's official totals. The official NEPSE index is included only when it
was captured for the same session (see nepse_index.csv); otherwise the report
says it is unavailable rather than guessing.
"""
import numpy as np

from . import data as D
from . import market as M
from . import technicals as T
from .report import _rs_big

LOOKBACK_SESSIONS = 20
MIN_SECTOR_TRADED = 3      # sectors with fewer traded stocks are not called leaders/laggards
DISCLAIMER = ("Generated automatically by fixed rules from end-of-day data for the stocks this site tracks. "
              "It describes what happened; it is not a forecast or investment advice.")


def session_aggregates(hists, sessions=LOOKBACK_SESSIONS + 1):
    """Per-session totals for the latest `sessions` market dates:
    {date: {"turnover", "volume", "advancing", "declining", "traded"}}."""
    all_dates = sorted({d for h in hists.values() for d in h.dates})[-sessions:]
    want = set(all_dates)
    agg = {d: {"turnover": 0.0, "volume": 0.0, "advancing": 0, "declining": 0, "unchanged": 0, "traded": 0}
           for d in all_dates}
    for h in hists.values():
        close, to, vol = h["Close"], h["Turnover"], h["Volume"]
        start = max(0, len(h) - sessions - 5)
        for i in range(start, len(h)):
            d = h.dates[i]
            if d not in want:
                continue
            a = agg[d]
            a["traded"] += 1
            if np.isfinite(to[i]):
                a["turnover"] += float(to[i])
            if np.isfinite(vol[i]):
                a["volume"] += float(vol[i])
            if i > 0 and close[i - 1] > 0:
                ch = round((close[i] / close[i - 1] - 1) * 100, 2)   # same rounding as the breadth counts
                a["advancing" if ch > 0 else "declining" if ch < 0 else "unchanged"] += 1
    return agg


def _breadth_tone(adv, dec):
    if dec >= max(1, adv) * 1.5:
        return "broad selling"
    if adv >= max(1, dec) * 1.5:
        return "broad buying"
    return "mixed trading"


def _fmt_pct(x):
    return "n/a" if x is None else f"{x:+.2f}%"


def build(path=None, index_row=None):
    """The report dict for the latest session in the data.

    index_row: optional {"date", "value", "change", "change_pct"} for the
    official NEPSE index; used only if its date equals the report date.
    """
    hists = D.universe(path)
    s = M.summary(path)
    date = s["as_of"]
    agg = session_aggregates(hists)
    dates = sorted(agg)
    prev_dates = [d for d in dates if d < date][-LOOKBACK_SESSIONS:]
    avg_turnover = float(np.mean([agg[d]["turnover"] for d in prev_dates])) if prev_dates else None
    prev = agg[prev_dates[-1]] if prev_dates else None
    b, tot = s["breadth"], s["totals"]

    headline = []
    idx = index_row if index_row and index_row.get("date") == date else None
    if idx:
        headline.append(f"NEPSE index closed at {idx['value']:,.2f} ({_fmt_pct(idx.get('change_pct'))}).")
    tone = _breadth_tone(b["advancing"], b["declining"])
    headline.append(f"{tone.capitalize()}: {b['advancing']} tracked stocks rose and {b['declining']} fell "
                    f"(median change {_fmt_pct(b['median_change_pct'])}).")
    turnover_vs_avg = T._r((tot["turnover"] / avg_turnover - 1) * 100) if avg_turnover else None
    if turnover_vs_avg is not None:
        headline.append(f"Turnover {_rs_big(tot['turnover'])}, {abs(turnover_vs_avg):.0f}% "
                        f"{'above' if turnover_vs_avg >= 0 else 'below'} its {len(prev_dates)}-session average.")

    sectors = [x for x in s["sectors"] if x["traded"] >= MIN_SECTOR_TRADED and x["median_1d_pct"] is not None]
    by_day = sorted(sectors, key=lambda x: x["median_1d_pct"], reverse=True)
    leaders, laggards = by_day[:3], list(reversed(by_day[-3:]))
    if leaders and laggards:
        headline.append(f"Strongest sector: {leaders[0]['sector']} ({_fmt_pct(leaders[0]['median_1d_pct'])} median); "
                        f"weakest: {laggards[0]['sector']} ({_fmt_pct(laggards[0]['median_1d_pct'])}).")

    observations = []
    top_sector = max(s["sectors"], key=lambda x: x["turnover_share_pct"] or 0, default=None)
    if top_sector and (top_sector["turnover_share_pct"] or 0) >= 35:
        observations.append(f"{top_sector['sector']} accounted for {top_sector['turnover_share_pct']:.0f}% of turnover, "
                            "so the day's activity was concentrated in one sector.")
    if s["unusual_volume"]:
        names = ", ".join(f"{u['ticker']} ({u['relative_volume']:.1f}x, {_fmt_pct(u['change_pct'])})" for u in s["unusual_volume"][:5])
        observations.append(f"{len(s['unusual_volume'])} stocks traded at {M.UNUSUAL_RELVOL:g}x or more their usual volume: {names}. "
                            "Volume spikes often follow news or announcements; check before reading anything into them.")
    observations.append(f"{b['near_1y_high']} stocks closed within 2% of their 1-year high and {b['near_1y_low']} within 2% of their 1-year low.")
    above = b["above_sma_50"]
    if b["traded"]:
        observations.append(f"{above} of {b['traded']} traded stocks ({above / b['traded'] * 100:.0f}%) are above their 50-day average.")
    if prev:
        observations.append(f"Previous session ({prev_dates[-1]}): {prev['advancing']} rose, {prev['declining']} fell, "
                            f"turnover {_rs_big(prev['turnover'])}.")
    big = [g for g in s["gainers"] + s["losers"] if abs(g["change_pct"] or 0) >= 9.5]
    if big:
        observations.append("Moved 9.5% or more in one session: "
                            + ", ".join(f"{g['ticker']} ({_fmt_pct(g['change_pct'])})" for g in big)
                            + ". Very large one-day moves can also come from price adjustments (bonus or right shares).")

    risks = []
    if tone == "broad selling":
        risks.append("Selling was broad-based rather than limited to a few stocks.")
    if turnover_vs_avg is not None and turnover_vs_avg <= -30:
        risks.append("Turnover was well below average; thin markets can move sharply on small orders.")
    if turnover_vs_avg is not None and turnover_vs_avg >= 50:
        risks.append("Turnover was far above average; unusually busy sessions can bring larger price swings in either direction.")
    if s["not_traded"]:
        risks.append(f"{len(s['not_traded'])} tracked stocks did not trade (possible suspensions or no buyers): "
                     + ", ".join(s["not_traded"][:10]) + ("..." if len(s["not_traded"]) > 10 else "") + ".")
    risks.append("Not covered: news, corporate announcements, regulatory changes and company financials.")

    from . import external
    ann = external.announcements(path, kind="announcement", since=date, limit=500)
    todays = [i for i in ann["items"] if i.get("date") == date]
    by_cat = {}
    for i in todays:
        by_cat[i["category_label"]] = by_cat.get(i["category_label"], 0) + 1
    if todays:
        observations.append(f"{len(todays)} company announcements on {date}: "
                            + ", ".join(f"{n} {k.lower()}" for k, n in sorted(by_cat.items(), key=lambda x: -x[1])) + ".")

    trend_days = [{"date": d, "turnover": T._r(agg[d]["turnover"]), "advancing": agg[d]["advancing"],
                   "declining": agg[d]["declining"]} for d in dates]
    return {
        "date": date,
        "source": D.SOURCE,
        "scope": M.SCOPE,
        "nepse_index": idx,
        "nepse_index_note": None if idx else "The official NEPSE index was not captured for this session.",
        "headline": headline,
        "breadth": b,
        "totals": dict(tot, turnover_vs_avg_pct=turnover_vs_avg,
                       avg_turnover_prev=T._r(avg_turnover) if avg_turnover else None),
        "gainers": s["gainers"], "losers": s["losers"],
        "top_turnover": s["top_turnover"], "top_volume": s["top_volume"],
        "unusual_volume": s["unusual_volume"],
        "sectors": s["sectors"],
        "sector_leaders": [x["sector"] for x in leaders], "sector_laggards": [x["sector"] for x in laggards],
        "observations": observations,
        "risks": risks,
        "recent_sessions": trend_days,
        "announcements": {"source": ann["source"], "count": len(todays), "by_category": by_cat,
                          "items": [{k: i.get(k) for k in ("title", "url", "ticker", "category", "category_label")}
                                    for i in todays[:15]]},
        "disclaimer": DISCLAIMER,
    }
