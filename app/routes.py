import csv
from pathlib import Path
from flask import Blueprint, render_template, abort

main = Blueprint("main", __name__)

DATA_DIR = Path("data")
MODELS_DIR = DATA_DIR / "models"
PROCESSED_DIR = DATA_DIR / "processed"
NEWS_DIR = DATA_DIR / "news"


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
    sentiment_rows = _read_csv(NEWS_DIR / "daily_market_sentiment.csv")
    latest_sentiment = sentiment_rows[-1] if sentiment_rows else None
    return render_template(
        "dashboard.html",
        backtest_rows=backtest_rows,
        num_sectors=len(backtest_rows),
        num_tickers=len(tickers),
        tickers=sorted(tickers),
        latest_sentiment=latest_sentiment,
    )


@main.route("/stock/<ticker>")
def stock_detail(ticker):
    ticker = ticker.upper()
    sector = _ticker_sector(ticker)
    if sector is None:
        abort(404, description=f"No processed data for ticker '{ticker}'")
    return render_template("stock_detail.html", ticker=ticker, sector=sector)


@main.route("/sentiment")
def sentiment():
    daily_rows = _read_csv(NEWS_DIR / "daily_market_sentiment.csv")
    headlines = _read_csv(NEWS_DIR / "news_sentiment.csv")
    headlines = list(reversed(headlines))[:25]
    return render_template("sentiment.html", daily_rows=daily_rows, headlines=headlines)


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
    return render_template("backtest.html", rows=rows)
