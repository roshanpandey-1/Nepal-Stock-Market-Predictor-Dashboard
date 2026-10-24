"""
JSON API for the dashboard's charts and live signal lookups.

All model inference here mirrors examples/run_backtests_oos.py: it loads the
same *_oos LSTM/XGBoost models trained on a chronological 2-year window with
the last 3 months held out, and applies them to a ticker's latest feature
row(s). See README.md "Known limitation" section -- many sector models
default heavily to Hold on unseen data, so every /signal response carries a
"reliability" verdict (see model_evidence.py) built from that sector's latest
holdout test, and a Buy/Sell/Hold here is not a confident trading recommendation.
"""
import csv
import pickle
from pathlib import Path

from flask import Blueprint, jsonify

from . import model_evidence, news_utils

api = Blueprint("api", __name__)

import os
DATA_DIR = Path(os.environ.get("DATA_DIR", "data"))
MODELS_DIR = DATA_DIR / "models"
PROCESSED_DIR = DATA_DIR / "processed"
NEWS_DIR = DATA_DIR / "news"

SEQ_LEN = 10
DROP_COLS = {"Date", "Open", "High", "Low", "Close", "Volume", "Trades",
             "Turnover", "Ticker", "Label", "Future_Return", "Sector"}
LSTM_SECTORS = {"Hydro Power", "Microfinance", "Commercial Banks",
                "Development Banks", "Finance", "Life Insurance",
                "Non Life Insurance",
                # Added for learning/coverage purposes -- these 4 collapse to
                # "Hold" even more heavily than the original 8 (0 trades on
                # the chronological OOS holdout for the representative
                # ticker in each). Kept in for completeness, not because
                # the signal is trustworthy -- see README Known Limitations.
                "Hotels And Tourism", "Investment", "Others", "Tradings"}
LABELS = {0: "Sell", 1: "Hold", 2: "Buy"}


def _read_feature_rows(ticker):
    path = PROCESSED_DIR / f"{ticker}_features.csv"
    if not path.exists():
        return None
    with open(path, newline="", encoding="utf-8") as f:
        return list(csv.DictReader(f))


@api.route("/forecast/<ticker>")
def forecast(ticker):
    """Recent price history for the chart. (No forecasting model has been
    built/validated in this project yet -- see README -- so this honestly
    returns historical closes, not a prediction.)"""
    ticker = ticker.upper()
    rows = _read_feature_rows(ticker)
    if rows is None:
        return jsonify({"ticker": ticker, "history": [], "status": "ticker not found"}), 404

    recent = rows[-180:]
    history = []
    for r in recent:
        if not r.get("Close"):
            continue
        entry = {"date": r["Date"], "close": float(r["Close"])}
        try:
            entry["volume"] = float(r["Volume"])
        except (KeyError, ValueError, TypeError):
            entry["volume"] = None
        history.append(entry)
    return jsonify({"ticker": ticker, "history": history, "status": "historical_only"})


@api.route("/price-forecast/<ticker>")
def price_forecast(ticker):
    """Precomputed Prophet forecast (fit on daily closes, data/models/forecast_*.csv,
    built by examples/build_forecasts.py) for one ticker.

    This is a SEPARATE, independent signal from both /live/quote (today's
    actual traded price) and /signal (the sector LSTM/XGBoost Buy-Sell-Hold
    classifier) -- it never overrides either. The stock page renders it in
    its own container precisely so a stale forecast snapshot is never
    confused with today's live price.

    Deliberately NOT fit live here: Prophet takes a few seconds per ticker,
    far too slow for a request. 404s for any ticker the batch script skipped
    (not enough price history) or hasn't covered yet.
    """
    ticker = ticker.upper()

    summary_path = MODELS_DIR / "forecast_summary.csv"
    daily_path = MODELS_DIR / "forecast_daily.csv"
    if not summary_path.exists() or not daily_path.exists():
        return jsonify({"ticker": ticker, "status": "not_available",
                         "error": "forecast data has not been generated yet"}), 404

    summary_row = None
    with open(summary_path, newline="", encoding="utf-8") as f:
        for row in csv.DictReader(f):
            if row["ticker"].strip().upper() == ticker:
                summary_row = row
                break
    if summary_row is None:
        return jsonify({"ticker": ticker, "status": "not_available",
                         "error": "no forecast for this ticker (too little price "
                                  "history, or not yet covered by the forecast batch)"}), 404

    days = []
    with open(daily_path, newline="", encoding="utf-8") as f:
        for row in csv.DictReader(f):
            if row["ticker"].strip().upper() != ticker:
                continue
            days.append({
                "day_offset": int(row["day_offset"]),
                "date": row["date"],
                "forecast_price": float(row["forecast_price"]),
                "lower_bound": float(row["lower_bound"]),
                "upper_bound": float(row["upper_bound"]),
                "change_pct": float(row["change_pct"]) if row["change_pct"] not in (None, "") else None,
            })
    days.sort(key=lambda d: d["day_offset"])

    return jsonify({
        "ticker": ticker,
        "status": "ok",
        "current_price": float(summary_row["current_price"]),
        "horizon_days": int(summary_row["horizon_days"]),
        "rows_used": int(summary_row["rows_used"]),
        "generated_at": summary_row["generated_at"],
        "days": days,
    })


@api.route("/signal/<ticker>")
def signal(ticker):
    ticker = ticker.upper()
    rows = _read_feature_rows(ticker)
    if not rows:
        return jsonify({"ticker": ticker, "signal": None, "error": "ticker not found"}), 404

    sector = rows[0].get("Sector")
    sector_name = sector.replace(" ", "_").replace("/", "_") if sector else None
    feature_cols = [c for c in rows[0].keys() if c not in DROP_COLS]

    def clean_row(r):
        try:
            return [float(r[c]) for c in feature_cols]
        except (ValueError, TypeError):
            return None

    try:
        if sector in LSTM_SECTORS:
            import torch
            import torch.nn as nn

            class StockLSTM(nn.Module):
                def __init__(self, input_dim, hidden_dim=128, num_layers=2, dropout=0.3):
                    super().__init__()
                    self.lstm = nn.LSTM(input_size=input_dim, hidden_size=hidden_dim,
                                         num_layers=num_layers, batch_first=True, dropout=dropout)
                    self.classifier = nn.Sequential(
                        nn.Linear(hidden_dim, 64), nn.ReLU(), nn.Dropout(0.2), nn.Linear(64, 3)
                    )

                def forward(self, x):
                    lstm_out, _ = self.lstm(x)
                    return self.classifier(lstm_out[:, -1, :])

            model_path = MODELS_DIR / f"{sector_name}_lstm_model_oos.pth"
            scaler_path = MODELS_DIR / f"{sector_name}_scaler_oos.pkl"
            if not model_path.exists() or not scaler_path.exists():
                return jsonify({"ticker": ticker, "sector": sector, "signal": None,
                                 "error": "model not found for this sector"}), 404

            usable = [r for r in rows[-(SEQ_LEN + 5):] if clean_row(r) is not None]
            if len(usable) < SEQ_LEN:
                return jsonify({"ticker": ticker, "sector": sector, "signal": None,
                                 "error": "not enough recent clean data to build a sequence"}), 200

            seq_raw = [clean_row(r) for r in usable[-SEQ_LEN:]]
            with open(scaler_path, "rb") as f:
                scaler = pickle.load(f)
            seq_scaled = scaler.transform(seq_raw)

            model = StockLSTM(input_dim=len(feature_cols))
            model.load_state_dict(torch.load(model_path, map_location="cpu"))
            model.eval()
            with torch.no_grad():
                x = torch.FloatTensor(seq_scaled).unsqueeze(0)
                probs = torch.softmax(model(x), dim=1).squeeze(0).tolist()
                pred = int(torch.argmax(model(x), dim=1).item())

        else:  # XGBoost sector (Manufacturing And Processing)
            model_path = MODELS_DIR / f"{sector_name}_xgb_model_oos.pkl"
            if not model_path.exists():
                return jsonify({"ticker": ticker, "sector": sector, "signal": None,
                                 "error": "model not found for this sector"}), 404
            latest = None
            for r in reversed(rows):
                cr = clean_row(r)
                if cr is not None:
                    latest = cr
                    break
            if latest is None:
                return jsonify({"ticker": ticker, "sector": sector, "signal": None,
                                 "error": "no clean recent row to score"}), 200

            with open(model_path, "rb") as f:
                model = pickle.load(f)
            pred = int(model.predict([latest])[0])
            probs = [float(p) for p in model.predict_proba([latest])[0]]

        reliability = model_evidence.assess(model_evidence.for_sector(sector))
        return jsonify({
            "ticker": ticker,
            "sector": sector,
            "signal": LABELS[pred],
            "confidence": round(max(probs), 4),
            "probabilities": {LABELS[i]: round(p, 4) for i, p in enumerate(probs)},
            "reliability": reliability,
            "note": reliability["headline"],
        })
    except Exception as e:
        return jsonify({"ticker": ticker, "sector": sector, "signal": None, "error": str(e)}), 500


@api.route("/sentiment/<ticker>")
def sentiment(ticker):
    """Sentiment here is market-wide, not per-ticker -- per-stock news
    matching was tried during scraping and found unreliable (see
    src/nlp/sentiment_analyzer.py), so this returns the overall market
    sentiment trend and recent headlines rather than fabricating a
    ticker-specific score."""
    ticker = ticker.upper()
    daily_path = NEWS_DIR / "daily_market_sentiment.csv"
    news_path = NEWS_DIR / "news_sentiment.csv"
    daily = []
    if daily_path.exists():
        with open(daily_path, newline="", encoding="utf-8") as f:
            daily = list(csv.DictReader(f))
    headlines = []
    if news_path.exists():
        with open(news_path, newline="", encoding="utf-8") as f:
            headlines = list(csv.DictReader(f))
    return jsonify({
        "ticker": ticker,
        "scope": "market_wide",
        "daily_sentiment": daily[-30:],
        "recent_headlines": news_utils.recent_headlines(headlines, 10),
    })


@api.route("/market/overview")
def market_overview():
    ticker_list_path = PROCESSED_DIR / "ticker_list.txt"
    tickers = []
    if ticker_list_path.exists():
        tickers = [t.strip() for t in ticker_list_path.read_text().splitlines() if t.strip()]

    backtest_path = MODELS_DIR / "backtest_summary_oos.csv"
    sectors = []
    if backtest_path.exists():
        with open(backtest_path, newline="", encoding="utf-8") as f:
            sectors = list(csv.DictReader(f))

    daily_path = NEWS_DIR / "daily_market_sentiment.csv"
    latest_sentiment = None
    if daily_path.exists():
        with open(daily_path, newline="", encoding="utf-8") as f:
            rows = list(csv.DictReader(f))
            latest_sentiment = rows[-1] if rows else None

    return jsonify({
        "num_tickers": len(tickers),
        "num_sectors": len(sectors),
        "sectors": [s["sector"] for s in sectors],
        "latest_market_sentiment": latest_sentiment,
    })


@api.route("/live")
def live_market():
    """Live NEPSE market snapshot (index, market status, top movers).

    Served from a short TTL cache in src/scraper/live_market.py -- NEPSE is
    never called per page load. Always returns HTTP 200 with an `available`
    flag rather than an error status, so the dashboard can degrade quietly
    when NEPSE is unreachable (a real possibility from hosts outside Nepal).

    Note: these are intraday values for display only. They are deliberately
    NOT fed into the Buy/Sell/Hold models, which were trained on completed
    daily candles -- see README "Known limitation".
    """
    try:
        from src.scraper.live_market import get_live_snapshot
        snapshot = dict(get_live_snapshot())
        # per-ticker lookup is server-side only; all ~333 rows would bloat
        # every 60s poll for data the dashboard doesn't display
        snapshot.pop("_quotes", None)
        snapshot.pop("_breadth_quotes", None)
        return jsonify(snapshot)
    except Exception as exc:  # import error, unexpected bug -- never 500 the page
        return jsonify({
            "available": False,
            "reason": f"Live data unavailable ({type(exc).__name__})",
            "market_open": None,
            "index": None,
            "gainers": [],
            "losers": [],
            "stale": False,
        })


@api.route("/live/breadth/<bucket>")
def live_breadth_list(bucket):
    """Every scrip behind the Advancing / Declining / Unchanged pills, with its
    full quote, for the dashboard's pop-up table. Same cached snapshot as
    /api/live, so no extra NEPSE call. Always 200 with an `available` flag."""
    bucket = (bucket or "").strip().lower()
    try:
        from src.scraper.live_market import get_breadth_list
        result = get_breadth_list(bucket)
        if result is None:
            return jsonify({"available": False, "bucket": bucket,
                            "reason": "unknown bucket", "rows": [], "count": 0}), 404
        return jsonify(result)
    except Exception as exc:
        return jsonify({"available": False, "bucket": bucket, "rows": [], "count": 0,
                        "reason": f"Live data unavailable ({type(exc).__name__})"})


@api.route("/live/quote/<ticker>")
def live_quote(ticker):
    """Live quote for a single ticker.

    Served from the same cached getLiveMarket payload the dashboard uses, so
    this costs no extra NEPSE calls. Returns available=false (not an error)
    when live data is unavailable or the ticker isn't trading today, letting
    the stock page fall back to its end-of-day figures.
    """
    ticker = (ticker or "").strip().upper()
    try:
        from src.scraper.live_market import get_live_quote
        quote = get_live_quote(ticker)
        if not quote:
            return jsonify({"available": False, "ticker": ticker})
        quote["available"] = True
        return jsonify(quote)
    except Exception as exc:
        return jsonify({
            "available": False,
            "ticker": ticker,
            "reason": f"{type(exc).__name__}",
        })


@api.route("/tickers")
def tickers():
    """Ticker + company name list, for the navbar search autocomplete.

    Fetched once per page rather than inlined into every page's HTML.
    """
    try:
        from app.routes import search_options
        return jsonify(search_options())
    except Exception:
        return jsonify([])
