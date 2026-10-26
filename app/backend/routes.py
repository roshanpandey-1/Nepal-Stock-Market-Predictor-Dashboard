import csv
import json
import os
import time
from pathlib import Path
from flask import Blueprint, render_template, abort, request

from . import explain, insights, model_evidence

main = Blueprint("main", __name__)

DATA_DIR = Path(os.environ.get("DATA_DIR", "data"))
MODELS_DIR = DATA_DIR / "models"
PROCESSED_DIR = DATA_DIR / "processed"

CLOSE_COL_INDEX = 4  # Date,Open,High,Low,Close,... -- fixed column order

_COMPANY_NAMES = None


def _company_names():
    """Ticker -> full company name, sourced from NEPSE's official company
    directory (data/processed/company_names.json). Falls back to an empty
    dict if the file is missing, so this stays optional."""
    global _COMPANY_NAMES
    if _COMPANY_NAMES is None:
        path = PROCESSED_DIR / "company_names.json"
        try:
            with open(path, encoding="utf-8") as f:
                _COMPANY_NAMES = json.load(f)
        except (OSError, json.JSONDecodeError):
            _COMPANY_NAMES = {}
    return _COMPANY_NAMES


def _company_name(ticker):
    """Full company name for a ticker, falling back to the ticker itself
    (e.g. for a couple of renamed/delisted symbols not in the directory)."""
    return _company_names().get(ticker, ticker)


def _read_csv(path):
    if not path.exists():
        return []
    with open(path, newline="", encoding="utf-8") as f:
        return list(csv.DictReader(f))


def _ticker_list():
    path = PROCESSED_DIR / "ticker_list.txt"
    if not path.exists():
        return []
    return [t.strip() for t in path.read_text().splitlines() if t.strip()]


def _ticker_sector(ticker):
    path = PROCESSED_DIR / f"{ticker}_features.csv"
    if not path.exists():
        return None
    with open(path, newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        row = next(reader, None)
        return row.get("Sector") if row else None


def _tail_last_rows(path, count=2, chunk_bytes=8192):
    """Read the last `count` non-empty lines of a CSV without loading the
    whole file -- matters when DATA_DIR points at the full local dataset
    (some ticker histories run 1MB+) rather than the trimmed deploy_data/
    snapshot. A single seek+read from the end is enough since rows are
    short and fixed-width-ish."""
    if not path.exists():
        return []
    size = path.stat().st_size
    seek_pos = max(0, size - chunk_bytes)
    with open(path, "rb") as f:
        f.seek(seek_pos)
        data = f.read()
    lines = data.decode("utf-8", errors="ignore").splitlines()
    if seek_pos > 0 and lines:
        lines = lines[1:]  # drop a possibly-truncated first line
    return [ln for ln in lines if ln.strip()][-count:]


def _compute_top_movers(tickers, limit=5):
    """Today's (latest row vs. previous row) top gainers/losers across every
    tracked ticker -- our equivalent of ShareHub's Top Gainers/Top Losers
    widgets, computed from our own OHLCV data rather than a live feed."""
    movers = []
    for ticker in tickers:
        rows = _tail_last_rows(PROCESSED_DIR / f"{ticker}_features.csv", count=2)
        if len(rows) < 2:
            continue
        try:
            prev = next(csv.reader([rows[-2]]))
            curr = next(csv.reader([rows[-1]]))
            prev_close = float(prev[CLOSE_COL_INDEX])
            curr_close = float(curr[CLOSE_COL_INDEX])
            if prev_close <= 0:
                continue
            pct = round((curr_close / prev_close - 1) * 100, 2)
            movers.append({
                "ticker": ticker,
                "name": _company_name(ticker),
                "date": curr[0],
                "close": round(curr_close, 2),
                "change_pct": pct,
            })
        except (ValueError, IndexError):
            continue

    gainers = sorted(movers, key=lambda m: m["change_pct"], reverse=True)[:limit]
    losers = sorted(movers, key=lambda m: m["change_pct"])[:limit]
    return gainers, losers, movers


_MOVERS_CACHE = {"gainers": [], "losers": [], "all": [], "ts": 0.0}
_MOVERS_TTL_SECONDS = 300  # recompute at most once every 5 minutes


def _get_cached_movers(limit=5):
    """Shared, TTL-cached top-movers scan. Every ticker's CSV is tailed once
    per TTL window no matter how many pages/requests ask for it (the ticker
    strip on every page, plus the dashboard's own gainers/losers widgets),
    instead of re-scanning all ~260 tickers on every single request."""
    now = time.time()
    if now - _MOVERS_CACHE["ts"] >= _MOVERS_TTL_SECONDS:
        tickers = _ticker_list()
        gainers, losers, all_movers = _compute_top_movers(tickers, limit=max(limit, 8))
        _MOVERS_CACHE["gainers"] = gainers
        _MOVERS_CACHE["losers"] = losers
        _MOVERS_CACHE["all"] = all_movers
        _MOVERS_CACHE["ts"] = now
    return (
        _MOVERS_CACHE["gainers"][:limit],
        _MOVERS_CACHE["losers"][:limit],
        _MOVERS_CACHE["all"],
    )


_SEARCH_OPTIONS = None


def search_options():
    """Ticker list for the navbar search: [{"t": symbol, "n": company name}].

    Built once per process from two static files and served via /api/tickers,
    so the 260-entry list is fetched once by the browser instead of being
    inlined into every page's HTML.
    """
    global _SEARCH_OPTIONS
    if _SEARCH_OPTIONS is None:
        names = _company_names()
        _SEARCH_OPTIONS = [
            {"t": ticker, "n": names.get(ticker) or ""}
            for ticker in sorted(_ticker_list())
        ]
    return _SEARCH_OPTIONS


@main.app_context_processor
def inject_ticker_strip():
    """Site-wide scrolling ticker strip (like ShareHub's top bar) available
    to base.html on every page, not just the dashboard. Backed by the
    shared, cached movers scan above."""
    gainers, losers, _ = _get_cached_movers(limit=4)
    return {"ticker_strip": (gainers + losers)[:8]}


@main.route("/")
def dashboard():
    backtest_rows = _read_csv(MODELS_DIR / "backtest_summary_oos.csv")
    for r in backtest_rows:
        for k in ("ml_return_pct", "bnh_return_pct", "sharpe_ratio",
                   "max_drawdown_pct", "win_rate_pct"):
            try:
                r[k] = round(float(r[k]), 2)
            except (KeyError, ValueError):
                r[k] = 0.0
    tickers = _ticker_list()
    gainers, losers, _ = _get_cached_movers(limit=5)
    sector_models, retrained = _sector_models()
    sample = "NABIL" if "NABIL" in tickers else (sorted(tickers)[0] if tickers else None)
    quote = _latest_quote(sample) if sample else None
    return render_template(
        "dashboard.html",
        backtest_rows=backtest_rows,
        num_sectors=len(sector_models) or len(backtest_rows),
        num_tickers=len(tickers),
        tickers=sorted(tickers),
        top_gainers=gainers,
        top_losers=losers,
        sector_models=sector_models,
        prices_as_of=quote["date"] if quote else None,
        models_retrained=retrained,
    )


def _sector_models():
    """Each sector model's reliability tag for the dashboard (from retrain_report.csv)."""
    rows, retrained = [], None
    for sector, ev in sorted(model_evidence.load_evidence().items()):
        verdict = model_evidence.assess(ev)
        rows.append({
            "sector": sector,
            "model": "LSTM" if sector in explain.LSTM_SECTORS else "XGBoost",
            "level": verdict["level"], "label": verdict["label"], "caveat": verdict["caveat"],
            "accuracy": round(ev["accuracy"] * 100, 1), "baseline": round(ev["baseline_accuracy"] * 100, 1),
        })
        retrained = max(retrained or "", ev.get("run_date") or "") or None
    order = {"tested": 0, "unproven": 1, "no_edge": 2, "unknown": 3}
    rows.sort(key=lambda r: (order.get(r["level"], 9), r["sector"]))
    return rows, retrained


def _latest_quote(ticker):
    """OHLCV + turnover snapshot for a ticker's most recent trading day,
    plus the previous day's close for a day-over-day change -- everything
    here comes straight from our own processed OHLCV data, no fundamentals
    feed involved."""
    rows = _tail_last_rows(PROCESSED_DIR / f"{ticker}_features.csv", count=2)
    if not rows:
        return None
    try:
        curr = next(csv.reader([rows[-1]]))
        quote = {
            "date": curr[0],
            "open": float(curr[1]),
            "high": float(curr[2]),
            "low": float(curr[3]),
            "close": float(curr[4]),
            "volume": float(curr[5]),
            "turnover": float(curr[6]),
        }
    except (ValueError, IndexError):
        return None
    quote["prev_close"] = None
    quote["change"] = None
    quote["change_pct"] = None
    if len(rows) >= 2:
        try:
            prev = next(csv.reader([rows[-2]]))
            prev_close = float(prev[4])
            if prev_close > 0:
                quote["prev_close"] = round(prev_close, 2)
                quote["change"] = round(quote["close"] - prev_close, 2)
                quote["change_pct"] = round((quote["close"] / prev_close - 1) * 100, 2)
        except (ValueError, IndexError):
            pass
    for k in ("open", "high", "low", "close", "turnover"):
        quote[k] = round(quote[k], 2)
    quote["volume"] = int(quote["volume"])
    return quote


def _live_quote_safe(ticker):
    """Live quote for a ticker, or None. Never raises, never blocks long --
    reads the same cached snapshot the dashboard uses."""
    try:
        from ml.scraper.live_market import get_live_quote
        return get_live_quote(ticker)
    except Exception:
        return None


@main.route("/stock/<ticker>")
def stock_detail(ticker):
    ticker = ticker.upper()
    sector = _ticker_sector(ticker)
    live = _live_quote_safe(ticker)

    # NEPSE trades ~333 instruments, but our processed dataset covers only the
    # 260 equities the models were trained on. Mutual funds, debentures and
    # newly listed scrips show up in the live feed (and therefore in the live
    # movers tables) with no history behind them -- serve those as a live-only
    # page instead of a 404.
    if sector is None:
        if not live:
            abort(404, description=f"No data for ticker '{ticker}'")
        return render_template(
            "stock_detail.html",
            ticker=ticker,
            sector=None,
            company_name=live.get("name") or ticker,
            quote=None,
            has_history=False,
        )

    return render_template(
        "stock_detail.html", ticker=ticker, sector=sector,
        company_name=_company_name(ticker),
        quote=_latest_quote(ticker),
        has_history=True,
        forecast_evidence=insights.load_forecast_evidence(),
    )


def _signal_evidence():
    """Honest signal tests (models/signal_evidence.json); None if the file is missing."""
    path = MODELS_DIR / "signal_evidence.json"
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


@main.route("/privacy")
def privacy():
    return render_template("privacy.html")


@main.route("/terms")
def terms():
    return render_template("terms.html")


@main.route("/backtest")
def backtest():
    rows = _read_csv(MODELS_DIR / "backtest_summary_oos.csv")
    for r in rows:
        for k in ("ml_return_pct", "bnh_return_pct", "sharpe_ratio",
                   "max_drawdown_pct", "win_rate_pct"):
            try:
                r[k] = round(float(r[k]), 2)
            except (KeyError, ValueError):
                r[k] = 0.0
        try:
            r["num_trades"] = int(float(r["num_trades"]))
        except (KeyError, ValueError):
            r["num_trades"] = 0
    return render_template("backtest.html", rows=rows, evidence=_signal_evidence())
