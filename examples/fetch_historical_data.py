"""
Bulk Historical Data Fetcher using Selenium
Fetches 15 years of price history for all NEPSE equity stocks
Run: python examples/fetch_historical_data.py
WARNING: This will take 15-20 hours. Run overnight.
"""
import sys
sys.path.append('.')

import time
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


def get_driver():
    options = Options()
    options.add_argument('--headless')
    options.add_argument('--no-sandbox')
    options.add_argument('--disable-dev-shm-usage')
    options.add_argument('--disable-gpu')
    driver = webdriver.Chrome(
        service=Service(ChromeDriverManager().install()),
        options=options
    )
    return driver


def scrape_ticker(driver, ticker: str) -> pd.DataFrame:
    try:
        driver.get(f'https://www.sharesansar.com/company/{ticker}')
        time.sleep(4)

        # Click Price History
        try:
            WebDriverWait(driver, 10).until(
                EC.element_to_be_clickable((By.LINK_TEXT, 'Price History'))
            ).click()
            time.sleep(3)
        except:
            logger.warning(f"{ticker}: Could not click Price History")
            return pd.DataFrame()

        all_rows = []
        page = 1

        while True:
            soup = BeautifulSoup(driver.page_source, 'lxml')
            table = soup.find('table', {'id': 'myTableCPriceHistory'})

            if not table:
                break

            rows = table.find('tbody').find_all('tr')
            for row in rows:
                cols = [td.text.strip() for td in row.find_all('td')]
                if len(cols) >= 8:
                    all_rows.append({
                        'Date':     cols[1],
                        'Open':     cols[2],
                        'High':     cols[3],
                        'Low':      cols[4],
                        'Close':    cols[5],
                        'Volume':   cols[7],
                        'Turnover': cols[8] if len(cols) > 8 else None
                    })

            # Check next button
            try:
                next_btn = driver.find_element(
                    By.CSS_SELECTOR, '#myTableCPriceHistory_next'
                )
                if 'disabled' in next_btn.get_attribute('class'):
                    logger.info(f"{ticker}: Last page reached! ({page} pages, {len(all_rows)} rows)")
                    break
                next_btn.click()
                time.sleep(1.5)
                page += 1
            except:
                break

        if not all_rows:
            return pd.DataFrame()

        df = pd.DataFrame(all_rows)
        df['Date'] = pd.to_datetime(df['Date'])
        for col in ['Open', 'High', 'Low', 'Close', 'Volume', 'Turnover']:
            df[col] = pd.to_numeric(
                df[col].str.replace(',', ''), errors='coerce'
            )
        df['Ticker'] = ticker
        df = df.sort_values('Date').reset_index(drop=True)
        return df

    except Exception as e:
        logger.error(f"{ticker}: Error - {e}")
        return pd.DataFrame()


# ── Main ─────────────────────────────────────────────────────
if __name__ == '__main__':
    print("Script started!")

    # Load tickers from existing ticker_list.txt
    with open('data/processed/ticker_list_full.txt', 'r') as f:
        tickers = [line.strip() for line in f.readlines()]
    logger.info(f"Total tickers to scrape: {len(tickers)}")

    # Load sector mapping from existing processed files
    sector_map = {}
    for ticker in tickers:
        try:
            df = pd.read_csv(f'data/processed/{ticker}_features.csv')
            if 'Sector' in df.columns:
                sector_map[ticker] = df['Sector'].iloc[0]
        except:
            sector_map[ticker] = 'Unknown'
    logger.info(f"Sector map loaded for {len(sector_map)} tickers")

    ti = TechnicalIndicators()

    # Resume capability
    try:
        with open('data/processed/historical_done.txt', 'r') as f:
            done = set(f.read().splitlines())
        logger.info(f"Resuming — {len(done)} already done")
    except:
        done = set()
        logger.info("Starting fresh")

    success = []
    failed = []

    print("Starting Chrome driver...")
    driver = get_driver()
    print("Chrome driver ready! Starting scrape...")

    for i, ticker in enumerate(tickers):
        # Skip if already done
        if ticker in done:
            logger.info(f"[{i+1}/{len(tickers)}] {ticker}: Already done, skipping")
            success.append(ticker)
            continue

        logger.info(f"[{i+1}/{len(tickers)}] Scraping {ticker}...")

        df = scrape_ticker(driver, ticker)

        if df.empty or len(df) < 100:
            logger.warning(f"{ticker}: Insufficient data ({len(df)} rows) - skipping")
            failed.append(ticker)
            continue

        # Add features and labels
        try:
            df = ti.add_all(df)
            df = add_labels(df)
            df['Sector'] = sector_map.get(ticker, 'Unknown')
        except Exception as e:
            logger.error(f"{ticker}: Feature engineering failed - {e}")
            failed.append(ticker)
            continue

        # Save to both raw and processed
        df.to_csv(f'data/raw/{ticker}.csv', index=False)
        df.to_csv(f'data/processed/{ticker}_features.csv', index=False)

        success.append(ticker)

        # Mark as done for resume
        with open('data/processed/historical_done.txt', 'a') as f:
            f.write(f'{ticker}\n')

        logger.info(f"{ticker}: {len(df)} rows saved ✓")
        time.sleep(1)

    driver.quit()

    # Update ticker list with successful ones
    with open('data/processed/ticker_list.txt', 'w') as f:
        f.write('\n'.join(success))

    logger.info(f"\n{'='*50}")
    logger.info(f"DONE! Success: {len(success)} | Failed: {len(failed)}")
    logger.info(f"Failed tickers: {failed}")