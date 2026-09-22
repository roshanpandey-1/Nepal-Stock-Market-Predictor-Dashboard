"""
NEPSE Stock Data Scraper
Uses NepseUnofficialApi to fetch real OHLCV data
"""
import pandas as pd
from nepse import NEPSE as Nepse  # pip package exports class NEPSE, not Nepse
from loguru import logger
from pathlib import Path


class NEPSEScraper:
    def __init__(self):
        self.nepse = Nepse()
        self.nepse.setTLSVerification(False)

    def fetch_stock_history(self, ticker: str) -> pd.DataFrame:
        try:
            raw = self.nepse.getCompanyPriceVolumeHistory(ticker)
            df = pd.DataFrame(raw['content'])
            df = df.rename(columns={
                'businessDate':        'Date',
                'highPrice':           'High',
                'lowPrice':            'Low',
                'closePrice':          'Close',
                'totalTradedQuantity': 'Volume',
                'totalTrades':         'Trades',
                'totalTradedValue':    'Turnover'
            })
            df['Date'] = pd.to_datetime(df['Date'])
            df = df.sort_values('Date').reset_index(drop=True)
            df['Ticker'] = ticker
            logger.info(f"{ticker}: {len(df)} rows fetched")
            return df
        except Exception as e:
            logger.error(f"Error fetching {ticker}: {e}")
            return pd.DataFrame()

    def save(self, df: pd.DataFrame, ticker: str):
        path = Path("data/raw") / f"{ticker}.csv"
        df.to_csv(path, index=False)
        logger.info(f"Saved -> {path}")

    def get_top_gainers(self):
        return self.nepse.getTopGainers()

    def get_top_losers(self):
        return self.nepse.getTopLosers()

    def get_market_summary(self):
        return self.nepse.getSummary()