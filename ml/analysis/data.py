"""Loading the daily price + indicator files (``<TICKER>_features.csv``).

Files are read with the csv module (the web image has no pandas) and cached in
memory until the file on disk changes.
"""
import csv
import json
import os
from pathlib import Path

import numpy as np

# Indicator columns already computed by ml/features/technical_indicators.py
# (the `ta` library). They are reused as-is so every page shows the same values.
NUMERIC_COLS = [
    "Open", "High", "Low", "Close", "Volume", "Turnover",
    "SMA_7", "SMA_21", "SMA_50", "EMA_12", "EMA_26", "MACD", "MACD_Signal",
    "RSI_14", "Stoch", "BB_High", "BB_Low", "BB_Width", "ATR", "OBV",
]
SOURCE = "Daily OHLCV from Sharesansar (completed sessions); indicators computed in this project"


def data_dir(path=None):
    return Path(path or os.environ.get("DATA_DIR", "data"))


def processed_dir(path=None):
    return data_dir(path) / "processed"


def _num(value):
    try:
        x = float(value)
    except (TypeError, ValueError):
        return np.nan
    return x if np.isfinite(x) else np.nan


class History:
    """One ticker's daily history as numpy arrays (oldest first)."""

    def __init__(self, ticker, sector, dates, cols):
        self.ticker = ticker
        self.sector = sector
        self.dates = dates
        self.cols = cols

    def __len__(self):
        return len(self.dates)

    def __getitem__(self, name):
        return self.cols[name]

    @property
    def last_date(self):
        return self.dates[-1] if self.dates else None


def _column(strings):
    """Strings -> float array; blanks and junk become NaN, inf becomes NaN."""
    try:
        a = np.array([x if x not in ("", None) else "nan" for x in strings], dtype=float)
    except ValueError:
        a = np.array([_num(x) for x in strings], dtype=float)
    a[~np.isfinite(a)] = np.nan
    return a


def parse_table(ticker, header, rows):
    """Build a History from a CSV header and its data rows (lists of strings).
    Rows without a date or a usable close are dropped; rows are sorted by date."""
    pos = {name: i for i, name in enumerate(header)}
    if "Date" not in pos or "Close" not in pos:
        return History(ticker, None, [], {c: np.array([]) for c in NUMERIC_COLS})
    di, ci = pos["Date"], pos["Close"]
    rows = [r for r in rows if len(r) > ci and r[di] and np.isfinite(_num(r[ci]))]
    rows.sort(key=lambda r: r[di])
    dates = [r[di][:10] for r in rows]
    cols = {}
    for c in NUMERIC_COLS:
        i = pos.get(c)
        cols[c] = _column([r[i] if i is not None and len(r) > i else "" for r in rows])
    si = pos.get("Sector")
    sector = next((r[si] for r in reversed(rows) if si is not None and len(r) > si and r[si]), None)
    return History(ticker, sector, dates, cols)


def parse_rows(ticker, rows):
    """Build a History from csv.DictReader-style dict rows (used by tests)."""
    header = list(rows[0].keys()) if rows else ["Date", "Close"]
    return parse_table(ticker, header, [[r.get(h, "") for h in header] for r in rows])


_CACHE = {}


def load_history(ticker, path=None):
    """History for one ticker, or None if there is no file. Cached by mtime."""
    ticker = ticker.upper()
    f = processed_dir(path) / f"{ticker}_features.csv"
    try:
        mtime = f.stat().st_mtime
    except OSError:
        return None
    key = (str(f), mtime)
    hit = _CACHE.get(ticker)
    if hit and hit[0] == key:
        return hit[1]
    with open(f, newline="", encoding="utf-8") as fh:
        reader = csv.reader(fh)
        header = next(reader, [])
        hist = parse_table(ticker, header, list(reader))
    _CACHE[ticker] = (key, hist)
    return hist


def tickers(path=None):
    """Tracked tickers from ticker_list.txt, falling back to the feature files."""
    d = processed_dir(path)
    lst = d / "ticker_list.txt"
    if lst.exists():
        out = [t.strip().upper() for t in lst.read_text(encoding="utf-8").splitlines() if t.strip()]
    else:
        out = sorted(p.name[:-len("_features.csv")] for p in d.glob("*_features.csv"))
    return [t for t in out if (d / f"{t}_features.csv").exists()]


_NAMES = {}


def company_names(path=None):
    f = processed_dir(path) / "company_names.json"
    try:
        mtime = f.stat().st_mtime
    except OSError:
        return {}
    if _NAMES.get("key") != (str(f), mtime):
        try:
            _NAMES.update(key=(str(f), mtime), data=json.loads(f.read_text(encoding="utf-8")))
        except ValueError:
            _NAMES.update(key=(str(f), mtime), data={})
    return _NAMES["data"]


def universe(path=None):
    """{ticker: History} for every tracked ticker."""
    out = {}
    for t in tickers(path):
        h = load_history(t, path)
        if h is not None and len(h):
            out[t] = h
    return out


def market_date(hists):
    """The latest session date present in the data (the 'as of' date)."""
    dates = [h.last_date for h in hists.values() if h.last_date]
    return max(dates) if dates else None
