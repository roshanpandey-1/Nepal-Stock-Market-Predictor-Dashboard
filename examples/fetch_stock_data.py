"""
Example: Fetch and save NEPSE stock data
Run from project root: python examples/fetch_stock_data.py
"""
import sys
sys.path.append(".")

from src.scraper.nepse_scraper import NEPSEScraper
from src.features.technical_indicators import TechnicalIndicators
from src.features.labeler import add_labels

scraper = NEPSEScraper()
ti = TechnicalIndicators()

tickers = ["NABIL", "NICA", "NTC"]

for ticker in tickers:
    print(f"\nFetching {ticker}...")
    df = scraper.fetch_stock_history(ticker, pages=5)
    if df.empty:
        print(f"  No data for {ticker}")
        continue
    df = ti.add_all(df)
    df = add_labels(df)
    scraper.save(df, ticker)
    print(f"  {ticker}: {len(df)} rows, {len(df.columns)} features")
