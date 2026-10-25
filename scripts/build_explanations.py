"""
Build the "Why this signal?" explanations for every stock and save them to
<DATA_DIR>/models/explanations.json, which the dashboard reads.

They are built here, not per web request: the LSTM attribution runs the model
thousands of times, which is quick on a normal machine but could exhaust the
free host's memory and take the site down. GitHub Actions run this after the
daily price refresh and after the weekly retrain, so the explanation always
matches the latest data and the deployed model, like /api/signal.

Usage (from the repo root):
    python scripts/build_explanations.py                 # DATA_DIR, default deploy_data
    python scripts/build_explanations.py --data-dir data
"""
import argparse
import csv
import json
import os
import sys
import time
from datetime import date
from pathlib import Path

sys.path.append('.')

from app.backend import explain  # noqa: E402
from app.backend.api import DROP_COLS, LSTM_SECTORS, SEQ_LEN  # noqa: E402


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--data-dir', default=os.environ.get('DATA_DIR', 'deploy_data'))
    args = ap.parse_args()
    data = Path(args.data_dir)
    tickers = [t.strip() for t in (data / 'processed' / 'ticker_list.txt').read_text().splitlines() if t.strip()]

    import torch
    torch.set_num_threads(max(1, os.cpu_count() or 1))
    stocks, failed, t0 = {}, 0, time.time()
    for i, ticker in enumerate(tickers, 1):
        path = data / 'processed' / f'{ticker}_features.csv'
        if not path.exists():
            continue
        with open(path, newline='', encoding='utf-8') as f:
            rows = list(csv.DictReader(f))
        try:
            stocks[ticker] = explain.explain_ticker(rows, data / 'models', DROP_COLS, LSTM_SECTORS, SEQ_LEN)
        except Exception as e:  # one bad stock must not stop the rest
            stocks[ticker] = {'error': f'could not explain: {type(e).__name__}'}
        failed += 'error' in stocks[ticker]
        if i % 50 == 0:
            print(f'  {i}/{len(tickers)} ({time.time() - t0:.0f}s)', flush=True)

    out = {'generated': date.today().isoformat(), 'stocks': stocks}
    target = data / 'models' / explain.EXPLANATIONS_FILE
    target.write_text(json.dumps(out, separators=(',', ':')), encoding='utf-8')
    print(f'Wrote {len(stocks) - failed} explanations ({failed} without) to {target} in {time.time() - t0:.0f}s')
    if not stocks or failed == len(stocks):
        sys.exit('No explanations were produced.')


if __name__ == '__main__':
    main()
