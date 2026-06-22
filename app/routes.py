from flask import Blueprint, render_template

main = Blueprint("main", __name__)

@main.route("/")
def dashboard():
    return render_template("dashboard.html")

@main.route("/stock/<ticker>")
def stock_detail(ticker):
    return render_template("stock_detail.html", ticker=ticker.upper())

@main.route("/sentiment")
def sentiment():
    return render_template("sentiment.html")

@main.route("/backtest")
def backtest():
    return render_template("backtest.html")
