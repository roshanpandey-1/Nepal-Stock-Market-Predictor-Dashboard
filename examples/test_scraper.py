import sys
sys.path.append('.')
from selenium import webdriver
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from webdriver_manager.chrome import ChromeDriverManager
from bs4 import BeautifulSoup
import pandas as pd
import time


def scrape_sharesansar(ticker: str) -> pd.DataFrame:
    options = Options()
    options.add_argument('--headless')
    options.add_argument('--no-sandbox')
    options.add_argument('--disable-dev-shm-usage')

    driver = webdriver.Chrome(service=Service(ChromeDriverManager().install()), options=options)
    driver.get(f'https://www.sharesansar.com/company/{ticker}')
    time.sleep(5)

    # Click Price History
    try:
        driver.find_element(By.LINK_TEXT, 'Price History').click()
        time.sleep(3)
    except:
        print(f'{ticker}: Could not click Price History')
        driver.quit()
        return pd.DataFrame()

    # Change page size to 500 via JavaScript
    try:
        driver.execute_script("$('#myTableCPriceHistory').DataTable().page.len(500).draw();")
        time.sleep(3)
        print(f'{ticker}: Page size changed to 500!')
    except Exception as e:
        print(f'{ticker}: JS approach failed - {e}')

    all_rows = []

    while True:
        soup = BeautifulSoup(driver.page_source, 'lxml')
        table = soup.find('table', {'id': 'myTableCPriceHistory'})

        if not table:
            print(f'{ticker}: Table not found')
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

        # Check if Next button is disabled
        try:
            next_btn = driver.find_element(By.CSS_SELECTOR, '#myTableCPriceHistory_next')
            if 'disabled' in next_btn.get_attribute('class'):
                print(f'{ticker}: Last page reached!')
                break
            next_btn.click()
            time.sleep(1.5)
        except:
            break

    driver.quit()

    df = pd.DataFrame(all_rows)
    if not df.empty:
        df['Date'] = pd.to_datetime(df['Date'])
        for col in ['Open', 'High', 'Low', 'Close', 'Volume', 'Turnover']:
            df[col] = pd.to_numeric(df[col].str.replace(',', ''), errors='coerce')
        df['Ticker'] = ticker
        df = df.sort_values('Date').reset_index(drop=True)
    return df


# Test with NABIL
print('Scraping NABIL...')
df = scrape_sharesansar('NABIL')
print(f'Rows fetched: {len(df)}')
print(f'Date range: {df.Date.min()} to {df.Date.max()}')
print(df.head(3))
df.to_csv('data/raw/NABIL_full.csv', index=False)
print('Saved!')