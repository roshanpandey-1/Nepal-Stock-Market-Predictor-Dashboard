"""
Builds deploy_data/ -- a trimmed snapshot of data/processed and data/models,
small enough to commit to git for a live deployment (the
full data/ directories are gitignored; see deploy_data/README.md for why).

Run this again any time the data pipeline / models are refreshed and you
want the live site to pick up the changes:
    python scripts/build_deploy_snapshot.py
Then commit and push deploy_data/ as usual.
"""
import csv
import shutil
from pathlib import Path

PROCESSED = Path("data/processed")
MODELS = Path("data/models")

OUT = Path("deploy_data")
OUT_PROCESSED = OUT / "processed"
OUT_MODELS = OUT / "models"

KEEP_ROWS = 260  # ~180 for the price chart + headroom for the LSTM's lookback


def build_processed():
    OUT_PROCESSED.mkdir(parents=True, exist_ok=True)
    ticker_list_path = PROCESSED / "ticker_list.txt"
    tickers = [t.strip() for t in ticker_list_path.read_text().splitlines() if t.strip()]

    for ticker in tickers:
        src = PROCESSED / f"{ticker}_features.csv"
        if not src.exists():
            continue
        with open(src, newline="", encoding="utf-8") as f:
            rows = list(csv.reader(f))
        header, body = rows[0], rows[1:]
        trimmed = body[-KEEP_ROWS:]
        with open(OUT_PROCESSED / f"{ticker}_features.csv", "w", newline="", encoding="utf-8") as f:
            w = csv.writer(f)
            w.writerow(header)
            w.writerows(trimmed)

    shutil.copy(ticker_list_path, OUT_PROCESSED / "ticker_list.txt")

    company_names_path = PROCESSED / "company_names.json"
    if company_names_path.exists():
        shutil.copy(company_names_path, OUT_PROCESSED / "company_names.json")

    print(f"Trimmed {len(tickers)} ticker files to last {KEEP_ROWS} rows each")


def build_models():
    OUT_MODELS.mkdir(parents=True, exist_ok=True)
    # forecast_*.csv back /api/price-forecast (the stock page's Price Forecast
    # panel, built by scripts/build_forecasts.py) -- without them the panel
    # 404s and stays hidden on the deployed site.
    patterns = ["*_oos*", "*split_date*", "backtest_summary_oos.csv",
                "forecast_summary.csv", "forecast_daily.csv"]
    count = 0
    for pattern in patterns:
        for src in MODELS.glob(pattern):
            shutil.copy(src, OUT_MODELS / src.name)
            count += 1
    print(f"Copied {count} model/scaler/metadata files")


if __name__ == "__main__":
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument("--only", choices=["processed", "models"],
                    help="rebuild just one part (CI jobs refresh one part at a time)")
    args = ap.parse_args()
    steps = {"processed": build_processed, "models": build_models}
    for name, fn in steps.items():
        if args.only in (None, name):
            fn()
    print("Done. Review deploy_data/, then git add/commit/push it.")
