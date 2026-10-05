"""
NEPSE News Sentiment Analyzer
Scrapes latest news from Sharesansar and scores sentiment using FinBERT.
Produces a daily market-wide sentiment score (per-stock matching was tried
and found unreliable — see notebooks/sentiment_analysis.ipynb for why).

Run: python src/nlp/sentiment_analyzer.py
"""
import sys
sys.path.append('.')

import os
os.environ["TRANSFORMERS_NO_TF"] = "1"
os.environ["USE_TF"] = "0"

import time
import pandas as pd
from selenium import webdriver
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.chrome.options import Options
from webdriver_manager.chrome import ChromeDriverManager
from bs4 import BeautifulSoup
from transformers import pipeline
from loguru import logger


class NewsSentimentAnalyzer:
    BASE_URL = 'https://www.sharesansar.com/category/latest'

    def __init__(self):
        self._finbert = None  # lazy-loaded, it's a ~400MB download on first use

    @property
    def finbert(self):
        if self._finbert is None:
            logger.info("Loading FinBERT model...")
            self._finbert = pipeline(
                "sentiment-analysis", model="ProsusAI/finbert", framework="pt"
            )
        return self._finbert

    def _get_driver(self):
        options = Options()
        options.add_argument('--headless')
        options.add_argument('--no-sandbox')
        options.add_argument('--disable-dev-shm-usage')
        return webdriver.Chrome(
            service=Service(ChromeDriverManager().install()), options=options
        )

    def _scrape_page(self, driver, url):
        """Scrape one page of headlines, return (articles, next_page_url_or_None)."""
        driver.get(url)
        time.sleep(2)
        soup = BeautifulSoup(driver.page_source, 'lxml')

        news_items = soup.find_all('div', class_='featured-news-list')
        articles = []
        for item in news_items:
            title_tag = item.find('h4', class_='featured-news-title')
            date_tag = item.find('span', class_='text-org')
            link_tag = item.find('a', href=lambda x: x and 'newsdetail' in x)
            if title_tag and link_tag:
                articles.append({
                    'title': title_tag.get_text(strip=True),
                    'date': date_tag.get_text(strip=True) if date_tag else None,
                    'url': link_tag['href']
                })

        # IMPORTANT: must use rel="next" specifically — the pagination links
        # alternate between prev/next without it, causing an infinite
        # back-and-forth loop between two pages.
        next_link = soup.find('a', rel='next')
        next_cursor = next_link['href'] if next_link else None
        return articles, next_cursor

    def scrape_news(self, max_pages: int = 50) -> pd.DataFrame:
        """Scrape up to max_pages of latest NEPSE news headlines."""
        driver = self._get_driver()
        all_articles = []
        current_url = self.BASE_URL

        for page in range(max_pages):
            articles, next_cursor = self._scrape_page(driver, current_url)
            all_articles.extend(articles)

            if (page + 1) % 10 == 0:
                logger.info(f"Page {page+1}/{max_pages} | Total articles: {len(all_articles)}")

            if not next_cursor:
                logger.info("No more pages")
                break
            current_url = f"{self.BASE_URL}{next_cursor}"
            time.sleep(0.5)

        driver.quit()

        df = pd.DataFrame(all_articles)
        df = df.drop_duplicates(subset='url').reset_index(drop=True)
        logger.info(f"Scraped {len(df)} unique articles")
        return df

    def score_sentiment(self, df: pd.DataFrame) -> pd.DataFrame:
        """Apply FinBERT sentiment scoring to a dataframe with a 'title' column."""
        def _score(text):
            result = self.finbert(text)[0]
            return result['label'], result['score']

        results = df['title'].apply(_score)
        df = df.copy()
        df['finbert_label'] = results.apply(lambda x: x[0])
        df['finbert_score'] = results.apply(lambda x: x[1])
        logger.info(f"Sentiment distribution: {df['finbert_label'].value_counts().to_dict()}")
        return df

    def build_daily_sentiment(self, df: pd.DataFrame) -> pd.DataFrame:
        """Aggregate per-headline sentiment into one market-wide score per day."""
        df = df.copy()
        df['Date'] = pd.to_datetime(df['date'], format='%A, %B %d, %Y', errors='coerce')

        sentiment_map = {'positive': 1, 'neutral': 0, 'negative': -1}
        df['sentiment_numeric'] = df['finbert_label'].map(sentiment_map)

        daily = df.groupby('Date').agg(
            avg_sentiment=('sentiment_numeric', 'mean'),
            news_count=('sentiment_numeric', 'count')
        ).reset_index()
        return daily

    def run(self, max_pages: int = 50, output_dir: str = 'data/news') -> pd.DataFrame:
        """Full pipeline: scrape -> score -> aggregate -> save. Returns daily sentiment df."""
        os.makedirs(output_dir, exist_ok=True)

        df = self.scrape_news(max_pages=max_pages)
        df = self.score_sentiment(df)
        df.to_csv(f'{output_dir}/news_sentiment.csv', index=False)
        logger.info(f"Saved headline-level sentiment to {output_dir}/news_sentiment.csv")

        daily = self.build_daily_sentiment(df)
        daily.to_csv(f'{output_dir}/daily_market_sentiment.csv', index=False)
        logger.info(f"Saved daily market sentiment to {output_dir}/daily_market_sentiment.csv")

        return daily


# ── Test ─────────────────────────────────────────────────────
if __name__ == '__main__':
    analyzer = NewsSentimentAnalyzer()
    daily_sentiment = analyzer.run(max_pages=50)
    print(daily_sentiment)