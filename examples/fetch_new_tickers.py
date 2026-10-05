"""
Fetch full price history for tickers that are NOT yet in our dataset at all
(as opposed to fetch_incremental_data.py, which only catches up existing
tickers to today).

Unlike fetch_historical_data.py, this does NOT touch any ticker we already
have data for, and it APPENDS the new tickers to ticker_list.txt /
ticker_list_full.txt instead of overwriting those files.

Run: python examples/fetch_new_tickers.py
"""
import sys
sys.path.append('.')

import time
from pathlib import Path
import pandas as pd
from selenium import webdriver
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from bs4 import BeautifulSoup
from src.features.technical_indicators import TechnicalIndicators
from src.features.labeler import add_labels
from loguru import logger

# ticker -> sector, from diffing NEPSE's live getCompanyList() (active,
# instrumentType == "Equity") against data/raw/*.csv on 2026-10-05.
NEW_TICKERS = {
    "SABBL":  "Development Banks",
    "HFIN":   "Hotels And Tourism",
    "APHL":   "Hydro Power",
    "BJHL":   "Hydro Power",
    "KAHL":   "Hydro Power",
    "KHPL":   "Hydro Power",
    "MEPDL":  "Hydro Power",
    "RLEL":   "Hydro Power",
    "SGHL":   "Hydro Power",
    "SIPD":   "Hydro Power",
    "SKHEL":  "Hydro Power",
    "SKHL":   "Hydro Power",
    "SNORL":  "Hydro Power",
    "SOHL":   "Hydro Power",
    "TPKHL":  "Hydro Power",
    "YMHL":   "Hydro Power",
    "ECL":    "Manufacturing And Processing",
    "PCIL":   "Manufacturing And Processing",
    "RSML":   "Manufacturing And Processing",
    "SAPIL":  "Manufacturing And Processing",
    "SOPL":   "Manufacturing And Processing",
}

RAW_DIR = Path("data/raw")
PROCESSED_DIR = Path("data/processed")
DONE_LOG = PROCESSED_DIR / "new_tickers_done.txt"
MIN_ROWS = 100


def get_driver():
    options = Options()
    options.add_argument('--headless=new')
    options.add_argument('--no-sandbox')
    options.add_argument('--disable-dev-shm-usage')
    options.add_argument('--disable-gpu')
    return webdriver.Chrome(options=options)


def scrape_ticker(driver, ticker: str) -> pd.DataFrame:
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
                        'Date': cols[1], 'Open': cols[2], 'High': cols[3],
                        'Low': cols[4], 'Close': cols[5], 'Volume': cols[7],
                        'Turnover': cols[8] if len(cols) > 8 else None
                    })
            try:
                next_btn = driver.find_element(By.CSS_SELECTOR, '#myTableCPriceHistory_next')
                if 'disabled' in next_btn.get_attribute('class'):
                    logger.info(f"{ticker}: last page reached ({page} pages, {len(all_rows)} rows)")
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
    try:
        done = set(DONE_LOG.read_text().splitlines())
        logger.info(f"Resuming -- {len(done)} already handled")
    except FileNotFoundError:
        done = set()

    ti = TechnicalIndicators()
    success, failed = [], []

    driver = get_driver()
    logger.info("Chrome driver ready! Fetching new tickers...")

    tickers = [t for t in NEW_TICKERS if t not in done]
    for i, ticker in enumerate(tickers, 1):
        if (RAW_DIR / f"{ticker}.csv").exists():
            logger.info(f"[{i}/{len(tickers)}] {ticker}: raw file already exists, skipping")
            with open(DONE_LOG, 'a') as f:
                f.write(f'{ticker}\n')
            continue

        logger.info(f"[{i}/{len(tickers)}] Scraping {ticker}...")
        df = scrape_ticker(driver, ticker)

        if df.empty or len(df) < MIN_ROWS:
            logger.warning(f"{ticker}: insufficient data ({len(df)} rows) - skipping")
            failed.append(ticker)
            with open(DONE_LOG, 'a') as f:
                f.write(f'{ticker}\n')
            continue

        try:
            df = ti.add_all(df)
            df = add_labels(df)
            df['Sector'] = NEW_TICKERS[ticker]
        except Exception as e:
            logger.error(f"{ticker}: feature engineering failed - {e}")
            failed.append(ticker)
            with open(DONE_LOG, 'a') as f:
                f.write(f'{ticker}\n')
            continue

        df.to_csv(RAW_DIR / f"{ticker}.csv", index=False)
        df.to_csv(PROCESSED_DIR / f"{ticker}_features.csv", index=False)
        success.append(ticker)
        with open(DONE_LOG, 'a') as f:
            f.write(f'{ticker}\n')
        logger.info(f"{ticker}: {len(df)} rows saved OK")
        time.sleep(1)

    driver.quit()

    # Append newly-succeeded tickers to the master lists (never overwrite).
    if success:
        for path in [PROCESSED_DIR / "ticker_list.txt", PROCESSED_DIR / "ticker_list_full.txt"]:
            old_text = path.read_text() if path.exists() else ""
            existing = set(old_text.splitlines())
            new_ones = [t for t in success if t not in existing]
            if new_ones:
                # Guard against a missing trailing newline on the existing
                # file gluing the first appended ticker onto the last line
                # (bit us once: "SYPNL" + "SABBL" -> "SYPNLSABBL").
                needs_leading_newline = old_text and not old_text.endswith('\n')
                with open(path, 'a') as f:
                    if needs_leading_newline:
                        f.write('\n')
                    for t in new_ones:
                        f.write(f'{t}\n')

    logger.info(f"\n{'='*50}")
    logger.info(f"DONE! Success: {len(success)} | Failed: {len(failed)}")
    if failed:
        logger.info(f"Failed tickers (likely too new / too little history): {failed}")

    if len(done) + len(success) + len(failed) >= len(NEW_TICKERS):
        try:
            DONE_LOG.unlink()
            logger.info("Resume log cleared.")
        except FileNotFoundError:
            pass
