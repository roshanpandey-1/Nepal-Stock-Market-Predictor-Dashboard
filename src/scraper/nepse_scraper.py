"""
NEPSE Stock Data Scraper
Fetches OHLCV data from Sharesansar and Merolagani
"""
import requests
import pandas as pd
import time
import yaml
from bs4 import BeautifulSoup
from loguru import logger
from pathlib import Path


class NEPSEScraper:
    def __init__(self, config_path="config/scraper_config.yaml"):
        with open(config_path) as f:
            self.config = yaml.safe_load(f)
        self.headers = self.config["headers"]
        self.delay = self.config["sources"]["sharesansar"]["delay_seconds"]

    def fetch_stock_history(self, ticker: str, pages: int = 10) -> pd.DataFrame:
        """
        Fetch historical OHLCV data for a given ticker from Sharesansar.
        Returns a cleaned DataFrame with Date, Open, High, Low, Close, Volume.
        """
        all_data = []
        base_url = f"https://www.sharesansar.com/company/{ticker}"

        for page in range(1, pages + 1):
            try:
                url = f"{base_url}?page={page}"
                response = requests.get(url, headers=self.headers, timeout=10)
                soup = BeautifulSoup(response.text, "lxml")

                table = soup.find("table", {"id": "headFixed"})
                if not table:
                    logger.warning(f"No table found for {ticker} page {page}")
                    break

                rows = table.find("tbody").find_all("tr")
                for row in rows:
                    cols = [td.text.strip() for td in row.find_all("td")]
                    if len(cols) >= 7:
                        all_data.append({
                            "Date":   cols[0],
                            "Open":   cols[2],
                            "High":   cols[3],
                            "Low":    cols[4],
                            "Close":  cols[1],
                            "Volume": cols[6],
                        })

                logger.info(f"{ticker} | Page {page} scraped ({len(rows)} rows)")
                time.sleep(self.delay)

            except Exception as e:
                logger.error(f"Error scraping {ticker} page {page}: {e}")
                break

        df = pd.DataFrame(all_data)
        if not df.empty:
            df = self._clean_dataframe(df, ticker)
        return df

    def _clean_dataframe(self, df: pd.DataFrame, ticker: str) -> pd.DataFrame:
        df["Date"] = pd.to_datetime(df["Date"], dayfirst=True, errors="coerce")
        for col in ["Open", "High", "Low", "Close", "Volume"]:
            df[col] = pd.to_numeric(df[col].str.replace(",", ""), errors="coerce")
        df["Ticker"] = ticker
        df = df.dropna(subset=["Date", "Close"])
        df = df.sort_values("Date").reset_index(drop=True)
        return df

    def save(self, df: pd.DataFrame, ticker: str):
        path = Path("data/raw") / f"{ticker}.csv"
        df.to_csv(path, index=False)
        logger.info(f"Saved {len(df)} rows → {path}")
