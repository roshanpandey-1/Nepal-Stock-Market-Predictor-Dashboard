import sys
sys.path.append('.')

import time
import pandas as pd
from nepse import Nepse
from src.scraper.nepse_scraper import NEPSEScraper
from src.features.technical_indicators import TechnicalIndicators
from src.features.labeler import add_labels
from loguru import logger

# ── 1. Get all listed companies ──────────────────────────────
nepse = Nepse()
nepse.setTLSVerification(False)

logger.info("Fetching company list...")
companies = nepse.getCompanyList()

# ── 2. Filter to Equity only ─────────────────────────────────
equity = [c for c in companies if c['instrumentType'] == 'Equity'
          and c['status'] == 'A']
logger.info(f"Total equity companies: {len(equity)}")

# ── 3. Fetch, process and save each ──────────────────────────
scraper = NEPSEScraper()
ti = TechnicalIndicators()

success = []
failed = []

for i, company in enumerate(equity):
    ticker = company['symbol']
    try:
        df = scraper.fetch_stock_history(ticker)

        # Skip if less than 100 rows (newly listed)
        if len(df) < 100:
            logger.warning(f"{ticker}: Only {len(df)} rows - skipping")
            failed.append(ticker)
            continue

        df = ti.add_all(df)
        df = add_labels(df)
        scraper.save(df, ticker)                                         # → data/raw/
        df.to_csv(f'data/processed/{ticker}_features.csv', index=False) # → data/processed/
        success.append(ticker)
        logger.info(f"[{i+1}/{len(equity)}] {ticker}: {len(df)} rows saved")

        # Be polite to the server
        time.sleep(0.5)

    except Exception as e:
        logger.error(f"{ticker}: Failed - {e}")
        failed.append(ticker)
        time.sleep(1)

# ── 4. Summary ────────────────────────────────────────────────
logger.info(f"Success: {len(success)} stocks")
logger.info(f"Failed/Skipped: {len(failed)} stocks")
logger.info(f"Failed tickers: {failed}")

# Save list of successful tickers
with open('data/processed/ticker_list.txt', 'w') as f:
    f.write('\n'.join(success))
logger.info("Ticker list saved to data/processed/ticker_list.txt")