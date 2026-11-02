"""Read-only access to the externally sourced data in deploy_data/external:

* fundamentals.json   -- company figures as reported on Merolagani (weekly)
* announcements.json  -- ShareSansar announcement and news headlines (daily)

Both files are written by scripts in scripts/; this module only loads them
(cached until the file changes) and never fills a gap with an estimate.
"""
import json
from datetime import date, datetime, timezone

from . import data as D

STALE_FUNDAMENTALS_DAYS = 21
FIELDS = ("eps", "eps_period", "pe", "book_value", "pbv", "cash_dividend_pct", "cash_dividend_fy", "bonus_pct",
          "bonus_fy", "market_cap", "shares_outstanding", "dividend_history", "bonus_history", "fetched_at", "url")


def _dir(path=None):
    return D.data_dir(path) / "external"


_CACHE = {}


def _load(name, path=None):
    f = _dir(path) / name
    try:
        mtime = f.stat().st_mtime
    except OSError:
        return None
    hit = _CACHE.get(str(f))
    if hit and hit[0] == mtime:
        return hit[1]
    try:
        val = json.loads(f.read_text(encoding="utf-8"))
    except ValueError:
        val = None
    _CACHE[str(f)] = (mtime, val)
    return val


def fundamentals_store(path=None):
    return _load("fundamentals.json", path)


def _age_days(iso):
    try:
        return (datetime.now(timezone.utc) - datetime.fromisoformat(iso)).days
    except (TypeError, ValueError):
        return None


def _collapse_years(history):
    """One entry per fiscal year. Merolagani sometimes lists a year twice, once with
    the declared value and once at 0.00; keep the non-zero one (the largest)."""
    best = {}
    for h in history or []:
        fy = h.get("fiscal_year")
        if fy not in best or (h.get("value_pct") or 0) > (best[fy].get("value_pct") or 0):
            best[fy] = h
    return [best[fy] for fy in dict.fromkeys(h.get("fiscal_year") for h in history or [])]


def company_fundamentals(ticker, path=None, price=None):
    """Reported figures for one company plus provenance, or None.

    If `price` (our latest close) is given, also returns P/E and P/B recomputed
    at that price from the reported EPS and book value, clearly marked as such.
    """
    store = fundamentals_store(path)
    if not store:
        return None
    c = (store.get("companies") or {}).get(ticker.upper())
    if not c:
        return None
    out = {k: None for k in FIELDS}
    out.update(c)
    out["dividend_history"] = _collapse_years(out.get("dividend_history"))
    out["bonus_history"] = _collapse_years(out.get("bonus_history"))
    out["source"] = store.get("source")
    out["source_note"] = store.get("source_note")
    age = _age_days(c.get("fetched_at"))
    out["age_days"] = age
    out["stale"] = age is None or age > STALE_FUNDAMENTALS_DAYS
    if price:
        out["pe_at_close"] = round(price / c["eps"], 2) if c.get("eps") and c["eps"] > 0 else None
        out["pbv_at_close"] = round(price / c["book_value"], 2) if c.get("book_value") and c["book_value"] > 0 else None
    return out


def fundamentals_map(path=None):
    """{ticker: {eps, pe, pbv, book_value, ...}} for screener/compare use."""
    store = fundamentals_store(path) or {}
    return store.get("companies") or {}


def announcements(path=None, ticker=None, kind=None, category=None, since=None, limit=50, query=None):
    store = _load("announcements.json", path) or {}
    items = store.get("items") or []
    if ticker:
        items = [i for i in items if i.get("ticker") == ticker.upper()]
    if kind:
        items = [i for i in items if i.get("kind") == kind]
    if category:
        items = [i for i in items if i.get("category") == category]
    if since:
        items = [i for i in items if (i.get("date") or "") >= since]
    if query:
        q = query.lower()
        items = [i for i in items if q in i.get("title", "").lower() or q == (i.get("ticker") or "").lower()]
    return {"source": store.get("source"), "source_note": store.get("source_note"),
            "updated_at": store.get("updated_at"), "count": len(items), "items": items[:limit]}


def categories(path=None):
    """[(key, label, count)] present in the stored items."""
    store = _load("announcements.json", path) or {}
    counts = {}
    for i in store.get("items") or []:
        k = (i.get("category"), i.get("category_label"))
        counts[k] = counts.get(k, 0) + 1
    return sorted(((k, l, n) for (k, l), n in counts.items()), key=lambda x: -x[2])


def today_iso():
    return date.today().isoformat()
