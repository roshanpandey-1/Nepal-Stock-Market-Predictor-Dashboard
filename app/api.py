"""
JSON API for the dashboard's charts and live signal lookups.

All model inference here mirrors examples/run_backtests_oos.py: it loads the
same *_oos LSTM/XGBoost models trained on a chronological 2-year window with
the last 3 months held out, and applies them to a ticker's latest feature
row(s). See README.md "Known limitation" section -- 6 of 8 sector models
default heavily to Hold on unseen data, so a Buy/Sell signal here should be
read with that caveat, not as a confident trading recommendation.
"""
import csv
import pickle
from pathlib import Path

from flask import Blueprint, jsonify

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
                "Non Life Insurance"}
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

        return jsonify({
            "ticker": ticker,
            "sector": sector,
            "signal": LABELS[pred],
            "confidence": round(max(probs), 4),
            "probabilities": {LABELS[i]: round(p, 4) for i, p in enumerate(probs)},
            "note": "Out-of-sample model; several sectors default heavily to Hold -- see README Known Limitations.",
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
        "recent_headlines": list(reversed(headlines))[:10],
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
