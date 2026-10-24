"""
Build a Prophet price forecast for every ticker and write the results to
data/models/forecast_summary.csv.

This precomputes forecasts in batch rather than fitting Prophet per web
request -- a single ticker takes a few seconds to fit, which is far too
slow to do inside a Flask request. Wiring this CSV into the app (an API
route, a chart overlay, wherever) is a separate, deliberately deferred
decision -- this script only produces the data.

Usage:
    python scripts/build_forecasts.py
    python scripts/build_forecasts.py --periods 14 --min-rows 200
"""
import argparse
import csv
import os
import sys
from datetime import date

sys.path.append('.')

from loguru import logger
from ml.models.forecaster import StockForecaster

MIN_ROWS_DEFAULT = 100  # below this, a Prophet forecast is not meaningful


def load_ticker_list():
    with open('data/processed/ticker_list.txt') as f:
        return [t.strip() for t in f if t.strip()]


def row_count(ticker):
    try:
        with open(f'data/raw/{ticker}.csv') as f:
            return sum(1 for _ in f) - 1  # minus header
    except FileNotFoundError:
        return 0


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--periods', type=int, default=30,
                     help='Forecast horizon in business days (default: 30)')
    ap.add_argument('--min-rows', type=int, default=MIN_ROWS_DEFAULT,
                     help=f'Skip tickers with fewer raw rows than this (default: {MIN_ROWS_DEFAULT})')
    ap.add_argument('--out', default='data/models/forecast_summary.csv')
    ap.add_argument('--daily-out', default='data/models/forecast_daily.csv',
                     help='Day-by-day forecast path (1..periods business days out) for '
                          'every ticker, used by the stock-page forecast slider.')
    ap.add_argument('--limit', type=int, default=None,
                     help='Only process the first N tickers (for a quick test run)')
    ap.add_argument('--start', type=int, default=0,
                     help='Skip the first N tickers (for resuming in chunks)')
    ap.add_argument('--append', action='store_true',
                     help='Append to --out instead of overwriting (for resuming in chunks)')
    args = ap.parse_args()

    tickers = load_ticker_list()
    if args.start:
        tickers = tickers[args.start:]
    if args.limit:
        tickers = tickers[:args.limit]

    logger.info(f"Building {args.periods}-day forecasts for {len(tickers)} tickers "
                f"(min {args.min_rows} rows)...")

    results = []
    daily_rows = []
    skipped = []
    failed = []

    for i, ticker in enumerate(tickers, 1):
        n_rows = row_count(ticker)
        if n_rows < args.min_rows:
            skipped.append((ticker, n_rows))
            continue

        try:
            forecaster = StockForecaster()
            result = forecaster.train(ticker, periods=args.periods)
        except Exception as exc:
            failed.append((ticker, f"{type(exc).__name__}: {exc}"))
            continue

        if not result:
            failed.append((ticker, "train() returned empty result"))
            continue

        results.append({
            "ticker": result["ticker"],
            "current_price": result["current_price"],
            "forecast_price": result["forecast_price"],
            "lower_bound": result["lower_bound"],
            "upper_bound": result["upper_bound"],
            "change_pct": result["change_pct"],
            "horizon_days": args.periods,
            "rows_used": n_rows,
            "generated_at": date.today().isoformat(),
        })

        # Day-by-day path (every business day Prophet predicted, not just the
        # final day) -- this is what lets the stock page offer a 1-day..30-day
        # slider instead of only ever showing the fixed horizon end-point.
        fdf = result.get("forecast_df")
        if fdf is not None and len(fdf):
            current_price = result["current_price"]
            for day_offset, (_, r) in enumerate(fdf.iterrows(), 1):
                yhat = round(float(r["yhat"]), 2)
                daily_rows.append({
                    "ticker": result["ticker"],
                    "day_offset": day_offset,
                    "date": r["ds"].date().isoformat(),
                    "forecast_price": yhat,
                    "lower_bound": round(float(r["yhat_lower"]), 2),
                    "upper_bound": round(float(r["yhat_upper"]), 2),
                    "change_pct": round((yhat - current_price) / current_price * 100, 2)
                                  if current_price else None,
                })

        if i % 20 == 0 or i == len(tickers):
            logger.info(f"  {i}/{len(tickers)} done "
                        f"({len(results)} ok, {len(skipped)} skipped, {len(failed)} failed)")

    if results:
        fieldnames = list(results[0].keys())
        write_header = not (args.append and os.path.exists(args.out))
        mode = 'a' if args.append else 'w'
        with open(args.out, mode, newline='', encoding='utf-8') as f:
            writer = csv.DictWriter(f, fieldnames=fieldnames)
            if write_header:
                writer.writeheader()
            writer.writerows(results)
        logger.info(f"Wrote {len(results)} forecasts to {args.out} (append={args.append})")
    else:
        logger.warning("No forecasts produced -- nothing written.")

    if daily_rows:
        fieldnames = list(daily_rows[0].keys())
        write_header = not (args.append and os.path.exists(args.daily_out))
        mode = 'a' if args.append else 'w'
        with open(args.daily_out, mode, newline='', encoding='utf-8') as f:
            writer = csv.DictWriter(f, fieldnames=fieldnames)
            if write_header:
                writer.writeheader()
            writer.writerows(daily_rows)
        logger.info(f"Wrote {len(daily_rows)} daily-path rows to {args.daily_out} (append={args.append})")

    if skipped:
        logger.info(f"Skipped {len(skipped)} tickers with < {args.min_rows} rows: "
                    f"{', '.join(t for t, _ in skipped[:15])}"
                    f"{' ...' if len(skipped) > 15 else ''}")
    if failed:
        logger.warning(f"Failed on {len(failed)} tickers:")
        for ticker, reason in failed[:20]:
            logger.warning(f"  {ticker}: {reason}")
        if len(failed) > 20:
            logger.warning(f"  ... and {len(failed) - 20} more")

    # Nothing produced is a failure, not a quiet success -- otherwise a scheduled
    # run just fails later with a confusing "no files to upload" message.
    if not results:
        logger.error("No forecasts were produced (see the failures above).")
        sys.exit(1)


if __name__ == '__main__':
    main()
