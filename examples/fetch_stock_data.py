"""
Example: Fetch, engineer features, label and save all stocks
Run: python examples/fetch_stock_data.py
"""
import sys
sys.path.append('.')

from src.scraper.nepse_scraper import NEPSEScraper
from src.features.technical_indicators import TechnicalIndicators
from src.features.labeler import add_labels

scraper = NEPSEScraper()
ti = TechnicalIndicators()

tickers = ['NABIL', 'NICA', 'NTC', 'HBL', 'GBIME',
           'ADBL', 'EBL', 'SCB', 'SBI', 'SANIMA']

for ticker in tickers:
    df = scraper.fetch_stock_history(ticker)
    if df.empty:
        continue
    df = ti.add_all(df)
    df = add_labels(df)
    scraper.save(df, ticker)                                          # → data/raw/
    df.to_csv(f'data/processed/{ticker}_features.csv', index=False)  # → data/processed/
    print(f'{ticker}: {df.shape} saved')