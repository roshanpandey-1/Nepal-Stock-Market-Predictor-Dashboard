"""
Example: Load trained models and get prediction for a stock
Run from project root: python examples/run_prediction.py
"""
import sys
sys.path.append(".")
import pandas as pd
from src.models.classifier import SignalClassifier
from src.models.forecaster import ProphetForecaster

ticker = "NABIL"

# Load models
clf = SignalClassifier.load(f"data/models/{ticker}_classifier.pkl")
forecaster = ProphetForecaster.load(f"data/models/{ticker}_prophet.pkl")

# Load latest features
df = pd.read_csv(f"data/processed/{ticker}_features.csv")
latest = df.drop(columns=["Date","Open","High","Low","Close","Volume","Ticker","Label","Future_Return"], errors="ignore").tail(1)

# Get signal
result = clf.predict(latest)
print(f"\n📊 {ticker} Signal: {result['signal']} ({result['confidence']*100:.1f}% confidence)")
print(f"   Buy: {result['probabilities']['Buy']*100:.1f}% | Hold: {result['probabilities']['Hold']*100:.1f}% | Sell: {result['probabilities']['Sell']*100:.1f}%")

# Get forecast
forecast = forecaster.forecast(days=7)
print(f"\n📈 7-Day Price Forecast:")
print(forecast.to_string(index=False))
