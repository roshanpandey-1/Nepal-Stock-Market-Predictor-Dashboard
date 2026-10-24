"""Stock ideas and holdings forecasts for signed-in users.

Two pieces:

* ``recommend()`` -- a transparent, rule-based "ideas to research" list. It
  looks at the sectors a user holds or has recently searched, then lists the
  other actively traded stocks in those sectors that have risen over the last
  20 sessions. It is a screening aid, not advice: every idea carries the
  plain-English reasons it was picked. It deliberately does NOT use the Prophet
  forecasts: tested on 260 stocks (scripts/validate_forecasts.py) they were
  less accurate than assuming no change and called the direction right less
  than half the time.
* ``holdings_forecast()`` -- the Prophet 30-day price range applied to each
  holding: middle of the range, the range and value, plus a portfolio total.
* ``load_forecast_evidence()`` -- the test result shown next to every range.

The scoring functions are pure (no Flask, no files) so they are easy to test;
the loaders below cache the CSVs in memory.
"""
import csv
import json
import os
import time
from pathlib import Path

DATA_DIR = Path(os.environ.get("DATA_DIR", "data"))
MODELS_DIR = DATA_DIR / "models"
PROCESSED_DIR = DATA_DIR / "processed"

CLOSE_IDX, TURNOVER_IDX = 4, 6
MOMENTUM_DAYS = 20
STATS_TTL = 3600  # market stats only change once a day


# --------------------------------------------------------------------------- loaders
_FC_CACHE = {"mtime": None, "summary": {}, "daily": {}}
_EV_CACHE = {"mtime": None, "data": None}


def load_forecast_evidence():
    """The forecast accuracy test (models/forecast_evidence.json), or None if missing."""
    path = MODELS_DIR / "forecast_evidence.json"
    try:
        mtime = path.stat().st_mtime
        if _EV_CACHE["mtime"] != mtime:
            _EV_CACHE.update(mtime=mtime, data=json.loads(path.read_text(encoding="utf-8")))
        return _EV_CACHE["data"]
    except (OSError, ValueError):
        return None


def load_forecasts():
    """(summary, daily) from data/models/forecast_*.csv, reloaded when the files change."""
    s_path, d_path = MODELS_DIR / "forecast_summary.csv", MODELS_DIR / "forecast_daily.csv"
    if not s_path.exists() or not d_path.exists():
        return {}, {}
    mtime = (s_path.stat().st_mtime, d_path.stat().st_mtime)
    if _FC_CACHE["mtime"] != mtime:
        summary, daily = {}, {}
        with open(s_path, newline="", encoding="utf-8") as f:
            for r in csv.DictReader(f):
                try:
                    summary[r["ticker"].strip().upper()] = {
                        "current_price": float(r["current_price"]),
                        "forecast_price": float(r["forecast_price"]),
                        "lower_bound": float(r["lower_bound"]),
                        "upper_bound": float(r["upper_bound"]),
                        "change_pct": float(r["change_pct"]),
                        "horizon_days": int(r["horizon_days"]),
                        "generated_at": r["generated_at"],
                    }
                except (KeyError, ValueError):
                    continue
        with open(d_path, newline="", encoding="utf-8") as f:
            for r in csv.DictReader(f):
                try:
                    daily.setdefault(r["ticker"].strip().upper(), []).append({
                        "d": int(r["day_offset"]), "date": r["date"],
                        "p": float(r["forecast_price"]),
                        "lo": float(r["lower_bound"]), "hi": float(r["upper_bound"]),
                    })
                except (KeyError, ValueError):
                    continue
        for rows in daily.values():
            rows.sort(key=lambda x: x["d"])
        _FC_CACHE.update(mtime=mtime, summary=summary, daily=daily)
    return _FC_CACHE["summary"], _FC_CACHE["daily"]


_STATS_CACHE = {"ts": 0.0, "stats": {}}


def _tail(path, count, chunk=32768):
    with open(path, "rb") as f:
        f.seek(0, 2)
        size = f.tell()
        f.seek(max(0, size - chunk))
        data = f.read().decode("utf-8", errors="ignore").splitlines()
    if size > chunk and data:
        data = data[1:]
    return [ln for ln in data if ln.strip()][-count:]


def market_stats(tickers):
    """{ticker: {sector, close, mom20, turnover20}} from each ticker's latest rows (TTL-cached)."""
    now = time.time()
    if now - _STATS_CACHE["ts"] < STATS_TTL and _STATS_CACHE["stats"]:
        return _STATS_CACHE["stats"]
    stats = {}
    for t in tickers:
        path = PROCESSED_DIR / f"{t}_features.csv"
        if not path.exists():
            continue
        try:
            rows = [next(csv.reader([ln])) for ln in _tail(path, MOMENTUM_DAYS + 1)]
            if len(rows) < MOMENTUM_DAYS + 1:
                continue
            closes = [float(r[CLOSE_IDX]) for r in rows]
            turnovers = [float(r[TURNOVER_IDX] or 0) for r in rows[1:]]
            if closes[0] <= 0:
                continue
            stats[t] = {
                "sector": rows[-1][-1] or None,
                "close": closes[-1],
                "mom20": round((closes[-1] / closes[0] - 1) * 100, 2),
                "turnover20": sum(turnovers) / len(turnovers),
            }
        except (ValueError, IndexError, OSError):
            continue
    _STATS_CACHE.update(ts=now, stats=stats)
    return stats


# --------------------------------------------------------------------------- ideas
def _clip(v, lo=-20.0, hi=20.0):
    return max(lo, min(hi, v))


def recommend(held, searched, stats, names=None, limit=5, exclude=()):
    """Rank "ideas to research" for one user.

    held / searched: ticker lists (searched newest first).  stats: market_stats() output.
    Returns a list of {ticker, name, sector, score, mom20, close, reasons, basis}.
    """
    names = names or {}
    held = [t for t in held if t in stats]
    searched = [t for t in searched if t in stats]
    skip = set(held) | set(searched) | set(exclude)

    # sector -> the user's stock that put it on the list (for the reason text)
    anchors = {}
    for t in held:
        anchors.setdefault(stats[t]["sector"], ("hold", t))
    for t in searched:
        anchors.setdefault(stats[t]["sector"], ("searched", t))
    anchors.pop(None, None)

    # liquidity floor: ignore the least-traded half of the market
    turnovers = sorted(s["turnover20"] for s in stats.values())
    floor = turnovers[len(turnovers) // 2] if turnovers else 0

    def scored(ticker):
        s = stats[ticker]
        if s["turnover20"] < floor or s["mom20"] <= 0:
            return None
        return _clip(s["mom20"]) / 20

    basis = "personal" if anchors else "market"
    pool = [t for t in stats if t not in skip and (not anchors or stats[t]["sector"] in anchors)]
    ideas = []
    for t in pool:
        score = scored(t)
        if score is None:
            continue
        s = stats[t]
        reasons = []
        if anchors:
            kind, src = anchors[s["sector"]]
            reasons.append(f"Same sector as {src}" + (" (you hold it)" if kind == "hold" else " (you searched it)"))
        reasons.append(f"Up {s['mom20']:.1f}% over the last 20 sessions")
        reasons.append("In the more actively traded half of the market")
        ideas.append({
            "ticker": t, "name": names.get(t, t), "sector": s["sector"], "score": round(score, 3),
            "mom20": s["mom20"], "close": s["close"],
            "reasons": reasons, "basis": basis,
        })
    ideas.sort(key=lambda x: -x["score"])

    # keep the list varied: at most 2 ideas per sector
    out, per_sector = [], {}
    for idea in ideas:
        if per_sector.get(idea["sector"], 0) >= 2:
            continue
        per_sector[idea["sector"]] = per_sector.get(idea["sector"], 0) + 1
        out.append(idea)
        if len(out) >= limit:
            break
    return out


# --------------------------------------------------------------------------- holdings forecast
def holdings_forecast(rows, summary, daily):
    """rows: value_holdings() rows (ticker, name, sector, quantity, ltp).

    Expected change is measured from today's LTP, so it reflects where the
    price is now rather than where it was when the forecast batch ran.
    """
    items, missing = [], []
    tot_now = tot_fc = tot_lo = tot_hi = 0.0
    generated = set()
    for r in rows:
        fc = summary.get(r["ticker"])
        ltp = r.get("ltp")
        if fc is None or not ltp:
            missing.append(r["ticker"])
            continue
        q = r["quantity"]
        # If the price has moved a lot since the forecast batch ran (a bonus
        # or rights adjustment, or just a big move), the forecast's absolute
        # price level no longer lines up with today's price. Then apply the
        # forecast's own expected % move to today's price instead, and flag it.
        snap = fc.get("current_price") or ltp
        stale = abs(ltp / snap - 1) > 0.20
        scale = ltp / snap if stale else 1.0
        fc = dict(fc, forecast_price=round(fc["forecast_price"] * scale, 2),
                  lower_bound=round(fc["lower_bound"] * scale, 2), upper_bound=round(fc["upper_bound"] * scale, 2))
        path = daily.get(r["ticker"], [])
        if stale:
            path = [dict(p, p=round(p["p"] * scale, 2), lo=round(p["lo"] * scale, 2), hi=round(p["hi"] * scale, 2)) for p in path]
        now_v, fc_v = q * ltp, q * fc["forecast_price"]
        lo_v, hi_v = q * fc["lower_bound"], q * fc["upper_bound"]
        tot_now += now_v
        tot_fc += fc_v
        tot_lo += lo_v
        tot_hi += hi_v
        generated.add(fc["generated_at"])
        items.append({
            "ticker": r["ticker"], "name": r.get("name"), "sector": r.get("sector"), "quantity": q,
            "ltp": round(ltp, 2),
            "forecast_price": fc["forecast_price"],
            "lower_bound": fc["lower_bound"], "upper_bound": fc["upper_bound"],
            "change_pct": round((fc["forecast_price"] / ltp - 1) * 100, 2),
            "lower_pct": round((fc["lower_bound"] / ltp - 1) * 100, 2),
            "upper_pct": round((fc["upper_bound"] / ltp - 1) * 100, 2),
            "value_now": round(now_v, 2), "value_forecast": round(fc_v, 2),
            "value_change": round(fc_v - now_v, 2),
            "band_pct": round((fc["upper_bound"] - fc["lower_bound"]) / ltp * 100, 1),
            "path": path,
            "rescaled": stale,
        })
    items.sort(key=lambda x: -x["change_pct"])
    totals = {
        "value_now": round(tot_now, 2), "value_forecast": round(tot_fc, 2),
        "value_change": round(tot_fc - tot_now, 2),
        "change_pct": round((tot_fc / tot_now - 1) * 100, 2) if tot_now else None,
        "value_low": round(tot_lo, 2), "value_high": round(tot_hi, 2),
        "count": len(items),
    }
    return {"items": items, "totals": totals, "missing": missing,
            "generated_at": max(generated) if generated else None}
