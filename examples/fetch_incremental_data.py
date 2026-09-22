"""
Incremental Historical Data Updater
Fetches only NEW rows (since each ticker's last saved date) from Sharesansar
and appends them to data/raw/{ticker}.csv, then recomputes features/labels
and rewrites data/processed/{ticker}_features.csv.

Unlike fetch_historical_data.py (which does a full 15-20 hour history pull),
this is meant to be run periodically to catch the project back up to the
present day. A run covering a ~3 month gap for 260 tickers should take
roughly 30-60 minutes depending on network/page-load speed.

Run: python examples/fetch_incremental_data.py
"""
import sys
sys.path.append('.')

import time
from pathlib import Path
import pandas as pd
from selenium import webdriver
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from webdriver_manager.chrome import ChromeDriverManager
from bs4 import BeautifulSoup
from src.features.technical_indicators import TechnicalIndicators
from src.features.labeler import add_labels
from loguru import logger

RAW_DIR = Path("data/raw")
PROCESSED_DIR = Path("data/processed")
DONE_LOG = PROCESSED_DIR / "incremental_done.txt"


def get_driver():
    options = Options()
    options.add_argument('--headless')
    options.add_argument('--no-sandbox')
    options.add_argument('--disable-dev-shm-usage')
    options.add_argument('--disable-gpu')
    return webdriver.Chrome(
        service=Service(ChromeDriverManager().install()),
        options=options
    )


def scrape_new_rows(driver, ticker: str, last_known_date: pd.Timestamp) -> pd.DataFrame:
    """Scrape Sharesansar price history, stopping as soon as we reach a row
    at or before last_known_date (the table is newest-first)."""
    try:
        driver.get(f'https://www.sharesansar.com/company/{ticker}')
        time.sleep(4)
        try:
            WebDriverWait(driver, 10).until(
                EC.element_to_be_clickable((By.LINK_TEXT, 'Price History'))
            ).click()
            time.sleep(3)
        except Exception:
            logger.warning(f"{ticker}: Could not click Price History")
            return pd.DataFrame()

        all_rows = []
        page = 1
        reached_known_data = False

        while not reached_known_data:
            soup = BeautifulSoup(driver.page_source, 'lxml')
            table = soup.find('table', {'id': 'myTableCPriceHistory'})
            if not table:
                break

            rows = table.find('tbody').find_all('tr')
            for row in rows:
                cols = [td.text.strip() for td in row.find_all('td')]
                if len(cols) < 8:
                    continue
                row_date = pd.to_datetime(cols[1], errors='coerce')
                if pd.isna(row_date):
                    continue
                if row_date <= last_known_date:
                    reached_known_data = True
                    break
                all_rows.append({
                    'Date': cols[1], 'Open': cols[2], 'High': cols[3],
                    'Low': cols[4], 'Close': cols[5], 'Volume': cols[7],
                    'Turnover': cols[8] if len(cols) > 8 else None
                })

            if reached_known_data:
                break

            try:
                next_btn = driver.find_element(By.CSS_SELECTOR, '#myTableCPriceHistory_next')
                if 'disabled' in next_btn.get_attribute('class'):
                    break
                next_btn.click()
                time.sleep(1.5)
                page += 1
            except Exception:
                break

        if not all_rows:
            return pd.DataFrame()

        df = pd.DataFrame(all_rows)
        df['Date'] = pd.to_datetime(df['Date'])
        for col in ['Open', 'High', 'Low', 'Close', 'Volume', 'Turnover']:
            df[col] = pd.to_numeric(df[col].astype(str).str.replace(',', ''), errors='coerce')
        df['Ticker'] = ticker
        df = df.sort_values('Date').reset_index(drop=True)
        return df

    except Exception as e:
        logger.error(f"{ticker}: Error - {e}")
        return pd.DataFrame()


if __name__ == '__main__':
    with open('data/processed/ticker_list_full.txt', 'r') as f:
        tickers = [line.strip() for line in f.readlines() if line.strip()]
    logger.info(f"Total tickers to check: {len(tickers)}")

    try:
        with open(DONE_LOG, 'r') as f:
            done = set(f.read().splitlines())
        logger.info(f"Resuming — {len(done)} already updated this run")
    except FileNotFoundError:
        done = set()

    ti = TechnicalIndicators()
    updated, unchanged, failed = [], [], []

    driver = get_driver()
    logger.info("Chrome driver ready! Starting incremental scrape...")

    for i, ticker in enumerate(tickers):
        if ticker in done:
            continue

        raw_path = RAW_DIR / f"{ticker}.csv"
        if not raw_path.exists():
            logger.warning(f"{ticker}: no existing raw file, skipping (use fetch_historical_data.py for new tickers)")
            failed.append(ticker)
            continue

        existing = pd.read_csv(raw_path, parse_dates=['Date'])
        last_date = existing['Date'].max()

        logger.info(f"[{i+1}/{len(tickers)}] {ticker}: last known date {last_date.date()}")
        new_rows = scrape_new_rows(driver, ticker, last_date)

        if new_rows.empty:
            logger.info(f"{ticker}: no new rows (already up to date)")
            unchanged.append(ticker)
            with open(DONE_LOG, 'a') as f:
                f.write(f'{ticker}\n')
            continue

        # Keep only columns matching the existing raw schema, append, dedupe, sort
        combined = pd.concat([existing, new_rows[existing.columns.intersection(new_rows.columns)]],
                              ignore_index=True)
        combined = combined.drop_duplicates(subset='Date').sort_values('Date').reset_index(drop=True)
        combined.to_csv(raw_path, index=False)

        # Recompute features + labels over the FULL updated series
        # (rolling indicators need history, so this can't be done incrementally)
        sector = None
        proc_path = PROCESSED_DIR / f"{ticker}_features.csv"
        if proc_path.exists():
            old_proc = pd.read_csv(proc_path)
            if 'Sector' in old_proc.columns and len(old_proc):
                sector = old_proc['Sector'].iloc[0]

        feat = ti.add_all(combined)
        feat = add_labels(feat)
        feat['Sector'] = sector or 'Unknown'
        feat.to_csv(proc_path, index=False)

        logger.info(f"{ticker}: +{len(new_rows)} new rows, {len(combined)} total ✓")
        updated.append(ticker)
        with open(DONE_LOG, 'a') as f:
            f.write(f'{ticker}\n')
        time.sleep(1)

    driver.quit()
    logger.info(f"\n{'='*50}")
    logger.info(f"DONE! Updated: {len(updated)} | Unchanged: {len(unchanged)} | Failed: {len(failed)}")
    if failed:
        logger.info(f"Failed tickers: {failed}")
