"""Helpers for the news/sentiment pages."""
from datetime import datetime

_DATE_FMT = "%A, %B %d, %Y"  # e.g. "Monday, October 12, 2026" (Sharesansar's format)


def _headline_date(row):
    try:
        return datetime.strptime((row.get("date") or "").strip(), _DATE_FMT)
    except ValueError:
        return datetime.min  # unparseable dates sort last


def recent_headlines(rows, limit=None):
    """Newest `limit` headlines (all of them if limit is None), regardless of how the CSV happens to be ordered.

    The scraper writes newest-first, but earlier code assumed oldest-first and
    reversed the list -- which showed the OLDEST headlines. Sorting by the actual
    date makes this independent of file order. sorted() is stable, so headlines
    from the same day keep the order they have in the file.
    """
    return sorted(rows, key=_headline_date, reverse=True)[:limit]


def page_window(page, pages, around=2):
    """Page numbers to show in a pager, with None marking a gap: 1 ... 4 5 [6] 7 8 ... 21"""
    keep = sorted({1, pages} | set(range(max(1, page - around), min(pages, page + around) + 1)))
    out, prev = [], 0
    for n in keep:
        if n - prev > 1:
            out.append(None)
        out.append(n)
        prev = n
    return out
