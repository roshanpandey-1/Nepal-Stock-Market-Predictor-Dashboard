from flask import Blueprint, jsonify

api = Blueprint("api", __name__)

@api.route("/forecast/<ticker>")
def forecast(ticker):
    # TODO: load forecaster model and return predictions
    return jsonify({"ticker": ticker, "forecast": [], "status": "not implemented yet"})

@api.route("/signal/<ticker>")
def signal(ticker):
    # TODO: load classifier model and return Buy/Sell/Hold signal
    return jsonify({"ticker": ticker, "signal": None, "confidence": None, "shap_values": []})

@api.route("/sentiment/<ticker>")
def sentiment(ticker):
    # TODO: return latest news + sentiment scores for ticker
    return jsonify({"ticker": ticker, "articles": []})

@api.route("/market/overview")
def market_overview():
    # TODO: return top movers, index value, sector performance
    return jsonify({"index": None, "top_gainers": [], "top_losers": []})
