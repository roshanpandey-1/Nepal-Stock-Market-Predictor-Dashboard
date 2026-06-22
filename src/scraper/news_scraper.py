"""
Financial News Scraper
Fetches headlines from Sharesansar and OnlineKhabar business section
"""
import requests
import pandas as pd
import time
from bs4 import BeautifulSoup
from loguru import logger
from datetime import datetime


class NewsScraper:
    def __init__(self):
        self.headers = {"User-Agent": "Mozilla/5.0"}

    def fetch_sharesansar_news(self, pages: int = 5) -> pd.DataFrame:
        """Fetch latest market news headlines from Sharesansar."""
        articles = []
        for page in range(1, pages + 1):
            try:
                url = f"https://www.sharesansar.com/category/latest?page={page}"
                r = requests.get(url, headers=self.headers, timeout=10)
                soup = BeautifulSoup(r.text, "lxml")

                for item in soup.select(".featured-news-list"):
                    title = item.select_one("h4")
                    date  = item.select_one(".date-time")
                    link  = item.select_one("a")
                    if title:
                        articles.append({
                            "source":    "sharesansar",
                            "title":     title.text.strip(),
                            "date":      date.text.strip() if date else None,
                            "url":       link["href"] if link else None,
                            "scraped_at": datetime.now().isoformat()
                        })

                logger.info(f"Sharesansar news | Page {page}: {len(articles)} total")
                time.sleep(1)
            except Exception as e:
                logger.error(f"News scrape error page {page}: {e}")

        return pd.DataFrame(articles)

    def save(self, df: pd.DataFrame, filename: str = "news_raw.csv"):
        path = f"data/raw/{filename}"
        df.to_csv(path, index=False)
        logger.info(f"Saved {len(df)} news articles → {path}")
